"""HarlyClient unit tests (mocked HTTP; no live Harly). Run from ats-mcp/."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import services.harly as harly_module
from services.harly import HarlyClient, HarlyError, get_harly_client


def _client(handler) -> HarlyClient:
    return HarlyClient(
        base_url="https://harly.test/api/v1", api_key="key", transport=httpx.MockTransport(handler)
    )


async def test_list_jobs_parses_envelope_and_auth() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={"data": [{"id": "j1"}], "meta": {"pagination": {"nextCursor": "c9", "hasMore": True}}},
        )

    client = _client(handler)
    try:
        result = await client.list_jobs(status="open", limit=5)
    finally:
        await client.aclose()
    assert seen["auth"] == "Bearer key"
    assert seen["params"] == {"limit": "5", "status": "open"}
    assert result == {"jobs": [{"id": "j1"}], "next_cursor": "c9", "has_more": True}


async def test_error_envelope_raises_harly_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"code": "not_found", "message": "nope"}})

    client = _client(handler)
    try:
        with pytest.raises(HarlyError) as exc_info:
            await client.get_job("j1")
    finally:
        await client.aclose()
    assert exc_info.value.code == "not_found"
    assert exc_info.value.status_code == 404
    assert exc_info.value.transient is False


async def test_rate_limit_retries_then_succeeds() -> None:
    calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, json={"error": {"code": "rate_limited", "message": "slow"}})
        return httpx.Response(200, json={"data": {"id": "j1"}, "meta": {}})

    client = _client(handler)
    try:
        assert await client.get_job("j1") == {"id": "j1"}
    finally:
        await client.aclose()
    assert len(calls) == 2


async def test_persistent_500_raises_transient() -> None:
    calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(500, json={"error": {"code": "boom", "message": "boom"}})

    client = _client(handler)
    try:
        with pytest.raises(HarlyError) as exc_info:
            await client.list_job_stages("j1")
    finally:
        await client.aclose()
    assert len(calls) == 3
    assert exc_info.value.transient is True


async def test_missing_key_fails_fast(monkeypatch) -> None:
    class FakeSettings:
        harly_base_url = "https://x"
        harly_api_key = ""

    monkeypatch.setattr(harly_module, "get_mcp_settings", lambda: FakeSettings())
    with pytest.raises(HarlyError, match="HARLY_API_KEY"):
        get_harly_client()
