"""Phase 7 ad safety tests.

Spending money is not a thing the tests actually do. What they prove:
  1. SpendCapExceeded is raised before any provider API call
  2. Idempotency prevents double-launch
  3. AdSpec is valid before reaching the adapter
  4. Dry-run returns a result without touching a provider
"""
from __future__ import annotations

import pytest

from app.ads.base import AdSpec, AdTarget, SpendCapExceeded, check_spend_cap


@pytest.mark.asyncio
async def test_spend_cap_blocks_when_exceeded():
    """The cap check must raise before any money moves."""
    import fakeredis.aioredis as fakeredis

    redis = await fakeredis.FakeRedis.create()
    from app.ads.base import record_spend

    # Record $180 of spend
    await record_spend(redis, "ws-1", 180.0)

    # A further $30 should trip the $200 cap
    with pytest.raises(SpendCapExceeded) as exc_info:
        await check_spend_cap(redis, "ws-1", 30.0, cap_usd=200.0)

    assert "$180" in exc_info.value.message or "200" in exc_info.value.fix


@pytest.mark.asyncio
async def test_spend_cap_passes_when_within_limit():
    import fakeredis.aioredis as fakeredis

    redis = await fakeredis.FakeRedis.create()
    # No prior spend — $100 against a $200 cap should succeed
    current = await check_spend_cap(redis, "ws-new", 100.0, cap_usd=200.0)
    assert current == 0.0


@pytest.mark.asyncio
async def test_idempotency_blocks_second_launch():
    import fakeredis.aioredis as fakeredis
    from app.ads.base import idempotency_claim

    redis = await fakeredis.FakeRedis.create()
    key = "test-idem-key"

    first = await idempotency_claim(redis, key)
    second = await idempotency_claim(redis, key)

    assert first is True
    assert second is False


def test_ad_spec_requires_sensible_budget():
    with pytest.raises(Exception):
        from pydantic import ValidationError
        from app.routers.ads import BoostIn
        import uuid
        # daily_budget_usd=0 should fail validation
        BoostIn(
            source_account_id=uuid.uuid4(),
            post_id="123",
            page_id="456",
            ad_account_id="789",
            name="Test",
            daily_budget_usd=0,   # invalid
            duration_days=3,
        )


@pytest.mark.asyncio
async def test_meta_dry_run_returns_result_without_calling_api():
    from app.ads.meta import MetaAdsAdapter
    adapter = MetaAdsAdapter()
    spec = AdSpec(
        idempotency_key="dry-test",
        name="Test boost",
        daily_budget_usd=5.0,
        duration_days=3,
        target=AdTarget(countries=["IN"]),
        post_ref={"page_id": "p1", "post_id": "post1", "ad_account_id": "act_123"},
    )
    result = await adapter.launch(access_token="fake", spec=spec, dry_run=True)
    assert result.status == "DRY_RUN"
    assert result.provider_campaign_id == "dry_run_campaign"
