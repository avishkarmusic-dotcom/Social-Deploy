"""Automation rules — create, test, inspect.

The `/test` endpoint exists because a rule that fires on the wrong thread at
3am is expensive to discover. Dry-running it against real recent threads before
enabling turns that from an incident into a preview.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.deps import DB, CurrentUser, audit, workspace_key
from app.core.errors import NotFound, ValidationFailed
from app.models import Automation, AutomationRun, InboundObject, Signal
from app.services.automations import (
    ACTIONS, FACTS, OPS, RuleInvalid, facts_for, matches, validate, run_for_object,
)

router = APIRouter(prefix="/v1/automations", tags=["automations"])


class Filter(BaseModel):
    field: str
    op: str
    value: Any


class Trigger(BaseModel):
    event: str = "thread.scored"
    filters: list[Filter] = Field(default_factory=list)


class Action(BaseModel):
    type: str
    params: dict[str, Any] = Field(default_factory=dict)


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    trigger: Trigger
    actions: list[Action]


class RuleOut(BaseModel):
    id: UUID
    name: str
    enabled: bool
    trigger: dict
    actions: list[dict]
    run_count: int
    last_run_at: datetime | None


@router.get("/vocabulary", summary="What rules can check and do")
async def vocabulary(user: CurrentUser) -> dict:
    """Lets the builder UI render only valid options, so an invalid rule is
    impossible to compose rather than merely rejected on save."""
    return {
        "events": ["thread.scored", "review.created", "post.published"],
        "fields": sorted(FACTS),
        "operators": sorted(OPS),
        "actions": sorted(ACTIONS),
    }


@router.get("", response_model=list[RuleOut], summary="List rules")
async def list_rules(user: CurrentUser, db: DB) -> list[RuleOut]:
    rows = await db.scalars(
        select(Automation)
        .where(Automation.workspace_id == user.workspace_id)
        .order_by(Automation.created_at.desc())
    )
    return [_present(r) for r in rows]


@router.post("", response_model=RuleOut, status_code=201, summary="Create a rule")
async def create_rule(
    payload: RuleIn, user: CurrentUser, db: DB, request: Request
) -> RuleOut:
    trigger = payload.trigger.model_dump()
    actions = [a.model_dump() for a in payload.actions]
    try:
        validate(trigger, actions)
    except RuleInvalid as exc:
        raise ValidationFailed(str(exc), fix="Check /v1/automations/vocabulary.") from exc

    rule = Automation(
        workspace_id=user.workspace_id, name=payload.name,
        enabled=payload.enabled, trigger=trigger, actions=actions,
    )
    db.add(rule)
    await db.flush()
    await audit(
        db, user, action="automation.create", resource="automation",
        resource_id=str(rule.id), request=request, name=payload.name,
    )
    return _present(rule)


@router.patch("/{rule_id}", response_model=RuleOut, summary="Update a rule")
async def update_rule(
    rule_id: UUID, payload: RuleIn, user: CurrentUser, db: DB, request: Request
) -> RuleOut:
    rule = await _load(db, rule_id, user.workspace_id)
    trigger = payload.trigger.model_dump()
    actions = [a.model_dump() for a in payload.actions]
    try:
        validate(trigger, actions)
    except RuleInvalid as exc:
        raise ValidationFailed(str(exc), fix="Check /v1/automations/vocabulary.") from exc
    rule.name, rule.enabled, rule.trigger, rule.actions = (
        payload.name, payload.enabled, trigger, actions
    )
    await audit(
        db, user, action="automation.update", resource="automation",
        resource_id=str(rule_id), request=request,
    )
    return _present(rule)


class TestResult(BaseModel):
    would_fire_on: list[dict]
    checked: int
    note: str


@router.post("/test", response_model=TestResult, summary="Dry-run a rule")
async def test_rule(
    payload: RuleIn, user: CurrentUser, db: DB, sample: int = Query(50, le=200)
) -> TestResult:
    """Runs the rule's *matching* against recent threads without executing any
    action. Nothing is sent, tagged or notified."""
    trigger = payload.trigger.model_dump()
    try:
        validate(trigger, [a.model_dump() for a in payload.actions])
    except RuleInvalid as exc:
        raise ValidationFailed(str(exc), fix="Check /v1/automations/vocabulary.") from exc

    threads = list((await db.scalars(
        select(InboundObject)
        .options(
            selectinload(InboundObject.payloads),
            selectinload(InboundObject.signals),
            selectinload(InboundObject.source_account),
            selectinload(InboundObject.contact),
        )
        .where(InboundObject.workspace_id == user.workspace_id)
        .order_by(InboundObject.last_activity_at.desc())
        .limit(sample)
    )).unique())

    key = await workspace_key(db, user)
    fired = [
        {
            "thread_id": str(t.id),
            "subject": t.subject,
            "from": t.messages[-1].author_name if t.messages else "",
            "opportunity": t.current_intel.opportunity_score if t.current_intel else 0,
        }
        for t in threads
        if matches(trigger, facts_for(t, key))
    ]
    return TestResult(
        would_fire_on=fired,
        checked=len(threads),
        note=(
            f"Matched {len(fired)} of your last {len(threads)} threads. "
            "No actions were run."
        ),
    )


@router.get("/{rule_id}/runs", summary="Run history")
async def runs(
    rule_id: UUID, user: CurrentUser, db: DB, limit: int = Query(50, le=200)
) -> list[dict]:
    await _load(db, rule_id, user.workspace_id)
    rows = await db.scalars(
        select(AutomationRun)
        .where(AutomationRun.automation_id == rule_id)
        .order_by(AutomationRun.ran_at.desc())
        .limit(limit)
    )
    return [
        {
            "id": r.id,
            "status": r.status,
            "thread_id": str(r.thread_id) if r.thread_id else None,
            "detail": r.detail,
            "ran_at": r.ran_at.isoformat(),
        }
        for r in rows
    ]


@router.delete("/{rule_id}", summary="Delete a rule")
async def delete_rule(
    rule_id: UUID, user: CurrentUser, db: DB, request: Request
) -> dict:
    rule = await _load(db, rule_id, user.workspace_id)
    await audit(
        db, user, action="automation.delete", resource="automation",
        resource_id=str(rule_id), request=request, name=rule.name,
    )
    await db.delete(rule)
    return {"deleted": str(rule_id)}


def _present(r: Automation) -> RuleOut:
    return RuleOut(
        id=r.id, name=r.name, enabled=r.enabled, trigger=r.trigger,
        actions=r.actions, run_count=r.run_count, last_run_at=r.last_run_at,
    )


async def _load(db, rule_id: UUID, workspace_id: UUID) -> Automation:
    rule = await db.scalar(
        select(Automation).where(
            Automation.id == rule_id, Automation.workspace_id == workspace_id
        )
    )
    if rule is None:
        raise NotFound("automation", str(rule_id))
    return rule
