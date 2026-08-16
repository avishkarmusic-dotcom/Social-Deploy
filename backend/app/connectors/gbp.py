"""Google Business Profile.

Reviews are the payload here, not messages — a one-star review is inbound
communication with a public audience and a clock on it, so it enters the same
inbox as everything else rather than living in a separate reputation tab.
"""
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

API = "https://mybusiness.googleapis.com/v4"
STARS = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}


@register
class GoogleBusinessAdapter(Connector):
    source_kind = ChannelKind.GOOGLE_BUSINESS
    supports_push = False
    poll_interval_s = 900
    scopes = ("https://www.googleapis.com/auth/business.manage",)

    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
            "client_id": settings.google_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        })

    async def exchange_code(self, code: str, *, redirect_uri: str) -> AuthBundle:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post("https://oauth2.googleapis.com/token", data={
                "code": code, "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri, "grant_type": "authorization_code",
            })
        r.raise_for_status()
        tok = r.json()
        return AuthBundle(external_id="gbp", display_name="Google Business",
                          access_token=tok["access_token"],
                          refresh_token=tok.get("refresh_token"),
                          scopes=list(self.scopes))

    async def sync(self, *, access_token: str, cursor: str | None, limit: int) -> SyncResult:
        async with httpx.AsyncClient(timeout=45,
                                     headers={"Authorization": f"Bearer {access_token}"}) as c:
            r = await c.get(f"{API}/accounts/-/locations/-/reviews",
                            params={"pageSize": limit, **({"pageToken": cursor} if cursor else {})})
        if r.status_code == 429:
            return SyncResult(retry_after_s=900)
        r.raise_for_status()
        d = r.json()
        return SyncResult(
            objects=[self._review(rv) for rv in d.get("reviews", [])],
            cursor=d.get("nextPageToken"),
            has_more=bool(d.get("nextPageToken")),
        )

    def _review(self, rv: dict[str, Any]) -> NormalizedObject:
        rating = STARS.get(rv.get("starRating", ""), 0)
        reviewer = rv.get("reviewer", {})
        posted = _ts(rv.get("createTime"))
        msgs = [NormalizedPayload(
            external_id=rv["reviewId"],
            author=Author(name=reviewer.get("displayName", "A customer"),
                          avatar_url=reviewer.get("profilePhotoUrl")),
            body_text=rv.get("comment") or f"Left {rating} stars without a comment.",
            sent_at=posted,
            action_ref={"review_name": rv["name"]},
        )]
        if reply := rv.get("reviewReply"):
            msgs.append(NormalizedPayload(
                external_id=f"{rv['reviewId']}:reply",
                author=Author(name="You", is_self=True),
                body_text=reply.get("comment", ""),
                sent_at=_ts(reply.get("updateTime")),
                direction="outbound",
                action_ref={"review_name": rv["name"]},
            ))
        return NormalizedObject(
            external_id=rv["reviewId"],
            subject=f"{rating}-star review",
            snippet=(rv.get("comment") or "")[:280],
            messages=msgs,
            last_activity_at=msgs[-1].sent_at,
            is_unread="reviewReply" not in rv,
            raw_kind="review",
        )

    async def send(self, *, access_token: str, action_ref: dict[str, Any], body: str) -> str:
        async with httpx.AsyncClient(timeout=30,
                                     headers={"Authorization": f"Bearer {access_token}"}) as c:
            r = await c.put(f"https://mybusiness.googleapis.com/v4/{action_ref['review_name']}/reply",
                            json={"comment": body})
        if r.status_code >= 400:
            raise ConnectorError(
                "Google didn't publish the reply.",
                fix="Replies are capped at 4,096 characters and can't contain links.",
            )
        return action_ref["review_name"]


def _ts(v: str | None) -> datetime:
    return datetime.fromisoformat(v.replace("Z", "+00:00")) if v else datetime.now(UTC)
