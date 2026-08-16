"""The three channels with no usable webhook: LinkedIn, X, YouTube.

Each is polled on its own interval because each rations quota differently.
LinkedIn's messaging API is partner-gated, so the adapter degrades to what a
standard app can actually read — notifications and post comments — instead of
pretending to have DM access it won't be granted.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx

from app.connectors.base import (
    ChannelKind,
    AuthBundle, Author, Connector,
    NormalizedPayload, NormalizedObject, SyncResult,
)
from app.connectors.registry import register
from app.core.config import settings


@register
class LinkedInAdapter(Connector):
    source_kind = "linkedin"
    poll_interval_s = 180
    scopes = ("r_liteprofile", "r_organization_social", "w_member_social")

    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        return "https://www.linkedin.com/oauth/v2/authorization?" + urlencode({
            "response_type": "code", "client_id": settings.linkedin_client_id,
            "redirect_uri": redirect_uri, "state": state, "scope": " ".join(self.scopes),
        })

    async def exchange_code(self, code: str, *, redirect_uri: str) -> AuthBundle:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post("https://www.linkedin.com/oauth/v2/accessToken", data={
                "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
                "client_id": settings.linkedin_client_id,
                "client_secret": settings.linkedin_client_secret,
            })
            r.raise_for_status()
            tok = r.json()
            me = await c.get("https://api.linkedin.com/v2/me",
                             headers={"Authorization": f"Bearer {tok['access_token']}"})
            me.raise_for_status()
        p = me.json()
        return AuthBundle(
            external_id=p["id"],
            display_name=f"{p.get('localizedFirstName','')} {p.get('localizedLastName','')}".strip(),
            access_token=tok["access_token"],
            scopes=list(self.scopes),
        )

    async def sync(self, *, access_token: str, cursor: str | None, limit: int) -> SyncResult:
        async with httpx.AsyncClient(
            timeout=45, headers={"Authorization": f"Bearer {access_token}",
                                 "LinkedIn-Version": "202405"}
        ) as c:
            r = await c.get("https://api.linkedin.com/rest/socialActions",
                            params={"count": limit, **({"start": cursor} if cursor else {})})
        if r.status_code == 429:
            return SyncResult(retry_after_s=600)
        if r.status_code == 403:
            # Partner tier not granted. Not an outage — say so once, not hourly.
            return SyncResult(cursor=cursor)
        r.raise_for_status()
        d = r.json()
        threads = []
        for el in d.get("elements", []):
            sent = datetime.fromtimestamp(el.get("created", {}).get("time", 0) / 1000, UTC)
            actor = el.get("actor~", {})
            threads.append(NormalizedObject(
                external_id=el.get("$URN", el.get("id", "")),
                subject=el.get("message", {}).get("text", "")[:120],
                snippet=el.get("message", {}).get("text", "")[:280],
                messages=[NormalizedPayload(
                    external_id=el.get("id", ""),
                    author=Author(name=actor.get("localizedName", "LinkedIn member"),
                                  handle=el.get("actor")),
                    body_text=el.get("message", {}).get("text", ""),
                    sent_at=sent,
                    action_ref={"urn": el.get("$URN")},
                )],
                last_activity_at=sent,
                raw_kind="comment",
            ))
        return SyncResult(objects=threads, cursor=str(d.get("paging", {}).get("start", "")))

    async def send(self, *, access_token: str, action_ref: dict[str, Any], body: str) -> str:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"https://api.linkedin.com/rest/socialActions/{action_ref['urn']}/comments",
                headers={"Authorization": f"Bearer {access_token}", "LinkedIn-Version": "202405"},
                json={"message": {"text": body}},
            )
        r.raise_for_status()
        return r.json().get("id", "")

    async def publish(self, *, access_token: str, body: str, media=None) -> str:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post("https://api.linkedin.com/rest/posts",
                             headers={"Authorization": f"Bearer {access_token}",
                                      "LinkedIn-Version": "202405"},
                             json={"commentary": body, "visibility": "PUBLIC",
                                   "distribution": {"feedDistribution": "MAIN_FEED"},
                                   "lifecycleState": "PUBLISHED"})
        r.raise_for_status()
        return f"https://www.linkedin.com/feed/update/{r.headers.get('x-restli-id','')}"


@register
class XAdapter(Connector):
    source_kind = "x"
    poll_interval_s = 900        # free tier reads are scarce; don't burn them
    scopes = ("tweet.read", "tweet.write", "users.read", "offline.access")

    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        return "https://twitter.com/i/oauth2/authorize?" + urlencode({
            "response_type": "code", "client_id": settings.x_client_id,
            "redirect_uri": redirect_uri, "scope": " ".join(self.scopes),
            "state": state, "code_challenge": state, "code_challenge_method": "plain",
        })

    async def exchange_code(self, code: str, *, redirect_uri: str) -> AuthBundle:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post("https://api.twitter.com/2/oauth2/token", data={
                "code": code, "grant_type": "authorization_code",
                "client_id": settings.x_client_id, "redirect_uri": redirect_uri,
                "code_verifier": "challenge",
            })
        r.raise_for_status()
        tok = r.json()
        return AuthBundle(external_id="x", display_name="X",
                          access_token=tok["access_token"],
                          refresh_token=tok.get("refresh_token"), scopes=list(self.scopes))

    async def sync(self, *, access_token: str, cursor: str | None, limit: int) -> SyncResult:
        async with httpx.AsyncClient(
            timeout=45, headers={"Authorization": f"Bearer {access_token}"}
        ) as c:
            r = await c.get("https://api.twitter.com/2/users/me/mentions", params={
                "max_results": min(limit, 100),
                "tweet.fields": "created_at,author_id,conversation_id,public_metrics",
                "expansions": "author_id",
                **({"since_id": cursor} if cursor else {}),
            })
        if r.status_code == 429:
            return SyncResult(retry_after_s=int(r.headers.get("x-rate-limit-reset-in", 900)))
        r.raise_for_status()
        d = r.json()
        users = {u["id"]: u for u in d.get("includes", {}).get("users", [])}
        threads = []
        for tw in d.get("data", []):
            u = users.get(tw["author_id"], {})
            sent = datetime.fromisoformat(tw["created_at"].replace("Z", "+00:00"))
            threads.append(NormalizedObject(
                external_id=tw["conversation_id"],
                subject=f"Mention by @{u.get('username', tw['author_id'])}",
                snippet=tw["text"][:280],
                messages=[NormalizedPayload(
                    external_id=tw["id"],
                    author=Author(name=u.get("name", "X user"), handle=u.get("username")),
                    body_text=tw["text"], sent_at=sent,
                    action_ref={"in_reply_to": tw["id"]},
                )],
                last_activity_at=sent, raw_kind="mention",
            ))
        newest = max((t.messages[0].external_id for t in threads), default=cursor)
        return SyncResult(objects=threads, cursor=newest)

    async def send(self, *, access_token: str, action_ref: dict[str, Any], body: str) -> str:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post("https://api.twitter.com/2/tweets",
                             headers={"Authorization": f"Bearer {access_token}"},
                             json={"text": body,
                                   "reply": {"in_reply_to_tweet_id": action_ref["in_reply_to"]}})
        r.raise_for_status()
        return r.json()["data"]["id"]

    async def publish(self, *, access_token: str, body: str, media=None) -> str:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post("https://api.twitter.com/2/tweets",
                             headers={"Authorization": f"Bearer {access_token}"},
                             json={"text": body})
        r.raise_for_status()
        return f"https://x.com/i/status/{r.json()['data']['id']}"


@register
class YouTubeAdapter(Connector):
    source_kind = "youtube"
    poll_interval_s = 600
    supports_send = True
    scopes = ("https://www.googleapis.com/auth/youtube.force-ssl",)

    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
            "client_id": settings.google_client_id, "redirect_uri": redirect_uri,
            "response_type": "code", "scope": " ".join(self.scopes),
            "access_type": "offline", "prompt": "consent", "state": state,
        })

    async def exchange_code(self, code: str, *, redirect_uri: str) -> AuthBundle:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post("https://oauth2.googleapis.com/token", data={
                "code": code, "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri, "grant_type": "authorization_code"})
        r.raise_for_status()
        tok = r.json()
        return AuthBundle(external_id="youtube", display_name="YouTube",
                          access_token=tok["access_token"],
                          refresh_token=tok.get("refresh_token"), scopes=list(self.scopes))

    async def sync(self, *, access_token: str, cursor: str | None, limit: int) -> SyncResult:
        async with httpx.AsyncClient(
            timeout=45, headers={"Authorization": f"Bearer {access_token}"}
        ) as c:
            r = await c.get("https://www.googleapis.com/youtube/v3/commentThreads", params={
                "part": "snippet", "allThreadsRelatedToChannelId": "mine",
                "maxResults": min(limit, 100), "order": "time",
                **({"pageToken": cursor} if cursor else {}),
            })
        if r.status_code == 403:
            return SyncResult(retry_after_s=3600)  # daily quota exhausted
        r.raise_for_status()
        d = r.json()
        threads = []
        for item in d.get("items", []):
            top = item["snippet"]["topLevelComment"]["snippet"]
            sent = datetime.fromisoformat(top["publishedAt"].replace("Z", "+00:00"))
            threads.append(NormalizedObject(
                external_id=item["id"],
                subject=f"Comment · {top.get('videoId', '')}",
                snippet=top["textOriginal"][:280],
                messages=[NormalizedPayload(
                    external_id=item["snippet"]["topLevelComment"]["id"],
                    author=Author(name=top["authorDisplayName"],
                                  handle=top.get("authorChannelId", {}).get("value"),
                                  avatar_url=top.get("authorProfileImageUrl")),
                    body_text=top["textOriginal"], sent_at=sent,
                    action_ref={"parent_id": item["snippet"]["topLevelComment"]["id"]},
                )],
                last_activity_at=sent, raw_kind="comment",
            ))
        return SyncResult(objects=threads, cursor=d.get("nextPageToken"))

    async def send(self, *, access_token: str, action_ref: dict[str, Any], body: str) -> str:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post("https://www.googleapis.com/youtube/v3/comments",
                             params={"part": "snippet"},
                             headers={"Authorization": f"Bearer {access_token}"},
                             json={"snippet": {"parentId": action_ref["parent_id"],
                                               "textOriginal": body}})
        r.raise_for_status()
        return r.json()["id"]
