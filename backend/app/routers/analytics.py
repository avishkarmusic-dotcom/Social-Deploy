"""Analytics endpoints.

Metrics carry a `confident` flag rather than a number the data can't support.
The client renders "not enough data yet" instead of a figure the user would
otherwise act on for months.
"""
from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.core.deps import DB, CurrentUser
from app.services import analytics as svc

router = APIRouter(prefix="/v1/analytics", tags=["analytics"])


class MetricOut(BaseModel):
    value: float | int | None
    label: str
    change_pct: float | None = None
    confident: bool = True
    note: str | None = None


@router.get("/overview", response_model=dict[str, MetricOut], summary="Headline metrics")
async def overview(user: CurrentUser, db: DB, days: int = Query(30, ge=1, le=365)):
    metrics = await svc.overview(db, user.workspace_id, days)
    return {k: MetricOut(**v.__dict__) for k, v in metrics.items()}


@router.get("/channels", summary="Where opportunities come from")
async def channels(user: CurrentUser, db: DB, days: int = Query(90, ge=7, le=365)):
    return await svc.channel_yield(db, user.workspace_id, days)


@router.get("/growth", summary="Weekly volume and opportunity counts")
async def growth(user: CurrentUser, db: DB, days: int = Query(180, ge=14, le=730)):
    return await svc.growth_series(db, user.workspace_id, days)


@router.get("/content", summary="How published posts performed")
async def content(user: CurrentUser, db: DB, days: int = Query(90, ge=7, le=365)):
    return await svc.content_performance(db, user.workspace_id, days)


@router.get("/attribution", summary="Value traced back to its thread")
async def attribution(user: CurrentUser, db: DB, days: int = Query(90, ge=7, le=365)):
    return await svc.attribution(db, user.workspace_id, days)
