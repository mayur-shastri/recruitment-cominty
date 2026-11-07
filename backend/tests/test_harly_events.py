"""Harly webhook endpoint: verification, dedupe, dispatch, release-on-failure."""

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

from app.api import harly as harly_module
from app.api.harly import HarlyRuntime
from app.api.slack import Runtime
from app.main import create_app
from recruitment_db.database import Base
from recruitment_db.models import HarlyEvent

SECRET = "whsec_test"


class FakeCominty:
    def __init__(self) -> None:
        self.calls: list = []

    async def start_thread(self, message: str, *, name=None):
        self.calls.append(("start", message, name))
        return "thr_1", "SCORED a1 total=80"

    async def send_message(self, thread_id: str, message: str):
        self.calls.append(("send", thread_id, message))
        return "continued!"

    async def aclose(self) -> None:
        pass


class _StubEngine:
    async def dispose(self) -> None:
        pass


@pytest.fixture
async def factory(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/harly.db",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def client(factory):
    app = create_app()
    app.state.runtime = Runtime(
        engine=_StubEngine(),
        session_factory=factory,
        cominty=FakeCominty(),
        cominty_user_id="user_test",
        slack=object(),
        signing_secret="x",
    )
    app.state.harly_runtime = HarlyRuntime(
        session_factory=factory,
        webhook_secrets=[SECRET],
        harly_base_url="",
        harly_api_key="",
        assessment=FakeCominty(),
        assessment_agent_id="agent_test",
        scheduler=FakeCominty(),
        scheduler_agent_id="sched_test",
    )
    return TestClient(app)


def _post(client: TestClient, payload: dict, secret: str = SECRET):
    raw = json.dumps(payload).encode()
    ts = int(time.time())
    sig = f"t={ts},v1=" + hmac.new(secret.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    return client.post("/harly/events", content=raw, headers={"x-harly-signature-256": sig})


def _event(event_id: str, event_type: str, data: dict | None = None):
    return {"id": event_id, "type": event_type, "data": data or {}}


async def _row_count(factory, event_id: str) -> int:
    async with factory() as session:
        rows = (await session.execute(select(HarlyEvent).where(HarlyEvent.event_id == event_id))).all()
        return len(rows)


def test_rejects_bad_signature(client: TestClient) -> None:
    resp = _post(client, _event("e1", "application.created"), secret="whsec_wrong")
    assert resp.status_code == 400


def test_rejects_malformed_payload(client: TestClient) -> None:
    raw = b"not json"
    ts = int(time.time())
    sig = f"t={ts},v1=" + hmac.new(SECRET.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    resp = client.post("/harly/events", content=raw, headers={"x-harly-signature-256": sig})
    assert resp.status_code == 400
    assert _post(client, {"id": "e2"}).status_code == 400


def test_unknown_event_accepted(client: TestClient) -> None:
    resp = _post(client, _event("e3", "candidate.updated"))
    assert resp.json() == {"received": True}


def test_duplicate_delivery_deduped(client: TestClient) -> None:
    assert _post(client, _event("e4", "candidate.updated")).json() == {"received": True}
    assert _post(client, _event("e4", "candidate.updated")).json() == {
        "received": True,
        "duplicate": True,
    }


def test_created_dispatches_pipeline(client: TestClient, monkeypatch) -> None:
    calls: list = []

    async def fake_process(runtime, application_id: str):
        calls.append(application_id)
        return {"status": "triggered"}

    monkeypatch.setattr(harly_module.assessment_pipeline, "process_new_application", fake_process)
    resp = _post(client, _event("e5", "application.created", {"applicationId": "a1"}))
    assert resp.json() == {"received": True}
    assert calls == ["a1"]


def test_stage_changed_dispatches(client: TestClient, monkeypatch) -> None:
    calls: list = []

    async def fake_process(runtime, data: dict, *, event_id: str):
        calls.append((data, event_id))
        return {"status": "ignored"}

    monkeypatch.setattr(harly_module.assessment_pipeline, "process_stage_change", fake_process)
    resp = _post(client, _event("e6", "application.stage_changed", {"applicationId": "a1"}))
    assert resp.json() == {"received": True}
    assert calls == [({"applicationId": "a1"}, "e6")]


async def test_failure_releases_dedupe_row(client: TestClient, factory, monkeypatch) -> None:
    async def boom(runtime, application_id: str):
        raise RuntimeError("agent down")

    monkeypatch.setattr(harly_module.assessment_pipeline, "process_new_application", boom)
    resp = _post(client, _event("e7", "application.created", {"applicationId": "a1"}))
    assert resp.json() == {"received": True}
    assert await _row_count(factory, "e7") == 0
