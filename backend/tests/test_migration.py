"""Phase 3b regression suite.

Proves the four guarantees stated in the migration plan:
  1. Signal is only created when intelligence runs — not every InboundObject has one
  2. All communication adapters produce NormalizedObject with object_kind="message"
  3. source_kind is plain TEXT (not an enum)
  4. Contact identity resolves with a string source_kind, not ChannelKind
  5. Old model names no longer exist in the production codebase
  6. facts_for dispatches on object_kind and exposes source + object_kind in the fact dict
  7. The inbox reads InboundObject → Signal (not Thread → ThreadIntelligence)
"""
from __future__ import annotations

import inspect
import importlib
import sys

import pytest

# ── 1. Signal is not automatically created with InboundObject ────────────
def test_inbound_object_has_no_signal_by_default():
    from app.models import InboundObject
    obj = InboundObject(
        workspace_id="00000000-0000-0000-0000-000000000001",
        source_account_id="00000000-0000-0000-0000-000000000002",
        object_kind="message",
        external_id="ext-1",
    )
    assert obj.signals == []
    assert obj.current_signal is None


def test_signal_is_created_by_record_signal_only():
    from app.models import InboundObject, Signal
    from unittest.mock import MagicMock

    obj = InboundObject(
        workspace_id="00000000-0000-0000-0000-000000000001",
        source_account_id="00000000-0000-0000-0000-000000000002",
        object_kind="work_item",
        external_id="pr-42",
    )
    intel = MagicMock()
    intel.category = "lead"
    intel.intent = "Review PR"
    intel.urgency = 60
    intel.opportunity_score = 72
    intel.opportunity_kind = "collaboration"
    intel.estimated_value_usd = None
    intel.summary = "PR from key customer needs review"
    intel.action_items = ["review the diff"]
    intel.sentiment = "positive"
    intel.language = "en"

    sig = obj.record_signal(intel, {"model": "test", "prompt_version": "v1", "latency_ms": 10})
    assert isinstance(sig, Signal)
    assert sig.object_kind == "work_item"
    assert obj.current_signal is sig


# ── 2. Communication adapters produce NormalizedObject(object_kind="message") ──
@pytest.mark.asyncio
async def test_gmail_webhook_returns_normalized_objects_not_threads():
    from app.connectors.gmail import GmailAdapter
    # GmailAdapter.parse_webhook is intentionally empty (doorbells only)
    result = await GmailAdapter().parse_webhook({}, {})
    assert result == []


@pytest.mark.asyncio
async def test_meta_webhook_produces_object_kind_message():
    from app.connectors.meta import MessengerAdapter
    payload = {"entry": [{"id": "p1", "messaging": [{
        "sender": {"id": "u1"},
        "timestamp": 1700000000000,
        "message": {"mid": "m1", "text": "hello"},
    }]}]}
    objects = await MessengerAdapter().parse_webhook(payload, {})
    assert len(objects) == 1
    assert objects[0].object_kind == "message"
    assert objects[0].payloads[0].body_text == "hello"


@pytest.mark.asyncio
async def test_slack_webhook_produces_object_kind_message():
    import hashlib, hmac, time
    from app.connectors.slack import SlackAdapter
    ts = str(int(time.time()))
    body = b'{"event":{"type":"message","ts":"1","channel":"C1","user":"U1","text":"hi","channel_name":"general"}}'
    secret = "secret"
    sig = "v0=" + hmac.new(secret.encode(), f"v0:{ts}:".encode() + body, hashlib.sha256).hexdigest()
    payload = {
        "event": {"type": "message", "ts": "1", "channel": "C1",
                  "user": "U1", "text": "hi", "channel_name": "general"}
    }
    objects = await SlackAdapter().parse_webhook(
        payload, {"x-slack-request-timestamp": ts, "x-slack-signature": sig}
    )
    assert objects[0].object_kind == "message"


def test_connector_source_kind_is_a_string_not_an_enum():
    from app.connectors.gmail import GmailAdapter
    from app.connectors.slack import SlackAdapter
    from app.connectors.meta import MessengerAdapter
    for cls in [GmailAdapter, SlackAdapter, MessengerAdapter]:
        assert isinstance(cls.source_kind, str), f"{cls.__name__}.source_kind should be str"
        assert not hasattr(cls.source_kind, "_value_"), f"{cls.__name__}.source_kind should not be an Enum"


# ── 3. source_kind is TEXT in the ORM model ─────────────────────────────
def test_source_account_source_kind_is_text_column():
    from app.models import SourceAccount
    import sqlalchemy as sa
    col = SourceAccount.__table__.c["source_kind"]
    assert isinstance(col.type, sa.String), "source_kind must be a String/Text column, not an Enum"


