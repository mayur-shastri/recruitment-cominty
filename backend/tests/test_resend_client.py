"""Resend client: send + inbound fetch (MockTransport, no network)."""

from __future__ import annotations

import json

import httpx
import pytest

from app.integrations.resend.client import ResendClient, ResendError


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


async def test_send_returns_id() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer re_test"
        return httpx.Response(200, json={"id": "email_1"})

    client = ResendClient("re_test", transport=_transport(handler))
    email_id = await client.send_email(
        from_email="Acme <sched@test.dev>",
        to_email="cand@test.com",
        subject="Interview",
        text="Tue?",
        reply_to="sched-a1-s9@test.dev",
    )
    assert email_id == "email_1"
    assert seen["reply_to"] == "sched-a1-s9@test.dev"
    assert seen["text"] == "Tue?"


async def test_send_requires_key() -> None:
    with pytest.raises(ResendError, match="not configured"):
        ResendClient("")


async def test_send_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"message": "bad from"})

    client = ResendClient("re_test", transport=_transport(handler))
    with pytest.raises(ResendError, match="status 422"):
        await client.send_email(
            from_email="x", to_email="y", subject="s", text="t", reply_to="r"
        )


async def test_get_received_email() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/emails/receiving/email_9"
        return httpx.Response(
            200, json={"from": "cand@test.com", "subject": "Re: Interview", "text": "Tue works"}
        )

    client = ResendClient("re_test", transport=_transport(handler))
    email = await client.get_received_email("email_9")
    assert email["text"] == "Tue works"


async def test_get_received_email_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={})

    client = ResendClient("re_test", transport=_transport(handler))
    with pytest.raises(ResendError, match="not found"):
        await client.get_received_email("email_nope")
