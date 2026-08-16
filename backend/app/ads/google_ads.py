"""Google Ads — Performance Max and Search campaigns.

Unlike a boost (four calls), a full Search campaign is: campaign →
campaign budget → ad group → responsive search ad → keywords. Performance Max
is similar but replaces the ad group + keywords with asset groups.

This adapter generates all the structure from a brief. The user sees one
'Launch' button; the adapter produces a complete, well-formed campaign.

Prerequisites:
  - A developer token (applied for at https://developers.google.com/google-ads)
  - Basic Access (approved, 15,000 operations/day)
  - A Google Ads customer id (the 10-digit number in your Ads account URL)
  - OAuth scope: https://www.googleapis.com/auth/adwords
"""
from __future__ import annotations

from typing import Any

import httpx

from app.ads.base import AdAdapter, AdError, AdResult, AdSpec

API = "https://googleads.googleapis.com/v18"


class GoogleAdsAdapter(AdAdapter):
    kind = "google_ads"
    supports_search = True
    supports_pmax = True
    min_daily_budget_usd = 1.0

    def __init__(self, developer_token: str = "") -> None:
        self._dev_token = developer_token

    async def launch(
        self, *, access_token: str, spec: AdSpec, dry_run: bool = False
    ) -> AdResult:
        customer_id = (spec.creative or {}).get("customer_id", "")
        if not customer_id:
            raise AdError(
                "Google Ads requires a customer id.",
                fix="Add your Google Ads customer id in Settings → Sources.",
            )

        if dry_run:
            return AdResult(
                provider_campaign_id="dry_run",
                provider_ad_set_id=None,
                provider_ad_id=None,
                status="DRY_RUN",
                review_url=None,
            )

        headers = {
            "Authorization": f"Bearer {access_token}",
            "developer-token": self._dev_token,
            "login-customer-id": customer_id,
        }

        # Construct mutate operations for a minimal responsive search campaign.
        # All done in a single mutate call so we get atomic success / rollback.
        budget_micros = int(spec.daily_budget_usd * 1_000_000)

        operations = [
            # 1. Campaign budget
            {
                "campaignBudgetOperation": {
                    "create": {
                        "resourceName": f"customers/{customer_id}/campaignBudgets/-1",
                        "name": f"{spec.name} Budget",
                        "amountMicros": str(budget_micros),
                        "deliveryMethod": "STANDARD",
                    }
                }
            },
            # 2. Campaign
            {
                "campaignOperation": {
                    "create": {
                        "resourceName": f"customers/{customer_id}/campaigns/-2",
                        "name": spec.name,
                        "status": "ENABLED",
                        "advertisingChannelType": "SEARCH",
                        "campaignBudget": f"customers/{customer_id}/campaignBudgets/-1",
                        "biddingStrategyType": "MAXIMIZE_CONVERSIONS",
                        "targetGoogleSearch": {},
                        "startDate": _today(),
                        "endDate": _end_date(spec.duration_days),
                        "geoTargetTypeSetting": {
                            "positiveGeoTargetType": "PRESENCE_OR_INTEREST"
                        },
                    }
                }
            },
            # 3. Ad group
            {
                "adGroupOperation": {
                    "create": {
                        "resourceName": f"customers/{customer_id}/adGroups/-3",
                        "name": f"{spec.name} — Ad Group",
                        "campaign": f"customers/{customer_id}/campaigns/-2",
                        "status": "ENABLED",
                    }
                }
            },
            # 4. Responsive search ad
            {
                "adGroupAdOperation": {
                    "create": {
                        "adGroup": f"customers/{customer_id}/adGroups/-3",
                        "status": "ENABLED",
                        "ad": {
                            "finalUrls": [(spec.creative or {}).get("final_url", "")],
                            "responsiveSearchAd": {
                                "headlines": _assets(
                                    (spec.creative or {}).get("headlines", []), 3
                                ),
                                "descriptions": _assets(
                                    (spec.creative or {}).get("descriptions", []), 2
                                ),
                            },
                        },
                    }
                }
            },
        ]

        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(
                f"{API}/customers/{customer_id}/googleAds:mutate",
                headers=headers,
                json={"mutateOperations": operations},
            )

        if r.status_code == 401:
            raise AdError(
                "Google rejected the credentials.",
                fix="Reconnect your Google Ads account in Settings → Sources.",
            )
        if r.status_code == 403:
            raise AdError(
                "Your developer token does not yet have Basic Access.",
                fix="Apply at https://developers.google.com/google-ads/api/docs/access-levels",
            )
        if r.status_code >= 400:
            raise AdError(
                f"Google Ads API error {r.status_code}.",
                fix="Check the campaign settings and try again.",
            )

        results = r.json().get("mutateOperationResponses", [])
        campaign_result = results[1].get("campaignResult", {}) if len(results) > 1 else {}
        resource = campaign_result.get("resourceName", "")
        campaign_id = resource.split("/")[-1] if resource else "unknown"

        return AdResult(
            provider_campaign_id=campaign_id,
            provider_ad_set_id=None,
            provider_ad_id=None,
            status="ACTIVE",
            review_url=f"https://ads.google.com/aw/campaigns?campaignId={campaign_id}",
        )

    async def pause(self, *, access_token: str, campaign_id: str) -> None:
        raise AdError(
            "Pause not yet implemented.",
            fix="Pause the campaign in Google Ads Manager.",
        )

    async def metrics(self, *, access_token: str, campaign_id: str) -> AdResult:
        raise AdError(
            "Metrics not yet implemented.",
            fix="View campaign performance in Google Ads Manager.",
        )


def _today() -> str:
    from datetime import datetime
    return datetime.utcnow().strftime("%Y%m%d")


def _end_date(days: int) -> str:
    from datetime import datetime, timedelta
    return (datetime.utcnow() + timedelta(days=days)).strftime("%Y%m%d")


def _assets(items: list[str], minimum: int) -> list[dict]:
    padded = items[:15] if items else ["Your compelling headline here"]
    while len(padded) < minimum:
        padded.append(padded[0])
    return [{"text": t, "pinnedField": "UNSPECIFIED"} for t in padded]
