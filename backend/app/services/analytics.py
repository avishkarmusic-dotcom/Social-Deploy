"""Computed metrics.

One rule runs through this file: never show a number the data can't support.
Every function that could produce a confident-looking figure from six data
points returns `None` instead, and the UI says "not enough data yet". A wrong
best-time-to-post is worse than no best-time-to-post, because the user acts on
it for months before noticing.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    SourceAccount, Contact, InboundPayload, PostMetric, ScheduledPost, InboundObject,
    Signal,
)

MIN_SAMPLES_FOR_TIMING = 20
MIN_SAMPLES_FOR_RATE = 10


@dataclass
class Metric:
    value: float | int | None
    label: str
    change_pct: float | None = None
    confident: bool = True
    note: str | None = None


async def overview(db: AsyncSession, workspace_id: UUID, days: int = 30) -> dict[str, Metric]:
    since = datetime.now(UTC) - timedelta(days=days)
    prior = since - timedelta(days=days)

    threads_now = await _count_threads(db, workspace_id, since, datetime.now(UTC))
    threads_before = await _count_threads(db, workspace_id, prior, since)

    opportunities = await db.scalar(
        select(func.count(Signal.id)).where(
            Signal.workspace_id == workspace_id,
            Signal.opportunity_score >= 60,
            Signal.created_at >= since,
        )
    ) or 0

    pipeline = await db.scalar(
        select(func.coalesce(func.sum(Signal.estimated_value_usd), 0)).where(
            Signal.workspace_id == workspace_id,
            Signal.opportunity_score >= 60,
            Signal.created_at >= since,
        )
    ) or 0

    return {
        "threads": Metric(threads_now, "Threads received", _pct(threads_now, threads_before)),
        "opportunities": Metric(opportunities, "Worth acting on"),
        "pipeline_usd": Metric(
            float(pipeline), "Estimated pipeline",
            note="Model estimates only. Treat as a ranking signal, not a forecast.",
        ),
        "response_time": await median_response_time(db, workspace_id, since),
        "signal_ratio": await signal_ratio(db, workspace_id, since),
    }


async def median_response_time(db: AsyncSession, workspace_id: UUID, since: datetime) -> Metric:
    """Median, not mean. One thread you forgot for three weeks would drag a
    mean into meaninglessness while the typical experience stayed fine."""
    inbound = (
        select(
            InboundPayload.thread_id.label("tid"),
            func.min(InboundPayload.sent_at).label("asked"),
        )
        .where(
            InboundPayload.workspace_id == workspace_id,
            InboundPayload.direction == "inbound",
            InboundPayload.sent_at >= since,
        )
        .group_by(InboundPayload.thread_id)
        .subquery()
    )
    outbound = (
        select(
            InboundPayload.thread_id.label("tid"),
            func.min(InboundPayload.sent_at).label("answered"),
        )
        .where(InboundPayload.workspace_id == workspace_id, InboundPayload.direction == "outbound")
        .group_by(InboundPayload.thread_id)
        .subquery()
    )
    gaps = await db.execute(
        select(func.extract("epoch", outbound.c.answered - inbound.c.asked) / 3600.0)
        .select_from(inbound)
        .join(outbound, outbound.c.tid == inbound.c.tid)
        .where(outbound.c.answered > inbound.c.asked)
    )
    hours = sorted(g for (g,) in gaps if g is not None)
    if len(hours) < MIN_SAMPLES_FOR_RATE:
        return Metric(
            None, "Median reply time", confident=False,
            note=f"Needs {MIN_SAMPLES_FOR_RATE} replied threads. You have {len(hours)}.",
        )
    mid = len(hours) // 2
    median = hours[mid] if len(hours) % 2 else (hours[mid - 1] + hours[mid]) / 2
    return Metric(round(median, 1), "Median reply time (hours)")


async def signal_ratio(db: AsyncSession, workspace_id: UUID, since: datetime) -> Metric:
    """The headline number: what fraction of what arrived was worth reading."""
    row = await db.execute(
        select(
            func.count(Signal.id),
            func.count(case((Signal.opportunity_score >= 60, 1))),
        ).where(
            Signal.workspace_id == workspace_id,
            Signal.created_at >= since,
        )
    )
    total, worthy = row.one()
    if not total:
        return Metric(None, "Signal ratio", confident=False, note="No scored threads yet.")
    return Metric(round(100 * worthy / total, 1), "Signal ratio (%)")


async def channel_yield(db: AsyncSession, workspace_id: UUID, days: int = 90) -> list[dict]:
    """Where opportunities actually come from.

    Counts high-scoring threads per channel, not total volume. A channel that
    delivers four investor intros beats one that delivers four hundred
    newsletters, and volume charts hide exactly that.
    """
    since = datetime.now(UTC) - timedelta(days=days)
    rows = await db.execute(
        select(
            SourceAccount.kind,
            func.count(InboundObject.id).label("total"),
            func.count(case((Signal.opportunity_score >= 60, 1))).label("worthy"),
            func.coalesce(func.sum(Signal.estimated_value_usd), 0).label("value"),
        )
        .select_from(InboundObject)
        .join(SourceAccount, SourceAccount.id == InboundObject.source_account_id)
        .join(Signal, Signal.object_id == InboundObject.id)
        .where(InboundObject.workspace_id == workspace_id, InboundObject.last_activity_at >= since)
        .group_by(SourceAccount.kind)
        .order_by(func.count(case((Signal.opportunity_score >= 60, 1))).desc())
    )
    return [
        {
            "channel": str(kind),
            "threads": total,
            "opportunities": worthy,
            "hit_rate": round(100 * worthy / total, 1) if total else 0,
            "estimated_value_usd": float(value),
        }
        for kind, total, worthy, value in rows
    ]


async def growth_series(db: AsyncSession, workspace_id: UUID, days: int = 180) -> list[dict]:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = await db.execute(
        select(
            func.date_trunc("week", InboundObject.last_activity_at).label("week"),
            func.count(InboundObject.id),
            func.count(case((Signal.opportunity_score >= 60, 1))),
        )
        .select_from(InboundObject)
        .join(Signal, Signal.object_id == InboundObject.id)
        .where(InboundObject.workspace_id == workspace_id, InboundObject.last_activity_at >= since)
        .group_by("week")
        .order_by("week")
    )
    return [
        {"week": week.date().isoformat(), "threads": threads, "opportunities": worthy}
        for week, threads, worthy in rows
    ]


async def content_performance(db: AsyncSession, workspace_id: UUID, days: int = 90) -> list[dict]:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = await db.execute(
        select(
            ScheduledPost.id,
            ScheduledPost.external_url,
            ScheduledPost.scheduled_for,
            SourceAccount.kind,
            func.max(PostMetric.impressions),
            func.max(PostMetric.engagements),
        )
        .join(SourceAccount, SourceAccount.id == ScheduledPost.source_account_id)
        .outerjoin(PostMetric, PostMetric.post_id == ScheduledPost.id)
        .where(
            ScheduledPost.workspace_id == workspace_id,
            ScheduledPost.status == "published",
            ScheduledPost.scheduled_for >= since,
        )
        .group_by(ScheduledPost.id, SourceAccount.kind)
        .order_by(func.max(PostMetric.engagements).desc().nullslast())
        .limit(20)
    )
    return [
        {
            "post_id": str(pid),
            "url": url,
            "channel": str(kind),
            "published_at": when.isoformat(),
            "impressions": impressions or 0,
            "engagements": engagements or 0,
            "rate": round(100 * engagements / impressions, 2)
            if impressions and engagements else None,
        }
        for pid, url, when, kind, impressions, engagements in rows
    ]


async def attribution(db: AsyncSession, workspace_id: UUID, days: int = 90) -> dict:
    """Traces value back to the thread that started it.

    Deliberately simple: first-touch on the thread, no multi-touch modelling.
    Multi-touch attribution on a dataset this size produces numbers with more
    decimal places than truth.
    """
    since = datetime.now(UTC) - timedelta(days=days)
    rows = await db.execute(
        select(
            Signal.opportunity_kind,
            func.count(Signal.id),
            func.coalesce(func.sum(Signal.estimated_value_usd), 0),
        )
        .where(
            Signal.workspace_id == workspace_id,
            Signal.opportunity_kind.isnot(None),
            Signal.created_at >= since,
        )
        .group_by(Signal.opportunity_kind)
        .order_by(func.coalesce(func.sum(Signal.estimated_value_usd), 0).desc())
    )
    breakdown = [
        {"kind": kind, "count": count, "estimated_value_usd": float(value)}
        for kind, count, value in rows
    ]
    return {
        "window_days": days,
        "by_opportunity_kind": breakdown,
        "caveat": (
            "Values are model estimates from message text, attributed first-touch. "
            "Useful for ranking where your attention pays off, not for forecasting."
        ),
    }


async def _count_threads(db, workspace_id, start, end) -> int:
    return await db.scalar(
        select(func.count(InboundObject.id)).where(
            InboundObject.workspace_id == workspace_id,
            InboundObject.last_activity_at >= start,
            InboundObject.last_activity_at < end,
        )
    ) or 0


def _pct(now: float, before: float) -> float | None:
    if not before:
        return None
    return round(100 * (now - before) / before, 1)
