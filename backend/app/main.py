"""Tryvanta Social API — composition root.

Wiring, middleware and lifespan only. Behaviour lives in routers and services
so this file stays readable as the surface grows.
"""
from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

import structlog
from arq.connections import create_pool
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from app.connectors.registry import load_all
from app.core.config import settings
from app.core.db import engine, init_engine
from app.core.errors import AppError, RateLimited
from app.core.ratelimit import RateLimiter
from app.routers import (
    ads, ai, analytics, automations, channels, content, crm, gbp,
    health, inbox, search, webhooks, ws,
)

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_all()  # every adapter self-registers on import
    init_engine()
    app.state.limiter = await RateLimiter.create(settings.redis_url)
    app.state.queue = await create_pool(_redis_settings())
    log.info("api.start", environment=settings.environment)
    yield
    await app.state.limiter.close()
    await app.state.queue.aclose()
    if engine is not None:
        await engine.dispose()
    log.info("api.stop")


def _redis_settings():
    from arq.connections import RedisSettings

    return RedisSettings.from_dsn(settings.redis_url)


app = FastAPI(
    title="Tryvanta Social API",
    version="1.0.0",
    summary="One inbox. One AI. One dashboard.",
    docs_url="/docs",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["x-request-id"],
)


@app.middleware("http")
async def strip_replit_api_prefix(request: Request, call_next):
    """The shared proxy keeps the /api prefix when forwarding requests."""
    path = request.scope.get("path", "")
    if path == "/api" or path.startswith("/api/"):
        stripped = path[4:] or "/"
        request.scope["path"] = stripped
        request.scope["raw_path"] = stripped.encode("ascii", "ignore")
    return await call_next(request)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    structlog.contextvars.bind_contextvars(request_id=request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        structlog.contextvars.clear_contextvars()
    response.headers["x-request-id"] = request_id
    log.info(
        "http",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        ms=round((time.perf_counter() - started) * 1000, 1),
    )
    return response


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    # Errors name what happened and what to do. They never apologise.
    headers = (
        {"Retry-After": str(exc.retry_after_s)} if isinstance(exc, RateLimited) else None
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.code, "message": exc.message, "fix": exc.fix},
        headers=headers,
    )


@app.exception_handler(Exception)
async def unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
    """Never leak a stack trace to a client. The request id in the response is
    what ties a user's report to the log line that has the detail."""
    log.exception("unhandled", error=str(exc))
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "message": "Something broke on our side.",
            "fix": "Try again. If it keeps happening, quote the x-request-id header.",
        },
    )


for module in (
    health, channels, inbox, ai, content, crm, analytics, automations, search,
    webhooks, ws, ads, gbp,
):
    app.include_router(module.router)

Instrumentator().instrument(app).expose(
    app, endpoint="/metrics", include_in_schema=False
)
