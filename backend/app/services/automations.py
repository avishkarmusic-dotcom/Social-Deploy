"""The automation engine.

Design constraint that shapes everything here: rules are data, not code. A user
composing "if a review drops below three stars, draft a reply" must never be
able to produce something that executes arbitrary logic on our workers. So a
trigger is a fixed event name plus a list of (field, op, value) comparisons
against a flat, whitelisted fact dictionary, and an action is a name from a
closed registry. There is no expression evaluator anywhere in this file, and
adding one would be the wrong kind of clever.
"""
from __future__ import annotations

import operator
from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Automation, AutomationRun, InboundObject, InboundPayload, Signal
from app.services.realtime import publish_event

log = structlog.get_logger()

OPS: dict[str, Callable[[Any, Any], bool]] = {
    "eq": operator.eq,
    "ne": operator.ne,
    "gt": operator.gt,
    "gte": operator.ge,
    "lt": operator.lt,
    "lte": operator.le,
    "in": lambda a, b: a in b,
    "not_in": lambda a, b: a not in b,
    "contains": lambda a, b: b.lower() in str(a).lower(),
}

# Only these fields can be referenced by a rule. An unknown field is a rule
# authoring bug and must fail loudly at save time, not silently at run time.
FACTS = {
    "channel", "source", "object_kind", "category", "opportunity_score", "opportunity_kind", "urgency",
    "sentiment", "estimated_value_usd", "sender", "subject", "body", "is_unread",
    "rating", "contact_tags", "language",
}


class RuleInvalid(ValueError):
    pass


def validate(trigger: dict, actions: list[dict]) -> None:
    """Called when a rule is saved, so bad rules never reach a worker."""
    if not trigger.get("event"):
        raise RuleInvalid("A rule needs an event to listen for.")
    for f in trigger.get("filters", []):
        if f.get("field") not in FACTS:
            raise RuleInvalid(
                f"'{f.get('field')}' isn't something a rule can check. "
                f"Available: {', '.join(sorted(FACTS))}"
            )
        if f.get("op") not in OPS:
            raise RuleInvalid(f"'{f.get('op')}' isn't a supported comparison.")
    if not actions:
        raise RuleInvalid("A rule that does nothing isn't a rule.")
    for a in actions:
        if a.get("type") not in ACTIONS:
            raise RuleInvalid(f"'{a.get('type')}' isn't an action this can perform.")


def matches(trigger: dict, facts: dict[str, Any]) -> bool:
    """All filters must pass. Missing facts fail closed — a rule never fires on
    data it couldn't actually see."""
    for f in trigger.get("filters", []):
        if (value := facts.get(f["field"])) is None:
            return False
        try:
            if not OPS[f["op"]](value, f["value"]):
                return False
        except TypeError:
            return False
    return True


def facts_for(obj: InboundObject, key: bytes) -> dict[str, Any]:
    intel = obj.current_signal
    last = obj.payloads[-1] if obj.payloads else None
    source = getattr(getattr(obj, "source_account", None), "source_kind", None) or ""
    return {
        "channel": str(source),
        "source": str(source),
        "object_kind": obj.object_kind,
        "category": intel.category if intel else None,
        "opportunity_score": intel.opportunity_score if intel else 0,
        "opportunity_kind": intel.opportunity_kind if intel else None,
        "urgency": intel.urgency if intel else 0,
        "sentiment": intel.sentiment if intel else None,
        "estimated_value_usd": float(intel.estimated_value_usd) if intel and intel.estimated_value_usd else None,
        "language": intel.language if intel else None,
        "sender": last.actor_name if last else None,
        "subject": obj.title,
        "body": last.decrypt(key) if last and last.body_enc else None,
        "is_unread": obj.is_unread,
        "contact_tags": obj.contact.tags if obj.contact else [],
    }


# ── Actions ─────────────────────────────────────────────────────────────────
async def _notify(ctx, db, thread, params) -> dict:
    await publish_event(ctx["redis"], thread.workspace_id, "notification", {
        "thread_id": str(thread.id),
        "title": params.get("title", "Something needs you"),
        "priority": params.get("priority", "normal"),
    })
    return {"notified": True}


async def _draft_reply(ctx, db, thread, params) -> dict:
    """Queues a draft rather than writing one inline.

    An automation must never block on a model call — a slow provider would
    stall every other rule behind it.
    """
    await ctx["redis"].enqueue_job(
        "draft_for_thread", str(thread.id), params.get("tone", "professional")
    )
    return {"queued": True}


async def _tag_contact(ctx, db, thread, params) -> dict:
    if thread.contact is None:
        return {"skipped": "thread has no resolved contact"}
    tag = params["tag"]
    if tag not in thread.contact.tags:
        thread.contact.tags = [*thread.contact.tags, tag]
    return {"tagged": tag}


async def _set_followup(ctx, db, thread, params) -> dict:
    if thread.contact is None:
        return {"skipped": "thread has no resolved contact"}
    thread.contact.next_followup_at = datetime.now(UTC) + timedelta(days=params.get("days", 3))
    return {"followup": thread.contact.next_followup_at.isoformat()}


async def _set_state(ctx, db, thread, params) -> dict:
    thread.state = params["state"]
    return {"state": thread.state}


async def _boost_importance(ctx, db, thread, params) -> dict:
    if thread.contact is None:
        return {"skipped": "thread has no resolved contact"}
    thread.contact.importance = min(100, thread.contact.importance + params.get("by", 15))
    return {"importance": thread.contact.importance}


ACTIONS: dict[str, Callable] = {
    "notify": _notify,
    "draft_reply": _draft_reply,
    "tag_contact": _tag_contact,
    "set_followup": _set_followup,
    "set_state": _set_state,
    "boost_importance": _boost_importance,
}


async def run_for_object(db: AsyncSession, ctx: dict, thread_id: str | UUID) -> int:
    thread = await db.scalar(
        select(InboundObject)
        .options(
            selectinload(InboundObject.payloads),
            selectinload(InboundObject.signals),
            selectinload(InboundObject.source_account),
            selectinload(InboundObject.contact),
        )
        .where(InboundObject.id == thread_id)
    )
    if thread is None:
        return 0

    rules = await db.scalars(
        select(Automation).where(
            Automation.workspace_id == thread.workspace_id, Automation.enabled.is_(True)
        )
    )
    key = thread.source_account.workspace.data_key
    facts = facts_for(thread, key)
    fired = 0

    for rule in rules:
        if rule.trigger.get("event") != "thread.scored":
            continue
        if not matches(rule.trigger, facts):
            db.add(AutomationRun(automation_id=rule.id, object_id=thread.id, status="skipped"))
            continue

        detail: dict[str, Any] = {}
        status = "success"
        for action in rule.actions:
            handler = ACTIONS.get(action["type"])
            if handler is None:
                status = "failed"
                detail[action["type"]] = "unknown action"
                continue
            try:
                detail[action["type"]] = await handler(
                    ctx, db, thread, action.get("params", {})
                )
            except Exception as exc:  # one bad action must not kill the rest
                status = "failed"
                detail[action["type"]] = str(exc)
                log.warning("automation.action_failed", rule=str(rule.id), error=str(exc))

        rule.run_count += 1
        rule.last_run_at = datetime.now(UTC)
        db.add(
            AutomationRun(
                automation_id=rule.id, object_id=thread.id, status=status, detail=detail
            )
        )
        fired += 1

    await db.commit()
    return fired
