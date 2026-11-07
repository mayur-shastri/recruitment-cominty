"""Interviewer comms: resolve Slack IDs by email and post proactive DMs (fakes)."""

from __future__ import annotations

import pytest
from slack_sdk.errors import SlackApiError

from app.services.interviewer_comms import (
    CommsError,
    post_interviewer_dm,
    resolve_slack_id,
)


class FakeSlack:
    def __init__(self, *, known: dict | None = None, errors: dict | None = None) -> None:
        self.known = known or {"asha@acme.tech": "UASHA"}
        self.errors = errors or {}
        self.posts: list = []

    async def users_lookupByEmail(self, email: str):
        if "lookup" in self.errors:
            raise self.errors["lookup"]
        if email not in self.known:
            raise SlackApiError("no user", {"ok": False, "error": "users_not_found"})
        return {"ok": True, "user": {"id": self.known[email]}}

    async def conversations_open(self, users: str):
        return {"ok": True, "channel": {"id": f"D{users}"}}

    async def chat_postMessage(self, channel: str, text: str):
        self.posts.append((channel, text))
        return {"ok": True, "ts": "1"}


def _api_error(code: str) -> SlackApiError:
    return SlackApiError("slack refused", {"ok": False, "error": code})


async def test_resolve_returns_id() -> None:
    assert await resolve_slack_id(FakeSlack(), "asha@acme.tech") == "UASHA"


async def test_resolve_unknown_email() -> None:
    with pytest.raises(CommsError, match="no Slack user for ghost@acme.tech"):
        await resolve_slack_id(FakeSlack(), "ghost@acme.tech")


async def test_resolve_missing_scope() -> None:
    with pytest.raises(CommsError, match="users:read.email"):
        await resolve_slack_id(FakeSlack(errors={"lookup": _api_error("missing_scope")}), "a@b.c")


async def test_post_dm_opens_and_posts() -> None:
    slack = FakeSlack()
    result = await post_interviewer_dm(slack, "asha@acme.tech", "Tue 10am?")
    assert result == {"slack_user_id": "UASHA", "channel": "DUASHA"}
    assert slack.posts == [("DUASHA", "Tue 10am?")]


async def test_post_dm_truncates_long_text() -> None:
    slack = FakeSlack()
    await post_interviewer_dm(slack, "asha@acme.tech", "x" * 50_000)
    assert len(slack.posts[0][1]) < 50_000


async def test_post_dm_blank_rejected() -> None:
    with pytest.raises(CommsError, match="must not be blank"):
        await post_interviewer_dm(FakeSlack(), "asha@acme.tech", "  ")
