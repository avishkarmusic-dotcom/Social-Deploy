"""Gmail.

The hardest of the fourteen and the one everything else was designed around.

Three things make it awkward:
  1. Push comes via Pub/Sub, and the notification contains no message — only a
     historyId. The webhook is a doorbell, not a delivery.
  2. historyId expires after roughly a week. When it does, the API returns 404
     and the only correct move is a bounded backfill, not a full re-sync of a
     200,000-message mailbox.
  3. Bodies are base64url MIME trees. Multipart/alternative means the same
     message arrives twice, once as text and once as HTML.
"""
from __future__ import annotations

import base64
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlencode

import httpx
import structlog

from app.connectors.base import (
    ChannelKind,
    AuthBundle, Author, ChannelKind, Connector, ConnectorError,
    NormalizedPayload, NormalizedObject, SyncResult,
)
from app.connectors.registry import register
from app.core.config import settings

log = structlog.get_logger()
API = "https://gmail.googleapis.com/gmail/v1/users/me"
OAUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"


@register
class GmailAdapter(Connector):
    source_kind = "gmail"
    supports_push = True
    scopes = (
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/userinfo.email",
    )

    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        return f"{OAUTH}?" + urlencode({
            "client_id": settings.google_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "access_type": "offline",
            # Without this Google silently omits the refresh token on
            # re-consent, and the account dies a week later with no error.
            "prompt": "consent",
            "state": state,
        })

    async def exchange_code(self, code: str, *, redirect_uri: str) -> AuthBundle:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(TOKEN, data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            })
            r.raise_for_status()
            tok = r.json()
            me = await c.get(f"{API}/profile", headers=_auth(tok["access_token"]))
            me.raise_for_status()
        return AuthBundle(
            external_id=me.json()["emailAddress"],
            display_name=me.json()["emailAddress"],
            access_token=tok["access_token"],
            refresh_token=tok.get("refresh_token"),
            expires_at=_expiry(tok.get("expires_in", 3600)),
            scopes=list(self.scopes),
        )

    async def refresh(self, refresh_token: str) -> AuthBundle:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(TOKEN, data={
                "refresh_token": refresh_token,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "grant_type": "refresh_token",
            })
        if r.status_code == 400:
            raise ConnectorError(
                "Google revoked this connection.",
                fix="Reconnect Gmail in Settings → Channels.",
            )
        r.raise_for_status()
        tok = r.json()
        return AuthBundle(
            external_id="", display_name="",
            access_token=tok["access_token"],
            refresh_token=refresh_token,
            expires_at=_expiry(tok.get("expires_in", 3600)),
        )

    async def sync(self, *, access_token: str, cursor: str | None, limit: int) -> SyncResult:
        async with httpx.AsyncClient(timeout=45, headers=_auth(access_token)) as c:
            if cursor:
                ids, next_cursor, expired = await self._incremental(c, cursor, limit)
                if expired:
                    # The history window closed. Backfill a bounded slice rather
                    # than re-reading the mailbox; anything older is already stored.
                    log.info("gmail.history_expired", action="bounded_backfill")
                    ids, next_cursor = await self._recent(c, limit)
            else:
                ids, next_cursor = await self._recent(c, limit)

            threads: list[NormalizedObject] = []
            for tid in ids[:limit]:
                r = await c.get(f"{API}/threads/{tid}", params={"format": "full"})
                if r.status_code == 429:
                    return SyncResult(objects=threads, cursor=cursor, retry_after_s=60)
                if r.status_code == 404:
                    continue  # deleted between listing and fetching
                r.raise_for_status()
                threads.append(self._thread(r.json()))
        return SyncResult(objects=threads, cursor=next_cursor, has_more=len(ids) > limit)

    async def _incremental(
        self, c: httpx.AsyncClient, start: str, limit: int
    ) -> tuple[list[str], str | None, bool]:
        r = await c.get(f"{API}/history", params={
            "startHistoryId": start, "historyTypes": "messageAdded", "maxResults": limit,
        })
        if r.status_code == 404:
            return [], None, True
        r.raise_for_status()
        data = r.json()
        ids = {
            m["message"]["threadId"]
            for h in data.get("history", [])
            for m in h.get("messagesAdded", [])
        }
        return list(ids), data.get("historyId", start), False

    async def _recent(self, c: httpx.AsyncClient, limit: int) -> tuple[list[str], str | None]:
        r = await c.get(f"{API}/threads", params={"maxResults": limit, "q": "-in:chats"})
        r.raise_for_status()
        ids = [t["id"] for t in r.json().get("threads", [])]
        p = await c.get(f"{API}/profile")
        p.raise_for_status()
        return ids, str(p.json()["historyId"])

    def _thread(self, raw: dict[str, Any]) -> NormalizedObject:
        messages = [self._message(m) for m in raw.get("messages", [])]
        messages.sort(key=lambda m: m.sent_at)
        first = raw.get("messages", [{}])[0]
        return NormalizedObject(
            external_id=raw["id"],
            subject=_header(first, "Subject"),
            snippet=raw.get("snippet", "")[:280],
            messages=messages,
            last_activity_at=messages[-1].sent_at if messages else datetime.now(UTC),
            is_unread="UNREAD" in first.get("labelIds", []),
        )

    def _message(self, m: dict[str, Any]) -> NormalizedPayload:
        name, email = _parse_from(_header(m, "From") or "")
        is_self = "SENT" in m.get("labelIds", [])
        text, html = _extract_body(m.get("payload", {}))
        raw_date = _header(m, "Date")
        try:
            sent = parsedate_to_datetime(raw_date) if raw_date else None
        except (TypeError, ValueError):
            sent = None
        return NormalizedPayload(
            external_id=m["id"],
            author=Author(name=name or email, email=email, is_self=is_self),
            body_text=text or _strip_html(html or "") or m.get("snippet", ""),
            body_html=html,
            sent_at=sent or datetime.fromtimestamp(int(m.get("internalDate", 0)) / 1000, UTC),
            direction="outbound" if is_self else "inbound",
            attachments=[
                {"filename": p.get("filename"), "mime": p.get("mimeType"),
                 "size": p.get("body", {}).get("size", 0)}
                for p in m.get("payload", {}).get("parts", [])
                if p.get("filename")
            ],
            action_ref={
                "thread_id": m.get("threadId"),
                "message_id": _header(m, "Message-Id"),
                "to": email,
                "subject": _header(m, "Subject"),
            },
        )

    def verify_webhook(self, body: bytes, headers: dict[str, str], secret: str) -> bool:
        # Pub/Sub push is authenticated by a Google-signed OIDC token on the
        # request, verified upstream in the router. The body itself is unsigned.
        return headers.get("x-goog-verified") == "true"

    async def parse_webhook(self, payload: dict[str, Any], headers: dict[str, str]):
        # Deliberately empty: the notification carries only a historyId. The
        # router enqueues a sync for the named account and returns 200 fast.
        return []

    async def send(self, *, access_token: str, action_ref: dict[str, Any], body: str) -> str:
        headers = [
            f"To: {action_ref['to']}",
            f"Subject: {_reply_subject(action_ref.get('subject'))}",
        ]
        if mid := action_ref.get("message_id"):
            headers += [f"In-Reply-To: {mid}", f"References: {mid}"]
        mime = "\r\n".join(headers) + "\r\n\r\n" + body
        raw = base64.urlsafe_b64encode(mime.encode()).decode()
        async with httpx.AsyncClient(timeout=30, headers=_auth(access_token)) as c:
            r = await c.post(f"{API}/messages/send", json={
                "raw": raw, "threadId": action_ref.get("thread_id"),
            })
        if r.status_code == 403:
            raise ConnectorError(
                "Gmail refused to send from this account.",
                fix="Reconnect Gmail and allow the send permission.",
            )
        r.raise_for_status()
        return r.json()["id"]


