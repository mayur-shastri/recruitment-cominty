"""Calendar UI + JSON API: login, availability, busy blocks (TestClient)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# All flat-layout suites share top-level names (config/server/tools/services);
# purge any other suite's bindings so this module resolves its own source.
for _mod in [m for m in list(sys.modules) if m.split(".", 1)[0] in {"config", "server", "tools", "services", "ui", "seed"}]:
    del sys.modules[_mod]

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

import ui
from recruitment_db.database import Base
from recruitment_db.models import Interviewer
from server import create_app
from services.booking import BookingStore


@pytest.fixture
async def client(tmp_path, monkeypatch):
    url = f"sqlite+aiosqlite:///{tmp_path}/ui.db"
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    store = BookingStore(url)
    async with store._session() as session:
        session.add(Interviewer(email="asha@acme.tech", name="Asha", password="asha123"))
        await session.commit()
    monkeypatch.setattr(ui, "get_booking_store", lambda: store)
    try:
        with TestClient(create_app()) as test_client:
            yield test_client
    finally:
        await store.aclose()


def test_index_serves_html(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "interviewer" in resp.text.lower()


def test_login_and_me_round_trip(client: TestClient) -> None:
    assert client.get("/api/me").status_code == 401
    resp = client.post("/api/login", json={"email": "asha@acme.tech", "password": "asha123"})
    assert resp.status_code == 200
    assert resp.json() == {"email": "asha@acme.tech", "name": "Asha"}
    assert client.get("/api/me").json()["email"] == "asha@acme.tech"


def test_login_rejects_bad_credentials(client: TestClient) -> None:
    assert (
        client.post("/api/login", json={"email": "asha@acme.tech", "password": "wrong"}).status_code
        == 401
    )
    assert (
        client.post("/api/login", json={"email": "ghost@acme.tech", "password": "x"}).status_code
        == 401
    )
    assert client.post("/api/login", json={"email": "asha@acme.tech"}).status_code == 400


def test_busy_block_requires_login(client: TestClient) -> None:
    resp = client.post(
        "/api/busy",
        json={
            "starts_at": "2026-11-20T09:00:00+00:00",
            "ends_at": "2026-11-20T10:00:00+00:00",
            "title": "Focus",
        },
    )
    assert resp.status_code == 401


def test_busy_block_round_trip_and_overlap(client: TestClient) -> None:
    client.post("/api/login", json={"email": "asha@acme.tech", "password": "asha123"})
    payload = {
        "starts_at": "2026-11-20T09:00:00+00:00",
        "ends_at": "2026-11-20T10:00:00+00:00",
        "title": "Focus",
    }
    created = client.post("/api/busy", json=payload)
    assert created.status_code == 200
    assert created.json()["kind"] == "busy"
    assert client.post("/api/busy", json=payload).status_code == 409
    assert client.post("/api/busy", json={**payload, "title": "  "}).status_code == 400


def test_availability_endpoint(client: TestClient) -> None:
    client.post("/api/login", json={"email": "asha@acme.tech", "password": "asha123"})
    client.post(
        "/api/busy",
        json={
            "starts_at": "2026-11-20T09:00:00+00:00",
            "ends_at": "2026-11-20T10:00:00+00:00",
            "title": "Focus",
        },
    )
    resp = client.get(
        "/api/availability",
        params={
            "interviewer_email": "asha@acme.tech",
            "start": "2026-11-20T00:00:00+00:00",
            "end": "2026-11-21T00:00:00+00:00",
        },
    )
    assert resp.status_code == 200
    events = resp.json()["events"]
    assert [e["title"] for e in events] == ["Focus"]
    bad = client.get(
        "/api/availability",
        params={
            "interviewer_email": "asha@acme.tech",
            "start": "not-a-date",
            "end": "2026-11-21T00:00:00+00:00",
        },
    )
    assert bad.status_code == 400
