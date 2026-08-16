"""Instagram, Messenger and WhatsApp.

All three arrive through the same Graph webhook with the same signature scheme
and three different payload shapes, so they share a base class. The differences
that actually matter:

  * WhatsApp has a 24-hour customer service window. Outside it, only approved
    templates send — a plain reply returns 400 and looks like a bug. The adapter
    surfaces that as an explanation instead.
  * Instagram DMs are page-scoped: the sender id is meaningless across accounts.
  * Messenger echoes your own sent messages back through the webhook, so
    without the is_echo check every reply appears as a new inbound message.
"""
from __future__ import annotations

import hashlib
import hmac
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

GRAPH = "https://graph.facebook.com/v21.0"


class _MetaBase(Connector):
    supports_push = True

    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        return "https://www.facebook.com/v21.0/dialog/oauth?" + urlencode({
            "client_id": settings.meta_app_id,
            "redirect_uri": redirect_uri,
            "scope": ",".join(self.scopes),
            "state": state,
            "response_type": "code",
        })

    async def exchange_code(self, code: str, *, redirect_uri: str) -> AuthBundle:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{GRAPH}/oauth/access_token", params={
                "client_id": settings.meta_app_id,
                "client_secret": settings.meta_app_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            })
            r.raise_for_status()
            short = r.json()["access_token"]
            # Short-lived tokens die in an hour. Always exchange immediately.
            long = await c.get(f"{GRAPH}/oauth/access_token", params={
                "grant_type": "fb_exchange_token",
                "client_id": settings.meta_app_id,
                "client_secret": settings.meta_app_secret,
                "fb_exchange_token": short,
            })
            long.raise_for_status()
            tok = long.json()
            me = await c.get(f"{GRAPH}/me", params={"access_token": tok["access_token"]})
            me.raise_for_status()
        return AuthBundle(
            external_id=me.json()["id"],
            display_name=me.json().get("name", self.kind),
            access_token=tok["access_token"],
            scopes=list(self.scopes),
        )

    def verify_webhook(self, body: bytes, headers: dict[str, str], secret: str) -> bool:
        sig = headers.get("x-hub-signature-256", "")
        if not sig.startswith("sha256="):
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig.removeprefix("sha256="))

    async def sync(self, *, access_token: str, cursor: str | None, limit: int) -> SyncResult:
        """Meta is push-first. Sync exists only for the initial backfill and for
        catching up after downtime."""
        async with httpx.AsyncClient(timeout=45) as c:
            r = await c.get(f"{GRAPH}/me/conversations", params={
                "access_token": access_token,
                "fields": "id,updated_time,messages.limit(20){id,message,from,created_time}",
                "limit": limit,
                **({"after": cursor} if cursor else {}),
            })
        if r.status_code == 429:
            return SyncResult(retry_after_s=300)
        r.raise_for_status()
        data = r.json()
        threads = [self._conversation(conv) for conv in data.get("data", [])]
        return SyncResult(
            objects=threads,
            cursor=data.get("paging", {}).get("cursors", {}).get("after"),
            has_more="next" in data.get("paging", {}),
        )

    def _conversation(self, conv: dict[str, Any]) -> NormalizedObject:
        msgs = []
        for m in reversed(conv.get("messages", {}).get("data", [])):
            sender = m.get("from", {})
            msgs.append(NormalizedPayload(
                external_id=m["id"],
                author=Author(name=sender.get("name", "Unknown"), handle=sender.get("id")),
                body_text=m.get("message", ""),
                sent_at=_ts(m.get("created_time")),
                action_ref={"recipient_id": sender.get("id")},
            ))
        return NormalizedObject(
            external_id=conv["id"],
            snippet=msgs[-1].body_text[:280] if msgs else "",
            messages=msgs,
            last_activity_at=_ts(conv.get("updated_time")),
            raw_kind="dm",
        )

    async def parse_webhook(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> list[NormalizedObject]:
        threads: list[NormalizedObject] = []
        for entry in payload.get("entry", []):
            for event in entry.get("messaging", []):
                msg = event.get("message", {})
                # Meta replays your own outbound messages. Without this the
                # inbox fills with your own replies as unread threads.
                if msg.get("is_echo"):
                    continue
                sender = event.get("sender", {}).get("id", "")
                threads.append(NormalizedObject(
                    external_id=f"{entry.get('id')}:{sender}",
                    snippet=msg.get("text", "")[:280],
                    messages=[NormalizedPayload(
                        external_id=msg.get("mid", ""),
                        author=Author(name=sender, handle=sender),
                        body_text=msg.get("text", ""),
                        sent_at=datetime.fromtimestamp(event.get("timestamp", 0) / 1000, UTC),
                        action_ref={"recipient_id": sender, "page_id": entry.get("id")},
                    )],
                    last_activity_at=datetime.fromtimestamp(event.get("timestamp", 0) / 1000, UTC),
                    raw_kind="dm",
                ))
        return threads

    async def send(self, *, access_token: str, action_ref: dict[str, Any], body: str) -> str:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{GRAPH}/me/messages", params={"access_token": access_token}, json={
                "recipient": {"id": action_ref["recipient_id"]},
                "message": {"text": body},
                "messaging_type": "RESPONSE",
            })
        if r.status_code >= 400:
            raise self._explain(r)
        return r.json().get("message_id", "")

    def _explain(self, r: httpx.Response) -> ConnectorError:
        code = r.json().get("error", {}).get("code")
        if code == 10:
            return ConnectorError(
                "This conversation is outside the reply window.",
                fix="Meta only allows free-form replies within 24 hours of the last message.",
            )
        if code in (4, 613):
            return ConnectorError(
                "Meta is rate limiting this account.",
                fix="Sending resumes automatically. Nothing to do.",
                retryable=True,
            )
        return ConnectorError(
            "Meta refused the message.",
            fix="Reconnect the account in Settings → Channels.",
        )


