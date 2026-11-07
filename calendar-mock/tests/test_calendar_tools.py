"""Calendar tools: validation, forwarding, registration (store faked)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# All flat-layout suites share top-level names (config/server/tools/services);
# purge any other suite's bindings so this module resolves its own source.
for _mod in [m for m in list(sys.modules) if m.split(".", 1)[0] in {"config", "server", "tools", "services", "ui", "seed"}]:
    del sys.modules[_mod]

from datetime import datetime

import pytest
from mcp.server.mcpserver.exceptions import ToolError

import tools.calendar as calendar
from services.booking import BookingConflictError, BookingNotFoundError


class FakeBookingStore:
    def __init__(self) -> None:
        self.calls: list = []

    async def list_interviewers(self):
        self.calls.append(("interviewers",))
        return {"interviewers": [{"email": "asha@acme.tech", "name": "Asha"}]}

    async def get_availability(self, emails, start, end):
        self.calls.append(("availability", emails, start, end))
        return {"availability": {e: [] for e in emails}}

    async def book_interview(
        self, *, interviewer_email, starts_at, ends_at, title, event_key,
        application_id=None, job_id=None,
    ):
        self.calls.append(("book", interviewer_email, event_key))
        return {"id": 7, "interviewer_email": interviewer_email, "event_key": event_key}

    async def list_interviews(self, application_id=None, limit=50):
        self.calls.append(("interviews", application_id, limit))
        return {"interviews": []}

    async def update_interview(self, event_id, **kwargs):
        self.calls.append(("update", event_id, kwargs))
        return {"id": event_id, **kwargs}

    async def cancel_interview(self, event_id):
        self.calls.append(("cancel", event_id))
        return {"status": "cancelled", "interview": {"id": event_id}}

    async def find_slots(self, emails, start, end, duration_mins, limit=10):
        self.calls.append(("slots", emails, duration_mins, limit))
        return {"interviewers": emails, "slots": []}

    async def aclose(self) -> None:
        pass


@pytest.fixture
def fake_store(monkeypatch):
    store = FakeBookingStore()
    monkeypatch.setattr(calendar, "get_booking_store", lambda: store)
    return store


async def test_list_interviewers_passthrough(fake_store) -> None:
    result = await calendar.list_interviewers()
    assert result["interviewers"][0]["email"] == "asha@acme.tech"
    assert fake_store.calls == [("interviewers",)]


async def test_get_availability_forwards_datetimes(fake_store) -> None:
    await calendar.get_availability(
        ["asha@acme.tech"], "2026-11-20T00:00:00+00:00", "2026-11-21T00:00:00+00:00"
    )
    name, emails, start, end = fake_store.calls[0]
    assert name == "availability"
    assert emails == ["asha@acme.tech"]
    assert isinstance(start, datetime) and start.tzinfo is not None
    assert end > start


async def test_get_availability_validates(fake_store) -> None:
    good = {
        "interviewer_emails": ["asha@acme.tech"],
        "start": "2026-11-20T00:00:00+00:00",
        "end": "2026-11-21T00:00:00+00:00",
    }
    with pytest.raises(ToolError, match="non-empty"):
        await calendar.get_availability(**{**good, "interviewer_emails": []})
    with pytest.raises(ToolError, match="ISO"):
        await calendar.get_availability(**{**good, "start": "next Friday"})
    with pytest.raises(ToolError, match="timezone"):
        await calendar.get_availability(**{**good, "start": "2026-11-20T10:00:00"})
    with pytest.raises(ToolError, match="before end"):
        await calendar.get_availability(**{**good, "end": good["start"]})
    with pytest.raises(ToolError, match="31 days"):
        await calendar.get_availability(**{**good, "end": "2027-06-01T00:00:00+00:00"})
    assert fake_store.calls == []


async def test_book_interview_validates(fake_store) -> None:
    good = {
        "interviewer_email": "asha@acme.tech",
        "starts_at": "2026-11-20T10:00:00+00:00",
        "ends_at": "2026-11-20T11:00:00+00:00",
        "title": "R1 screen",
        "event_key": "evt-1",
    }
    with pytest.raises(ToolError, match="must not be blank"):
        await calendar.book_interview(**{**good, "title": "  "})
    with pytest.raises(ToolError, match="before end"):
        await calendar.book_interview(**{**good, "ends_at": good["starts_at"]})
    with pytest.raises(ToolError, match="timezone"):
        await calendar.book_interview(**{**good, "starts_at": "2026-11-20T10:00:00"})
    assert fake_store.calls == []


async def test_book_interview_forwards_and_returns(fake_store) -> None:
    result = await calendar.book_interview(
        interviewer_email="asha@acme.tech",
        starts_at="2026-11-20T10:00:00+00:00",
        ends_at="2026-11-20T11:00:00+00:00",
        title="R1 screen",
        event_key="evt-1",
        application_id="a1",
    )
    assert result["id"] == 7
    assert fake_store.calls == [("book", "asha@acme.tech", "evt-1")]


async def test_list_interviews_limit(fake_store) -> None:
    with pytest.raises(ToolError, match="limit"):
        await calendar.list_interviews(limit=0)
    await calendar.list_interviews(application_id="a1", limit=5)
    assert fake_store.calls == [("interviews", "a1", 5)]


async def test_store_errors_become_tool_errors(monkeypatch) -> None:
    class Failing(FakeBookingStore):
        async def book_interview(self, **kwargs):
            raise BookingConflictError("overlaps interview 3")

        async def get_availability(self, emails, start, end):
            raise BookingNotFoundError("unknown interviewer ghost@acme.tech")

    monkeypatch.setattr(calendar, "get_booking_store", lambda: Failing())
    with pytest.raises(ToolError, match="overlaps"):
        await calendar.book_interview(
            interviewer_email="asha@acme.tech",
            starts_at="2026-11-20T10:00:00+00:00",
            ends_at="2026-11-20T11:00:00+00:00",
            title="R1",
            event_key="e1",
        )
    with pytest.raises(ToolError, match="unknown interviewer"):
        await calendar.get_availability(
            ["ghost@acme.tech"], "2026-11-20T00:00:00+00:00", "2026-11-21T00:00:00+00:00"
        )


async def test_update_interview_validates(fake_store) -> None:
    with pytest.raises(ToolError, match="event_id"):
        await calendar.update_interview(0, title="x")
    with pytest.raises(ToolError, match="at least one"):
        await calendar.update_interview(7)
    with pytest.raises(ToolError, match="timezone"):
        await calendar.update_interview(7, starts_at="2026-11-20T10:00:00")
    with pytest.raises(ToolError, match="before end"):
        await calendar.update_interview(
            7, starts_at="2026-11-20T11:00:00+00:00", ends_at="2026-11-20T10:00:00+00:00"
        )
    assert fake_store.calls == []


async def test_update_interview_forwards(fake_store) -> None:
    result = await calendar.update_interview(
        7, starts_at="2026-11-21T14:00:00+00:00", ends_at="2026-11-21T15:00:00+00:00"
    )
    assert result["id"] == 7
    name, event_id, kwargs = fake_store.calls[0]
    assert (name, event_id) == ("update", 7)
    assert isinstance(kwargs["starts_at"], datetime)


async def test_cancel_interview(fake_store) -> None:
    with pytest.raises(ToolError, match="event_id"):
        await calendar.cancel_interview(-1)
    result = await calendar.cancel_interview(7)
    assert result["status"] == "cancelled"
    assert fake_store.calls == [("cancel", 7)]


async def test_find_common_slots_validates(fake_store) -> None:
    good = {
        "interviewer_emails": ["asha@acme.tech"],
        "start": "2026-11-20T00:00:00+00:00",
        "end": "2026-11-21T00:00:00+00:00",
        "duration_mins": 60,
    }
    with pytest.raises(ToolError, match="duration"):
        await calendar.find_common_slots(**{**good, "duration_mins": 5})
    with pytest.raises(ToolError, match="duration"):
        await calendar.find_common_slots(**{**good, "duration_mins": 999})
    with pytest.raises(ToolError, match="limit"):
        await calendar.find_common_slots(**{**good, "limit": 0})
    with pytest.raises(ToolError, match="non-empty"):
        await calendar.find_common_slots(**{**good, "interviewer_emails": []})
    await calendar.find_common_slots(**good)
    assert fake_store.calls == [(("slots", ["asha@acme.tech"], 60, 10))]


def test_register_all_exposes_seven_tools() -> None:
    class Stub:
        def __init__(self) -> None:
            self.registered: list = []

        def tool(self, name, description):
            def deco(fn):
                self.registered.append((name, description))
                return fn

            return deco

    stub = Stub()
    calendar.register_tools(stub)
    assert [name for name, _ in stub.registered] == [
        "list_interviewers",
        "get_availability",
        "book_interview",
        "list_interviews",
        "update_interview",
        "cancel_interview",
        "find_common_slots",
    ]
    assert all(description for _, description in stub.registered)
