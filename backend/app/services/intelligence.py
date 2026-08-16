"""Turns a raw thread into the structured signal the inbox renders."""
from __future__ import annotations

import structlog
from pydantic import BaseModel, Field

from app.services.ai_router import AIRouter, Task

log = structlog.get_logger()
PROMPT_VERSION = "intel-2026-07-1"

SYSTEM = """You triage a professional's inbound messages across email, LinkedIn, \
Instagram, WhatsApp, Slack and Google Business.

Return ONLY a JSON object, no prose and no markdown fences, with keys:
  category            one of: recruiter, lead, client, investor, partnership, customer,
                      support, friend, spam, newsletter, other
  intent              one short sentence, the sender's actual ask
  urgency             0-100, how time-sensitive the reply is
  opportunity_score   0-100, how much value acting on this could create
  opportunity_kind    null, or one of: job, interview, investment, client_lead,
                      collaboration, speaking, conference, grant, scholarship, research
  estimated_value_usd null or a number, only when the message names or clearly implies one
  summary             max 25 words, written to the recipient, no greeting
  action_items        array of max 3 imperative strings
  sentiment           positive | neutral | negative
  language            BCP-47 tag of the message

Score conservatively. A mass newsletter is not an opportunity. Silence on value \
is better than a guess."""


class ThreadIntel(BaseModel):
    category: str
    intent: str | None = None
    urgency: int = Field(ge=0, le=100)
    opportunity_score: int = Field(ge=0, le=100)
    opportunity_kind: str | None = None
    estimated_value_usd: float | None = None
    summary: str
    action_items: list[str] = []
    sentiment: str = "neutral"
    language: str = "en"


async def analyse(router: AIRouter, *, channel: str, sender: str, body: str) -> tuple[ThreadIntel, dict]:
    prompt = f"Channel: {channel}\nFrom: {sender}\n\n{body[:6000]}"
    completion = await router.complete(Task.CLASSIFY, system=SYSTEM, prompt=prompt, temperature=0.0)
    intel = ThreadIntel.model_validate(completion.as_json())
    meta = {
        "model": completion.model,
        "prompt_version": PROMPT_VERSION,
        "latency_ms": completion.latency_ms,
        "cost_usd": completion.cost_usd,
    }
    return intel, meta


TONES = {
    "professional": "measured, warm, precise. No filler, no exclamation marks.",
    "casual": "relaxed and human, contractions welcome, still competent.",
    "polite": "courteous and appreciative without being deferential.",
    "confident": "direct, decisive, leads with the answer.",
    "ceo": "brief and strategic. Two or three sentences. Delegates specifics.",
    "founder": "candid and energetic, speaks in first person about the product.",
    "sales": "value-first, ends on one clear next step with a proposed time.",
    "support": "calm, specific, states exactly what happens next and by when.",
}


async def draft_reply(
    router: AIRouter, *, object_text: str | None = None, thread_text: str | None = None,
    tone: str = "professional", voice_samples: list[str] | None = None, length: str = "same"
) -> str:
    """Drafts in the user's own voice — past accepted replies are the style guide."""
    text = object_text if object_text is not None else (thread_text or "")
    voice = "\n---\n".join((voice_samples or [])[:5]) or "(no samples yet)"
    system = (
        f"You draft replies for a busy professional. Tone: {TONES.get(tone, TONES['professional'])}\n"
        f"Match the vocabulary and rhythm of these replies they wrote themselves:\n{voice}\n\n"
        "Reply with the message body only. No subject line, no sign-off placeholder, "
        "no square-bracket blanks. If a fact is genuinely unknown, leave it out rather "
        "than inventing it."
    )
    prompt = f"Length: {length}\n\nThread:\n{text[:8000]}"
    completion = await router.complete(Task.DRAFT_REPLY, system=system, prompt=prompt, temperature=0.6)
    return completion.text.strip()
