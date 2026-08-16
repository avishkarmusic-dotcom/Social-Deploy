"""Background jobs. arq over Redis — one queue, four job types.

Ordering matters and is enforced by the chain, not by hope:
    sync/webhook → ingest → score → notify → automate
A thread is never announced to the UI before it has been scored, because an
unscored thread in a priority inbox is worse than a late one.
"""
from __future__ import annotations

import asyncio

import structlog
from arq import cron
from arq.connections import RedisSettings

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.connectors.base import ConnectorError
from app.connectors.registry import get, load_all, pollable
from app.core.config import settings
from app.core.db import sessionmaker
from app.core.ratelimit import ProviderBudget, RateLimiter
from app.services.ai_router import AIRouter
from app.services.automations import run_for_object
from app.services.ingestion import ingest, workspace_key
from app.services.intelligence import analyse
from app.models import SourceAccount, InboundObject, InboundPayload, Signal
from app.services.realtime import publish_event

log = structlog.get_logger()


async def sync_account(ctx: dict, account_id: str) -> dict:
    budget: ProviderBudget = ctx["budget"]
    async with sessionmaker() as db:
        account = await _load(db, account_id)
        adapter = get(account.source_kind)

        wait = await budget.acquire(account.source_kind, str(account.id))
        if wait > 0:
            await ctx["redis"].enqueue_job("sync_account", account_id, _defer_by=int(wait))
            return {"deferred": wait}

        try:
            result = await adapter.sync(
                access_token=await _token(db, account),
                cursor=account.sync_cursor,
                limit=adapter.page_size,
            )
        except ConnectorError as exc:
            account.status = "error" if not exc.retryable else account.status
            account.last_error = exc.message
            await db.commit()
            log.warning("sync.failed", channel=account.source_kind, fix=exc.fix)
            return {"error": exc.message}

        if result.retry_after_s:
            await budget.penalise(account.source_kind, str(account.id), result.retry_after_s)

        outcome = await ingest(
            db, account=account, threads=result.threads, key=workspace_key(account)
        )
        account.sync_cursor = result.cursor or account.sync_cursor
        account.last_synced_at = datetime.now(UTC)
        await db.commit()

    for object_id in outcome.needs_signals:
        await ctx["redis"].enqueue_job("score_object", object_id)
    if result.has_more:
        await ctx["redis"].enqueue_job("sync_account", account_id)
    return {"threads": outcome.threads_created, "messages": outcome.messages_created}


async def score_object(ctx: dict, object_id: str) -> dict:
    """Classify, then announce. The UI learns about the thread here, not earlier."""
    async with sessionmaker() as db:
        obj = await _load_object(db, object_id)
        intel, meta = await analyse(
            ctx["ai"],
            channel=obj.source_account.source_kind,
            sender=obj.payloads[-1].actor_name,
            body=obj.transcript(obj.source_account.workspace.data_key, limit=3),
        )
        obj.record_signal(intel, meta)
        await db.commit()
        await publish_event(ctx["redis"], obj.workspace_id, "thread.scored", {
            "object_id": object_id,
            "opportunity_score": intel.opportunity_score,
            "urgency": intel.urgency,
            "category": intel.category,
            "summary": intel.summary,
        })
    await ctx["redis"].enqueue_job("run_automations", object_id)
    return {"score": intel.opportunity_score, "cost": meta["cost_usd"]}


async def run_automations(ctx: dict, object_id: str) -> dict:
    async with sessionmaker() as db:
        fired = await run_for_object(db, ctx, object_id)
    return {"fired": fired}


async def poll_due_accounts(ctx: dict) -> None:
    """Every 30s, enqueue whichever polled accounts are due. Push channels never
    appear here — they arrive on their own."""
    kinds = [a.kind for a in pollable()]
    async with sessionmaker() as db:
        due = await _due_accounts(db, kinds)
    for account_id in due:
        await ctx["redis"].enqueue_job("sync_account", str(account_id))


async def startup(ctx: dict) -> None:
    load_all()
    limiter = await RateLimiter.create(settings.redis_url)
    ctx["limiter"] = limiter
    ctx["budget"] = ProviderBudget(limiter, limiter._redis)
    ctx["ai"] = AIRouter()


async def shutdown(ctx: dict) -> None:
    await ctx["limiter"].close()


# ── helpers the jobs above lean on ──────────────────────────────────────────
async def _load(db, account_id: str) -> SourceAccount:
    account = await db.scalar(
        select(SourceAccount)
        .options(selectinload(SourceAccount.workspace))
        .where(SourceAccount.id == account_id)
    )
    if account is None:
        raise LookupError(f"Channel account {account_id} no longer exists")
    return account


async def _token(db, account: SourceAccount) -> str:
    """Returns a live token, refreshing first if it is about to expire.

    Refreshing five minutes early rather than on failure means a long sync
    never dies halfway through with half its pages ingested.
    """
    key = account.workspace.data_key
    if account.needs_refresh and (refresh := account.refresh_token(key)):
        bundle = await get(account.source_kind).refresh(refresh)
        account.set_tokens(bundle.access_token, bundle.refresh_token or refresh, key)
        account.token_expires = bundle.expires_at
        await db.commit()
    return account.access_token(key)


async def _load_object(db, object_id: str) -> InboundObject:
    thread = await db.scalar(
        select(InboundObject)
        .options(
            selectinload(InboundObject.payloads),
            selectinload(InboundObject.signals),
            selectinload(InboundObject.source_account).selectinload(SourceAccount.workspace),
        )
        .where(InboundObject.id == object_id)
    )
    if thread is None:
        raise LookupError(f" {object_id} no longer exists")
    return thread


async def _due_accounts(db, kinds: list[str]) -> list:
    """Accounts whose poll interval has elapsed. Push channels never appear."""
    now = datetime.now(UTC)
    result = await db.execute(
        select(SourceAccount.id, SourceAccount.source_kind, SourceAccount.last_synced_at)
        .where(SourceAccount.source_kind.in_(kinds), SourceAccount.status == "connected")
    )
    return [
        account_id
        for account_id, kind, last in result
        if last is None or (now - last).total_seconds() >= get(kind).poll_interval_s
    ]


class WorkerSettings:
    functions = [sync_account, score_object, run_automations]
    cron_jobs = [cron(poll_due_accounts, second={0, 30})]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 20
    job_timeout = 120
    # Providers fail in bursts. Retry generously but never forever.
    max_tries = 4
    retry_jobs = True
