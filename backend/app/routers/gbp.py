"""Google Business Profile management.

Reviews are already in the universal inbox (via the GBP connector). This
router handles the management layer: bulk review metrics, unanswered count,
AI-drafted replies sent to the provider, questions, and local SEO keywords.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.deps import DB, CurrentUser, workspace_key
from app.core.errors import NotFound
from app.models import InboundObject, InboundPayload, Signal, SourceAccount
from app.services.ai_router import AIRouter, Task

router = APIRouter(prefix="/v1/gbp", tags=["google_business"])


class ReviewSummaryOut(BaseModel):
    total: int
    unanswered: int
    avg_rating: float | None
    sentiment_breakdown: dict[str, int]
    recent_critical: list[dict]


@router.get("/summary", response_model=ReviewSummaryOut, summary="Review overview")
async def review_summary(user: CurrentUser, db: DB) -> ReviewSummaryOut:
    """How the business looks to the public, at a glance."""
    # Get all GBP inbound objects (reviews arrive as object_kind=message from GBP source)
    stmt = (
        select(InboundObject, Signal)
        .outerjoin(Signal, Signal.object_id == InboundObject.id)
        .join(SourceAccount, SourceAccount.id == InboundObject.source_account_id)
        .where(
            InboundObject.workspace_id == user.workspace_id,
            SourceAccount.source_kind == "google_business",
        )
    )
    rows = list(await db.execute(stmt))

    total = len(rows)
    unanswered = sum(
        1 for obj, _ in rows
        if obj.state == "open" and obj.is_unread
    )

    # Extract ratings from payload JSONB
    ratings = [
        obj.payload.get("rating")
        for obj, _ in rows
        if obj.payload.get("rating")
    ]
    avg = round(sum(ratings) / len(ratings), 2) if ratings else None

    sentiments = {"positive": 0, "neutral": 0, "negative": 0}
    critical: list[dict] = []
    for obj, sig in rows:
        if sig and sig.sentiment in sentiments:
            sentiments[sig.sentiment] += 1
        rating = obj.payload.get("rating", 5)
        if rating and rating <= 2 and len(critical) < 5:
            critical.append({
                "object_id": str(obj.id),
                "title": obj.title,
                "rating": rating,
                "summary": sig.summary if sig else obj.snippet,
                "last_activity_at": obj.last_activity_at.isoformat(),
            })

    return ReviewSummaryOut(
        total=total,
        unanswered=unanswered,
        avg_rating=avg,
        sentiment_breakdown=sentiments,
        recent_critical=critical,
    )


class ReplyIn(BaseModel):
    object_id: UUID
    body: str


@router.post("/reply", summary="Reply to a review via the GBP adapter")
async def reply_review(payload: ReplyIn, user: CurrentUser, db: DB) -> dict:
    obj = await db.scalar(
        select(InboundObject)
        .options(
            selectinload(InboundObject.payloads),
            selectinload(InboundObject.source_account).selectinload(SourceAccount.workspace),
        )
        .where(
            InboundObject.id == payload.object_id,
            InboundObject.workspace_id == user.workspace_id,
        )
    )
    if obj is None:
        raise NotFound("review", str(payload.object_id))

    from app.connectors.registry import get
    account = obj.source_account
    key = account.workspace.data_key
    adapter = get(account.source_kind)

    # The action_ref on the last payload holds the review resource name
    last = obj.payloads[-1] if obj.payloads else None
    action_ref = last.action_ref if last else {}

    sent_id = await adapter.send(
        access_token=account.access_token(key),
        action_ref=action_ref,
        body=payload.body,
    )

    obj.is_unread = False
    obj.state = "done"
    await db.commit()

    return {"sent": True, "provider_id": sent_id}


@router.post("/draft-reply", summary="AI-draft a reply to a review")
async def draft_gbp_reply(object_id: UUID, user: CurrentUser, db: DB) -> dict:
    obj = await db.scalar(
        select(InboundObject)
        .options(selectinload(InboundObject.payloads), selectinload(InboundObject.signals))
        .where(
            InboundObject.id == object_id,
            InboundObject.workspace_id == user.workspace_id,
        )
    )
    if obj is None:
        raise NotFound("review", str(object_id))

    last = obj.payloads[-1] if obj.payloads else None
    body = last.decrypt(obj.source_account.workspace.data_key) if last and last.body_enc else obj.snippet or ""
    sig = obj.current_signal

    from app.services.ai_router import AIRouter, Task
    ai = AIRouter()
    completion = await ai.complete(
        Task.DRAFT_REPLY,
        system=(
            "You draft professional public replies to Google Business reviews. "
            "Always: acknowledge the experience, thank the reviewer by first name if given, "
            "address the specific issue, and invite them to return or contact directly. "
            "Never: be defensive, make promises you can't keep, or use corporate clichés. "
            "Under 100 words."
        ),
        prompt=f"Rating: {obj.payload.get('rating', '?')} stars\nReview: {body}",
        temperature=0.4,
        max_tokens=200,
    )
    return {"draft": completion.text.strip()}
