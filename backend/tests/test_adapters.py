"""Adapter tests.

These don't test that HTTP works. They pin the three behaviours that have
actually broken products before: signature verification, normalisation of odd
payloads, and idempotency under replay.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime

import pytest

from app.connectors.gmail import GmailAdapter, _extract_body, _parse_from, _reply_subject
from app.connectors.meta import MessengerAdapter, WhatsAppAdapter
from app.connectors.slack import SlackAdapter
from app.connectors.base import ConnectorError


# ── signatures ───────────────────────────────────────────────────────────
def test_meta_rejects_unsigned_payload():
    assert MessengerAdapter().verify_webhook(b"{}", {}, "secret") is False


def test_meta_accepts_correct_signature():
    body, secret = b'{"entry":[]}', "secret"
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert MessengerAdapter().verify_webhook(body, {"x-hub-signature-256": sig}, secret)


def test_meta_rejects_signature_for_different_body():
    secret = "secret"
    sig = "sha256=" + hmac.new(secret.encode(), b"original", hashlib.sha256).hexdigest()
    assert not MessengerAdapter().verify_webhook(b"tampered", {"x-hub-signature-256": sig}, secret)


def test_slack_rejects_replayed_request():
    old = str(int(time.time()) - 3600)
    body, secret = b"payload", "secret"
    sig = "v0=" + hmac.new(secret.encode(), f"v0:{old}:".encode() + body, hashlib.sha256).hexdigest()
    assert not SlackAdapter().verify_webhook(
        body, {"x-slack-request-timestamp": old, "x-slack-signature": sig}, secret
    )


def test_slack_accepts_fresh_request():
    now = str(int(time.time()))
    body, secret = b"payload", "secret"
    sig = "v0=" + hmac.new(secret.encode(), f"v0:{now}:".encode() + body, hashlib.sha256).hexdigest()
    assert SlackAdapter().verify_webhook(
        body, {"x-slack-request-timestamp": now, "x-slack-signature": sig}, secret
    )


# ── normalisation ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_messenger_drops_echoes_of_our_own_replies():
    payload = {"entry": [{"id": "page1", "messaging": [
        {"sender": {"id": "u1"}, "timestamp": 1700000000000,
         "message": {"mid": "m1", "text": "hello"}},
        {"sender": {"id": "page1"}, "timestamp": 1700000001000,
         "message": {"mid": "m2", "text": "our reply", "is_echo": True}},
    ]}]}
    threads = await MessengerAdapter().parse_webhook(payload, {})
    assert len(threads) == 1
    assert threads[0].payloads[0].body_text == "hello"


@pytest.mark.asyncio
async def test_whatsapp_uses_profile_name_not_phone_number():
    payload = {"entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": "p1"},
        "contacts": [{"wa_id": "919", "profile": {"name": "Devansh"}}],
        "messages": [{"id": "wm1", "from": "919", "timestamp": "1700000000",
                      "type": "text", "text": {"body": "renewal question"}}],
    }}]}]}
    threads = await WhatsAppAdapter().parse_webhook(payload, {})
    assert threads[0].payloads[0].author.name == "Devansh"
    assert threads[0].payloads[0].action_ref["phone_id"] == "p1"


@pytest.mark.asyncio
async def test_whatsapp_refuses_to_send_outside_the_24_hour_window():
    stale = datetime(2020, 1, 1, tzinfo=UTC).isoformat()
    with pytest.raises(ConnectorError) as exc:
        await WhatsAppAdapter().send(
            access_token="t",
            action_ref={"to": "919", "phone_id": "p1", "window_opened_at": stale},
            body="hi",
        )
    assert "template" in exc.value.fix


def test_gmail_prefers_plain_text_over_html_in_multipart():
    payload = {"mimeType": "multipart/alternative", "parts": [
        {"mimeType": "text/plain", "body": {"data": "aGVsbG8gcGxhaW4"}},
        {"mimeType": "text/html", "body": {"data": "PHA-aGVsbG8gaHRtbDwvcD4"}},
    ]}
    text, html = _extract_body(payload)
    assert text == "hello plain"
    assert html is not None


def test_gmail_parses_display_name_and_address():
    assert _parse_from('"Ananya Rao" <ana@northwind.com>') == ("Ananya Rao", "ana@northwind.com")
    assert _parse_from("ana@northwind.com")[1] == "ana@northwind.com"


def test_gmail_does_not_double_prefix_reply_subjects():
    assert _reply_subject("Re: Staff engineer") == "Re: Staff engineer"
    assert _reply_subject("Staff engineer") == "Re: Staff engineer"
    assert _reply_subject(None) == "Re: (no subject)"


@pytest.mark.asyncio
async def test_gmail_webhook_yields_nothing_because_it_is_only_a_doorbell():
    assert await GmailAdapter().parse_webhook({"message": {"data": ""}}, {}) == []
