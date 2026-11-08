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
from app.main import create_app
from recruitment_db.database import Base
from recruitment_db.models import Employee


class FakeCominty:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.started = "started!"
        self.continued = "continued!"

    async def start_thread(self, message: str, *, name=None):
        self.calls.append(("start", message, name))
        return "thr_1", self.started

    async def send_message(self, thread_id: str, message: str):
        self.calls.append(("send", thread_id, message))
        return self.continued

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
        scheduler=FakeCominty(),
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


def test_hm_reply_converts_markdown(client: TestClient, runtime) -> None:
    runtime.cominty.started = "Job **posted** — see [board](https://x/y)"
    _post(client, _dm_event("ev20"))
    assert runtime.slack.posts == [{"channel": "D1", "text": "Job *posted* — see <https://x/y|board>"}]


async def test_interviewer_reply_converts_markdown(client: TestClient, runtime) -> None:
    from app.services.conversation import record_scheduler_thread

    async with runtime.session_factory() as session:
        await record_scheduler_thread(
            session,
            slack_user_id="U_IV",
            application_id="a1",
            stage_id="s9",
            cominty_thread_id="thr_coord",
        )
    runtime.scheduler.continued = "## Slots\n- **Tue** 10am"
    _post(client, _dm_event("ev21", user="U_IV", text="hi"))
    assert runtime.slack.posts == [{"channel": "D1", "text": "*Slots*\n• *Tue* 10am"}]


def test_non_hm_ignored(client: TestClient, runtime) -> None:
    _post(client, _dm_event("ev9", user="U_JUNIOR"))
    assert runtime.cominty.calls == []
    assert runtime.scheduler.calls == []
    assert runtime.slack.posts == []


async def test_interviewer_reply_routes_to_coordination(client: TestClient, runtime) -> None:
    from app.services.conversation import record_scheduler_thread
    from recruitment_db.models import Interviewer

    async with runtime.session_factory() as session:
        await record_scheduler_thread(
            session,
            slack_user_id="U_IV",
            application_id="a1",
            stage_id="s9",
            cominty_thread_id="thr_coord",
        )
        session.add(
            Interviewer(
                email="ravi@test.dev", name="Ravi Kumar", password="x", slack_user_id="U_IV"
            )
        )
        await session.commit()
    _post(client, _dm_event("ev10", user="U_IV", text="Tue works for me"))
    assert runtime.cominty.calls == []
    assert runtime.scheduler.calls == [
        ("send", "thr_coord", "Ravi Kumar <ravi@test.dev> replied by Slack:\n\nTue works for me")
    ]
    assert runtime.slack.posts == [{"channel": "D1", "text": "continued!"}]


async def test_interviewer_reply_unknown_speaker_falls_back(client: TestClient, runtime) -> None:
    from app.services.conversation import record_scheduler_thread

    async with runtime.session_factory() as session:
        await record_scheduler_thread(
            session,
            slack_user_id="U_STRANGER",
            application_id="a1",
            stage_id="s9",
            cominty_thread_id="thr_coord",
        )
    _post(client, _dm_event("ev11", user="U_STRANGER", text="hi"))
    assert runtime.scheduler.calls == [
        ("send", "thr_coord", "Slack user U_STRANGER replied by Slack:\n\nhi")
    ]


async def test_interviewer_reply_failure_posts_error(client: TestClient, runtime) -> None:
    from app.services.cominty import ComintyServiceError
    from app.services.conversation import record_scheduler_thread

    async with runtime.session_factory() as session:
        await record_scheduler_thread(
            session,
            slack_user_id="U_IV",
            application_id="a1",
            stage_id="s9",
            cominty_thread_id="thr_coord",
        )

    async def boom(thread_id: str, message: str):
        raise ComintyServiceError("cominty down", transient=True)

    runtime.scheduler.send_message = boom
    _post(client, _dm_event("ev11", user="U_IV", text="hi"))
    assert runtime.slack.posts == [
        {
            "channel": "D1",
            "text": "Sorry — I couldn't reach the scheduling agent just now. Please try again in a bit.",
        }
    ]


def test_bot_message_ignored(client: TestClient, runtime) -> None:
    _post(client, _dm_event("ev10", subtype="bot_message", bot_id="B1"))
    assert runtime.cominty.calls == []
    assert runtime.slack.posts == []