@register
class InstagramAdapter(_MetaBase):
    source_kind = "instagram"
    scopes = ("instagram_basic", "instagram_manage_messages", "pages_show_list")


@register
class MessengerAdapter(_MetaBase):
    source_kind = "messenger"
    scopes = ("pages_messaging", "pages_manage_metadata", "pages_show_list")


@register
class WhatsAppAdapter(_MetaBase):
    source_kind = "whatsapp"
    scopes = ("whatsapp_business_messaging", "whatsapp_business_management")

    async def parse_webhook(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> list[NormalizedObject]:
        threads: list[NormalizedObject] = []
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                phone_id = value.get("metadata", {}).get("phone_number_id")
                names = {
                    c["wa_id"]: c.get("profile", {}).get("name", c["wa_id"])
                    for c in value.get("contacts", [])
                }
                for m in value.get("messages", []):
                    wa_id = m.get("from", "")
                    sent = datetime.fromtimestamp(int(m.get("timestamp", 0)), UTC)
                    text = m.get("text", {}).get("body") or f"[{m.get('type', 'media')}]"
                    threads.append(NormalizedObject(
                        external_id=f"wa:{phone_id}:{wa_id}",
                        snippet=text[:280],
                        messages=[NormalizedPayload(
                            external_id=m["id"],
                            author=Author(name=names.get(wa_id, wa_id), handle=wa_id),
                            body_text=text,
                            sent_at=sent,
                            action_ref={"to": wa_id, "phone_id": phone_id, "window_opened_at": sent.isoformat()},
                        )],
                        last_activity_at=sent,
                        raw_kind="dm",
                    ))
        return threads

    async def send(self, *, access_token: str, action_ref: dict[str, Any], body: str) -> str:
        opened = action_ref.get("window_opened_at")
        if opened and (datetime.now(UTC) - datetime.fromisoformat(opened)).total_seconds() > 86_400:
            raise ConnectorError(
                "The 24-hour WhatsApp reply window has closed.",
                fix="Send an approved template message instead, or wait for them to write again.",
            )
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"{GRAPH}/{action_ref['phone_id']}/messages",
                headers={"Authorization": f"Bearer {access_token}"},
                json={
                    "messaging_product": "whatsapp",
                    "to": action_ref["to"],
                    "type": "text",
                    "text": {"preview_url": False, "body": body},
                },
            )
        if r.status_code >= 400:
            raise self._explain(r)
        return r.json()["messages"][0]["id"]


def _ts(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