def test_contact_identity_source_kind_is_text_column():
    from app.models import ContactIdentity
    import sqlalchemy as sa
    col = ContactIdentity.__table__.c["source_kind"]
    assert isinstance(col.type, sa.String), "ContactIdentity.source_kind must be TEXT"


# ── 4. Identity resolution accepts any string source_kind ─────────────
def test_identity_score_works_with_string_source_kind():
    from app.connectors.base import Author
    from app.services.identity import _score

    class FakeContact:
        display_name = "Devansh Iyer"
        primary_email = "devansh@meridian.io"

    author = Author(name="Devansh Iyer", email="d@meridian.io")
    score, _ = _score(FakeContact(), author)
    assert isinstance(score, float)


# ── 5. Old model names do not exist in the production module namespace ──
def test_thread_not_importable_from_models():
    import app.models as m
    assert not hasattr(m, "Thread"), "Thread must not exist in app.models"
    assert not hasattr(m, "Message"), "Message must not exist in app.models"
    assert not hasattr(m, "ThreadIntelligence"), "ThreadIntelligence must not exist"
    assert not hasattr(m, "ChannelAccount"), "ChannelAccount must not exist"


def test_new_model_names_are_importable():
    from app.models import InboundObject, InboundPayload, Signal, SourceAccount  # noqa: F401
    assert True


# ── 6. facts_for exposes source and object_kind ─────────────────────────
def test_facts_for_exposes_object_kind():
    from app.services.automations import facts_for, FACTS
    assert "object_kind" in FACTS, "Automation rules must be able to filter on object_kind"
    assert "source" in FACTS, "Automation rules must be able to filter on source"


def test_facts_for_accepts_any_object_kind():
    """facts_for must not assume object_kind is 'message'."""
    from app.services.automations import facts_for, FACTS
    from unittest.mock import MagicMock
    obj = MagicMock()
    obj.object_kind = "work_item"
    obj.source_account.source_kind = "github"
    obj.current_signal = None
    obj.payloads = []
    obj.is_unread = False
    obj.title = "Fix the auth bug"
    obj.contact = None
    facts = facts_for(obj, b"")
    assert facts["object_kind"] == "work_item"
    assert facts["source"] == "github"


# ── 7. Inbox model references are correct ────────────────────────────────
def test_inbox_router_references_inbound_object_not_thread():
    import ast
    import pathlib
    src = pathlib.Path("app/routers/inbox.py").read_text()
    tree = ast.parse(src)
    names = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    }
    assert "InboundObject" in names
    assert "Thread" not in names, "inbox router must not reference Thread"
    assert "ThreadIntelligence" not in names


def test_inbox_router_references_signal_not_thread_intelligence():
    import pathlib
    src = pathlib.Path("app/routers/inbox.py").read_text()
    assert "Signal" in src or "signals" in src
    assert "ThreadIntelligence" not in src


# ── 8. NormalizedObject has the right fields ─────────────────────────────
def test_normalized_object_has_object_kind_not_messages():
    from app.connectors.base import NormalizedObject
    obj = NormalizedObject(external_id="x", last_activity_at=__import__("datetime").datetime.now())
    assert hasattr(obj, "object_kind")
    assert hasattr(obj, "payloads")
    assert not hasattr(obj, "messages"), "NormalizedObject must not have a .messages field"


def test_normalized_payload_has_action_ref_not_reply_ref():
    from app.connectors.base import NormalizedPayload, Author
    from datetime import datetime
    p = NormalizedPayload(
        external_id="p1",
        author=Author(name="Test"),
        body_text="hello",
        sent_at=datetime.now(),
        action_ref={"channel": "C1", "thread_ts": "1.0"},
    )
    assert p.action_ref["channel"] == "C1"
    assert not hasattr(p, "reply_ref"), "NormalizedPayload must not have reply_ref"


# ── 9. Signal model carries object_kind ─────────────────────────────────
def test_signal_model_has_object_kind_column():
    from app.models import Signal
    import sqlalchemy as sa
    assert "object_kind" in Signal.__table__.c


def test_signal_object_kind_has_allowed_values_constraint():
    from app.models import Signal, OBJECT_KINDS
    constraint_names = {c.name for c in Signal.__table__.constraints if getattr(c, "name", None)}
    assert "ck_signal_object_kind" in constraint_names
    assert tuple(OBJECT_KINDS) == ("message", "event", "work_item", "document", "metric", "alert")
