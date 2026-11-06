"""HarlyReads against mocked HTTP (no live Harly)."""

from __future__ import annotations

import httpx
import pytest

from app.integrations.harly.client import HarlyReadError, HarlyReads


def _reads(handler) -> HarlyReads:
    return HarlyReads("https://harly.test", "key", transport=httpx.MockTransport(handler))


async def test_requires_config() -> None:
    with pytest.raises(HarlyReadError, match="not configured"):
        HarlyReads("", "key")
    with pytest.raises(HarlyReadError, match="not configured"):
        HarlyReads("https://harly.test", "")


async def test_get_application() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/applications/a1"
        assert request.headers["authorization"] == "Bearer key"
        return httpx.Response(200, json={"data": {"id": "a1", "candidateId": "c1"}, "meta": {}})

    assert await _reads(handler).get_application("a1") == {"id": "a1", "candidateId": "c1"}


async def test_list_candidate_files_paginates() -> None:
    seen: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params.get("cursor"))
        if len(seen) == 1:
            return httpx.Response(
                200,
                json={
                    "data": [{"id": "f1"}],
                    "meta": {"pagination": {"nextCursor": "c9", "hasMore": True}},
                },
            )
        return httpx.Response(
            200, json={"data": [{"id": "f2"}], "meta": {"pagination": {"nextCursor": None, "hasMore": False}}}
        )

    files = await _reads(handler).list_candidate_files("c1")
    assert [f["id"] for f in files] == ["f1", "f2"]


async def test_errors_are_user_safe() -> None:
    def not_found(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"code": "x", "message": "nope"}})

    with pytest.raises(HarlyReadError, match="not found"):
        await _reads(not_found).get_application("a9")

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns down")

    with pytest.raises(HarlyReadError, match="ConnectError"):
        await _reads(boom).get_application("a1")
