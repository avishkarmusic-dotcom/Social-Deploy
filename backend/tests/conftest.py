"""Test fixtures.

The database fixture creates the schema once per session and rolls back after
every test, so tests are isolated without paying the cost of a rebuild each
time. No test is allowed to depend on another's leftovers.
"""
from __future__ import annotations

import asyncio
import base64
import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATA_ENCRYPTION_KEY", base64.b64encode(os.urandom(32)).decode())
os.environ.setdefault("APP_SECRET", "test-secret-not-used-in-production")

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.db import Base, init_engine  # noqa: E402
from app.core.crypto import new_workspace_key  # noqa: E402
from app.core.deps import get_db, get_principal, issue_session, Principal  # noqa: E402
from app.models import User, Workspace, WorkspaceMember, SourceAccount  # noqa: E402


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def engine():
    eng = init_engine()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine) -> AsyncIterator[AsyncSession]:
    """Each test runs inside a transaction that is rolled back afterwards."""
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = async_sessionmaker(bind=connection, expire_on_commit=False, autoflush=False)()
        yield session
        await session.close()
        await transaction.rollback()


@pytest_asyncio.fixture
async def workspace(db) -> Workspace:
    user = User(email="test@tryvanta.social", full_name="Test User")
    db.add(user)
    await db.flush()
    _, wrapped = new_workspace_key()
    ws = Workspace(name="Test", slug="test", owner_id=user.id, wrapped_key=wrapped)
    db.add(ws)
    await db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="owner"))
    await db.flush()
    ws.owner = user
    return ws


@pytest_asyncio.fixture
async def client(db, workspace) -> AsyncIterator[AsyncClient]:
    """An authenticated client bound to the test transaction.

    get_db is overridden so handlers join the same rolled-back transaction as
    the test body — otherwise assertions would read a database the handler
    never wrote to.
    """
    from app.main import app  # noqa: E402

    principal = Principal(
        user_id=workspace.owner_id, workspace_id=workspace.id,
        role="owner", email="test@tryvanta.social",
    )

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_principal] = lambda: principal

    token = issue_session(principal.user_id, principal.workspace_id, "owner", principal.email)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as c:
        yield c
    app.dependency_overrides.clear()
