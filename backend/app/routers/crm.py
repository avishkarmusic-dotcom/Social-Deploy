"""Personal CRM.

The useful view here isn't "all my contacts" — it's "who am I losing". So the
default sort is by decay risk: importance the user assigned, weighted against
how long the silence has run.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.deps import DB, CurrentUser, audit, workspace_key
from app.core.errors import NotFound
from app.models import Contact, ContactIdentity, InboundPayload, InboundObject

router = APIRouter(prefix="/v1/contacts", tags=["crm"])


class ContactOut(BaseModel):
    id: UUID
    display_name: str
    company: str | None
    title: str | None
    primary_email: str | None
    tags: list[str]
    importance: int
    relationship_strength: int
    last_interaction_at: datetime | None
    next_followup_at: datetime | None
    days_silent: int | None
    channels: list[str] = []


@router.get("", response_model=list[ContactOut], summary="List people")
async def list_contacts(
    user: CurrentUser,
    db: DB,
    sort: Literal["decay_risk", "strength", "importance", "recent", "name"] = "decay_risk",
    tag: str | None = None,
    limit: int = Query(50, le=200),
) -> list[ContactOut]:
    stmt = (
        select(Contact)
        .options(selectinload(Contact.identities))
        .where(Contact.workspace_id == user.workspace_id)
    )
    if tag:
        stmt = stmt.where(Contact.tags.any(tag))

    if sort == "decay_risk":
        # Importance you set, discounted by silence. A VIP you last spoke to in
        # March outranks a acquaintance you messaged yesterday.
        risk = Contact.importance * func.least(
            func.extract("epoch", func.now() - func.coalesce(
                Contact.last_interaction_at, func.now()
            )) / 86400.0, 120.0
        )
        stmt = stmt.order_by(risk.desc())
    else:
        stmt = stmt.order_by({
            "strength": Contact.relationship_strength.desc(),
            "importance": Contact.importance.desc(),
            "recent": Contact.last_interaction_at.desc(),
            "name": Contact.display_name.asc(),
        }[sort])

    rows = list((await db.scalars(stmt.limit(limit))).unique())
    return [_present(c) for c in rows]


@router.get("/followups", response_model=list[ContactOut], summary="Who's due")
async def followups(user: CurrentUser, db: DB, within_days: int = 7) -> list[ContactOut]:
    rows = await db.scalars(
        select(Contact)
        .options(selectinload(Contact.identities))
        .where(
            Contact.workspace_id == user.workspace_id,
            Contact.next_followup_at.isnot(None),
            Contact.next_followup_at <= datetime.now(UTC) + timedelta(days=within_days),
        )
        .order_by(Contact.next_followup_at.asc())
    )
    return [_present(c) for c in rows]


class TimelineEntry(BaseModel):
    thread_id: UUID
    channel: str
    subject: str | None
    direction: str
    body: str
    sent_at: datetime


@router.get("/{contact_id}/timeline", response_model=list[TimelineEntry],
            summary="Everything you've ever exchanged")
async def timeline(
    contact_id: UUID, user: CurrentUser, db: DB, limit: int = Query(50, le=200)
) -> list[TimelineEntry]:
    contact = await _load(db, contact_id, user.workspace_id)
    key = await workspace_key(db, user)
    rows = await db.execute(
        select(InboundPayload, InboundObject)
        .join(InboundObject, InboundObject.id == InboundPayload.object_id)
        .options(selectinload(InboundObject.source_account))
        .where(InboundObject.contact_id == contact.id)
        .order_by(InboundPayload.sent_at.desc())
        .limit(limit)
    )
    return [
        TimelineEntry(
            thread_id=t.id,
            channel=str(t.source_account.source_kind),
            subject=t.subject,
            direction=m.direction,
            body=m.decrypt(key),
            sent_at=m.sent_at,
        )
        for m, t in rows
    ]


class ContactPatch(BaseModel):
    notes: str | None = None
    tags: list[str] | None = None
    importance: int | None = Field(default=None, ge=0, le=100)
    company: str | None = None
    title: str | None = None
    next_followup_at: datetime | None = None


@router.patch("/{contact_id}", response_model=ContactOut, summary="Update a person")
async def update_contact(
    contact_id: UUID, payload: ContactPatch, user: CurrentUser, db: DB, request: Request
) -> ContactOut:
    contact = await _load(db, contact_id, user.workspace_id)
    changed = payload.model_dump(exclude_unset=True, exclude_none=True)
    for field, value in changed.items():
        setattr(contact, field, value)
    await audit(
        db, user, action="contact.update", resource="contact",
        resource_id=str(contact_id), request=request, fields=list(changed),
    )
    await db.flush()
    return _present(contact)


class MergeIn(BaseModel):
    absorb_id: UUID


@router.post("/{contact_id}/merge", summary="Merge two people into one")
async def merge(
    contact_id: UUID, payload: MergeIn, user: CurrentUser, db: DB, request: Request
) -> dict:
    """Merging is user-initiated by design.

    The resolver never merges on a weak signal, because a wrong merge is close
    to unrecoverable. This endpoint is where a human takes that responsibility,
    and the audit row records who did.
    """
    keeper = await _load(db, contact_id, user.workspace_id)
    absorbed = await _load(db, payload.absorb_id, user.workspace_id)

    await db.execute(
        InboundObject.__table__.update()
        .where(InboundObject.contact_id == absorbed.id)
        .values(contact_id=keeper.id)
    )
    await db.execute(
        ContactIdentity.__table__.update()
        .where(ContactIdentity.contact_id == absorbed.id)
        .values(contact_id=keeper.id)
    )
    keeper.tags = sorted(set(keeper.tags) | set(absorbed.tags))
    keeper.notes = "\n\n".join(filter(None, [keeper.notes, absorbed.notes])) or None
    keeper.importance = max(keeper.importance, absorbed.importance)
    if absorbed.last_interaction_at and (
        not keeper.last_interaction_at
        or absorbed.last_interaction_at > keeper.last_interaction_at
    ):
        keeper.last_interaction_at = absorbed.last_interaction_at

    await audit(
        db, user, action="contact.merge", resource="contact",
        resource_id=str(keeper.id), request=request, absorbed=str(absorbed.id),
        absorbed_name=absorbed.display_name,
    )
    await db.delete(absorbed)
    return {"kept": str(keeper.id), "absorbed": str(absorbed.id)}


def _present(c: Contact) -> ContactOut:
    silent = (
        (datetime.now(UTC) - c.last_interaction_at).days
        if c.last_interaction_at else None
    )
    return ContactOut(
        id=c.id,
        display_name=c.display_name,
        company=c.company,
        title=c.title,
        primary_email=c.primary_email,
        tags=list(c.tags),
        importance=c.importance,
        relationship_strength=c.relationship_strength,
        last_interaction_at=c.last_interaction_at,
        next_followup_at=c.next_followup_at,
        days_silent=silent,
        channels=sorted({str(i.kind) for i in c.identities}),
    )


async def _load(db, contact_id: UUID, workspace_id: UUID) -> Contact:
    contact = await db.scalar(
        select(Contact)
        .options(selectinload(Contact.identities))
        .where(Contact.id == contact_id, Contact.workspace_id == workspace_id)
    )
    if contact is None:
        raise NotFound("contact", str(contact_id))
    return contact
