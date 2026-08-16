"""ORM models — Phase 3b revision.

Naming changes from Phase 3:
  SourceAccount    → SourceAccount
  InboundObject            → InboundObject
  InboundPayload (was Message)
  Signal → Signal   ← this is the key semantic: a Signal is what
                                   the intelligence layer creates when it decides
                                   an object warrants attention. Not every
                                   InboundObject has a Signal.
  ContactIdentity.kind  column type: channel_kind ENUM → source_kind TEXT

Everything else is structurally identical.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    ARRAY, BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey,
    Index, Integer, Numeric, SmallInteger, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym

from app.core.crypto import open_sealed, seal, unwrap
from app.core.db import Base


def _uuid_pk() -> Mapped[UUID]:
    return mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)


def _now() -> datetime:
    return datetime.now(UTC)


TS = DateTime(timezone=True)

# Valid object_kind values — plain strings, not a Postgres ENUM.
OBJECT_KINDS = ("message", "event", "work_item", "document", "metric", "alert")


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(TS, default=_now, server_default=func.now())


# ── Identity ────────────────────────────────────────────────────────────────
class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(String(16), default="en")
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")

    memberships: Mapped[list["WorkspaceMember"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Workspace(Base, TimestampMixin):
    __tablename__ = "workspaces"

    id: Mapped[UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    plan: Mapped[str] = mapped_column(String(20), default="free")
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    wrapped_key: Mapped[bytes] = mapped_column()
    ai_spend_today_usd: Mapped[float] = mapped_column(Numeric(10, 4), default=0)

    members: Mapped[list["WorkspaceMember"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    source_accounts: Mapped[list["SourceAccount"]] = relationship(back_populates="workspace")

    __table_args__ = (
        CheckConstraint("plan IN ('free','pro','team','enterprise')", name="ck_workspace_plan"),
    )

    @property
    def data_key(self) -> bytes:
        return unwrap(self.wrapped_key)


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(20))
    joined_at: Mapped[datetime] = mapped_column(TS, default=_now)

    workspace: Mapped[Workspace] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")

    RANK = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}

    def can(self, minimum: str) -> bool:
        return self.RANK.get(self.role, -1) >= self.RANK[minimum]


# ── Sources ─────────────────────────────────────────────────────────────────
class SourceAccount(Base, TimestampMixin):
    """A connected source. `source_kind` is a plain TEXT column, not a Postgres
    ENUM. New sources never require a DDL migration, only a new Connector class.
    """
    __tablename__ = "source_accounts"

    kind = synonym("source_kind")

    id: Mapped[UUID] = _uuid_pk()
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    source_kind: Mapped[str] = mapped_column(String(80))   # "gmail", "github", etc.
    external_id: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str] = mapped_column(String(200))
    avatar_url: Mapped[str | None] = mapped_column(Text)

    access_token_enc: Mapped[bytes | None] = mapped_column()
    refresh_token_enc: Mapped[bytes | None] = mapped_column()
    token_expires: Mapped[datetime | None] = mapped_column(TS)

    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    status: Mapped[str] = mapped_column(String(20), default="connected")
    sync_cursor: Mapped[str | None] = mapped_column(Text)
    last_synced_at: Mapped[datetime | None] = mapped_column(TS)
    last_error: Mapped[str | None] = mapped_column(Text)

    workspace: Mapped[Workspace] = relationship(back_populates="source_accounts")
    inbound_objects: Mapped[list["InboundObject"]] = relationship(back_populates="source_account")

    __table_args__ = (
        UniqueConstraint("workspace_id", "source_kind", "external_id", name="uq_source_identity"),
        CheckConstraint("status IN ('connected','expired','revoked','error')", name="ck_source_status"),
        Index("ix_source_due", "source_kind", "last_synced_at"),
    )

    def set_tokens(self, access: str, refresh: str | None, key: bytes) -> None:
        self.access_token_enc = seal(access, key, aad=str(self.id))
        self.refresh_token_enc = seal(refresh, key, aad=str(self.id)) if refresh else None

    def access_token(self, key: bytes) -> str:
        if not self.access_token_enc:
            raise ValueError(f"{self.source_kind} account has no stored token")
        return open_sealed(self.access_token_enc, key, aad=str(self.id))

    def refresh_token(self, key: bytes) -> str | None:
        if not self.refresh_token_enc:
            return None
        return open_sealed(self.refresh_token_enc, key, aad=str(self.id))

    @property
    def needs_refresh(self) -> bool:
        return bool(self.token_expires and self.token_expires <= _now() + timedelta(minutes=5))


# ── People ───────────────────────────────────────────────────────────────────
class Contact(Base, TimestampMixin):
    __tablename__ = "contacts"

    id: Mapped[UUID] = _uuid_pk()
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    display_name: Mapped[str] = mapped_column(String(200))
    primary_email: Mapped[str | None] = mapped_column(String(320))
    company: Mapped[str | None] = mapped_column(String(200))
    title: Mapped[str | None] = mapped_column(String(200))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    notes: Mapped[str | None] = mapped_column(Text)
    importance: Mapped[int] = mapped_column(SmallInteger, default=50)
    relationship_strength: Mapped[int] = mapped_column(SmallInteger, default=0)
    last_interaction_at: Mapped[datetime | None] = mapped_column(TS)
    next_followup_at: Mapped[datetime | None] = mapped_column(TS)
    birthday_on: Mapped[datetime | None] = mapped_column(Date)

    identities: Mapped[list["ContactIdentity"]] = relationship(
        back_populates="contact", cascade="all, delete-orphan"
    )
    inbound_objects: Mapped[list["InboundObject"]] = relationship(back_populates="contact")

    __table_args__ = (
        Index("ix_contacts_followup", "workspace_id", "next_followup_at"),
        Index("ix_contacts_strength", "workspace_id", "relationship_strength"),
    )

    def recompute_strength(self, *, exchanges: int, days_silent: int) -> int:
        base = min(exchanges * 8, 80)
        decay = 0 if days_silent <= 30 else min((days_silent - 30) * 1.5, 70)
        self.relationship_strength = max(0, min(100, int(base + 20 - decay)))
        return self.relationship_strength

    @property
    def is_stale(self) -> bool:
        if not self.last_interaction_at:
            return False
        return (_now() - self.last_interaction_at).days > 45


class ContactIdentity(Base):
    """An identifier for a contact on a specific source.

    `source_kind` is TEXT, not a Postgres ENUM. A GitHub username, a Notion
    user id, or a Google Calendar attendee email all fit here without migrations.
    """
    __tablename__ = "contact_identities"

    id: Mapped[UUID] = _uuid_pk()
    contact_id: Mapped[UUID] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"))
    source_kind: Mapped[str] = mapped_column(String(80))   # "gmail", "github", etc.
    handle: Mapped[str] = mapped_column(String(320))

    contact: Mapped[Contact] = relationship(back_populates="identities")

    __table_args__ = (UniqueConstraint("source_kind", "handle", name="uq_identity_handle"),)


# ── Inbound Objects ──────────────────────────────────────────────────────────
class InboundObject(Base, TimestampMixin):
    """Something that arrived from a source.

    `object_kind` is the discriminator: 'message' for communications, 'event'
    for calendar/deployment events, 'work_item' for PRs and tasks, 'document'
    for docs and pages, 'metric' for data reports, 'alert' for anomalies.

    Not every InboundObject has a Signal. An object becomes a Signal when the
    intelligence layer decides it warrants attention.
    """
    __tablename__ = "inbound_objects"

    subject = synonym("title")
    account_id = synonym("source_account_id")
    message_count = synonym("payload_count")

    id: Mapped[UUID] = _uuid_pk()
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    source_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_accounts.id", ondelete="CASCADE")
    )
    contact_id: Mapped[UUID | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    object_kind: Mapped[str] = mapped_column(String(30), default="message")
    external_id: Mapped[str] = mapped_column(String(512))
    title: Mapped[str | None] = mapped_column(Text)       # subject, PR title, event name
    snippet: Mapped[str | None] = mapped_column(Text)
    # Structured payload for non-message objects (event times, PR status, metric values…)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    state: Mapped[str] = mapped_column(String(20), default="open")
    is_unread: Mapped[bool] = mapped_column(Boolean, default=True)
    is_starred: Mapped[bool] = mapped_column(Boolean, default=False)
    snoozed_until: Mapped[datetime | None] = mapped_column(TS)
    payload_count: Mapped[int] = mapped_column(Integer, default=0)
    last_activity_at: Mapped[datetime] = mapped_column(TS, default=_now)

    source_account: Mapped[SourceAccount] = relationship(back_populates="inbound_objects")
    contact: Mapped[Contact | None] = relationship(back_populates="inbound_objects")
    payloads: Mapped[list["InboundPayload"]] = relationship(
        back_populates="inbound_object", cascade="all, delete-orphan",
        order_by="InboundPayload.sent_at",
    )
    signals: Mapped[list["Signal"]] = relationship(
        back_populates="inbound_object", cascade="all, delete-orphan",
        order_by="Signal.created_at.desc()",
    )

    __table_args__ = (
        UniqueConstraint("source_account_id", "external_id", name="uq_object_external"),
        CheckConstraint(
            "state IN ('open','snoozed','archived','done','spam')", name="ck_object_state"
        ),
        CheckConstraint(
            f"object_kind IN {OBJECT_KINDS}", name="ck_object_kind"
        ),
        Index("ix_objects_inbox", "workspace_id", "state", "last_activity_at"),
    )

    @property
    def current_signal(self) -> "Signal | None":
        return self.signals[0] if self.signals else None

    def transcript(self, key: bytes, limit: int = 12) -> str:
        """Recent payloads decrypted, formatted for a model prompt."""
        return "\n\n".join(
            f"{p.actor_name}: {p.decrypt(key)}"
            for p in self.payloads[-limit:]
            if p.body_enc
        )

    def record_signal(self, intel: Any, meta: dict[str, Any]) -> "Signal":
        """Create a Signal from an intelligence run. Append-only — old scores
        stay auditable. 'Why is this an 88?' is answerable a year later."""
        row = Signal(
            workspace_id=self.workspace_id,
            object_id=self.id,
            object_kind=self.object_kind,
            category=intel.category,
            intent=intel.intent,
            urgency=intel.urgency,
            opportunity_score=intel.opportunity_score,
            opportunity_kind=intel.opportunity_kind,
            estimated_value_usd=intel.estimated_value_usd,
            summary=intel.summary,
            action_items=intel.action_items,
            sentiment=intel.sentiment,
            language=intel.language,
            model=meta["model"],
            prompt_version=meta["prompt_version"],
            latency_ms=meta.get("latency_ms"),
        )
        self.signals.insert(0, row)
        return row


class InboundPayload(Base):
    """One item within an InboundObject.

    `direction` is None for non-communication payloads (commits, metric data
    points). `body_enc` is None for purely structured payloads.
    """
    __tablename__ = "inbound_payloads"

    thread_id = synonym("object_id")
    author_name = synonym("actor_name")

    id: Mapped[UUID] = _uuid_pk()
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    object_id: Mapped[UUID] = mapped_column(
        ForeignKey("inbound_objects.id", ondelete="CASCADE")
    )
    external_id: Mapped[str] = mapped_column(String(512))
    direction: Mapped[str | None] = mapped_column(String(10))   # "inbound"|"outbound"|None
    actor_name: Mapped[str] = mapped_column(String(200))
    actor_handle: Mapped[str | None] = mapped_column(String(320))
    body_enc: Mapped[bytes | None] = mapped_column()            # null for purely structured payloads
    body_html: Mapped[str | None] = mapped_column(Text)
    attachments: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    action_ref: Mapped[dict] = mapped_column(JSONB, default=dict)
    structured: Mapped[dict] = mapped_column(JSONB, default=dict)   # type-specific data
    search_tsv: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)  # computed in DB
    sent_at: Mapped[datetime] = mapped_column(TS)

    inbound_object: Mapped[InboundObject] = relationship(back_populates="payloads")

    __table_args__ = (
        UniqueConstraint("object_id", "external_id", name="uq_payload_external"),
        Index("ix_payloads_object", "object_id", "sent_at"),
        Index("ix_payloads_search", "search_tsv", postgresql_using="gin"),
    )

    def decrypt(self, key: bytes) -> str:
        if not self.body_enc:
            return ""
        return open_sealed(self.body_enc, key, aad=str(self.object_id))


class Signal(Base, TimestampMixin):
    """The intelligence layer's verdict on an InboundObject.

    A Signal is created when the intelligence layer determines an object warrants
    the person's attention. Not every InboundObject has a Signal. This is the
    key semantic: the Signal Rail shows Signals, not all objects.
    """
    __tablename__ = "signals"

    id: Mapped[UUID] = _uuid_pk()
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    object_id: Mapped[UUID] = mapped_column(
        ForeignKey("inbound_objects.id", ondelete="CASCADE")
    )
    object_kind: Mapped[str] = mapped_column(String(30))   # denormalised for fast filtering
    category: Mapped[str] = mapped_column(String(40))
    intent: Mapped[str | None] = mapped_column(Text)
    urgency: Mapped[int] = mapped_column(SmallInteger)
    opportunity_score: Mapped[int] = mapped_column(SmallInteger)
    opportunity_kind: Mapped[str | None] = mapped_column(String(40))
    estimated_value_usd: Mapped[float | None] = mapped_column(Numeric(12, 2))
    summary: Mapped[str] = mapped_column(Text)
    action_items: Mapped[list[str]] = mapped_column(JSONB, default=list)
    sentiment: Mapped[str | None] = mapped_column(String(20))
    language: Mapped[str | None] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(80))
    prompt_version: Mapped[str] = mapped_column(String(40))
    latency_ms: Mapped[int | None] = mapped_column(Integer)

    inbound_object: Mapped[InboundObject] = relationship(back_populates="signals")

    __table_args__ = (
        UniqueConstraint("object_id", "prompt_version", name="uq_signal_run"),
        CheckConstraint(f"object_kind IN {OBJECT_KINDS}", name="ck_signal_object_kind"),
        CheckConstraint("urgency BETWEEN 0 AND 100", name="ck_signal_urgency"),
        CheckConstraint("opportunity_score BETWEEN 0 AND 100", name="ck_signal_opportunity"),
        Index("ix_signals_opportunity", "workspace_id", "opportunity_score"),
        Index("ix_signals_object_kind", "workspace_id", "object_kind"),
    )


class AIDraft(Base, TimestampMixin):
    __tablename__ = "ai_drafts"

    id: Mapped[UUID] = _uuid_pk()
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    object_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("inbound_objects.id", ondelete="CASCADE")
    )
    tone: Mapped[str] = mapped_column(String(30))
    body: Mapped[str] = mapped_column(Text)
    accepted: Mapped[bool | None] = mapped_column(Boolean)
    edited_body: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    __table_args__ = (Index("ix_drafts_voice", "workspace_id", "accepted", "created_at"),)


# ── Publishing ───────────────────────────────────────────────────────────────
class ContentPiece(Base, TimestampMixin):
    __tablename__ = "content_pieces"

    id: Mapped[UUID] = _uuid_pk()
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    hashtags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    media: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(20), default="draft")

    posts: Mapped[list["ScheduledPost"]] = relationship(back_populates="content")


class ScheduledPost(Base):
    __tablename__ = "scheduled_posts"

    id: Mapped[UUID] = _uuid_pk()
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    content_id: Mapped[UUID] = mapped_column(ForeignKey("content_pieces.id", ondelete="CASCADE"))
    source_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_accounts.id", ondelete="CASCADE")
    )
    scheduled_for: Mapped[datetime] = mapped_column(TS)
    rrule: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    external_url: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)

    content: Mapped[ContentPiece] = relationship(back_populates="posts")
    metrics: Mapped[list["PostMetric"]] = relationship(cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','publishing','published','failed','cancelled')",
            name="ck_post_status",
        ),
        Index("ix_posts_due", "scheduled_for", postgresql_where="status = 'queued'"),
    )

    def next_occurrence(self) -> "ScheduledPost":
        step = {
            "FREQ=DAILY": timedelta(days=1),
            "FREQ=WEEKLY": timedelta(weeks=1),
            "FREQ=MONTHLY": timedelta(days=30),
        }.get((self.rrule or "").upper())
        if step is None:
            raise ValueError(f"Unsupported recurrence rule: {self.rrule}")
        return ScheduledPost(
            workspace_id=self.workspace_id,
            content_id=self.content_id,
            source_account_id=self.source_account_id,
            scheduled_for=self.scheduled_for + step,
            rrule=self.rrule,
            status="queued",
        )


class PostMetric(Base):
    __tablename__ = "post_metrics"

    post_id: Mapped[UUID] = mapped_column(
        ForeignKey("scheduled_posts.id", ondelete="CASCADE"), primary_key=True
    )
    captured_at: Mapped[datetime] = mapped_column(TS, primary_key=True)
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    engagements: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    follows: Mapped[int] = mapped_column(Integer, default=0)


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[UUID] = _uuid_pk()
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    source_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_accounts.id", ondelete="CASCADE")
    )
    external_id: Mapped[str] = mapped_column(String(512))
    author_name: Mapped[str] = mapped_column(String(200))
    rating: Mapped[int] = mapped_column(SmallInteger)
    body: Mapped[str | None] = mapped_column(Text)
    replied_at: Mapped[datetime | None] = mapped_column(TS)
    reply_body: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime] = mapped_column(TS)

    __table_args__ = (
        UniqueConstraint("source_account_id", "external_id", name="uq_review_external"),
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_review_rating"),
    )


# ── Automation ───────────────────────────────────────────────────────────────
class Automation(Base, TimestampMixin):
    __tablename__ = "automations"

    id: Mapped[UUID] = _uuid_pk()
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    trigger: Mapped[dict] = mapped_column(JSONB)
    actions: Mapped[list[dict]] = mapped_column(JSONB)
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    last_run_at: Mapped[datetime | None] = mapped_column(TS)

    runs: Mapped[list["AutomationRun"]] = relationship(
        back_populates="automation", cascade="all, delete-orphan"
    )


class AutomationRun(Base):
    __tablename__ = "automation_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    automation_id: Mapped[UUID] = mapped_column(ForeignKey("automations.id", ondelete="CASCADE"))
    # Generic object reference — no FK because objects span multiple kinds.
    object_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    object_kind: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20))
    detail: Mapped[dict | None] = mapped_column(JSONB)
    ran_at: Mapped[datetime] = mapped_column(TS, default=_now)

    automation: Mapped[Automation] = relationship(back_populates="runs")

    __table_args__ = (
        CheckConstraint("status IN ('success','failed','skipped')", name="ck_run_status"),
        Index("ix_runs_recent", "automation_id", "ran_at"),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL")
    )
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_kind: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(80))
    resource: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[str | None] = mapped_column(String(120))
    ip: Mapped[str | None] = mapped_column(String(45))
    audit_metadata: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(TS, default=_now)

    __table_args__ = (
        CheckConstraint(
            "actor_kind IN ('user','system','automation','ai')", name="ck_audit_actor"
        ),
        Index("ix_audit_workspace", "workspace_id", "created_at"),
    )


__all__ = [
    "AIDraft", "Automation", "AutomationRun", "AuditLog", "Base",
    "Contact", "ContactIdentity", "ContentPiece",
    "InboundObject", "InboundPayload",
    "PostMetric", "Review", "ScheduledPost",
    "Signal", "SourceAccount",
    "User", "Workspace", "WorkspaceMember",
    "OBJECT_KINDS",
]
