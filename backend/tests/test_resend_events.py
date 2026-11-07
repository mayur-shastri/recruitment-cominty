"""Resend inbound receiver: verify, dedupe, route to thread, reply (fakes)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api import resend as resend_module
from app.api.resend import ResendRuntime
from app.main import create_app
from recruitment_db.database import Base
from recruitment_db.models import CandidateThread, ResendEvent

SECRET = "whsec_MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODk="


class FakeCominty:
    def __init__(self) -> None:
        self.calls: list = []

    async def send_message(self, thread_id: str, message: str):
        self.calls.append(("send", thread_id, message))
        return "How about Wed 2pm instead?"


class FakeResend:
    def __init__(self, email: dict | None = None) -> None:
        self.email = email or {
            "from": "cand@test.com",
            "to": ["sched-tok1@in.test.dev"],
            "subject": "R1 options",
            "text": "Tue doesn't work for me",
        }
        self.sends: list = []

    async def get_received_email(self, email_id: str):
        assert email_id == "email_9"
        return self.email

    async def send_email(self, *, from_email, to_email, subject, text, reply_to):
        self.sends.append(
            {
                "from_email": from_email,
                "to_email": to_email,
                "subject": subject,
                "text": text,
                "reply_to": reply_to,
            }
        )
        return "email_10"


@pytest.fixture
async def factory(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/resend.db",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def resend_client(factory, monkeypatch):
    resend = FakeResend()
    cominty = FakeCominty()
    monkeypatch.setattr(resend_module, "ResendClient", lambda api_key: resend)
    app = create_app()
    app.state.resend_runtime = ResendRuntime(
        session_factory=factory,
        webhook_secret=SECRET,
        scheduler=cominty,
        resend_api_key="re_test",
        resend_from_email="Acme <sched@test.dev>",
    )
    # No lifespan (needs real settings); background tasks still run per request.
    yield TestClient(app), factory, resend, cominty


def _signed(body: dict, svix_id: str = "msg_1") -> tuple[bytes, dict]:
    raw = json.dumps(body).encode()
    key = base64.b64decode(SECRET.split("_", 1)[1])
    import time

    ts = str(int(time.time()))
    sig = base64.b64encode(
        hmac.new(key, f"{svix_id}.{ts}.".encode() + raw, hashlib.sha256).digest()
    ).decode()
    return raw, {"svix-id": svix_id, "svix-timestamp": ts, "svix-signature": f"v1,{sig}"}


def _received(svix_id: str = "msg_1", **data_overrides) -> tuple[bytes, dict]:
    data = {
        "email_id": "email_9",
        "from": "cand@test.com",
        "to": ["sched-tok1@in.test.dev"],
        "subject": "R1 options",
    }
    data.update(data_overrides)
    return _signed({"type": "email.received", "data": data}, svix_id)


async def _seed_thread(factory) -> None:
    async with factory() as session:
        session.add(
            CandidateThread(
                token="tok1",
                application_id="a1",
                stage_id="s9",
                cominty_thread_id="thr_1",
                candidate_email="cand@test.com",
            )
        )
        await session.commit()


async def test_inbound_routes_and_replies(resend_client) -> None:
    client, factory, resend, cominty = resend_client
    await _seed_thread(factory)
    raw, headers = _received()
    resp = client.post("/resend/events", content=raw, headers=headers)
    assert resp.json() == {"received": True}
    assert cominty.calls == [
        ("send", "thr_1", "Candidate cand@test.com replied by email:\n\nTue doesn't work for me")
    ]
    assert len(resend.sends) == 1
    sent = resend.sends[0]
    assert sent["to_email"] == "cand@test.com"
    assert sent["subject"] == "Re: R1 options"
    assert sent["text"] == "How about Wed 2pm instead?"
    assert sent["reply_to"] == "sched-tok1@in.test.dev"


async def test_unknown_token_ignored(resend_client) -> None:
    client, factory, resend, cominty = resend_client
    raw, headers = _received(to=["sched-nope@in.test.dev"])
    assert client.post("/resend/events", content=raw, headers=headers).json() == {"received": True}
    assert cominty.calls == []
    assert resend.sends == []


async def test_other_event_types_ignored(resend_client) -> None:
    client, factory, resend, cominty = resend_client
    raw, headers = _signed({"type": "email.delivered", "data": {}}, "msg_2")
    assert client.post("/resend/events", content=raw, headers=headers).json() == {"received": True}
    assert cominty.calls == []


def test_bad_signature_rejected(resend_client) -> None:
    client, *_ = resend_client
    raw, headers = _received()
    headers["svix-signature"] = "v1,AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
    assert client.post("/resend/events", content=raw, headers=headers).status_code == 400


async def test_replay_deduped(resend_client) -> None:
    client, factory, resend, cominty = resend_client
    await _seed_thread(factory)
    raw, headers = _received()
    assert client.post("/resend/events", content=raw, headers=headers).json() == {"received": True}
    dup = client.post("/resend/events", content=raw, headers=headers).json()
    assert dup == {"received": True, "duplicate": True}
    assert len(cominty.calls) == 1


async def test_failure_releases_row(resend_client) -> None:
    client, factory, resend, cominty = resend_client
    await _seed_thread(factory)

    async def boom(thread_id: str, message: str):
        raise RuntimeError("cominty down")

    cominty.send_message = boom
    raw, headers = _received()
    assert client.post("/resend/events", content=raw, headers=headers).json() == {"received": True}
    async with factory() as session:
        rows = (await session.execute(select(ResendEvent))).scalars().all()
        assert rows == []
