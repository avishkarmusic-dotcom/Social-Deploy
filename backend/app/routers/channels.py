"""Connecting, listing and disconnecting channel accounts.

The OAuth dance is the one place a user hands us keys to their livelihood, so
three things are non-negotiable here: state is signed and single-use, tokens
are sealed before they touch the database, and disconnecting revokes upstream
before it deletes locally — in that order, because a local delete followed by a
failed revoke leaves a live token we can no longer see or kill.
"""
from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.connectors.base import ConnectorError
from app.connectors.registry import get
from app.core.config import settings
from app.core.deps import DB, CurrentUser, audit, get_queue, workspace_key
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.models import SourceAccount

log = structlog.get_logger()
router = APIRouter(prefix="/v1/channels", tags=["channels"])

STATE_TTL_S = 600


class AccountOut(BaseModel):
    id: str
    kind: str
    display_name: str
    avatar_url: str | None
    status: str
    last_synced_at: datetime | None
    last_error: str | None
    supports_push: bool
    can_publish: bool


@router.get("", response_model=list[AccountOut], summary="Connected accounts")
async def list_accounts(user: CurrentUser, db: DB) -> list[AccountOut]:
    rows = await db.scalars(
        select(SourceAccount)
        .where(SourceAccount.workspace_id == user.workspace_id)
        .order_by(SourceAccount.source_kind)
    )
    out = []
    for a in rows:
        adapter = get(a.source_kind)
        out.append(
            AccountOut(
                id=str(a.id),
                kind=str(a.source_kind),
                display_name=a.display_name,
                avatar_url=a.avatar_url,
                status=a.status,
                last_synced_at=a.last_synced_at,
                last_error=a.last_error,
                supports_push=adapter.supports_push,
                can_publish=type(adapter).publish is not type(adapter).__mro__[-2].publish
                if hasattr(adapter, "publish") else False,
            )
        )
    return out


class ConnectOut(BaseModel):
    authorize_url: str
    expires_in: int


@router.get("/{kind}/connect", response_model=ConnectOut, summary="Start OAuth")
async def connect(kind: str, user: CurrentUser, request: Request) -> ConnectOut:
    try:
        adapter = get(kind)
    except LookupError as exc:
        raise ValidationFailed(
            f"'{kind}' isn't a channel this deployment supports.",
            fix="Check /v1/meta for the list of channels available here.",
        ) from exc

    # State is a random nonce held in Redis against the workspace, so a callback
    # can't be replayed and can't be redirected into someone else's workspace.
    state = secrets.token_urlsafe(32)
    await request.app.state.limiter._redis.set(
        f"oauth:{state}",
        f"{user.workspace_id}:{user.user_id}:{kind}",
        ex=STATE_TTL_S,
    )
    return ConnectOut(
        authorize_url=adapter.authorize_url(
            state=state, redirect_uri=f"{settings.oauth_redirect_base}/{kind}"
        ),
        expires_in=STATE_TTL_S,
    )


@router.get("/callback/{kind}", include_in_schema=False)
async def callback(
    kind: str,
    request: Request,
    db: DB,
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    """The provider redirects the browser here. This endpoint takes no session
    header — the signed state parameter is the only thing that authorises it."""
    ui = settings.cors_origins[0]
    if error or not code or not state:
        return RedirectResponse(f"{ui}/settings/channels?error={error or 'cancelled'}")

    redis = request.app.state.limiter._redis
    stored = await redis.getdel(f"oauth:{state}")   # single use, atomically
    if not stored:
        log.warning("oauth.state_invalid", kind=kind)
        return RedirectResponse(f"{ui}/settings/channels?error=expired")

    workspace_id, user_id, expected_kind = stored.split(":")
    if expected_kind != kind:
        return RedirectResponse(f"{ui}/settings/channels?error=mismatch")

    adapter = get(kind)
    try:
        bundle = await adapter.exchange_code(
            code, redirect_uri=f"{settings.oauth_redirect_base}/{kind}"
        )
    except (ConnectorError, Exception) as exc:
        log.warning("oauth.exchange_failed", kind=kind, error=str(exc))
        return RedirectResponse(f"{ui}/settings/channels?error=exchange_failed")

    from app.core.crypto import unwrap
    from app.models import Workspace

    workspace = await db.get(Workspace, workspace_id)
    key = unwrap(workspace.wrapped_key)

    existing = await db.scalar(
        select(SourceAccount).where(
            SourceAccount.workspace_id == workspace_id,
            SourceAccount.source_kind == kind,
            SourceAccount.external_id == bundle.external_id,
        )
    )
    account = existing or SourceAccount(
        workspace_id=workspace.id,
        source_kind=kind,
        external_id=bundle.external_id,
    )
    account.display_name = bundle.display_name
    account.avatar_url = bundle.avatar_url
    account.scopes = bundle.scopes
    account.status = "connected"
    account.last_error = None
    account.token_expires = bundle.expires_at
    if existing is None:
        db.add(account)
        await db.flush()
    # Sealing needs the account id as AAD, so tokens are set after the flush.
    account.set_tokens(bundle.access_token, bundle.refresh_token, key)
    await db.commit()

    queue = await get_queue(request)
    await queue.enqueue_job("sync_account", str(account.id))
    return RedirectResponse(f"{ui}/settings/channels?connected={kind}")


@router.post("/{account_id}/sync", summary="Force a sync now")
async def sync_now(account_id: str, user: CurrentUser, db: DB, request: Request) -> dict:
    account = await _load(db, account_id, user.workspace_id)
    queue = await get_queue(request)
    await queue.enqueue_job("sync_account", str(account.id))
    return {"queued": True, "kind": str(account.source_kind)}


@router.delete("/{account_id}", summary="Disconnect an account")
async def disconnect(
    account_id: str, user: CurrentUser, db: DB, request: Request
) -> dict:
    user.require("admin", "disconnect a channel")
    account = await _load(db, account_id, user.workspace_id)
    key = await workspace_key(db, user)

    # Revoke upstream first. If this fails we still delete locally, but we log
    # loudly — a token we can no longer see is worse than one we can.
    try:
        await get(account.source_kind).revoke(account.access_token(key))
    except Exception as exc:
        log.warning("channel.revoke_failed", kind=str(account.source_kind), error=str(exc))

    await audit(
        db, user, action="channel.disconnect", resource="channel_account",
        resource_id=account_id, request=request, kind=str(account.source_kind),
    )
    await db.delete(account)
    return {"disconnected": str(account.source_kind)}


async def _load(db, account_id: str, workspace_id) -> SourceAccount:
    account = await db.scalar(
        select(SourceAccount)
        .options(selectinload(SourceAccount.workspace))
        .where(
            SourceAccount.id == account_id,
            SourceAccount.workspace_id == workspace_id,
        )
    )
    if account is None:
        raise NotFound("channel account", account_id)
    return account
