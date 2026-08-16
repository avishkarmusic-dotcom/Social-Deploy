"""Deciding whether two handles are the same person.

This is the load-bearing decision in the CRM, and it is asymmetric: a duplicate
contact is a mild annoyance the user can merge in two clicks, while a wrong
merge silently mixes two people's history and is close to unrecoverable. So the
resolver only merges on evidence it can defend, and creates a new contact
whenever it can't.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.base import Author
from app.models import Contact, ContactIdentity

MERGE_THRESHOLD = 0.90


@dataclass
class Resolution:
    contact: Contact
    created: bool
    confidence: float
    basis: str          # shown in the UI when a merge is questioned


async def resolve(
    db: AsyncSession, *, workspace_id, source_kind: str, author: Author
) -> Resolution:
    # 1. The same handle on the same channel is the same person. No judgement
    #    needed — the provider already guaranteed it.
    if author.handle:
        stmt = (
            select(Contact)
            .join(ContactIdentity)
            .where(ContactIdentity.source_kind == source_kind, ContactIdentity.handle == author.handle,
                   Contact.workspace_id == workspace_id)
        )
        if found := await db.scalar(stmt):
            return Resolution(found, False, 1.0, "same handle on the same channel")

    # 2. A verified email is the strongest cross-channel evidence there is.
    if author.email:
        stmt = select(Contact).where(
            Contact.workspace_id == workspace_id,
            Contact.primary_email == author.email.lower(),
        )
        if found := await db.scalar(stmt):
            await _link(db, found, source_kind, author.handle)
            return Resolution(found, False, 0.99, "matching email address")

    # 3. Name similarity alone is not evidence. It needs a second signal, and
    #    even then it stays below the threshold on common names.
    candidates = await db.scalars(
        select(Contact).where(Contact.workspace_id == workspace_id)
    )
    best, score, basis = None, 0.0, ""
    for c in candidates:
        s, why = _score(c, author)
        if s > score:
            best, score, basis = c, s, why

    if best is not None and score >= MERGE_THRESHOLD:
        await _link(db, best, source_kind, author.handle)
        return Resolution(best, False, score, basis)

    contact = Contact(
        workspace_id=workspace_id,
        display_name=author.name or author.handle or "Unknown",
        primary_email=author.email.lower() if author.email else None,
        avatar_url=author.avatar_url,
    )
    db.add(contact)
    await db.flush()
    await _link(db, contact, source_kind, author.handle)
    return Resolution(contact, True, 1.0, "no confident match")


def _score(contact: Contact, author: Author) -> tuple[float, str]:
    a, b = _norm(contact.display_name), _norm(author.name)
    if not a or not b:
        return 0.0, ""
    if a == b:
        # Exact name plus a shared domain is defensible. Exact name alone is
        # not — there are four Priya Sharmas in any real address book.
        if author.email and contact.primary_email:
            if author.email.split("@")[-1] == contact.primary_email.split("@")[-1]:
                return 0.95, "same name and same email domain"
        return 0.55, "same name only"
    if _initials(a) == _initials(b) and abs(len(a) - len(b)) <= 3:
        return 0.40, "similar name"
    return 0.0, ""


def _norm(value: str | None) -> str:
    return re.sub(r"[^a-z ]", "", (value or "").lower()).strip()


def _initials(value: str) -> str:
    return "".join(w[0] for w in value.split() if w)


async def _link(db: AsyncSession, contact: Contact, source_kind: str, handle: str | None) -> None:
    if not handle:
        return
    exists = await db.scalar(
        select(ContactIdentity).where(
            ContactIdentity.source_kind == source_kind, ContactIdentity.handle == handle
        )
    )
    if not exists:
        db.add(ContactIdentity(contact_id=contact.id, source_kind=source_kind, handle=handle))
