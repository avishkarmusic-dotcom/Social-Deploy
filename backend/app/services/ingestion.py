"""Where a normalised thread becomes a row, exactly once.

Providers replay. Webhooks arrive twice. A sync that timed out halfway gets
retried from the same cursor. So this path is written to be safe to run again
with the same input and produce no second row and no second notification.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.base import NormalizedObject
from app.core.crypto import seal, unwrap
from app.models import SourceAccount, InboundPayload
from app.services.identity import resolve

log = structlog.get_logger()


@dataclass
class IngestOutcome:
    threads_created: int = 0
    messages_created: int = 0
    objects_created: int = 0
    payloads_created: int = 0
    contacts_created: int = 0
    needs_signals: list[str] = field(default_factory=list)


async def ingest(
    db: AsyncSession, *, account: SourceAccount, objects: list[NormalizedObject], key: bytes
) -> IngestOutcome:
    out = IngestOutcome()

    for nt in objects:
        counterpart = nt.counterpart
        contact_id = None
        if counterpart:
            res = await resolve(
                db, workspace_id=account.workspace_id,
                source_kind=account.source_kind, author=counterpart,
            )
            contact_id = res.contact.id
            out.contacts_created += int(res.created)
            if not res.created and res.confidence < 0.99:
                log.info("identity.merged", basis=res.basis, confidence=res.confidence)

        # ON CONFLICT DO UPDATE, not DO NOTHING: a replayed thread usually
        # carries a newer last_activity_at, and we want that without a second row.
        stmt = (
            insert(InboundObject)
            .values(
                workspace_id=account.workspace_id,
                source_account_id=account.id,
                contact_id=contact_id,
                object_kind=nt.object_kind,
                external_id=nt.external_id,
                title=nt.subject,
                snippet=nt.snippet,
                payload={},
                is_unread=nt.is_unread,
                last_activity_at=nt.last_activity_at,
                payload_count=len(nt.payloads),
            )
            .on_conflict_do_update(
                index_elements=[InboundObject.source_account_id, InboundObject.external_id],
                set_={
                    "snippet": nt.snippet,
                    "last_activity_at": nt.last_activity_at,
                    "is_unread": nt.is_unread,
                    "payload_count": len(nt.payloads),
                },
            )
            .returning(InboundObject.id, InboundObject.created_at, InboundObject.last_activity_at)
        )
        row = (await db.execute(stmt)).one()
        object_id, created_at, last_act = row
        is_new = created_at == last_act or await _is_new(db, object_id)
        out.objects_created += int(is_new)

        added = 0
        for m in nt.payloads:
            msg = (
                insert(InboundPayload)
                .values(
                    workspace_id=account.workspace_id,
                    object_id=object_id,
                    external_id=m.external_id,
                    direction=m.direction,
                    actor_name=m.author.name,
                    actor_handle=m.author.handle,
                    # Bodies are sealed with the workspace key and bound to the
                    # thread, so a leaked row can't be decrypted out of context.
                    body_enc=seal(m.body_text, key, aad=str(object_id)),
                    action_ref=m.action_ref,
                    body_html=m.body_html,
                    attachments=m.attachments,
                    sent_at=m.sent_at,
                )
                .on_conflict_do_nothing(
                    index_elements=[InboundPayload.object_id, InboundPayload.external_id]
                )
                .returning(InboundPayload.id)
            )
            if (await db.execute(msg)).scalar() is not None:
                added += 1

        out.payloads_created += added
        # Only score threads that actually changed. Re-scoring an unchanged
        # thread costs money and produces the same answer.
        if added:
            out.needs_signals.append(str(object_id))

    await db.commit()
    return out


async def _is_new(db: AsyncSession, thread_id) -> bool:
    return (
        await db.scalar(select(InboundObject.message_count).where(InboundObject.id == thread_id))
    ) == 0


def workspace_key(account: SourceAccount) -> bytes:
    return unwrap(account.workspace.wrapped_key)


__all__ = ["IngestOutcome", "ingest", "workspace_key"]
