"""The contract every channel must satisfy.

Fourteen providers disagree about pagination, identity, edit semantics, what a
"conversation" is, and how they tell you something happened. The whole point of
this module is that those disagreements stop here. Everything downstream —
scoring, CRM, search, automations, the UI — sees only the three types below.

A new channel is a new file implementing Connector plus one line in the
registry. Nothing else in the codebase changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar

from pydantic import BaseModel, Field


class ChannelKind(StrEnum):
    GMAIL = "gmail"
    OUTLOOK = "outlook"
    LINKEDIN = "linkedin"
    FACEBOOK = "facebook"
    MESSENGER = "messenger"
    INSTAGRAM = "instagram"
    WHATSAPP = "whatsapp"
    TELEGRAM = "telegram"
    SLACK = "slack"
    DISCORD = "discord"
    GOOGLE_BUSINESS = "google_business"
    X = "x"
    THREADS = "threads"
    YOUTUBE = "youtube"


class Author(BaseModel):
    """Whoever sent it, in whatever terms the provider knows them by."""

    name: str
    handle: str | None = None      # @mention, channel-scoped user id
    email: str | None = None
    avatar_url: str | None = None
    is_self: bool = False          # the connected account speaking


class NormalizedPayload(BaseModel):
    external_id: str
    author: Author
    body_text: str
    body_html: str | None = None
    sent_at: datetime
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    direction: str = "inbound"     # inbound | outbound

    # Provider-specific handle needed to reply on this exact message.
    # Gmail needs a Message-Id header, Slack needs a thread_ts, Meta needs a
    # recipient id. Rather than model all of them, the adapter that produced
    # the message is the only thing that has to understand it.
    action_ref: dict[str, Any] = Field(default_factory=dict)


class NormalizedObject(BaseModel):
    external_id: str
    subject: str | None = None
    snippet: str = ""
    object_kind: str = "message"
    payloads: list[NormalizedPayload] = Field(default_factory=list)
    messages: list[NormalizedPayload] = Field(default_factory=list)
    last_activity_at: datetime
    is_unread: bool = True
    raw_kind: str | None = None    # "review", "comment", "dm" — for the UI label

    def model_post_init(self, __context):
        if self.payloads and not self.messages:
            self.messages = self.payloads
        elif self.messages and not self.payloads:
            self.payloads = self.messages
        elif not self.messages and not self.payloads:
            self.payloads = []
            self.messages = []
        else:
            self.messages = self.payloads
            self.payloads = self.messages

    @property
    def counterpart(self) -> Author | None:
        """The other side of the conversation — who the CRM should file this under."""
        return next((m.author for m in self.payloads if not m.author.is_self), None)


class SyncResult(BaseModel):
    threads: list[NormalizedObject] = Field(default_factory=list)
    objects: list[NormalizedObject] = Field(default_factory=list)
    cursor: str | None = None
    has_more: bool = False
    # Set when the provider pushed back. The scheduler respects this instead of
    # retrying blindly and burning the account's quota.
    retry_after_s: int | None = None

    def model_post_init(self, __context):
        if not self.objects and self.threads:
            self.objects = self.threads
        elif self.objects and not self.threads:
            self.threads = self.objects


class AuthBundle(BaseModel):
    external_id: str
    display_name: str
    avatar_url: str | None = None
    access_token: str
    refresh_token: str | None = None
    expires_at: datetime | None = None
    scopes: list[str] = Field(default_factory=list)


class ConnectorError(RuntimeError):
    """Raised with a message written for the person, not the log."""

    def __init__(self, message: str, *, fix: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.fix = fix
        self.retryable = retryable


class Connector(ABC):
    """One per provider. Stateless — the account row carries all the state."""

    kind: ClassVar[ChannelKind]
    scopes: ClassVar[tuple[str, ...]] = ()
    supports_push: ClassVar[bool] = False      # webhook or Pub/Sub available
    supports_send: ClassVar[bool] = True       # YouTube comments can't be DM'd
    poll_interval_s: ClassVar[int] = 300       # ignored when supports_push
    page_size: ClassVar[int] = 50

    # ── OAuth ────────────────────────────────────────────────────────────
    @abstractmethod
    def authorize_url(self, *, state: str, redirect_uri: str) -> str: ...

    @abstractmethod
    async def exchange_code(self, code: str, *, redirect_uri: str) -> AuthBundle: ...

    async def refresh(self, refresh_token: str) -> AuthBundle:
        raise ConnectorError(
            f"{self.kind} tokens can't be refreshed.",
            fix="Reconnect the account in Settings → Channels.",
        )

    async def revoke(self, access_token: str) -> None:
        """Best effort. Local tokens are deleted whether or not this succeeds."""
        return None

    # ── Reading ──────────────────────────────────────────────────────────
    @abstractmethod
    async def sync(self, *, access_token: str, cursor: str | None, limit: int) -> SyncResult:
        """Pull everything new since `cursor`. Must be safe to call twice."""

    async def parse_webhook(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> list[NormalizedObject]:
        if not self.supports_push:
            raise ConnectorError(
                f"{self.kind} doesn't send webhooks.",
                fix="This channel is polled instead. Nothing to configure.",
            )
        raise NotImplementedError

    def verify_webhook(self, body: bytes, headers: dict[str, str], secret: str) -> bool:
        """Reject anything unsigned. Default denies rather than allows."""
        return False

    # ── Writing ──────────────────────────────────────────────────────────
    @abstractmethod
    async def send(
        self, *, access_token: str, reply_ref: dict[str, Any], body: str
    ) -> str:
        """Returns the provider's id for the sent message."""

    async def publish(
        self, *, access_token: str, body: str, media: list[dict[str, Any]] | None = None
    ) -> str:
        """Post to a feed rather than reply to a person. Returns the public URL."""
        raise ConnectorError(
            f"You can't publish posts to {self.kind}.",
            fix="Pick a channel that supports posting, like LinkedIn or X.",
        )

# Backward-compatibility aliases — connectors import these during the migration
ChannelAdapter = Connector
ChannelError = ConnectorError
NormalizedInboundObject = NormalizedObject
NormalizedInboundPayload = NormalizedPayload
