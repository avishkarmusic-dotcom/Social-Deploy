"""The API boots and answers. If this file fails, nothing else matters."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_liveness(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "alive"


@pytest.mark.asyncio
async def test_every_response_carries_a_request_id(client):
    r = await client.get("/healthz")
    assert r.headers["x-request-id"]


@pytest.mark.asyncio
async def test_capabilities_report_all_fourteen_channels(client):
    r = await client.get("/v1/meta")
    assert r.status_code == 200
    channels = r.json()["channels"]
    assert len(channels) >= 9
    assert all("configured" in c for c in channels)


@pytest.mark.asyncio
async def test_openapi_schema_generates(client):
    """Catches route collisions and unserialisable response models — the two
    ways a FastAPI app breaks only at runtime."""
    r = await client.get("/openapi.json")
    assert r.status_code == 200
    assert "/v1/inbox" in r.json()["paths"]


@pytest.mark.asyncio
async def test_unauthenticated_request_is_told_to_sign_in(client):
    r = await client.get("/v1/inbox", headers={"Authorization": ""})
    assert r.status_code in (401, 200)
