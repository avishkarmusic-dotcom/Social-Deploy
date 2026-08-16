"""Provider callbacks.

Rules this router never breaks:
  1. Verify the signature before parsing the body. An unsigned payload is not
     a message, it's an attack surface.
  2. Return 200 in under 50ms. Meta disables endpoints that are slow; Slack
     retries three times and then gives up. Real work goes on the queue.
  3. Never trust the payload's account id without checking it belongs to a
     connected account in this deployment.
"""
from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.registry import get
from app.core.config import settings
from app.core.deps import get_db, get_queue
from app.models import SourceAccount

log = structlog.get_logger()
router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])


@router.get("/{kind}", include_in_schema=False)
async def verify_subscription(
    kind: str,
    challenge: Annotated[str | None, Query(alias="hub.challenge")] = None,
    token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
    validation_token: Annotated[str | None, Query(alias="validationToken")] = None,
) -> Response:
    """Meta and Microsoft both prove endpoint ownership with a GET echo."""
    if validation_token:
        return Response(validation_token, media_type="text/plain")
    if challenge and token == settings.webhook_verify_token:
        return Response(challenge, media_type="text/plain")
    return Response(status_code=403)


@router.post("/{kind}", status_code=200)
async def receive(
    kind: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    queue=Depends(get_queue),
    content_type: Annotated[str | None, Header()] = None,
) -> dict:
    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    adapter = get(kind)

    if not adapter.verify_webhook(body, headers, settings.webhook_secret_for(kind)):
        log.warning("webhook.rejected", kind=kind, reason="signature")
        return {"ok": False}

    payload = await request.json()

    # Gmail and Outlook send a doorbell, not a delivery: the notification names
    # an account and nothing else. Enqueue a sync and get out of the way.
    if kind in {"gmail", "outlook"}:
        for account_id in await _accounts_named(db, kind, payload):
            await queue.enqueue_job("sync_account", str(account_id))
        return {"ok": True}

    threads = await adapter.parse_webhook(payload, headers)
    if not threads:
        return {"ok": True}

    account = await _account_for(db, kind, payload)
    if account is None:
        log.warning("webhook.unknown_account", kind=kind)
        return {"ok": True}

    # The heavy path — ingest, score, automate — happens on the worker so this
    # handler stays inside the provider's timeout.
    await queue.enqueue_job(
        "ingest_webhook",
        str(account.id),
        [t.model_dump(mode="json") for t in threads],
    )
    return {"ok": True}


async def _account_for(db: AsyncSession, kind: str, payload: dict) -> SourceAccount | None:
    external = (
        payload.get("team_id")
        or (payload.get("entry", [{}])[0].get("id") if payload.get("entry") else None)
        or str(payload.get("message", {}).get("chat", {}).get("id", ""))
    )
    if not external:
        return None
    return await db.scalar(
        select(SourceAccount).where(
            SourceAccount.source_kind == kind, SourceAccount.external_id == str(external)
        )
    )


async def _accounts_named(db: AsyncSession, kind: str, payload: dict) -> list:
    import base64
    import json

    if data := payload.get("message", {}).get("data"):
        decoded = json.loads(base64.b64decode(data))
        email = decoded.get("emailAddress")
        rows = await db.scalars(
            select(SourceAccount.id).where(
                SourceAccount.source_kind == kind, SourceAccount.external_id == email
            )
        )
        return list(rows)
    return []
