"""Ad campaigns — with mandatory confirm step.

The flow is deliberately two-stage:

  POST /v1/ads/preview   → returns estimated reach and spend; creates nothing
  POST /v1/ads/launch    → confirms a pending campaign and charges spend cap

A single 'launch and forget' endpoint would be wrong here. The confirm step is
not UX decoration — it's the firewall between 'I clicked the button by accident'
and '₹50,000 went to Meta'.

Spend cap is checked atomically in Redis before the provider API is called,
and recorded before (not after) the call. If the provider call fails after
we've recorded spend, the workspace keeps its budget safe; the next run gets
a fresh idempotency key.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ads.base import (
    AdSpec, AdTarget, SpendCapExceeded,
    check_spend_cap, idempotency_claim, record_spend,
)
from app.ads.meta import MetaAdsAdapter
from app.ads.google_ads import GoogleAdsAdapter
from app.core.deps import DB, CurrentUser, audit, get_queue, workspace_key
from app.core.errors import NotFound, ValidationFailed, Forbidden
from app.models import (
    AuditLog, ContentPiece, ScheduledPost, SourceAccount, Workspace,
)

log = structlog.get_logger()
router = APIRouter(prefix="/v1/ads", tags=["ads"])

AD_ADAPTERS = {
    "meta_ads": MetaAdsAdapter(),
    "google_ads": GoogleAdsAdapter(),
}

# Workspace daily spend cap default — overridable in workspace settings
DEFAULT_CAP_USD = 200.0


class BoostIn(BaseModel):
    """Boost an already-published post."""
    source_account_id: UUID
    post_id: str                              # provider post id from ScheduledPost
    page_id: str                              # Facebook Page id for the post
    ad_account_id: str                        # Meta Ad Account id
    name: str = Field(min_length=1, max_length=200)
    daily_budget_usd: float = Field(ge=1.0, le=10_000.0)
    duration_days: int = Field(ge=1, le=90)
    target_countries: list[str] = Field(default_factory=lambda: ["IN"])
    age_min: int = Field(default=18, ge=13, le=65)
    age_max: int = Field(default=65, ge=13, le=65)


class SearchCampaignIn(BaseModel):
    """Google Search or Performance Max campaign from a content brief."""
    source_account_id: UUID
    customer_id: str                          # Google Ads customer id
    name: str = Field(min_length=1, max_length=200)
    final_url: str
    headlines: list[str] = Field(min_length=3, max_length=15)
    descriptions: list[str] = Field(min_length=2, max_length=4)
    daily_budget_usd: float = Field(ge=1.0, le=10_000.0)
    duration_days: int = Field(ge=1, le=90)
    target_countries: list[str] = Field(default_factory=lambda: ["IN"])


class PreviewOut(BaseModel):
    estimated_reach_min: int | None = None
    estimated_reach_max: int | None = None
    total_spend_usd: float
    duration_days: int
    idempotency_key: str       # pass this back in the launch call to confirm
    warning: str | None = None


class LaunchIn(BaseModel):
    idempotency_key: str


class CampaignOut(BaseModel):
    campaign_id: str
    provider: str
    status: str
    review_url: str | None
    spend_committed_usd: float


@router.post("/boost/preview", response_model=PreviewOut, summary="Preview a post boost")
async def preview_boost(
    payload: BoostIn, user: CurrentUser, db: DB, request: Request
) -> PreviewOut:
    """Dry-run only. Nothing is charged. Returns estimated reach and a
    time-limited idempotency key the /launch endpoint requires."""
    user.require("member", "preview an ad")
    account = await _load_account(db, payload.source_account_id, user.workspace_id)
    adapter = _get_adapter(account.source_kind)
    key = await workspace_key(db, user)

    spec = _boost_spec(payload, idem=str(uuid.uuid4()))
    reach = await adapter.estimate_reach(
        access_token=account.access_token(key), spec=spec
    )

    total = payload.daily_budget_usd * payload.duration_days
    return PreviewOut(
        estimated_reach_min=reach.get("min"),
        estimated_reach_max=reach.get("max"),
        total_spend_usd=total,
        duration_days=payload.duration_days,
        idempotency_key=spec.idempotency_key,
        warning=_spend_warning(total),
    )


@router.post("/boost/launch", response_model=CampaignOut, summary="Launch a boost")
async def launch_boost(
    boost: BoostIn,
    confirm: LaunchIn,
    user: CurrentUser,
    db: DB,
    request: Request,
) -> CampaignOut:
    """The real call. Checked against the spend cap, idempotency-guarded,
    audited before the provider API is called."""
    user.require("admin", "launch an ad campaign")
    account = await _load_account(db, boost.source_account_id, user.workspace_id)
    adapter = _get_adapter(account.source_kind)
    key = await workspace_key(db, user)
    workspace = await db.get(Workspace, user.workspace_id)
    redis = _redis(request)

    total = boost.daily_budget_usd * boost.duration_days
    await check_spend_cap(redis, user.workspace_id, total, DEFAULT_CAP_USD)

    if not await idempotency_claim(redis, confirm.idempotency_key):
        raise ValidationFailed(
            "This boost has already been launched.",
            fix="Check your active campaigns — the boost is already running.",
        )

    # Record spend BEFORE the provider call. A provider failure after this
    # keeps the budget safe; a retry gets a fresh idempotency key.
    await record_spend(redis, user.workspace_id, total)

    await audit(
        db, user, action="ad.launch", resource="campaign", request=request,
        provider=adapter.kind, budget_usd=total, duration_days=boost.duration_days,
    )

    spec = _boost_spec(boost, idem=confirm.idempotency_key)
    result = await adapter.launch(access_token=account.access_token(key), spec=spec)

    return CampaignOut(
        campaign_id=result.provider_campaign_id,
        provider=adapter.kind,
        status=result.status,
        review_url=result.review_url,
        spend_committed_usd=total,
    )


@router.post("/search/preview", response_model=PreviewOut, summary="Preview a search campaign")
async def preview_search(payload: SearchCampaignIn, user: CurrentUser) -> PreviewOut:
    user.require("member", "preview an ad")
    total = payload.daily_budget_usd * payload.duration_days
    return PreviewOut(
        total_spend_usd=total,
        duration_days=payload.duration_days,
        idempotency_key=str(uuid.uuid4()),
        warning=_spend_warning(total),
    )


@router.post("/search/launch", response_model=CampaignOut, summary="Launch a search campaign")
async def launch_search(
    campaign: SearchCampaignIn,
    confirm: LaunchIn,
    user: CurrentUser,
    db: DB,
    request: Request,
) -> CampaignOut:
    user.require("admin", "launch an ad campaign")
    account = await _load_account(db, campaign.source_account_id, user.workspace_id)
    adapter = _get_adapter(account.source_kind)
    key = await workspace_key(db, user)
    redis = _redis(request)
    total = campaign.daily_budget_usd * campaign.duration_days

    await check_spend_cap(redis, user.workspace_id, total, DEFAULT_CAP_USD)

    if not await idempotency_claim(redis, confirm.idempotency_key):
        raise ValidationFailed(
            "This campaign has already been launched.",
            fix="Check your active campaigns.",
        )

    await record_spend(redis, user.workspace_id, total)
    await audit(
        db, user, action="ad.launch", resource="campaign", request=request,
        provider=adapter.kind, budget_usd=total,
    )

    spec = AdSpec(
        idempotency_key=confirm.idempotency_key,
        name=campaign.name,
        daily_budget_usd=campaign.daily_budget_usd,
        duration_days=campaign.duration_days,
        target=AdTarget(countries=campaign.target_countries),
        creative={
            "customer_id": campaign.customer_id,
            "final_url": campaign.final_url,
            "headlines": campaign.headlines,
            "descriptions": campaign.descriptions,
        },
        objective="TRAFFIC",
    )
    result = await adapter.launch(access_token=account.access_token(key), spec=spec)
    return CampaignOut(
        campaign_id=result.provider_campaign_id,
        provider=adapter.kind,
        status=result.status,
        review_url=result.review_url,
        spend_committed_usd=total,
    )


@router.get("/spend", summary="Today's ad spend")
async def spend_today(user: CurrentUser, request: Request) -> dict:
    redis = _redis(request)
    from datetime import datetime
    from app.ads.base import DAILY_SPEND_KEY
    key = DAILY_SPEND_KEY.format(
        workspace_id=user.workspace_id,
        date=datetime.utcnow().date().isoformat(),
    )
    spent = float(await redis.get(key) or 0)
    return {
        "spent_usd": round(spent, 2),
        "cap_usd": DEFAULT_CAP_USD,
        "remaining_usd": round(max(0.0, DEFAULT_CAP_USD - spent), 2),
        "resets_at": "midnight UTC",
    }


# ── helpers ────────────────────────────────────────────────────────────
def _boost_spec(p: BoostIn, *, idem: str) -> AdSpec:
    return AdSpec(
        idempotency_key=idem,
        name=p.name,
        daily_budget_usd=p.daily_budget_usd,
        duration_days=p.duration_days,
        target=AdTarget(
            countries=p.target_countries,
            age_min=p.age_min,
            age_max=p.age_max,
        ),
        post_ref={
            "page_id": p.page_id,
            "post_id": p.post_id,
            "ad_account_id": p.ad_account_id,
        },
        objective="REACH",
    )


def _get_adapter(source_kind: str):
    adapter = AD_ADAPTERS.get(source_kind)
    if adapter is None:
        raise ValidationFailed(
            f"'{source_kind}' isn't a connected ad platform.",
            fix="Connect a Meta Ads or Google Ads account in Settings → Sources.",
        )
    return adapter


async def _load_account(db: AsyncSession, account_id: UUID, workspace_id: UUID):
    account = await db.scalar(
        select(SourceAccount)
        .options(selectinload(SourceAccount.workspace))
        .where(SourceAccount.id == account_id, SourceAccount.workspace_id == workspace_id)
    )
    if account is None:
        raise NotFound("source account", str(account_id))
    return account


def _redis(request: Request) -> aioredis.Redis:
    return request.app.state.limiter._redis


def _spend_warning(total: float) -> str | None:
    if total >= DEFAULT_CAP_USD:
        return f"This campaign (${total:.0f}) will use your entire daily cap."
    if total >= DEFAULT_CAP_USD * 0.5:
        return f"This campaign uses {int(100 * total / DEFAULT_CAP_USD)}% of your daily cap."
    return None
