"""AI endpoints: assistant, content generation, rewriting.

Every route here is rate limited harder than the rest of the API, because these
are the only requests that cost money per call rather than per thousand.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.deps import AI, DB, CurrentUser, rate_limit
from app.core.errors import UpstreamUnavailable
from app.services.ai_router import ProviderUnavailable, Task
from app.services.assistant import answer

router = APIRouter(prefix="/v1/ai", tags=["ai"])

AI_LIMIT = rate_limit(burst=30, per_second=0.3)


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class AskOut(BaseModel):
    answer: str
    intent: str
    rows_considered: int


@router.post("/assistant", response_model=AskOut, summary="Ask about your inbox",
             dependencies=[AI_LIMIT])
async def assistant(payload: AskIn, user: CurrentUser, db: DB, ai: AI) -> AskOut:
    try:
        text, plan, rows = await answer(
            ai, db, workspace_id=user.workspace_id, question=payload.question
        )
    except ProviderUnavailable as exc:
        raise UpstreamUnavailable(
            "No AI provider answered.",
            fix="Add a provider key in Settings → AI, or start Ollama for local models.",
        ) from exc
    return AskOut(answer=text, intent=plan.intent, rows_considered=rows)


ContentKind = Literal[
    "linkedin_post", "x_thread", "instagram_caption", "facebook_post",
    "blog_article", "newsletter", "email_campaign", "product_launch",
    "hashtags", "seo_title", "meta_description",
]

FORMAT_RULES = {
    "linkedin_post": "150-250 words. One idea. No hashtag walls, max 3 at the end.",
    "x_thread": "5-8 posts, each under 280 characters, numbered. First post must stand alone.",
    "instagram_caption": "Under 125 words before the fold. Up to 8 hashtags.",
    "facebook_post": "80-150 words, conversational.",
    "blog_article": "700-1000 words with subheadings. No conclusion that restates the intro.",
    "newsletter": "300-500 words. Open with the single most useful sentence.",
    "email_campaign": "Under 150 words with one clear call to action.",
    "product_launch": "120-200 words. What it does, who it's for, what changed.",
    "hashtags": "Return only hashtags, 8-15 of them, mixed reach.",
    "seo_title": "Under 60 characters. Primary keyword in the first half.",
    "meta_description": "150-158 characters. Describes the page, not the brand.",
}


class GenerateIn(BaseModel):
    kind: ContentKind
    brief: str = Field(min_length=5, max_length=2000)
    tone: str = "confident"
    variants: int = Field(default=3, ge=1, le=5)


class Variant(BaseModel):
    angle: str
    body: str
    hashtags: list[str] = []


@router.post("/content", response_model=list[Variant], summary="Generate content",
             dependencies=[AI_LIMIT])
async def generate(payload: GenerateIn, user: CurrentUser, ai: AI) -> list[Variant]:
    system = (
        f"You write for a professional's own audience. Tone: {payload.tone}.\n"
        f"Format rules: {FORMAT_RULES[payload.kind]}\n\n"
        f"Return ONLY a JSON array of exactly {payload.variants} objects, no fences, "
        'each {"angle": "2-4 words naming the strategy", "body": "the finished piece, '
        'ready to publish", "hashtags": []}.\n\n'
        "Give genuinely different approaches, not rewrites of one idea. No emoji "
        "spam, no 'in today's fast-paced world', no rhetorical-question openers, "
        "no square-bracket placeholders."
    )
    try:
        completion = await ai.complete(
            Task.CONTENT, system=system, prompt=payload.brief,
            temperature=0.8, max_tokens=2200,
        )
        return [Variant.model_validate(v) for v in completion.as_json()]
    except ProviderUnavailable as exc:
        raise UpstreamUnavailable(
            "No AI provider answered.", fix="Add a key in Settings → AI."
        ) from exc


class RewriteIn(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    mode: Literal["shorter", "longer", "grammar", "translate", "simplify", "formal"]
    target_language: str | None = None


@router.post("/rewrite", summary="Rewrite text", dependencies=[AI_LIMIT])
async def rewrite(payload: RewriteIn, user: CurrentUser, ai: AI) -> dict:
    instruction = {
        "shorter": "Cut it to roughly half the length. Keep every fact, drop every adjective you can.",
        "longer": "Expand with specifics, not padding. If you have nothing to add, say so instead.",
        "grammar": "Fix grammar and punctuation only. Do not change voice, tone or word choice.",
        "translate": f"Translate into {payload.target_language or 'English'}, preserving register.",
        "simplify": "Rewrite so a smart person outside the field understands it. No jargon.",
        "formal": "Raise the register without becoming stiff. No 'kindly', no 'please find attached'.",
    }[payload.mode]
    completion = await ai.complete(
        Task.DRAFT_REPLY,
        system=f"{instruction}\n\nReturn only the rewritten text.",
        prompt=payload.text,
        temperature=0.3,
    )
    return {"text": completion.text.strip(), "mode": payload.mode}
