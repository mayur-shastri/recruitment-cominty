"""Calendar tools for the Scheduler Agent (single consumer, no profiles).

The scheduler is headless (triggered, no Hiring Manager to quote), so
booking needs no confirmation — same rationale as the assessment writes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

from services.booking import BookingError, get_booking_store

MAX_RANGE_DAYS = 31


def _require_non_blank(value: str | None, field: str) -> None:
    if value is not None and not value.strip():
        raise ToolError(f"{field} must not be blank.")


def _require_aware(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ToolError(f"{field} must be an ISO datetime, got {value!r}.") from None
    if parsed.tzinfo is None:
        raise ToolError(f"{field} must include a timezone offset (e.g. +00:00), got {value!r}.")
    return parsed


async def list_interviewers() -> dict[str, Any]:
    """List the mock interviewer accounts (see tool description)."""
    store = get_booking_store()
    try:
        return await store.list_interviewers()
    except BookingError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await store.aclose()


async def get_availability(
    interviewer_emails: list, start: str, end: str
) -> dict[str, Any]:
    """Read busy blocks for interviewers over a date range (see tool description)."""
    if not isinstance(interviewer_emails, list) or not interviewer_emails:
        raise ToolError("interviewer_emails must be a non-empty list.")
    starts_at = _require_aware(start, "start")
    ends_at = _require_aware(end, "end")
    if not starts_at < ends_at:
        raise ToolError(f"start must be before end, got {start!r}..{end!r}.")
    if (ends_at - starts_at).days > MAX_RANGE_DAYS:
        raise ToolError(f"range must not exceed {MAX_RANGE_DAYS} days.")
    store = get_booking_store()
    try:
        return await store.get_availability(interviewer_emails, starts_at, ends_at)
    except BookingError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await store.aclose()


async def book_interview(
    interviewer_email: str,
    starts_at: str,
    ends_at: str,
    title: str,
    event_key: str,
    application_id: str | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    """Book an interview on an interviewer's calendar (see tool description)."""
    _require_non_blank(interviewer_email, "interviewer_email")
    _require_non_blank(title, "title")
    _require_non_blank(event_key, "event_key")
    _require_non_blank(application_id, "application_id")
    _require_non_blank(job_id, "job_id")
    start = _require_aware(starts_at, "starts_at")
    end = _require_aware(ends_at, "ends_at")
    if not start < end:
        raise ToolError(f"starts_at must be before end, got {starts_at!r}..{ends_at!r}.")
    store = get_booking_store()
    try:
        return await store.book_interview(
            interviewer_email=interviewer_email,
            starts_at=start,
            ends_at=end,
            title=title,
            event_key=event_key,
            application_id=application_id,
            job_id=job_id,
        )
    except BookingError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await store.aclose()


async def list_interviews(
    application_id: str | None = None, limit: int = 50
) -> dict[str, Any]:
    """List booked interviews, optionally for one application (see tool description)."""
    _require_non_blank(application_id, "application_id")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ToolError(f"limit must be 1-100, got {limit!r}")
    store = get_booking_store()
    try:
        return await store.list_interviews(application_id=application_id, limit=limit)
    except BookingError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await store.aclose()


def _require_event_id(event_id: Any) -> None:
    if isinstance(event_id, bool) or not isinstance(event_id, int) or event_id < 1:
        raise ToolError(f"event_id must be a positive integer, got {event_id!r}")