# ── helpers ──────────────────────────────────────────────────────────────
def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _expiry(seconds: int) -> datetime:
    return datetime.fromtimestamp(datetime.now(UTC).timestamp() + seconds - 60, UTC)


def _header(msg: dict[str, Any], name: str) -> str | None:
    for h in msg.get("payload", {}).get("headers", []):
        if h["name"].lower() == name.lower():
            return h["value"]
    return None


def _parse_from(value: str) -> tuple[str, str]:
    # Try matching "Name" <email> format first
    m = re.match(r'^\s*"?([^"<]*?)"?\s*<(.+?)>\s*$', value)
    if m:
        name = m.group(1).strip()
        email = m.group(2).strip()
        return name, email
    # Fall back to just an email address
    email = value.strip()
    return email, email


def _extract_body(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    """Walk the MIME tree once, taking the first of each type it finds."""
    text = html = None

    def walk(part: dict[str, Any]) -> None:
        nonlocal text, html
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data:
            decoded = base64.urlsafe_b64decode(data + "===").decode("utf-8", "replace")
            if mime == "text/plain" and text is None:
                text = decoded
            elif mime == "text/html" and html is None:
                html = decoded
        for child in part.get("parts", []):
            walk(child)

    walk(payload)
    return text, html


def _strip_html(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _reply_subject(subject: str | None) -> str:
    s = subject or "(no subject)"
    return s if s.lower().startswith("re:") else f"Re: {s}"
