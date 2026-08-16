"""Slack. Events API push, replies threaded on thread_ts."""
from __future__ import annotations

import hashlib
import hmac
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx

from app.connectors.base import (
    ChannelKind,
    AuthBundle, Author, Connector, ConnectorError,
    NormalizedPayload, NormalizedObject, SyncResult,
)
from app.connectors.registry import register
from app.core.config import settings

API = "https://slack.com/api"


@register
class SlackAdapter(Connector):
    source_kind = "slack"
    supports_push = True
    scopes = ("channels:history", "groups:history", "im:history", "chat:write", "users:read")

    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        return "https://slack.com/oauth/v2/authorize?" + urlencode({
            "client_id": settings.slack_client_id,
            "scope": ",".join(self.scopes),
            "redirect_uri": redirect_uri,
            "state": state,
        })

    async def exchange_code(self, code: str, *, redirect_uri: str) -> AuthBundle:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{API}/oauth.v2.access", data={
                "client_id": settings.slack_client_id,
                "client_secret": settings.slack_client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            })
        r.raise_for_status()
        d = r.json()
        if not d.get("ok"):
            raise ConnectorError("Slack rejected the connection.", fix="Try connecting again.")
        return AuthBundle(
            external_id=d["team"]["id"],
            display_name=d["team"]["name"],
            access_token=d["access_token"],
            scopes=list(self.scopes),
        )

    def verify_webhook(self, body: bytes, headers: dict[str, str], secret: str) -> bool:
        ts = headers.get("x-slack-request-timestamp", "0")
        # Replay guard: Slack's own guidance is five minutes.
        if abs(time.time() - int(ts)) > 300:
            return False
        base = f"v0:{ts}:".encode() + body
        expected = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, headers.get("x-slack-signature", ""))

    async def parse_webhook(self, payload: dict[str, Any], headers: dict[str, str]):
        e = payload.get("event", {})
        if e.get("type") != "message" or e.get("bot_id") or e.get("subtype"):
            return []
        ts = float(e["ts"])
        root = e.get("thread_ts", e["ts"])
        sent = datetime.fromtimestamp(ts, UTC)
        return [NormalizedObject(
            external_id=f"{e['channel']}:{root}",
            subject=f"#{e.get('channel_name', e['channel'])}",
            snippet=e.get("text", "")[:280],
            messages=[NormalizedPayload(
                external_id=e["ts"],
                author=Author(name=e.get("user_profile", {}).get("real_name") or e.get("user", ""),
                              handle=e.get("user")),
                body_text=e.get("text", ""),
                sent_at=sent,
                action_ref={"channel": e["channel"], "thread_ts": root},
            )],
            last_activity_at=sent,
            raw_kind="channel" if e["channel"].startswith("C") else "dm",
        )]

    async def sync(self, *, access_token: str, cursor: str | None, limit: int) -> SyncResult:
        # Backfill only; steady state is push. Slack's conversations.history is
        # per-channel, so a full backfill fans out one call per channel.
        return SyncResult(cursor=cursor)

    async def send(self, *, access_token: str, action_ref: dict[str, Any], body: str) -> str:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{API}/chat.postMessage",
                             headers={"Authorization": f"Bearer {access_token}"},
                             json={"channel": action_ref["channel"],
                                   "thread_ts": action_ref.get("thread_ts"),
                                   "text": body})
        d = r.json()
        if not d.get("ok"):
            raise ConnectorError(
                f"Slack didn't post the message ({d.get('error')}).",
                fix="Check the app is still invited to that channel.",
            )
        return d["ts"]
