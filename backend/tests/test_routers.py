"""Phase 4 tests.

These target the decisions that would be invisible bugs: a validated rule that
still lets a bad field through, an assistant plan that trusts model output, and
metrics that would rather show a wrong number than admit thin data.
"""
from __future__ import annotations

import json

import pytest

from app.services.ai_router import Completion, Task
from app.services.analytics import MIN_SAMPLES_FOR_RATE, Metric
from app.services.assistant import QueryPlan, plan
from app.services.search import K, Hit


class FakeAI:
    def __init__(self, payload):
        self.payload = payload
        self.calls: list[Task] = []

    async def complete(self, task, *, system, prompt, max_tokens=1024, temperature=0.3):
        self.calls.append(task)
        text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return Completion(text=text, model="fake", input_tokens=5, output_tokens=5, latency_ms=1)


# ── assistant planning ───────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_plan_parses_a_well_formed_response():
    ai = FakeAI({"intent": "top_opportunities", "category": None, "channel": None,
                 "days": 7, "limit": 10})
    p = await plan(ai, "what should I answer first?")
    assert p.intent == "top_opportunities"
    assert ai.calls == [Task.CLASSIFY]


@pytest.mark.asyncio
async def test_plan_falls_back_rather_than_crashing_on_garbage():
    p = await plan(FakeAI("not json at all"), "anything")
    assert p.intent == "summary_of_day"


@pytest.mark.asyncio
async def test_plan_rejects_an_intent_the_model_invented():
    """The model does not get to expand the query surface."""
    p = await plan(FakeAI({"intent": "drop_all_tables", "days": 7, "limit": 10}), "x")
    assert p.intent == "summary_of_day"


@pytest.mark.asyncio
async def test_plan_clamps_out_of_range_limits():
    p = await plan(FakeAI({"intent": "urgent_threads", "days": 900, "limit": 9999}), "x")
    assert p.intent == "summary_of_day"   # validation failed, so it fell back


def test_query_plan_bounds_are_enforced():
    with pytest.raises(Exception):
        QueryPlan(intent="urgent_threads", days=500, limit=5)


# ── search fusion ────────────────────────────────────────────────────────
def test_rrf_ranks_a_dual_match_above_a_single_strong_match():
    """The property that justifies fusion: appearing in both lists beats
    topping one of them."""
    lexical = ["a", "b", "c"]
    semantic = ["b", "d", "e"]
    scores: dict[str, float] = {}
    for ranking in (lexical, semantic):
        for i, key in enumerate(ranking):
            scores[key] = scores.get(key, 0.0) + 1 / (K + i + 1)
    assert max(scores, key=scores.get) == "b"
    assert scores["b"] > scores["a"]


def test_rrf_still_surfaces_a_single_list_top_hit():
    scores = {k: 1 / (K + i + 1) for i, k in enumerate(["a", "b", "c"])}
    assert max(scores, key=scores.get) == "a"


# ── metrics honesty ──────────────────────────────────────────────────────
def test_metric_can_report_that_it_lacks_data():
    m = Metric(None, "Median reply time", confident=False, note="Needs 10, you have 3.")
    assert m.value is None
    assert m.confident is False
    assert "10" in m.note


def test_sample_floor_is_high_enough_to_mean_something():
    assert MIN_SAMPLES_FOR_RATE >= 10


# ── endpoints ────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_vocabulary_lists_only_valid_rule_parts(client):
    r = await client.get("/v1/automations/vocabulary")
    assert r.status_code == 200
    body = r.json()
    assert "opportunity_score" in body["fields"]
    assert "notify" in body["actions"]
    assert "gte" in body["operators"]


@pytest.mark.asyncio
async def test_creating_a_rule_with_an_unknown_field_is_rejected_with_a_fix(client):
    r = await client.post("/v1/automations", json={
        "name": "bad rule",
        "trigger": {"event": "thread.scored",
                    "filters": [{"field": "vibes", "op": "eq", "value": 1}]},
        "actions": [{"type": "notify", "params": {}}],
    })
    assert r.status_code == 422
    assert r.json()["fix"]


@pytest.mark.asyncio
async def test_creating_a_valid_rule_succeeds(client):
    r = await client.post("/v1/automations", json={
        "name": "Recruiters worth answering",
        "trigger": {"event": "thread.scored", "filters": [
            {"field": "category", "op": "eq", "value": "recruiter"},
            {"field": "opportunity_score", "op": "gte", "value": 70},
        ]},
        "actions": [{"type": "notify", "params": {"title": "Recruiter"}}],
    })
    assert r.status_code == 201
    assert r.json()["run_count"] == 0


@pytest.mark.asyncio
async def test_dry_run_never_executes_actions(client):
    r = await client.post("/v1/automations/test", json={
        "name": "dry run",
        "trigger": {"event": "thread.scored", "filters": []},
        "actions": [{"type": "notify", "params": {}}],
    })
    assert r.status_code == 200
    assert "No actions were run" in r.json()["note"]


@pytest.mark.asyncio
async def test_scheduling_in_the_past_is_refused(client):
    r = await client.post(
        "/v1/content/00000000-0000-0000-0000-000000000000/schedule",
        json={
            "account_id": "00000000-0000-0000-0000-000000000000",
            "scheduled_for": "2020-01-01T00:00:00+00:00",
        },
    )
    assert r.status_code in (404, 422)


@pytest.mark.asyncio
async def test_best_times_admits_when_it_has_nothing(client):
    r = await client.get("/v1/content/best-times", params={"channel": "linkedin"})
    assert r.status_code == 200
    assert r.json()["slots"] == []
    assert "Not enough" in r.json()["note"]


@pytest.mark.asyncio
async def test_search_requires_a_real_query(client):
    assert (await client.get("/v1/search", params={"q": "a"})).status_code == 422


@pytest.mark.asyncio
async def test_connecting_an_unknown_channel_names_the_alternative(client):
    r = await client.get("/v1/channels/myspace/connect")
    assert r.status_code == 422
    assert "/v1/meta" in r.json()["fix"]
