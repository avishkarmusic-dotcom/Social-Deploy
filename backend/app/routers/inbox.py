"""Universal Inbox — one read model over every connected channel.

The endpoint that defines the product. `sort=opportunity` is the reason this
isn't a mail client: an inbox ordered by arrival time treats a newsletter and a
term sheet as equals, and the whole point here is that they aren't.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.deps import AI, DB, CurrentUser, audit, rate_limit, workspace_key
from app.core.errors import NotFound, ValidationFailed
from app.models import AIDraft, SourceAccount, InboundPayload, InboundObject, Signal
from app.services.intelligence import TONES, draft_reply

router = APIRouter(prefix="/v1/inbox", tags=["inbox"])

Sort = Literal["newest", "opportunity", "urgency"]
Tone = Literal[tuple(TONES)]  # type: ignore[valid-type]


class ThreadOut(BaseModel):
    id: UUID
    channel: str
    subject: str | None
    snippet: str
    sender: str
    unread: bool
    starred: bool
    last_activity_at: datetime
    category: str | None = None
    opportunity_score: int = 0
    opportunity_kind: str | None = None
    urgency: int = 0
    summary: str | None = None
    action_items: list[str] = []


class Page(BaseModel):
    items: list[ThreadOut]
    next_cursor: str | None
    unread_total: int


@router.get("", response_model=Page, summary="List threads")
async def list_threads(
    user: CurrentUser,
    db: DB,
    channel: Annotated[list[str] | None, Query()] = None,
    category: Annotated[list[str] | None, Query()] = None,
    state: str = "open",
    min_opportunity: int = 0,
    sort: Sort = "newest",
    cursor: str | None = None,
    limit: int = Query(50, le=200),
) -> Page:
    stmt = (
        select(InboundObject)
        .join(SourceAccount, SourceAccount.id == InboundObject.source_account_id)
        .options(
            selectinload(InboundObject.signals),
            selectinload(InboundObject.source_account),
            selectinload(InboundObject.payloads),
        )
        .where(InboundObject.workspace_id == user.workspace_id, InboundObject.state == state)
    )
    if channel:
        stmt = stmt.where(SourceAccount.source_kind.in_(channel))

    # Only join intelligence when a filter or sort actually needs it — the
    # default listing is the hot path and shouldn't pay for a join it ignores.
    if category or min_opportunity or sort in {"opportunity", "urgency"}:
        stmt = stmt.join(
            Signal, Signal.object_id == InboundObject.id
        )
        if category:
            stmt = stmt.where(Signal.category.in_(category))
        if min_opportunity:
            stmt = stmt.where(Signal.opportunity_score >= min_opportunity)

    if cursor:
        try:
            stmt = stmt.where(InboundObject.last_activity_at < datetime.fromisoformat(cursor))
        except ValueError as exc:
            raise ValidationFailed(
                "That cursor isn't a valid timestamp.",
                fix="Drop the cursor parameter to start from the top.",
            ) from exc

    order = {
        "newest": InboundObject.last_activity_at.desc(),
        "opportunity": Signal.opportunity_score.desc(),
        "urgency": Signal.urgency.desc(),
    }[sort]

    rows = list((await db.scalars(stmt.order_by(order).limit(limit + 1))).unique())
    has_more = len(rows) > limit
    rows = rows[:limit]

    unread_total = await db.scalar(
        select(func.count(InboundObject.id)).where(
            InboundObject.workspace_id == user.workspace_id,
            InboundObject.state == "open",
            InboundObject.is_unread.is_(True),
        )
    )
    return Page(
        items=[_present(t) for t in rows],
        next_cursor=rows[-1].last_activity_at.isoformat() if has_more and rows else None,
        unread_total=unread_total or 0,
    )


class ThreadDetail(ThreadOut):
    messages: list[dict]


@router.get("/{thread_id}", response_model=ThreadDetail, summary="One thread")
async def get_thread(thread_id: UUID, user: CurrentUser, db: DB) -> ThreadDetail:
    thread = await _load(db, thread_id, user.workspace_id)
    key = await workspace_key(db, user)
    return ThreadDetail(
        **_present(thread).model_dump(),
        messages=[
            {
                "id": str(m.id),
                "author": m.actor_name,
                "direction": m.direction,
                "sent_at": m.sent_at.isoformat(),
                "body": m.decrypt(key),
            }
            for m in thread.payloads
        ],
    )


class DraftIn(BaseModel):
    tone: Tone = "professional"
    length: Literal["shorter", "same", "longer"] = "same"
    translate_to: str | None = None


class DraftOut(BaseModel):
    draft_id: UUID
    body: str
    tone: str


@router.post(
    "/{thread_id}/draft",
    response_model=DraftOut,
    summary="Draft a reply",
    dependencies=[rate_limit(burst=20, per_second=0.5, cost=1)],
)
async def draft(thread_id: UUID, payload: DraftIn, user: CurrentUser, db: DB, ai: AI) -> DraftOut:
    thread = await _load(db, thread_id, user.workspace_id)
    key = await workspace_key(db, user)

    transcript = thread.transcript(key)
    if payload.translate_to:
        transcript += f"\n\nWrite the reply in {payload.translate_to}."

    body = await draft_reply(
        ai,
        thread_text=transcript,
        tone=payload.tone,
        voice_samples=await _voice_samples(db, user.workspace_id),
        length=payload.length,
    )
    row = AIDraft(
        workspace_id=user.workspace_id, object_id=thread.id,
        tone=payload.tone, body=body, created_by=user.user_id,
    )
    db.add(row)
    await db.flush()
    return DraftOut(draft_id=row.id, body=body, tone=payload.tone)


class StateIn(BaseModel):
    state: Literal["open", "snoozed", "archived", "done", "spam"]
    snoozed_until: datetime | None = None


@router.post("/{thread_id}/state", summary="Change thread state")
async def set_state(
    thread_id: UUID, payload: StateIn, user: CurrentUser, db: DB, request: Request
) -> dict:
    thread = await _load(db, thread_id, user.workspace_id)
    if payload.state == "snoozed" and payload.snoozed_until is None:
        raise ValidationFailed(
            "Snoozing needs a time to wake up.",
            fix="Send snoozed_until, or pick a different state.",
        )
    thread.state = payload.state
    thread.snoozed_until = payload.snoozed_until
    if payload.state != "open":
        thread.is_unread = False
    await audit(
        db, user, action="obj.state", resource="thread",
        resource_id=str(thread_id), request=request, to=payload.state,
    )
    return {"id": str(thread_id), "state": thread.state}


# ── helpers ──────────────────────────────────────────────────────────────
async def _load(db, thread_id: UUID, workspace_id: UUID) -> InboundObject:
    thread = await db.scalar(
        select(InboundObject)
        .options(
            selectinload(InboundObject.payloads),
            selectinload(InboundObject.signals),
            selectinload(InboundObject.source_account),
        )
        .where(InboundObject.id == thread_id, InboundObject.workspace_id == workspace_id)
    )
    if thread is None:
        raise NotFound("thread", str(thread_id))
    return thread


def _present(t: InboundObject) -> ThreadOut:
    intel = t.current_signal
    last = t.payloads[-1] if t.payloads else None
    return ThreadOut(
        id=t.id,
        channel=str(t.source_account.source_kind),
        subject=t.title,
        snippet=t.snippet or "",
        sender=last.actor_name if last else "",
        unread=t.is_unread,
        starred=t.is_starred,
        last_activity_at=t.last_activity_at,
        category=intel.category if intel else None,
        opportunity_score=intel.opportunity_score if intel else 0,
        opportunity_kind=intel.opportunity_kind if intel else None,
        urgency=intel.urgency if intel else 0,
        summary=intel.summary if intel else None,
        action_items=list(intel.action_items) if intel else [],
    )


async def _voice_samples(db, workspace_id: UUID) -> list[str]:
    """Replies the user actually sent. These are the style guide — a model
    imitating five real messages beats any adjective in a prompt."""
    rows = await db.scalars(
        select(AIDraft.edited_body)
        .where(
            AIDraft.workspace_id == workspace_id,
            AIDraft.accepted.is_(True),
            AIDraft.edited_body.isnot(None),
        )
        .order_by(AIDraft.created_at.desc())
        .limit(5)
    )
    return [r for r in rows if r]
