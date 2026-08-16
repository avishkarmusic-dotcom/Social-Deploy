"""WebSocket gateway.

One socket per open tab. The server pushes deltas from the workspace's Redis
Stream; the client never polls. A tab that reconnects sends its last cursor and
gets the gap replayed, which is the whole reason events live in a stream.
"""
from __future__ import annotations

import asyncio

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from jose import JWTError, jwt

from app.core.config import settings
from app.core.deps import ALGORITHM
from app.services.realtime import read_events

log = structlog.get_logger()
router = APIRouter(tags=["realtime"])


@router.websocket("/v1/ws")
async def events(
    websocket: WebSocket,
    token: str = Query(...),
    since: str = Query("$"),
) -> None:
    # Browsers can't set headers on a WebSocket handshake, so the session token
    # arrives as a query parameter. It is verified before accept(), so an
    # unauthenticated socket is never established at all.
    try:
        claims = jwt.decode(token, settings.app_secret, algorithms=[ALGORITHM])
    except JWTError:
        await websocket.close(code=4401, reason="Session expired")
        return

    workspace_id = claims["ws"]
    await websocket.accept()
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    cursor = since

    try:
        while True:
            events_batch = await read_events(redis, workspace_id, since=cursor)
            if not events_batch:
                # Timed out with nothing new. Ping so intermediaries don't reap
                # an idle connection, and hand the cursor back for reconnects.
                await websocket.send_json({"event": "ping", "cursor": cursor})
                continue
            for item in events_batch:
                await websocket.send_json(item)
                cursor = item["cursor"]
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except Exception as exc:
        log.warning("ws.error", error=str(exc))
    finally:
        await redis.aclose()
