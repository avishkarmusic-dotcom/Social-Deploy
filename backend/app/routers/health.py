"""Liveness and readiness.

These are two different questions and conflating them causes outages.
`/healthz` asks "is this process alive" — if it fails, restart the container.
`/readyz` asks "can this process serve traffic" — if it fails, take it out of
the load balancer but leave it running, because a restart won't fix a database
that's still coming back.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Request, Response

from app.core.config import settings
from app.core.db import healthy as db_healthy

log = structlog.get_logger()
router = APIRouter(tags=["health"])


@router.get("/healthz", include_in_schema=False)
async def liveness() -> dict:
    return {"status": "alive", "environment": settings.environment}


@router.get("/readyz", include_in_schema=False)
async def readiness(request: Request, response: Response) -> dict:
    checks = {"database": await db_healthy(), "redis": await _redis_ok(request)}
    ready = all(checks.values())
    response.status_code = 200 if ready else 503
    return {"ready": ready, "checks": checks}


@router.get("/v1/meta", tags=["meta"], summary="What this deployment can do")
async def capabilities() -> dict:
    """Lets the client render honest UI — a channel with no configured OAuth
    credentials shows as unavailable rather than failing on click."""
    from app.connectors.registry import all_adapters, load_all

    load_all()
    return {
        "version": "1.0.0",
        "ai_providers": [
            name
            for name, configured in {
                "anthropic": bool(settings.anthropic_api_key),
                "openai": bool(settings.openai_api_key),
                "google": bool(settings.google_api_key),
                "groq": bool(settings.groq_api_key),
                "ollama": True,
            }.items()
            if configured
        ],
        "channels": [
            {
                "kind": str(a.source_kind),
                "push": a.supports_push,
                "can_send": a.supports_send,
                "configured": _configured(a.source_kind),
            }
            for a in all_adapters()
        ],
    }


def _configured(kind: str) -> bool:
    needs = {
        "gmail": settings.google_client_id,
        "youtube": settings.google_client_id,
        "google_business": settings.google_client_id,
        "outlook": settings.microsoft_client_id,
        "linkedin": settings.linkedin_client_id,
        "instagram": settings.meta_app_id,
        "messenger": settings.meta_app_id,
        "whatsapp": settings.meta_app_id,
        "facebook": settings.meta_app_id,
        "slack": settings.slack_client_id,
        "x": settings.x_client_id,
        "telegram": "always",
    }
    return bool(needs.get(str(kind), ""))


async def _redis_ok(request: Request) -> bool:
    try:
        limiter = getattr(request.app.state, "limiter", None)
        if limiter is None:
            return False
        return bool(await limiter.allow("healthcheck", burst=1000, per_second=1000))
    except Exception:
        return False
