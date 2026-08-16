"""Outlook via Microsoft Graph. Delta queries make incremental sync trivial —
the deltaLink Graph hands back is the cursor, and it never expires the way
Gmail's historyId does."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx

from app.connectors.base import (
    ChannelKind,
    AuthBundle, Author, ChannelKind, Connector, ConnectorError,
    NormalizedPayload, NormalizedObject, SyncResult,
)
from app.connectors.registry import register
from app.core.config import settings

GRAPH = "https://graph.microsoft.com/v1.0"
AUTH = "https://login.microsoftonline.com/common/oauth2/v2.0"


@register
class OutlookAdapter(Connector):
    source_kind = ChannelKind.OUTLOOK
    supports_push = True
    scopes = ("Mail.Read", "Mail.Send", "User.Read", "offline_access")

    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        return f"{AUTH}/authorize?" + urlencode({
            "client_id": settings.microsoft_client_id, "response_type": "code",
            "redirect_uri": redirect_uri, "scope": " ".join(self.scopes),
            "state": state, "response_mode": "query",
        })

    async def exchange_code(self, code: str, *, redirect_uri: str) -> AuthBundle:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{AUTH}/token", data={
                "client_id": settings.microsoft_client_id,
                "client_secret": settings.microsoft_client_secret,
                "code": code, "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            })
            r.raise_for_status()
            tok = r.json()
            me = await c.get(f"{GRAPH}/me",
                             headers={"Authorization": f"Bearer {tok['access_token']}"})
            me.raise_for_status()
        p = me.json()
        return AuthBundle(external_id=p["id"],
                          display_name=p.get("mail") or p.get("userPrincipalName", "Outlook"),
                          access_token=tok["access_token"],
                          refresh_token=tok.get("refresh_token"), scopes=list(self.scopes))

    async def refresh(self, refresh_token: str) -> AuthBundle:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{AUTH}/token", data={
                "client_id": settings.microsoft_client_id,
                "client_secret": settings.microsoft_client_secret,
                "refresh_token": refresh_token, "grant_type": "refresh_token",
            })
        if r.status_code >= 400:
            raise ConnectorError("Microsoft revoked this connection.",
                               fix="Reconnect Outlook in Settings → Channels.")
        tok = r.json()
        return AuthBundle(external_id="", display_name="",
                          access_token=tok["access_token"],
                          refresh_token=tok.get("refresh_token", refresh_token))

    async def sync(self, *, access_token: str, cursor: str | None, limit: int) -> SyncResult:
        url = cursor or f"{GRAPH}/me/mailFolders/inbox/messages/delta?$top={limit}"
        async with httpx.AsyncClient(
            timeout=45, headers={"Authorization": f"Bearer {access_token}"}
        ) as c:
            r = await c.get(url)
        if r.status_code == 429:
            return SyncResult(cursor=cursor, retry_after_s=int(r.headers.get("Retry-After", 60)))
        r.raise_for_status()
        d = r.json()
        return SyncResult(
            objects=[self._thread(m) for m in d.get("value", []) if "id" in m],
            cursor=d.get("@odata.deltaLink") or d.get("@odata.nextLink"),
            has_more="@odata.nextLink" in d,
        )

    def _thread(self, m: dict[str, Any]) -> NormalizedObject:
        sender = m.get("from", {}).get("emailAddress", {})
        sent = datetime.fromisoformat(
            m.get("receivedDateTime", "").replace("Z", "+00:00")
        ) if m.get("receivedDateTime") else datetime.now(UTC)
        return NormalizedObject(
            external_id=m.get("conversationId", m["id"]),
            subject=m.get("subject"),
            snippet=(m.get("bodyPreview") or "")[:280],
            messages=[NormalizedPayload(
                external_id=m["id"],
                author=Author(name=sender.get("name", ""), email=sender.get("address")),
                body_text=m.get("bodyPreview", ""),
                body_html=m.get("body", {}).get("content"),
                sent_at=sent,
                action_ref={"message_id": m["id"]},
            )],
            last_activity_at=sent,
            is_unread=not m.get("isRead", False),
        )

    def verify_webhook(self, body: bytes, headers: dict[str, str], secret: str) -> bool:
        return headers.get("clientstate") == secret

    async def parse_webhook(self, payload: dict[str, Any], headers: dict[str, str]):
        return []  # notifications carry ids only; the router enqueues a delta sync

    async def send(self, *, access_token: str, action_ref: dict[str, Any], body: str) -> str:
        async with httpx.AsyncClient(
            timeout=30, headers={"Authorization": f"Bearer {access_token}"}
        ) as c:
            r = await c.post(f"{GRAPH}/me/messages/{action_ref['message_id']}/reply",
                             json={"comment": body})
        r.raise_for_status()
        return action_ref["message_id"]
