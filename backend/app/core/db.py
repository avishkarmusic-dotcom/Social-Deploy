"""Database session management, with tenant isolation wired into the session.

The important line in this file is `SET LOCAL app.workspace_id`. Every
tenant-scoped table has row-level security keyed on that setting, so a query
that forgets its `WHERE workspace_id = ...` returns zero rows instead of
another customer's inbox. Isolation is enforced by Postgres, not by everyone
remembering to add a filter — which is the only kind of enforcement that
survives a codebase growing past one author.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, MappedAsDataclass
from sqlalchemy.pool import NullPool

from app.core.config import settings


class Base(DeclarativeBase):
    """Declarative base. Deliberately not MappedAsDataclass — the models carry
    behaviour, and dataclass semantics fight with SQLAlchemy's default loading."""


engine: AsyncEngine | None = None


def _engine_kwargs() -> dict:
    kwargs = {
        "echo": False,
        "pool_pre_ping": True,
        "connect_args": {"server_settings": {"application_name": "tryvanta-social"}},
    }
    if settings.environment == "test":
        kwargs["poolclass"] = NullPool
    else:
        kwargs.update({
            "pool_size": 20,
            "max_overflow": 10,
            "pool_recycle": 1800,
        })
    return kwargs


def init_engine() -> AsyncEngine:
    global engine
    if engine is None:
        engine = create_async_engine(settings.database_url, **_engine_kwargs())
    return engine


def get_sessionmaker():
    """Returns a new async sessionmaker bound to the lazy engine."""
    return async_sessionmaker(
        init_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


def make_sessionmaker():
    """Deprecated: use get_sessionmaker() instead."""
    return get_sessionmaker()


# Callable for backward compatibility with imports like `from app.core.db import sessionmaker`
sessionmaker = get_sessionmaker


@asynccontextmanager
async def tenant_session(workspace_id: UUID | str) -> AsyncIterator[AsyncSession]:
    """A session scoped to one workspace for its whole lifetime.

    SET LOCAL is transaction-scoped, so the setting cannot leak into another
    request that reuses this pooled connection.
    """
    sm = make_sessionmaker()
    async with sm() as session:
        await session.execute(
            text("SET LOCAL app.workspace_id = :wid"), {"wid": str(workspace_id)}
        )
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def system_session() -> AsyncIterator[AsyncSession]:
    """For work that legitimately spans tenants — cron, migrations, admin.

    Rare by design. If a request handler reaches for this, that's a bug.
    """
    sm = make_sessionmaker()
    async with sm() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def healthy() -> bool:
    try:
        eng = init_engine()
        async with eng.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
