"""Calendar UI routes: mock login plus a tiny JSON API for the week view.

Mock auth is a plain `cal_user` cookie naming the interviewer — explicitly
no security pretense; this service exists for scheduling demos.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Cookie, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

from services.booking import (
    BookingConflictError,
    BookingError,
    BookingNotFoundError,
    BookingStore,
    get_booking_store,
)

router = APIRouter()
_INDEX = Path(__file__).resolve().parent / "static" / "index.html"


class _BadInput(ValueError):
    """Bad query/body field; the route turns this into a 400."""


def _aware(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise _BadInput(f"{field} must be an ISO datetime, got {value!r}.") from None
    if parsed.tzinfo is None:
        raise _BadInput(f"{field} must include a timezone offset (e.g. +00:00).")
    return parsed


def _bad(message: str) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": message})


def _failed(exc: BookingError) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@asynccontextmanager
async def _store():
    """One store per request, always closed (construction errors propagate)."""
    store: BookingStore = get_booking_store()
    try:
        yield store
    finally:
        await store.aclose()


@router.get("/", response_class=HTMLResponse)
async def index() -> str:
    return _INDEX.read_text()


@router.get("/api/interviewers")
async def api_interviewers() -> Any:
    try:
        async with _store() as store:
            return await store.list_interviewers()
    except BookingError as exc:
        return _failed(exc)


@router.post("/api/login")
async def api_login(request: Request, response: Response) -> Any:
    body = await request.json()
    email = (body.get("email") or "").strip()
    if not email:
        return _bad("email must not be blank.")
    try:
        async with _store() as store:
            found = [i for i in (await store.list_interviewers())["interviewers"] if i["email"] == email]
    except BookingError as exc:
        return _failed(exc)
    if not found:
        return JSONResponse(status_code=404, content={"detail": f"unknown interviewer {email!r}"})
    response.set_cookie("cal_user", email, httponly=True, samesite="lax")
    return found[0]


@router.get("/api/me")
async def api_me(cal_user: str | None = Cookie(default=None)) -> Any:
    if not cal_user:
        return JSONResponse(status_code=401, content={"detail": "not logged in"})
    try:
        async with _store() as store:
            found = [i for i in (await store.list_interviewers())["interviewers"] if i["email"] == cal_user]
    except BookingError as exc:
        return _failed(exc)
    if not found:
        return JSONResponse(status_code=401, content={"detail": "not logged in"})
    return found[0]


@router.get("/api/availability")
async def api_availability(
    interviewer_email: str, start: str, end: str
) -> Any:
    try:
        starts_at = _aware(start, "start")
        ends_at = _aware(end, "end")
    except _BadInput as exc:
        return _bad(str(exc))
    if not starts_at < ends_at:
        return _bad("start must be before end.")
    try:
        async with _store() as store:
            result = await store.get_availability([interviewer_email], starts_at, ends_at)
    except BookingNotFoundError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})
    except BookingError as exc:
        return _failed(exc)
    return {"events": result["availability"][interviewer_email]}


@router.post("/api/busy")
async def api_busy(request: Request, cal_user: str | None = Cookie(default=None)) -> Any:
    if not cal_user:
        return JSONResponse(status_code=401, content={"detail": "not logged in"})
    body = await request.json()
    title = (body.get("title") or "").strip()
    if not title:
        return _bad("title must not be blank.")
    try:
        starts_at = _aware(str(body.get("starts_at")), "starts_at")
        ends_at = _aware(str(body.get("ends_at")), "ends_at")
    except _BadInput as exc:
        return _bad(str(exc))
    if not starts_at < ends_at:
        return _bad("starts_at must be before ends_at.")
    try:
        async with _store() as store:
            return await store.add_busy_block(
                interviewer_email=cal_user, starts_at=starts_at, ends_at=ends_at, title=title
            )
    except BookingNotFoundError as exc:
        return JSONResponse(status_code=401, content={"detail": str(exc)})
    except BookingConflictError as exc:
        return JSONResponse(status_code=409, content={"detail": str(exc)})
    except BookingError as exc:
        return _failed(exc)
