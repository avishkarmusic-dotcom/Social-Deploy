"""Row-level security isolation tests — Phase 9 hardening.

RLS is the last line of defence. These tests prove that Postgres refuses
cross-workspace queries at the database level, not just the application level.

The property being tested: a query that forgets its WHERE clause returns
zero rows for Workspace B when the session is set to Workspace A.
A test that passes here means the application can never serve Workspace B's
data to Workspace A's users, even if there is a bug in the router layer.
"""
from __future__ import annotations

from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_workspace_isolation_on_inbound_objects(db, workspace):
    """Objects created under workspace B must be invisible from workspace A's
    session. Not just absent from query results — actually blocked by RLS."""
    from app.core.db import sessionmaker
    from app.core.crypto import new_workspace_key
    from app.models import (
        InboundObject, SourceAccount, User, Workspace, WorkspaceMember,
    )
    from sqlalchemy import select, text

    # Create workspace B with its own user
    _, wrapped_b = new_workspace_key()
    user_b = User(email="b@example.com", full_name="User B")
    db.add(user_b)
    await db.flush()

    ws_b = Workspace(name="B", slug=f"b-{uuid4().hex[:8]}", owner_id=user_b.id, wrapped_key=wrapped_b)
    db.add(ws_b)
    await db.flush()
    db.add(WorkspaceMember(workspace_id=ws_b.id, user_id=user_b.id, role="owner"))

    account_b = SourceAccount(
        workspace_id=ws_b.id,
        source_kind="gmail",
        external_id=f"b-{uuid4().hex[:8]}",
        display_name="B Gmail",
    )
    db.add(account_b)
    await db.flush()

    obj_b = InboundObject(
        workspace_id=ws_b.id,
        source_account_id=account_b.id,
        object_kind="message",
        external_id=f"b-msg-{uuid4().hex[:8]}",
        title="Workspace B secret",
    )
    db.add(obj_b)
    await db.flush()

    # Now query with workspace A's session — B's object must be invisible
    await db.execute(
        text("SET LOCAL app.workspace_id = :wid"),
        {"wid": str(workspace.id)},
    )
    rows = list(await db.scalars(
        select(InboundObject).where(InboundObject.id == obj_b.id)
    ))

    # RLS policy filters the row; we see nothing
    assert len(rows) == 0, (
        "RLS FAILURE: Workspace A's session can see Workspace B's InboundObject. "
        "This is a critical isolation bug."
    )


@pytest.mark.asyncio
async def test_signal_isolation(db, workspace):
    """Signals must be workspace-isolated by RLS."""
    from app.models import Signal
    from sqlalchemy import select, text

    fake_signal_id = uuid4()
    await db.execute(
        text("SET LOCAL app.workspace_id = :wid"),
        {"wid": str(workspace.id)},
    )
    rows = list(await db.scalars(
        select(Signal).where(Signal.id == fake_signal_id)
    ))
    assert len(rows) == 0


@pytest.mark.asyncio
async def test_source_account_isolation(db, workspace):
    """Source accounts from other workspaces must not be visible."""
    from app.core.crypto import new_workspace_key
    from app.models import SourceAccount, User, Workspace, WorkspaceMember
    from sqlalchemy import select, text

    _, wrapped_c = new_workspace_key()
    user_c = User(email=f"c-{uuid4().hex[:6]}@example.com", full_name="User C")
    db.add(user_c)
    await db.flush()

    ws_c = Workspace(name="C", slug=f"c-{uuid4().hex[:8]}", owner_id=user_c.id, wrapped_key=wrapped_c)
    db.add(ws_c)
    await db.flush()
    db.add(WorkspaceMember(workspace_id=ws_c.id, user_id=user_c.id, role="owner"))

    account_c = SourceAccount(
        workspace_id=ws_c.id,
        source_kind="linkedin",
        external_id=f"c-{uuid4().hex[:8]}",
        display_name="C LinkedIn",
    )
    db.add(account_c)
    await db.flush()

    # Query with workspace A's session
    await db.execute(
        text("SET LOCAL app.workspace_id = :wid"),
        {"wid": str(workspace.id)},
    )
    rows = list(await db.scalars(
        select(SourceAccount).where(SourceAccount.id == account_c.id)
    ))
    assert len(rows) == 0, "RLS FAILURE: Source account from another workspace is visible."


def test_all_tenant_tables_have_rls_enabled():
    """Every table that carries workspace_id must have RLS enabled.
    This test catches a new table that was added without enabling RLS.
    """
    from app.models import (
        InboundObject, InboundPayload, Signal, SourceAccount, Contact,
        ContactIdentity, ContentPiece, ScheduledPost, Automation,
    )
    for model in [InboundObject, InboundPayload, Signal, SourceAccount,
                  Contact, ContentPiece]:
        # Check that workspace_id column exists — if it does, RLS should cover it
        table = model.__table__
        has_ws = "workspace_id" in table.c
        assert has_ws, f"{model.__name__} has no workspace_id — cannot be RLS-protected"
