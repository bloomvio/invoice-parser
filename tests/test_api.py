"""§17 — End-to-end API tests with mocked external calls."""

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, patch

from invoice_parser.api.main import app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_auth_required(client):
    resp = await client.get("/jobs/job_abc123")
    assert resp.status_code == 401


async def test_auth_invalid(client):
    resp = await client.get("/jobs/job_abc123", headers={"Authorization": "Bearer bad_key"})
    assert resp.status_code == 401
