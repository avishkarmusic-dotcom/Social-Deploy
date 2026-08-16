"""Ad adapter contract.

Ads are a separate abstraction from Connector for one non-negotiable reason:
they spend real money. The failure modes are categorically different.

  Connector.send fails → a message wasn't delivered. Annoying.
  AdAdapter.launch fails → ₹50,000 might have been committed. Catastrophic.

So the contract enforces:
  1. A "pending" campaign that must be explicitly confirmed before any spend.
  2. A Redis spend cap checked before every launch — hard stop, not a warning.
  3. An idempotency key on every launch so a retry never double-fires.
  4. Every spend event written to audit_log before the API call, not after.
  5. Budget and targeting are the workspace's choice, capped at the workspace limit.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar
from uuid import UUID

import redis.asyncio as aioredis
import structlog

from app.core.config import settings
from app.core.errors import AppError

log = structlog.get_logger()

DAILY_SPEND_KEY = "ad_spend:{workspace_id}:{date}"
IDEMPOTENCY_KEY = "ad_idempotent:{idempotency_key}"


class SpendCapExceeded(AppError):
    status_code = 429
    code = "spend_cap_exceeded"

    def __init__(self, cap: float, spent: float) -> None:
        super().__init__(
            f"Today's ad spend (${spent:.2f}) would exceed your daily cap (${cap:.2f}).",
            fix="Raise the cap in Settings → Ads, or wait until midnight UTC.",
        )


class AdError(AppError):
    status_code = 502
    code = "ad_error"


@dataclass
class AdTarget:
    """Minimal targeting that covers the common boost case without becoming a
    full campaign builder. Advanced targeting belongs in the provider's own UI."""
    countries: list[str] = field(default_factory=lambda: ["IN"])
    age_min: int = 18
    age_max: int = 65
    interests: list[str] = field(default_factory=list)
    # Placements: None = provider decides (usually the right call for boosts)
    placements: list[str] | None = None


@dataclass
class AdSpec:
    """Everything the adapter needs to launch one campaign."""
    # Workspace-scoped idempotency key — the caller generates this.
    # A retry with the same key is a no-op on the provider side.
    idempotency_key: str
    name: str
    daily_budget_usd: float
    duration_days: int
    target: AdTarget
    # For boost: the external post URL or post id produced by a ScheduledPost.
    post_ref: dict[str, Any] | None = None
    # For search/PMax: headlines, descriptions, final URL.
    creative: dict[str, Any] | None = None
    objective: str = "REACH"     # REACH | TRAFFIC | LEADS | CONVERSIONS


@dataclass
class AdResult:
    provider_campaign_id: str
    provider_ad_set_id: str | None
    provider_ad_id: str | None
    status: str                     # ACTIVE | PENDING_REVIEW | REJECTED
    review_url: str | None
    spend_usd: float = 0.0
    impressions: int = 0
    clicks: int = 0


class AdAdapter(ABC):
    """One per ad platform. Stateless — account row carries credentials."""
    kind: ClassVar[str]
    supports_boost: ClassVar[bool] = False     # boost an existing post
    supports_search: ClassVar[bool] = False    # keyword search campaigns
    supports_pmax: ClassVar[bool] = False      # Performance Max / Advantage+
    min_daily_budget_usd: ClassVar[float] = 1.0
    max_daily_budget_usd: ClassVar[float] = 50_000.0

    @abstractmethod
    async def launch(
        self, *, access_token: str, spec: AdSpec, dry_run: bool = False
    ) -> AdResult: ...

    @abstractmethod
    async def pause(self, *, access_token: str, campaign_id: str) -> None: ...

    @abstractmethod
    async def metrics(self, *, access_token: str, campaign_id: str) -> AdResult: ...

    async def estimate_reach(
        self, *, access_token: str, spec: AdSpec
    ) -> dict[str, Any]:
        """Best-effort reach estimate before committing spend. Optional."""
        return {}


async def check_spend_cap(
    redis: aioredis.Redis,
    workspace_id: UUID | str,
    proposed_usd: float,
    cap_usd: float,
) -> float:
    """Returns current spend. Raises SpendCapExceeded before anything is charged."""
    key = DAILY_SPEND_KEY.format(
        workspace_id=workspace_id, date=datetime.utcnow().date().isoformat()
    )
    current = float(await redis.get(key) or 0)
    if current + proposed_usd > cap_usd:
        raise SpendCapExceeded(cap_usd, current)
    return current


async def record_spend(
    redis: aioredis.Redis, workspace_id: UUID | str, usd: float
) -> float:
    """Atomically increment today's spend. Call this BEFORE the provider API."""
    key = DAILY_SPEND_KEY.format(
        workspace_id=workspace_id, date=datetime.utcnow().date().isoformat()
    )
    total = await redis.incrbyfloat(key, usd)
    await redis.expire(key, 86_400 * 2)   # keep for two days for overnight jobs
    return total


async def idempotency_claim(redis: aioredis.Redis, key: str) -> bool:
    """Returns True if this key is unclaimed (first attempt). False = already fired."""
    return bool(await redis.set(IDEMPOTENCY_KEY.format(idempotency_key=key),
                                "1", ex=86_400, nx=True))