async def update_interview(
    event_id: int,
    starts_at: str | None = None,
    ends_at: str | None = None,
    interviewer_email: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """Reschedule or retitle a booked interview (see tool description)."""
    _require_event_id(event_id)
    if starts_at is None and ends_at is None and interviewer_email is None and title is None:
        raise ToolError("update_interview needs at least one of starts_at, ends_at, interviewer_email, title.")
    _require_non_blank(interviewer_email, "interviewer_email")
    _require_non_blank(title, "title")
    start = _require_aware(starts_at, "starts_at") if starts_at is not None else None
    end = _require_aware(ends_at, "ends_at") if ends_at is not None else None
    if start is not None and end is not None and not start < end:
        raise ToolError(f"starts_at must be before end, got {starts_at!r}..{ends_at!r}.")
    store = get_booking_store()
    try:
        return await store.update_interview(
            event_id,
            starts_at=start,
            ends_at=end,
            interviewer_email=interviewer_email,
            title=title,
        )
    except BookingError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await store.aclose()


async def cancel_interview(event_id: int) -> dict[str, Any]:
    """Cancel a booked interview, freeing its slot (see tool description)."""
    _require_event_id(event_id)
    store = get_booking_store()
    try:
        return await store.cancel_interview(event_id)
    except BookingError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await store.aclose()


async def find_common_slots(
    interviewer_emails: list,
    start: str,
    end: str,
    duration_mins: int = 60,
    limit: int = 10,
) -> dict[str, Any]:
    """Find shared free windows across interviewers (see tool description)."""
    if not isinstance(interviewer_emails, list) or not interviewer_emails:
        raise ToolError("interviewer_emails must be a non-empty list.")
    starts_at = _require_aware(start, "start")
    ends_at = _require_aware(end, "end")
    if not starts_at < ends_at:
        raise ToolError(f"start must be before end, got {start!r}..{end!r}.")
    if (ends_at - starts_at).days > MAX_RANGE_DAYS:
        raise ToolError(f"range must not exceed {MAX_RANGE_DAYS} days.")
    if isinstance(duration_mins, bool) or not isinstance(duration_mins, int) or not 15 <= duration_mins <= 480:
        raise ToolError(f"duration_mins must be 15-480, got {duration_mins!r}")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
        raise ToolError(f"limit must be 1-20, got {limit!r}")
    store = get_booking_store()
    try:
        return await store.find_slots(interviewer_emails, starts_at, ends_at, duration_mins, limit)
    except BookingError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await store.aclose()


def register_tools(mcp: Any) -> None:
    """Register every calendar tool (single consumer: the scheduler agent)."""
    specs = [
        (
            "list_interviewers",
            "List the mock interviewer accounts ({email, name}). Match "
            "interview-plan pool emails against this list before booking.",
            list_interviewers,
        ),
        (
            "get_availability",
            "Read what's already on interviewers' calendars over a range. "
            "Takes interviewer_emails (non-empty list), start/end ISO "
            "datetimes with timezone offsets, range at most 31 days. "
            "Returns each interviewer's busy blocks and interviews ordered "
            "by start. Book only in the gaps.",
            get_availability,
        ),
        (
            "book_interview",
            "Book an interview on one interviewer's calendar. Required: "
            "interviewer_email, starts_at/ends_at (ISO with timezone "
            "offsets, inside a free gap from get_availability), title, "
            "event_key (the trigger event ID — replaying a key returns the "
            "original booking instead of double-booking). Optional: "
            "application_id, job_id. Overlapping bookings fail loudly — "
            "pick another slot instead.",
            book_interview,
        ),
        (
            "list_interviews",
            "List booked interviews ordered by start (limit 1-100, default "
            "50), optionally filtered to one application_id. Call this "
            "before acting on a trigger: when an interview already covers "
            "the stage, do nothing (triggers are at-least-once).",
            list_interviews,
        ),
        (
            "update_interview",
            "Reschedule or retitle a booked interview by its event id "
            "(from list_interviews). Partial: pass any of starts_at/ends_at "
            "(ISO with timezone offsets), interviewer_email, title — at "
            "least one is required. Overlaps fail loudly; the booking keeps "
            "its event key, so replays stay safe.",
            update_interview,
        ),
        (
            "cancel_interview",
            "Cancel a booked interview by its event id, freeing the slot. "
            "Use when a round is dropped or a booking must move further "
            "than an update allows (then book fresh).",
            cancel_interview,
        ),
        (
            "find_common_slots",
            "Find shared free windows across interviewers instead of "
            "eyeballing busy lists. Takes interviewer_emails, start/end ISO "
            "datetimes with offsets (range at most 31 days), duration_mins "
            "15-480 (default 60), limit 1-20 (default 10). Returns windows "
            "free for everyone, ordered by start — book inside one with "
            "book_interview.",
            find_common_slots,
        ),
    ]
    for name, description, fn in specs:
        mcp.tool(name=name, description=description)(fn)
