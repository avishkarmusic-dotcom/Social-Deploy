"""The classifier is the product. These tests pin its contract, not its prose."""
from __future__ import annotations

import json

import pytest

from app.services.ai_router import AIRouter, Completion, Task
from app.services.intelligence import analyse, draft_reply


class FakeRouter(AIRouter):
    def __init__(self, payload: dict | str) -> None:  # noqa: D107
        self.payload = payload
        self.calls: list[Task] = []

    async def complete(self, task, *, system, prompt, max_tokens=1024, temperature=0.3):
        self.calls.append(task)
        text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return Completion(text=text, model="fake", input_tokens=10, output_tokens=20, latency_ms=1)


RECRUITER = {
    "category": "recruiter",
    "intent": "Wants to discuss a staff engineer role",
    "urgency": 70,
    "opportunity_score": 88,
    "opportunity_kind": "job",
    "estimated_value_usd": None,
    "summary": "Recruiter at Northwind wants 20 minutes this week about a staff role.",
    "action_items": ["Reply with two time slots", "Ask for the compensation band"],
    "sentiment": "positive",
    "language": "en",
}


@pytest.mark.asyncio
async def test_analyse_maps_model_output_to_typed_intel():
    intel, meta = await analyse(
        FakeRouter(RECRUITER), channel="gmail", sender="ana@northwind.com", body="Hi, are you open?"
    )
    assert intel.category == "recruiter"
    assert intel.opportunity_kind == "job"
    assert 0 <= intel.opportunity_score <= 100
    assert len(intel.action_items) <= 3
    assert meta["prompt_version"]


@pytest.mark.asyncio
async def test_analyse_tolerates_fenced_json():
    fenced = "```json\n" + json.dumps(RECRUITER) + "\n```"
    intel, _ = await analyse(FakeRouter(fenced), channel="linkedin", sender="a", body="b")
    assert intel.category == "recruiter"


@pytest.mark.asyncio
async def test_analyse_rejects_out_of_range_scores():
    bad = RECRUITER | {"opportunity_score": 140}
    with pytest.raises(Exception):
        await analyse(FakeRouter(bad), channel="gmail", sender="a", body="b")


@pytest.mark.asyncio
async def test_classification_uses_the_cheap_route():
    router = FakeRouter(RECRUITER)
    await analyse(router, channel="gmail", sender="a", body="b")
    assert router.calls == [Task.CLASSIFY]


@pytest.mark.asyncio
async def test_draft_reply_uses_quality_route_and_trims():
    router = FakeRouter("  Happy to talk Thursday at 3pm IST.  ")
    body = await draft_reply(router, thread_text="...", tone="confident", voice_samples=[])
    assert body == "Happy to talk Thursday at 3pm IST."
    assert router.calls == [Task.DRAFT_REPLY]
