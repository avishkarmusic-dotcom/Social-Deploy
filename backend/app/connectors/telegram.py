"""Telegram Bot API. Webhook push, secret token in a header."""
from __future__ import annotations

import hmac
from datetime import UTC, datetime
from typing import Any

import httpx

from app.connectors.base import (
    ChannelKind,
    AuthBundle, Author, Connector,
    NormalizedPayload, NormalizedObject, SyncResult,
)
from app.connectors.registry import register


@register
class TelegramAdapter(Connector):
    source_kind = ChannelKind.TELEGRAM
    supports_push = True

    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        # Telegram has no OAuth. The user pastes a bot token from BotFather.
        return f"tryvanta://connect/telegram?state={state}"

    async def exchange_code(self, code: str, *, redirect_uri: str) -> AuthBundle:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"https://api.telegram.org/bot{code}/getMe")
        r.raise_for_status()
        bot = r.json()["result"]
        return AuthBundle(external_id=str(bot["id"]),
                          display_name=f"@{bot.get('username', 'bot')}",
                          access_token=code)

    def verify_webhook(self, body: bytes, headers: dict[str, str], secret: str) -> bool:
        return hmac.compare_digest(
            headers.get("x-telegram-bot-api-secret-token", ""), secret
        )

    async def parse_webhook(self, payload: dict[str, Any], headers: dict[str, str]):
        m = payload.get("message") or payload.get("channel_post")
        if not m or not m.get("text"):
            return []
        chat, frm = m["chat"], m.get("from", {})
        sent = datetime.fromtimestamp(m.get("date", 0), UTC)
        name = " ".join(filter(None, [frm.get("first_name"), frm.get("last_name")])) or "Telegram"
        return [NormalizedObject(
            external_id=str(chat["id"]),
            subject=chat.get("title") or name,
            snippet=m["text"][:280],
            messages=[NormalizedPayload(
                external_id=str(m["message_id"]),
                author=Author(name=name, handle=frm.get("username")),
                body_text=m["text"], sent_at=sent,
                action_ref={"chat_id": chat["id"], "reply_to": m["message_id"]},
            )],
            last_activity_at=sent, raw_kind="dm",
        )]

    async def sync(self, *, access_token: str, cursor: str | None, limit: int) -> SyncResult:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"https://api.telegram.org/bot{access_token}/getUpdates",
                            params={"limit": limit, **({"offset": int(cursor)} if cursor else {})})
        r.raise_for_status()
        updates = r.json().get("result", [])
        threads = []
        for u in updates:
            threads += await self.parse_webhook(u, {})
        return SyncResult(objects=threads,
                          cursor=str(updates[-1]["update_id"] + 1) if updates else cursor)

    async def send(self, *, access_token: str, action_ref: dict[str, Any], body: str) -> str:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"https://api.telegram.org/bot{access_token}/sendMessage",
                             json={"chat_id": action_ref["chat_id"], "text": body,
                                   "reply_to_message_id": action_ref.get("reply_to")})
        r.raise_for_status()
        return str(r.json()["result"]["message_id"])
