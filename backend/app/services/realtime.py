"""Realtime fan-out over Redis Streams.

Streams rather than pub/sub for one reason: a browser tab that was asleep for
ninety seconds can reconnect with `?since=<cursor>` and replay what it missed.
Pub/sub would have dropped those events on the floor, and an inbox that
silently skips a thread is worse than one that's slow.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import redis.asyncio as aioredis
import structlog

log = structlog.get_logger()

STREAM_MAXLEN = 1000        # ~a day of events for an active workspace
BLOCK_MS = 25_000           # just under the client's 30s ping


def stream_key(workspace_id: UUID | str) -> str:
    return f"events:{workspace_id}"


async def publish_event(
    redis: aioredis.Redis, workspace_id: UUID | str, event: str, data: dict[str, Any]
) -> str:
    """Append an event. Approximate trimming (`~`) keeps this O(1)."""
    return await redis.xadd(
        stream_key(workspace_id),
        {
            "event": event,
            "data": json.dumps(data, default=str),
            "at": datetime.now(UTC).isoformat(),
        },
        maxlen=STREAM_MAXLEN,
        approximate=True,
    )


async def read_events(
    redis: aioredis.Redis, workspace_id: UUID | str, *, since: str = "$"
) -> list[dict[str, Any]]:
    """Block until something arrives or BLOCK_MS elapses.

    `since="$"` means "only what happens from now"; a real cursor replays the
    gap. Returning an empty list on timeout is normal, not an error — it's what
    lets the caller send a keepalive and go round again.
    """
    result = await redis.xread({stream_key(workspace_id): since}, block=BLOCK_MS, count=100)
    if not result:
        return []
    _, entries = result[0]
    return [
        {
            "cursor": entry_id,
            "event": fields["event"],
            "at": fields["at"],
            "data": json.loads(fields["data"]),
        }
        for entry_id, fields in entries
    ]
