"""Interviewer comms: resolve Slack IDs by email and post proactive DMs (fakes)."""

from __future__ import annotations

import pytest
from slack_sdk.errors import SlackApiError

from app.services.interviewer_comms import (
    CommsError,
    post_dm_by_id,
    post_interviewer_dm,
    resolve_slack_id,
    resolve_stored_slack_id,
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


async def test_post_dm_by_id_skips_open() -> None:
    class NoOpen(FakeSlack):
        async def conversations_open(self, users: str):
            raise AssertionError("open must not run on the direct path")

    slack = NoOpen()
    result = await post_dm_by_id(slack, "UASHA", "Hi **Asha**")
    assert result == {"slack_user_id": "UASHA", "channel": "UASHA"}
    assert slack.posts == [("UASHA", "Hi *Asha*")]


async def test_post_dm_open_missing_scope_falls_back_to_direct() -> None:
    class NoOpenScope(FakeSlack):
        async def conversations_open(self, users: str):
            raise _api_error("missing_scope")

    slack = NoOpenScope()
    result = await post_interviewer_dm(slack, "asha@acme.tech", "Tue?")
    assert result == {"slack_user_id": "UASHA", "channel": "UASHA"}
    assert slack.posts == [("UASHA", "Tue?")]


async def test_resolve_stored_slack_id(tmp_path) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from recruitment_db.database import Base
    from recruitment_db.models import Interviewer

    url = f"sqlite+aiosqlite:///{tmp_path}/ids.db"
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(Interviewer(email="a@t.co", name="A", password="x", slack_user_id="U1"))
        session.add(Interviewer(email="b@t.co", name="B", password="x"))
        await session.commit()
    try:
        assert await resolve_stored_slack_id(factory, "a@t.co") == "U1"
        assert await resolve_stored_slack_id(factory, "b@t.co") is None
        assert await resolve_stored_slack_id(factory, "ghost@t.co") is None
    finally:
        await engine.dispose()
