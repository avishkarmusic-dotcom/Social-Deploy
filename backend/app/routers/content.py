"""Content pieces and the publishing schedule."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.deps import DB, CurrentUser, audit
from app.core.errors import NotFound, ValidationFailed
from app.models import SourceAccount, ContentPiece, ScheduledPost
from app.services.publishing import best_times

router = APIRouter(prefix="/v1/content", tags=["content"])


class PieceIn(BaseModel):
    kind: str
    title: str | None = None
    body: str = Field(min_length=1, max_length=20_000)
    hashtags: list[str] = Field(default_factory=list)
    media: list[dict] = Field(default_factory=list)


class PieceOut(BaseModel):
    id: UUID
    kind: str
    title: str | None
    body: str
    hashtags: list[str]
    status: str
    created_at: datetime
    scheduled_for: datetime | None = None
    external_url: str | None = None


@router.get("", response_model=list[PieceOut], summary="List content")
async def list_content(
    user: CurrentUser,
    db: DB,
    status: Literal["draft", "approved", "scheduled", "published", "failed", "all"] = "all",
    limit: int = Query(50, le=200),
) -> list[PieceOut]:
    stmt = (
        select(ContentPiece)
        .options(selectinload(ContentPiece.posts))
        .where(ContentPiece.workspace_id == user.workspace_id)
        .order_by(ContentPiece.created_at.desc())
        .limit(limit)
    )
    if status != "all":
        stmt = stmt.where(ContentPiece.status == status)
    return [_present(p) for p in (await db.scalars(stmt)).unique()]


@router.post("", response_model=PieceOut, status_code=201, summary="Save a draft")
async def create_content(payload: PieceIn, user: CurrentUser, db: DB) -> PieceOut:
    piece = ContentPiece(workspace_id=user.workspace_id, **payload.model_dump())
    db.add(piece)
    await db.flush()
    return _present(piece)


class ScheduleIn(BaseModel):
    account_id: UUID
    scheduled_for: datetime
    rrule: str | None = None


@router.post("/{content_id}/schedule", summary="Queue it for publishing")
async def schedule(
    content_id: UUID, payload: ScheduleIn, user: CurrentUser, db: DB, request: Request
) -> dict:
    piece = await _load(db, content_id, user.workspace_id)
    if payload.scheduled_for <= datetime.now(UTC):
        raise ValidationFailed(
            "That time has already passed.",
            fix="Pick a future time, or publish now instead of scheduling.",
        )
    account = await db.scalar(
        select(SourceAccount).where(
            SourceAccount.id == payload.account_id,
            SourceAccount.workspace_id == user.workspace_id,
        )
    )
    if account is None:
        raise NotFound("channel account", str(payload.account_id))
    if account.status != "connected":
        raise ValidationFailed(
            f"Your {account.source_kind} account isn't connected right now.",
            fix="Reconnect it in Settings → Channels, then schedule again.",
        )

    post = ScheduledPost(
        workspace_id=user.workspace_id,
        content_id=piece.id,
        source_account_id=account.id,
        scheduled_for=payload.scheduled_for,
        rrule=payload.rrule,
    )
    piece.status = "scheduled"
    db.add(post)
    await db.flush()
    await audit(
        db, user, action="content.schedule", resource="scheduled_post",
        resource_id=str(post.id), request=request,
        channel=str(account.source_kind), at=payload.scheduled_for.isoformat(),
    )
    return {
        "post_id": str(post.id),
        "channel": str(account.source_kind),
        "scheduled_for": post.scheduled_for.isoformat(),
        "recurring": bool(post.rrule),
    }


@router.get("/calendar", summary="What's queued, by date")
async def calendar(
    user: CurrentUser,
    db: DB,
    start: datetime,
    end: datetime,
) -> list[dict]:
    rows = await db.execute(
        select(ScheduledPost, ContentPiece, SourceAccount.source_kind)
        .join(ContentPiece, ContentPiece.id == ScheduledPost.content_id)
        .join(SourceAccount, SourceAccount.id == ScheduledPost.source_account_id)
        .where(
            ScheduledPost.workspace_id == user.workspace_id,
            ScheduledPost.scheduled_for.between(start, end),
        )
        .order_by(ScheduledPost.scheduled_for)
    )
    return [
        {
            "post_id": str(post.id),
            "title": piece.title or piece.body[:60],
            "channel": str(kind),
            "scheduled_for": post.scheduled_for.isoformat(),
            "status": post.status,
            "external_url": post.external_url,
            "last_error": post.last_error,
        }
        for post, piece, kind in rows
    ]


@router.get("/best-times", summary="When this audience actually engages")
async def when_to_post(user: CurrentUser, db: DB, channel: str) -> dict:
    """Computed from this workspace's own history, never an industry chart.

    Below the sample floor it returns nothing rather than a plausible-looking
    number — a wrong best-time gets acted on for months before anyone notices.
    """
    times = await best_times(db, workspace_id=user.workspace_id, channel=channel)
    if not times:
        return {
            "channel": channel,
            "slots": [],
            "note": (
                "Not enough published posts with metrics yet. Publish about twenty "
                "and this becomes meaningful."
            ),
        }
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return {
        "channel": channel,
        "slots": [
            {"day": days[d], "hour": h, "engagement_rate": round(rate * 100, 2)}
            for d, h, rate in times
        ],
        "note": "From your own published posts in the last 180 days.",
    }


def _present(p: ContentPiece) -> PieceOut:
    post = p.posts[0] if p.posts else None
    return PieceOut(
        id=p.id, kind=p.kind, title=p.title, body=p.body,
        hashtags=list(p.hashtags), status=p.status, created_at=p.created_at,
        scheduled_for=post.scheduled_for if post else None,
        external_url=post.external_url if post else None,
    )


async def _load(db, content_id: UUID, workspace_id: UUID) -> ContentPiece:
    piece = await db.scalar(
        select(ContentPiece)
        .options(selectinload(ContentPiece.posts))
        .where(ContentPiece.id == content_id, ContentPiece.workspace_id == workspace_id)
    )
    if piece is None:
        raise NotFound("content piece", str(content_id))
    return piece
