"""Request dependencies — auth, tenancy, rate limiting, audit.

The one non-obvious decision: `CurrentUser` resolves the workspace *and* opens
a session already scoped to it. Handlers therefore cannot accidentally query
across tenants, because they never hold an unscoped session in the first place.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

import structlog
from arq.connections import ArqRedis, create_pool
from fastapi import Depends, Header, Request
from jose import JWTError, jwt
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.db import sessionmaker
from app.core.errors import Forbidden, RateLimited, Unauthorized
from app.models import AuditLog, WorkspaceMember
from app.services.ai_router import AIRouter

log = structlog.get_logger()
ALGORITHM = "HS256"


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    workspace_id: UUID
    role: str
    email: str

    def require(self, minimum: str, action: str) -> None:
        if WorkspaceMember.RANK.get(self.role, -1) < WorkspaceMember.RANK[minimum]:
            raise Forbidden(action, minimum)


def issue_session(user_id: UUID, workspace_id: UUID, role: str, email: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user_id),
            "ws": str(workspace_id),
            "role": role,
            "email": email,
            "iat": now,
            "exp": now + timedelta(hours=settings.session_ttl_hours),
        },
        settings.app_secret,
        algorithm=ALGORITHM,
    )


async def get_principal(
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("This endpoint needs a signed-in session.")
    try:
        claims = jwt.decode(
            authorization.split(" ", 1)[1], settings.app_secret, algorithms=[ALGORITHM]
        )
    except JWTError as exc:
        raise Unauthorized() from exc
    return Principal(
        user_id=UUID(claims["sub"]),
        workspace_id=UUID(claims["ws"]),
        role=claims.get("role", "member"),
        email=claims.get("email", ""),
    )


CurrentUser = Annotated[Principal, Depends(get_principal)]


async def get_db(user: CurrentUser) -> AsyncIterator[AsyncSession]:
    """A session pinned to the caller's workspace for its whole transaction.

    SET LOCAL is transaction-scoped, so this cannot leak onto the next request
    that borrows the same pooled connection.
    """
    async with sessionmaker() as session:
        await session.execute(
            text("SET LOCAL app.workspace_id = :wid"), {"wid": str(user.workspace_id)}
        )
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


DB = Annotated[AsyncSession, Depends(get_db)]


async def get_queue(request: Request) -> ArqRedis:
    if not hasattr(request.app.state, "queue"):
        request.app.state.queue = await create_pool(_redis_settings())
    return request.app.state.queue


def _redis_settings():
    from arq.connections import RedisSettings

    return RedisSettings.from_dsn(settings.redis_url)


_ai_router: AIRouter | None = None


def get_router() -> AIRouter:
    global _ai_router
    if _ai_router is None:
        _ai_router = AIRouter()
    return _ai_router


AI = Annotated[AIRouter, Depends(get_router)]


def rate_limit(*, burst: int, per_second: float, cost: int = 1):
    """Per-workspace token bucket. AI endpoints pass a higher cost because a
    single request there is worth a hundred cheap ones downstream."""

    async def guard(request: Request, user: CurrentUser) -> None:
        limiter = getattr(request.app.state, "limiter", None)
        if limiter is None:
            return
        key = f"{user.workspace_id}:{request.url.path}"
        if not await limiter.allow(key, burst=burst, per_second=per_second, cost=cost):
            raise RateLimited(int(cost / per_second))

    return Depends(guard)


async def audit(
    db: AsyncSession,
    user: Principal,
    *,
    action: str,
    resource: str,
    resource_id: str | None = None,
    request: Request | None = None,
    **metadata: object,
) -> None:
    """Write-only record of anything consequential.

    Called explicitly rather than via middleware: a middleware that logs every
    request produces noise nobody reads, while an explicit call at the six
    places that matter produces a trail someone can actually audit.
    """
    db.add(
        AuditLog(
            workspace_id=user.workspace_id,
            actor_id=user.user_id,
            actor_kind="user",
            action=action,
            resource=resource,
            resource_id=resource_id,
            ip=request.client.host if request and request.client else None,
            audit_metadata=dict(metadata),
        )
    )


async def membership(db: AsyncSession, user: Principal) -> WorkspaceMember:
    row = await db.scalar(
        select(WorkspaceMember)
        .options(selectinload(WorkspaceMember.workspace))
        .where(
            WorkspaceMember.workspace_id == user.workspace_id,
            WorkspaceMember.user_id == user.user_id,
        )
    )
    if row is None:
        raise Unauthorized("You're no longer a member of this workspace.")
    return row


async def workspace_key(db: AsyncSession, user: Principal) -> bytes:
    return (await membership(db, user)).workspace.data_key
