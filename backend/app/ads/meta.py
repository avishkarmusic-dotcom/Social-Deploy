"""Meta Ads — boost an existing Facebook / Instagram post.

The boost flow is four calls:
  campaign → ad_set (budget, audience) → creative (post reference) → ad.

The simplicity is intentional. A workspace that wants full campaign management
should use Meta Ads Manager directly. This adapter handles the 80% case:
'I just posted this and I want to put ₹5,000 behind it for three days.'

Prerequisites the workspace owner must handle before any key works:
  1. Business Verification in Meta Business Manager
  2. app_review approval for ads_management
  3. A valid ad account id in the account row
  4. A Facebook Page the post belongs to
"""
from __future__ import annotations

import hashlib
from typing import Any

import httpx

from app.ads.base import AdAdapter, AdError, AdResult, AdSpec

GRAPH = "https://graph.facebook.com/v21.0"

_OBJECTIVE_MAP = {
    "REACH": "REACH",
    "TRAFFIC": "OUTCOME_TRAFFIC",
    "LEADS": "OUTCOME_LEADS",
    "CONVERSIONS": "OUTCOME_SALES",
}


class MetaAdsAdapter(AdAdapter):
    kind = "meta_ads"
    supports_boost = True
    supports_pmax = True          # Meta Advantage+ Shopping
    min_daily_budget_usd = 1.0

    async def launch(
        self, *, access_token: str, spec: AdSpec, dry_run: bool = False
    ) -> AdResult:
        if not spec.post_ref:
            raise AdError(
                "Meta boost requires a published post reference.",
                fix="Publish the post first, then boost it.",
            )

        ad_account = spec.post_ref.get("ad_account_id", "")
        page_id = spec.post_ref.get("page_id", "")
        post_id = spec.post_ref.get("post_id", "")

        if dry_run:
            return AdResult(
                provider_campaign_id="dry_run_campaign",
                provider_ad_set_id="dry_run_adset",
                provider_ad_id=None,
                status="DRY_RUN",
                review_url=None,
            )

        async with httpx.AsyncClient(timeout=60) as c:
            # 1. Campaign
            campaign = await c.post(
                f"{GRAPH}/act_{ad_account}/campaigns",
                params={"access_token": access_token},
                json={
                    "name": spec.name,
                    "objective": _OBJECTIVE_MAP.get(spec.objective, "REACH"),
                    "status": "ACTIVE",
                    "special_ad_categories": [],
                },
            )
            _raise(campaign, "campaign creation")
            campaign_id = campaign.json()["id"]

            # 2. Ad set with budget and targeting
            budget_cents = int(spec.daily_budget_usd * 100)
            ad_set = await c.post(
                f"{GRAPH}/act_{ad_account}/adsets",
                params={"access_token": access_token},
                json={
                    "name": f"{spec.name} — Ad Set",
                    "campaign_id": campaign_id,
                    "daily_budget": budget_cents,
                    "billing_event": "IMPRESSIONS",
                    "optimization_goal": "REACH",
                    "end_time": _end_time(spec.duration_days),
                    "status": "ACTIVE",
                    "targeting": {
                        "geo_locations": {
                            "countries": spec.target.countries or ["IN"]
                        },
                        "age_min": spec.target.age_min,
                        "age_max": spec.target.age_max,
                    },
                },
            )
            _raise(ad_set, "ad set creation")
            ad_set_id = ad_set.json()["id"]

            # 3. Creative — reference the existing post
            creative = await c.post(
                f"{GRAPH}/act_{ad_account}/adcreatives",
                params={"access_token": access_token},
                json={
                    "name": f"{spec.name} — Creative",
                    "object_story_id": f"{page_id}_{post_id}",
                },
            )
            _raise(creative, "creative creation")
            creative_id = creative.json()["id"]

            # 4. Ad
            ad = await c.post(
                f"{GRAPH}/act_{ad_account}/ads",
                params={"access_token": access_token},
                json={
                    "name": spec.name,
                    "adset_id": ad_set_id,
                    "creative": {"creative_id": creative_id},
                    "status": "ACTIVE",
                },
            )
            _raise(ad, "ad creation")
            ad_id = ad.json()["id"]

        return AdResult(
            provider_campaign_id=campaign_id,
            provider_ad_set_id=ad_set_id,
            provider_ad_id=ad_id,
            status="PENDING_REVIEW",
            review_url=f"https://www.facebook.com/adsmanager/manage/ads?ids={ad_id}",
        )

    async def pause(self, *, access_token: str, campaign_id: str) -> None:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"{GRAPH}/{campaign_id}",
                params={"access_token": access_token},
                json={"status": "PAUSED"},
            )
            _raise(r, "pause")

    async def metrics(self, *, access_token: str, campaign_id: str) -> AdResult:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(
                f"{GRAPH}/{campaign_id}/insights",
                params={
                    "access_token": access_token,
                    "fields": "spend,impressions,clicks,campaign_name",
                },
            )
            _raise(r, "metrics")
        d = r.json().get("data", [{}])[0]
        return AdResult(
            provider_campaign_id=campaign_id,
            provider_ad_set_id=None,
            provider_ad_id=None,
            status="ACTIVE",
            review_url=None,
            spend_usd=float(d.get("spend", 0)),
            impressions=int(d.get("impressions", 0)),
            clicks=int(d.get("clicks", 0)),
        )

    async def estimate_reach(self, *, access_token: str, spec: AdSpec) -> dict:
        ad_account = (spec.post_ref or {}).get("ad_account_id", "")
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(
                f"{GRAPH}/act_{ad_account}/reachestimate",
                params={
                    "access_token": access_token,
                    "targeting_spec": '{"geo_locations":{"countries":["IN"]}}',
                    "optimize_for": "REACH",
                },
            )
        if r.status_code != 200:
            return {}
        d = r.json()
        return {"min": d.get("users_lower_bound"), "max": d.get("users_upper_bound")}


def _raise(r: httpx.Response, step: str) -> None:
    if r.status_code >= 400:
        err = r.json().get("error", {})
        code = err.get("code")
        msg = err.get("message", "Unknown error")
        fix = {
            10: "This operation needs ads_management permission. Complete Meta App Review.",
            190: "The access token has expired. Reconnect the Meta account.",
            200: "The ad account doesn't have permission. Check ad account id in settings.",
        }.get(code, "Check Meta Business Manager for details.")
        raise AdError(f"Meta {step} failed: {msg}", fix=fix)


def _end_time(days: int) -> str:
    from datetime import datetime, timedelta
    return (datetime.utcnow() + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S+0000")
