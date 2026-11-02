"""HarlyClient unit tests (mocked HTTP; no live Harly). Run from ats-mcp/."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import services.harly as harly_module
from services.harly import HarlyClient, HarlyError, get_harly_client


def _client(handler) -> HarlyClient:
    return HarlyClient(
        base_url="https://harly.test", api_key="key", transport=httpx.MockTransport(handler)
    )


async def test_list_jobs_parses_envelope_and_auth() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["path"] = request.url.path
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
    assert seen["path"] == "/api/v1/jobs"
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


def test_base_url_with_api_prefix_fails_fast(monkeypatch) -> None:
    class FakeSettings:
        harly_base_url = "https://x/api/v1"
        harly_api_key = "key"

    monkeypatch.setattr(harly_module, "get_mcp_settings", lambda: FakeSettings())
    with pytest.raises(HarlyError, match="without the /api/v1 suffix"):
        get_harly_client()


async def test_create_job_forces_draft() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(201, json={"data": {"id": "j9", "status": "draft"}, "meta": {}})

    client = _client(handler)
    try:
        result = await client.create_job(
            title="T", description="D", employment_type="full_time", workplace_type="remote"
        )
    finally:
        await client.aclose()
    assert (seen["method"], seen["path"]) == ("POST", "/api/v1/jobs")
    assert seen["body"] == {
        "title": "T",
        "description": "D",
        "employmentType": "full_time",
        "workplaceType": "remote",
        "status": "draft",
    }
    assert result == {"id": "j9", "status": "draft"}


async def test_update_job_sends_only_provided_fields() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"data": {"id": "j1"}, "meta": {}})

    client = _client(handler)
    try:
        await client.update_job("j1", title="T", salary_min=5)
    finally:
        await client.aclose()
    assert (seen["method"], seen["path"]) == ("PATCH", "/api/v1/jobs/j1")
    assert seen["body"] == {"title": "T", "salaryMin": 5}
    assert "status" not in seen["body"]


async def test_publish_and_close_post_empty_bodies() -> None:
    seen: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.content))
        return httpx.Response(200, json={"data": {"id": "j1"}, "meta": {}})

    client = _client(handler)
    try:
        await client.publish_job("j1")
        await client.close_job("j1")
    finally:
        await client.aclose()
    assert seen == [
        ("POST", "/api/v1/jobs/j1/publish", b""),
        ("POST", "/api/v1/jobs/j1/close", b""),
    ]


async def test_delete_job_uses_delete() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        return httpx.Response(200, json={"data": {"id": "j1"}, "meta": {}})

    client = _client(handler)
    try:
        await client.delete_job("j1")
    finally:
        await client.aclose()
    assert (seen["method"], seen["path"]) == ("DELETE", "/api/v1/jobs/j1")


async def test_422_maps_to_harly_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"error": {"code": "validation_failed", "message": "bad"}})

    client = _client(handler)
    try:
        with pytest.raises(HarlyError) as exc_info:
            await client.create_job(
                title="T", description="D", employment_type="x", workplace_type="y"
            )
    finally:
        await client.aclose()
    assert exc_info.value.code == "validation_failed"
    assert exc_info.value.status_code == 422
    assert exc_info.value.transient is False


async def test_list_applications_filters_and_pagination() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={"data": [{"id": "a1"}], "meta": {"pagination": {"nextCursor": "c9", "hasMore": True}}},
        )

    client = _client(handler)
    try:
        result = await client.list_applications(job_id="j1", status="active", limit=5)
    finally:
        await client.aclose()
    assert seen["path"] == "/api/v1/applications"
    assert seen["params"] == {"limit": "5", "jobId": "j1", "status": "active"}
    assert result == {"applications": [{"id": "a1"}], "next_cursor": "c9", "has_more": True}


async def test_get_application_passthrough() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        return httpx.Response(200, json={"data": {"id": "a1"}, "meta": {}})

    client = _client(handler)
    try:
        result = await client.get_application("a1")
    finally:
        await client.aclose()
    assert (seen["method"], seen["path"]) == ("GET", "/api/v1/applications/a1")
    assert result == {"id": "a1"}


async def test_get_candidate_passthrough() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        return httpx.Response(200, json={"data": {"id": "c1"}, "meta": {}})

    client = _client(handler)
    try:
        result = await client.get_candidate("c1")
    finally:
        await client.aclose()
    assert (seen["method"], seen["path"]) == ("GET", "/api/v1/candidates/c1")
    assert result == {"id": "c1"}
