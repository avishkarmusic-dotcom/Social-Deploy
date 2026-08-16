"""Phase 3 tests: does the floor hold weight.

These cover the three things that would be silent disasters — a placeholder
secret reaching production, encryption that decrypts in the wrong context, and
an automation rule that fires on data it couldn't see.
"""
from __future__ import annotations

import base64
import os

import pytest
from cryptography.exceptions import InvalidTag

from app.core.config import Settings
from app.core.crypto import new_workspace_key, open_sealed, seal, unwrap
from app.core.errors import Forbidden, NotFound, RateLimited
from app.models import WorkspaceMember
from app.services.automations import RuleInvalid, matches, validate


# ── config guards ────────────────────────────────────────────────────────
def test_production_refuses_to_start_with_placeholder_secret():
    with pytest.raises(ValueError, match="placeholder"):
        Settings(environment="production", app_secret="change-me", data_encryption_key="")


def test_production_refuses_wildcard_cors():
    with pytest.raises(ValueError, match="CORS"):
        Settings(
            environment="production", app_secret="a-real-secret",
            data_encryption_key="a-real-key", cors_origins=["*"],
        )


def test_development_tolerates_defaults():
    # Test environment sets APP_SECRET for configuration, but development mode
    # should still allow defaults. Verify by creating a new Settings without override.
    s = Settings(environment="development", app_secret="change-me", data_encryption_key="")
    assert s.app_secret == "change-me"


def test_webhook_secrets_differ_per_channel():
    s = Settings(environment="development", app_secret="seed")
    assert s.webhook_secret_for("gmail") != s.webhook_secret_for("linkedin")


# ── encryption ───────────────────────────────────────────────────────────
def test_sealed_data_round_trips():
    os.environ["DATA_ENCRYPTION_KEY"] = base64.b64encode(os.urandom(32)).decode()
    key, wrapped = new_workspace_key()
    assert unwrap(wrapped) == key
    blob = seal("board meeting Friday", key, aad="thread-1")
    assert open_sealed(blob, key, aad="thread-1") == "board meeting Friday"


def test_ciphertext_cannot_be_opened_in_another_context():
    """A row lifted into a different thread's context must fail, not decode."""
    key, _ = new_workspace_key()
    blob = seal("private", key, aad="thread-1")
    with pytest.raises(InvalidTag):
        open_sealed(blob, key, aad="thread-2")


def test_ciphertext_cannot_be_opened_with_another_workspace_key():
    key_a, _ = new_workspace_key()
    key_b, _ = new_workspace_key()
    with pytest.raises(InvalidTag):
        open_sealed(seal("private", key_a, aad="t"), key_b, aad="t")


# ── errors ───────────────────────────────────────────────────────────────
def test_errors_always_tell_the_user_what_to_do():
    for err in (NotFound("thread"), Forbidden("delete this channel"), RateLimited(30)):
        assert err.fix, f"{type(err).__name__} has no fix text"
        assert not err.message.lower().startswith("sorry")


def test_rate_limit_says_when_it_clears():
    assert "30 seconds" in RateLimited(30).fix


# ── roles ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("role", "minimum", "allowed"),
    [("owner", "admin", True), ("admin", "admin", True), ("member", "admin", False),
     ("viewer", "member", False), ("member", "member", True)],
)
def test_role_hierarchy(role, minimum, allowed):
    assert WorkspaceMember(role=role).can(minimum) is allowed


# ── automation rules ─────────────────────────────────────────────────────
def test_rule_referencing_unknown_field_is_rejected_at_save_time():
    with pytest.raises(RuleInvalid, match="isn't something a rule can check"):
        validate({"event": "thread.scored", "filters": [{"field": "vibes", "op": "eq", "value": 1}]},
                 [{"type": "notify"}])


def test_rule_with_no_actions_is_rejected():
    with pytest.raises(RuleInvalid, match="isn't a rule"):
        validate({"event": "thread.scored", "filters": []}, [])


def test_rule_with_unknown_action_is_rejected():
    with pytest.raises(RuleInvalid, match="isn't an action"):
        validate({"event": "thread.scored"}, [{"type": "launch_missiles"}])


def test_rule_fails_closed_when_a_fact_is_missing():
    """A rule must never fire on data it couldn't actually see."""
    trigger = {"filters": [{"field": "category", "op": "eq", "value": "recruiter"}]}
    assert matches(trigger, {"category": None}) is False
    assert matches(trigger, {}) is False


def test_rule_matches_when_every_filter_passes():
    trigger = {"filters": [
        {"field": "category", "op": "eq", "value": "recruiter"},
        {"field": "opportunity_score", "op": "gte", "value": 70},
    ]}
    assert matches(trigger, {"category": "recruiter", "opportunity_score": 86}) is True
    assert matches(trigger, {"category": "recruiter", "opportunity_score": 40}) is False


def test_rule_survives_comparing_incompatible_types():
    trigger = {"filters": [{"field": "opportunity_score", "op": "gte", "value": 70}]}
    assert matches(trigger, {"opportunity_score": "not a number"}) is False
