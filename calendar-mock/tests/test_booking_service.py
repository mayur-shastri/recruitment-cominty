"""BookingStore against a real (SQLite) database. Run from calendar-mock/."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# All flat-layout suites share top-level names (config/server/tools/services);
# purge any other suite's bindings so this module resolves its own source.
for _mod in [m for m in list(sys.modules) if m.split(".", 1)[0] in {"config", "server", "tools", "services", "ui", "seed"}]:
    del sys.modules[_mod]

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

import services.booking as booking_module
from recruitment_db.database import Base
from recruitment_db.models import CalendarEvent, Interviewer
from services.booking import (
    BookingConflictError,
    BookingError,
    BookingNotFoundError,
    BookingStore,
)


def _dt(day: int, hour: int, minute: int = 0):
    return datetime(2026, 11, day, hour, minute, tzinfo=timezone.utc)


@pytest.fixture
async def store(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/booking.db"
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    s = BookingStore(url)
    try:
        yield s
    finally:
        await s.aclose()


async def _seed_interviewer(store: BookingStore, email: str = "asha@acme.tech") -> None:
    async with store._session() as session:
        session.add(Interviewer(email=email, name="Asha", password="asha123"))
        await session.commit()


async def test_list_interviewers_empty(store: BookingStore) -> None:
    assert await store.list_interviewers() == {"interviewers": []}


async def test_list_interviewers(store: BookingStore) -> None:
    await _seed_interviewer(store, "asha@acme.tech")
    await _seed_interviewer(store, "ravi@acme.tech")
    result = await store.list_interviewers()
    assert result == {
        "interviewers": [
            {"email": "asha@acme.tech", "name": "Asha"},
            {"email": "ravi@acme.tech", "name": "Asha"},
        ]
    }


async def test_book_interview_round_trip(store: BookingStore) -> None:
    await _seed_interviewer(store)
    booked = await store.book_interview(
        interviewer_email="asha@acme.tech",
        starts_at=_dt(20, 10),
        ends_at=_dt(20, 11),
        title="R1 screen",
        event_key="evt-1",
        application_id="a1",
        job_id="j1",
    )
    assert booked["interviewer_email"] == "asha@acme.tech"
    assert booked["starts_at"] == "2026-11-20T10:00:00+00:00"
    assert booked["ends_at"] == "2026-11-20T11:00:00+00:00"
    assert booked["kind"] == "interview"
    assert booked["event_key"] == "evt-1"


async def test_book_interview_replay_returns_same_row(store: BookingStore) -> None:
    await _seed_interviewer(store)
    first = await store.book_interview(
        interviewer_email="asha@acme.tech",
        starts_at=_dt(20, 10),
        ends_at=_dt(20, 11),
        title="R1 screen",
        event_key="evt-1",
    )
    second = await store.book_interview(
        interviewer_email="asha@acme.tech",
        starts_at=_dt(20, 10),
        ends_at=_dt(20, 11),
        title="R1 screen",
        event_key="evt-1",
    )
    assert first["id"] == second["id"]
    listed = await store.list_interviews(application_id=None)
    assert len(listed["interviews"]) == 1


async def test_book_interview_unknown_interviewer(store: BookingStore) -> None:
    with pytest.raises(BookingNotFoundError, match="nobody@acme.tech"):
        await store.book_interview(
            interviewer_email="nobody@acme.tech",
            starts_at=_dt(20, 10),
            ends_at=_dt(20, 11),
            title="R1",
            event_key="evt-9",
        )


async def test_book_interview_overlap_rejected(store: BookingStore) -> None:
    await _seed_interviewer(store)
    await store.book_interview(
        interviewer_email="asha@acme.tech",
        starts_at=_dt(20, 10),
        ends_at=_dt(20, 11),
        title="R1",
        event_key="evt-1",
    )
    with pytest.raises(BookingConflictError, match="overlaps"):
        await store.book_interview(
            interviewer_email="asha@acme.tech",
            starts_at=_dt(20, 10, 30),
            ends_at=_dt(20, 11, 30),
            title="R2",
            event_key="evt-2",
        )
    # Boundary-touching is fine.
    ok = await store.book_interview(
        interviewer_email="asha@acme.tech",
        starts_at=_dt(20, 11),
        ends_at=_dt(20, 12),
        title="R2",
        event_key="evt-3",
    )
    assert ok["starts_at"] == "2026-11-20T11:00:00+00:00"


async def test_add_busy_block_and_availability(store: BookingStore) -> None:
    await _seed_interviewer(store, "asha@acme.tech")
    await _seed_interviewer(store, "ravi@acme.tech")
    async with store._session() as session:
        session.add(
            CalendarEvent(
                interviewer_email="asha@acme.tech",
                starts_at=_dt(20, 9),
                ends_at=_dt(20, 10),
                kind="busy",
                title="Focus",
            )
        )
        await session.commit()
    result = await store.get_availability(
        ["asha@acme.tech", "ravi@acme.tech"], _dt(20, 0), _dt(21, 0)
    )
    assert [e["title"] for e in result["availability"]["asha@acme.tech"]] == ["Focus"]
    assert result["availability"]["ravi@acme.tech"] == []


async def test_get_availability_unknown_email(store: BookingStore) -> None:
    with pytest.raises(BookingNotFoundError, match="ghost@acme.tech"):
        await store.get_availability(["ghost@acme.tech"], _dt(20, 0), _dt(21, 0))


async def test_seed_is_idempotent(store: BookingStore) -> None:
    import seed as seed_module

    expected = sum(len(slots) for days in seed_module.PATTERNS.values() for slots in days.values())
    first = await seed_module.seed(store)
    second = await seed_module.seed(store)
    assert first == second == {"interviewers": 3, "blocks": expected}
    assert expected > 40  # a full-feeling week with gaps left for agent bookings
    assert len((await store.list_interviewers())["interviewers"]) == 3


async def test_verify_interviewer(store: BookingStore) -> None:
    await _seed_interviewer(store)
    ok = await store.verify_interviewer("asha@acme.tech", "asha123")
    assert ok == {"email": "asha@acme.tech", "name": "Asha"}
    with pytest.raises(BookingNotFoundError, match="invalid email or password"):
        await store.verify_interviewer("asha@acme.tech", "wrong")
    with pytest.raises(BookingNotFoundError, match="invalid email or password"):
        await store.verify_interviewer("ghost@acme.tech", "x")


async def test_get_booking_store_normalizes_libpq_url(monkeypatch) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(
        booking_module,
        "get_calendar_settings",
        lambda: SimpleNamespace(database_url="postgresql://u:p@h/db?sslmode=require"),
    )
    store = booking_module.get_booking_store()
    try:
        assert store._engine.url.drivername == "postgresql+asyncpg"
        assert "ssl=require" in str(store._engine.url)
    finally:
        await store.aclose()


async def _book(
    store: BookingStore, key: str, day: int = 20, hour: int = 10, email: str = "asha@acme.tech"
):
    return await store.book_interview(
        interviewer_email=email,
        starts_at=_dt(day, hour),
        ends_at=_dt(day, hour + 1),
        title="R1",
        event_key=key,
        application_id="a1",
    )


async def test_update_interview_reschedules(store: BookingStore) -> None:
    await _seed_interviewer(store)
    booked = await _book(store, "e1")
    moved = await store.update_interview(booked["id"], starts_at=_dt(21, 14), ends_at=_dt(21, 15))
    assert moved["starts_at"] == "2026-11-21T14:00:00+00:00"
    assert moved["event_key"] == "e1"


async def test_update_interview_validates(store: BookingStore) -> None:
    await _seed_interviewer(store)
    booked = await _book(store, "e1")
    await _book(store, "e2", hour=14)
    with pytest.raises(BookingConflictError, match="overlaps"):
        await store.update_interview(booked["id"], starts_at=_dt(20, 14, 30), ends_at=_dt(20, 15, 30))
    with pytest.raises(BookingError, match="before end"):
        await store.update_interview(booked["id"], starts_at=_dt(20, 12), ends_at=_dt(20, 11))
    with pytest.raises(BookingNotFoundError, match="no interview 999"):
        await store.update_interview(999, title="x")
    with pytest.raises(BookingError, match="not an interview"):
        async with store._session() as session:
            from recruitment_db.models import CalendarEvent

            row = CalendarEvent(
                interviewer_email="asha@acme.tech",
                starts_at=_dt(22, 9),
                ends_at=_dt(22, 10),
                kind="busy",
                title="Focus",
            )
            session.add(row)
            await session.commit()
            busy_id = row.id
        await store.update_interview(busy_id, title="x")


async def test_update_interview_moves_interviewer(store: BookingStore) -> None:
    await _seed_interviewer(store, "asha@acme.tech")
    await _seed_interviewer(store, "ravi@acme.tech")
    booked = await _book(store, "e1")
    moved = await store.update_interview(booked["id"], interviewer_email="ravi@acme.tech")
    assert moved["interviewer_email"] == "ravi@acme.tech"
    with pytest.raises(BookingNotFoundError, match="ghost@acme.tech"):
        await store.update_interview(booked["id"], interviewer_email="ghost@acme.tech")


async def test_cancel_interview(store: BookingStore) -> None:
    await _seed_interviewer(store)
    booked = await _book(store, "e1")
    result = await store.cancel_interview(booked["id"])
    assert result["status"] == "cancelled"
    assert result["interview"]["id"] == booked["id"]
    with pytest.raises(BookingNotFoundError, match="no interview"):
        await store.cancel_interview(booked["id"])
    # Slot is free again.
    again = await _book(store, "e2")
    assert again["starts_at"] == "2026-11-20T10:00:00+00:00"


async def test_find_slots_common_gaps(store: BookingStore) -> None:
    await _seed_interviewer(store, "asha@acme.tech")
    await _seed_interviewer(store, "ravi@acme.tech")
    await store.add_busy_block(
        interviewer_email="asha@acme.tech", starts_at=_dt(20, 9), ends_at=_dt(20, 12), title="Busy"
    )
    await store.add_busy_block(
        interviewer_email="ravi@acme.tech", starts_at=_dt(20, 14), ends_at=_dt(20, 16), title="Busy"
    )
    result = await store.find_slots(
        ["asha@acme.tech", "ravi@acme.tech"], _dt(20, 9), _dt(20, 17), duration_mins=60
    )
    windows = [(s["starts_at"], s["ends_at"]) for s in result["slots"]]
    assert ("2026-11-20T12:00:00+00:00", "2026-11-20T14:00:00+00:00") in windows
    assert ("2026-11-20T16:00:00+00:00", "2026-11-20T17:00:00+00:00") in windows
    # Too-long durations filter everything.
    narrow = await store.find_slots(["asha@acme.tech"], _dt(20, 9), _dt(20, 17), duration_mins=480)
    assert narrow["slots"] == []
    with pytest.raises(BookingNotFoundError, match="ghost@acme.tech"):
        await store.find_slots(["ghost@acme.tech"], _dt(20, 9), _dt(20, 17), duration_mins=30)


async def test_list_interviews_filters_application(store: BookingStore) -> None:
    await _seed_interviewer(store)
    for key, app in (("e1", "a1"), ("e2", "a2")):
        await store.book_interview(
            interviewer_email="asha@acme.tech",
            starts_at=_dt(20, 9 if key == "e1" else 14),
            ends_at=_dt(20, 10 if key == "e1" else 15),
            title="R1",
            event_key=key,
            application_id=app,
        )
    only_a1 = await store.list_interviews(application_id="a1")
    assert [i["application_id"] for i in only_a1["interviews"]] == ["a1"]
    everything = await store.list_interviews()
    assert len(everything["interviews"]) == 2
