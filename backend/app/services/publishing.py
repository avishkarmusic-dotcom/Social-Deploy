"""Outbound: scheduled posts and the best time to send them.

Publishing is the one place where a retry can do real damage — a double-posted
LinkedIn update is public and permanent. So every attempt claims its row first
with a conditional UPDATE, and a claim that returns zero rows means another
worker already has it.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


from app.connectors.registry import get
from app.models import SourceAccount, PostMetric, ScheduledPost

log = structlog.get_logger()
MAX_ATTEMPTS = 4


async def publish_due(db: AsyncSession, *, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(UTC)
    due = await db.scalars(
        select(ScheduledPost.id).where(
            ScheduledPost.status == "queued",
            ScheduledPost.scheduled_for <= now,
            ScheduledPost.attempts < MAX_ATTEMPTS,
        ).limit(100)
    )
    published = []
    for post_id in due:
        if await _claim(db, post_id):
            if await _publish_one(db, post_id):
                published.append(str(post_id))
    return published


async def _claim(db: AsyncSession, post_id) -> bool:
    """Exactly-once, enforced by the database rather than by the worker."""
    result = await db.execute(
        update(ScheduledPost)
        .where(ScheduledPost.id == post_id, ScheduledPost.status == "queued")
        .values(status="publishing", attempts=ScheduledPost.attempts + 1)
    )
    await db.commit()
    return result.rowcount == 1


async def _publish_one(db: AsyncSession, post_id) -> bool:
    post = await db.get(ScheduledPost, post_id)
    account = await db.get(SourceAccount, post.source_account_id)
    adapter = get(account.source_kind)
    try:
        url = await adapter.publish(
            access_token=account.access_token(account.workspace.data_key),
            body=post.content.body,
            media=post.content.media,
        )
    except Exception as exc:
        post.status = "queued" if getattr(exc, 'retryable', False) and post.attempts < MAX_ATTEMPTS else "failed"
        post.last_error = str(exc)
        await db.commit()
        return False

    post.status = "published"
    post.external_url = url
    post.content.status = "published"
    await db.commit()

    if post.rrule:
        db.add(post.next_occurrence())
        await db.commit()
    return True


async def best_times(db: AsyncSession, *, workspace_id, channel: str) -> list[tuple[int, int, float]]:
    """Returns (weekday, hour, engagement rate), strongest first.

    Deliberately computed from this workspace's own history rather than an
    industry chart. Nine published posts is not a pattern, so below a floor of
    twenty the caller is told there isn't enough data instead of being handed
    a confident-looking number built on noise.
    """
    rows = await db.execute(
        select(ScheduledPost.scheduled_for, PostMetric.impressions, PostMetric.engagements)
        .join(PostMetric, PostMetric.post_id == ScheduledPost.id)
        .join(SourceAccount, SourceAccount.id == ScheduledPost.source_account_id)
        .where(
            ScheduledPost.workspace_id == workspace_id,
            SourceAccount.source_kind == channel,
            ScheduledPost.status == "published",
            ScheduledPost.scheduled_for > datetime.now(UTC) - timedelta(days=180),
        )
    )
    buckets: dict[tuple[int, int], list[float]] = defaultdict(list)
    for when, impressions, engagements in rows:
        if impressions:
            buckets[(when.weekday(), when.hour)].append(engagements / impressions)

    if sum(len(v) for v in buckets.values()) < 20:
        return []
    ranked = [(d, h, sum(v) / len(v)) for (d, h), v in buckets.items() if len(v) >= 2]
    return sorted(ranked, key=lambda r: r[2], reverse=True)[:5]
