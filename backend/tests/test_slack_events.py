"""Slack endpoint: verification handshake, auth, dedupe, gating, round trip."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.slack import Runtime
from app.database import Base
from app.main import create_app
from app.models import Employee


class FakeCominty:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def start_thread(self, message: str, *, name=None):
        self.calls.append(("start", message, name))
        return "thr_1", "started!"

    async def send_message(self, thread_id: str, message: str):
        self.calls.append(("send", thread_id, message))
        return "continued!"

    async def aclose(self) -> None:
        pass


class FakeSlack:
    def __init__(self) -> None:
        self.posts: list[dict] = []

    async def chat_postMessage(self, channel: str, text: str):
        self.posts.append({"channel": channel, "text": text})
        return {"ok": True}


@pytest.fixture
async def runtime(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/slack.db",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(Employee(slack_user_id="U_HM", grade=8))
        await session.commit()
    yield Runtime(
        engine=engine,
        session_factory=factory,
        cominty=FakeCominty(),
        cominty_user_id="user_test",
        slack=FakeSlack(),
        signing_secret="test-secret",
    )
    await engine.dispose()


@pytest.fixture
def client(runtime):
    app = create_app()
    app.state.runtime = runtime
    return TestClient(app)


def _post(client: TestClient, payload: dict, secret: str = "test-secret"):
    raw = json.dumps(payload).encode()
    ts = str(int(time.time()))
    sig = "v0=" + hmac.new(secret.encode(), f"v0:{ts}:".encode() + raw, hashlib.sha256).hexdigest()
    return client.post(
        "/slack/events",
        content=raw,
        headers={"x-slack-signature": sig, "x-slack-request-timestamp": ts},
    )


def _dm_event(event_id: str, **overrides):
    event = {"type": "message", "channel_type": "im", "channel": "D1", "user": "U_HM", "text": "hi"}
    event.update(overrides)
    return {"type": "event_callback", "event_id": event_id, "event": event}


def test_url_verification(client: TestClient) -> None:
    resp = _post(client, {"type": "url_verification", "challenge": "abc123"})
    assert resp.status_code == 200
    assert resp.json() == {"challenge": "abc123"}


def test_bad_signature_rejected(client: TestClient) -> None:
    resp = _post(client, {"type": "url_verification", "challenge": "x"}, secret="wrong")
    assert resp.status_code == 401


def test_dm_round_trip_and_dedupe(client: TestClient, runtime) -> None:
    payload = _dm_event("ev1")
    assert _post(client, payload).status_code == 200
    assert runtime.cominty.calls == [("start", "hi", "slack:U_HM")]
    assert runtime.slack.posts == [{"channel": "D1", "text": "started!"}]
    resp = _post(client, payload)
    assert resp.json() == {"ok": True, "deduped": True}
    assert len(runtime.cominty.calls) == 1
    assert len(runtime.slack.posts) == 1


def test_follow_up_uses_thread(client: TestClient, runtime) -> None:
    _post(client, _dm_event("ev1"))
    _post(client, _dm_event("ev2", text="again"))
    assert runtime.cominty.calls == [("start", "hi", "slack:U_HM"), ("send", "thr_1", "again")]


def test_non_hm_ignored(client: TestClient, runtime) -> None:
    _post(client, _dm_event("ev9", user="U_JUNIOR"))
    assert runtime.cominty.calls == []
    assert runtime.slack.posts == []


def test_bot_message_ignored(client: TestClient, runtime) -> None:
    _post(client, _dm_event("ev10", subtype="bot_message", bot_id="B1"))
    assert runtime.cominty.calls == []
    assert runtime.slack.posts == []
