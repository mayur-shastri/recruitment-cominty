"""Postgres-backed interviewer calendar store.

Tools open one store per tool call and close it — stateless by
construction (no shared engines), mirroring the scores store's shape.
"""

from __future__ import annotations

import hmac
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from config import get_calendar_settings
from recruitment_db.models import CalendarEvent, Interviewer
from recruitment_db.urls import to_async_database_url


class BookingError(Exception):
    """Store failure with user-safe details (never includes credentials or SQL internals)."""


class BookingNotFoundError(BookingError):
    """Unknown interviewer email."""


class BookingConflictError(BookingError):
    """New event overlaps an existing one for the same interviewer."""


def _is_postgres(url: str) -> bool:
    return url.split(":", 1)[0] in {"postgres", "postgresql", "postgresql+asyncpg"}


def _iso(dt: datetime) -> str:
    # SQLite drops tzinfo on read; every writer stores UTC-aware values.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


class BookingStore:
    """Calendar reads and writes over one short-lived engine."""

    def __init__(self, database_url: str) -> None:
        connect_args: dict[str, Any] = {}
        if _is_postgres(database_url):
            # Supabase pooler is pgbouncer (transaction mode): server-side prepared
            # statements don't survive across checkouts, so disable the cache.
            # (SQLite test URLs skip this: the option is asyncpg-only.)
            connect_args = {"statement_cache_size": 0}
        self._engine: AsyncEngine = create_async_engine(
            database_url, poolclass=NullPool, pool_pre_ping=True, connect_args=connect_args
        )
        self._sessions = async_sessionmaker(self._engine, expire_on_commit=False)

    def _session(self):
        """Raw session factory. Tests use it to seed; tools use the methods below."""
        return self._sessions()

    async def aclose(self) -> None:
        await self._engine.dispose()

    async def list_interviewers(self) -> dict[str, Any]:
        try:
            async with self._sessions() as session:
                rows = (await session.execute(select(Interviewer).order_by(Interviewer.email))).scalars()
                return {"interviewers": [{"email": r.email, "name": r.name} for r in rows]}
        except SQLAlchemyError as exc:
            raise BookingError("calendar store request failed") from exc

    async def verify_interviewer(self, email: str, password: str) -> dict[str, Any]:
        """Direct password check for demo login (same error either way)."""
        try:
            async with self._sessions() as session:
                row = await session.get(Interviewer, email)
                if row is None or not hmac.compare_digest(row.password, password):
                    raise BookingNotFoundError("invalid email or password")
                return {"email": row.email, "name": row.name}
        except BookingNotFoundError:
            raise
        except SQLAlchemyError as exc:
            raise BookingError("calendar store request failed") from exc

    async def get_availability(
        self, emails: list[str], start: datetime, end: datetime
    ) -> dict[str, Any]:
        try:
            async with self._sessions() as session:
                known = {
                    r.email
                    for r in (await session.execute(select(Interviewer))).scalars()
                }
                unknown = [e for e in emails if e not in known]
                if unknown:
                    raise BookingNotFoundError(f"unknown interviewer {unknown[0]!r}")
                rows = (
                    await session.execute(
                        select(CalendarEvent)
                        .where(
                            CalendarEvent.interviewer_email.in_(emails),
                            CalendarEvent.starts_at < end,
                            CalendarEvent.ends_at > start,
                        )
                        .order_by(CalendarEvent.starts_at)
                    )
                ).scalars()
                by_email: dict[str, list] = {e: [] for e in emails}
                for row in rows:
                    by_email[row.interviewer_email].append(self._shape(row))
                return {"availability": by_email}
        except BookingNotFoundError:
            raise
        except SQLAlchemyError as exc:
            raise BookingError("calendar store request failed") from exc

    async def book_interview(
        self,
        *,
        interviewer_email: str,
        starts_at: datetime,
        ends_at: datetime,
        title: str,
        event_key: str,
        application_id: str | None = None,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        """Book an interview; replaying an event_key returns the original row."""
        try:
            async with self._sessions() as session:
                if await session.get(Interviewer, interviewer_email) is None:
                    raise BookingNotFoundError(f"unknown interviewer {interviewer_email!r}")
                replay = await self._replay(session, event_key)
                if replay is not None:
                    self._verify_replay(
                        replay,
                        application_id=application_id,
                        interviewer_email=interviewer_email,
                        starts_at=starts_at,
                        ends_at=ends_at,
                    )
                    return replay
                await self._reject_overlap(
                    session, interviewer_email=interviewer_email, starts_at=starts_at, ends_at=ends_at
                )
                row = CalendarEvent(
                    interviewer_email=interviewer_email,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    kind="interview",
                    title=title,
                    application_id=application_id,
                    job_id=job_id,
                    event_key=event_key,
                )
                session.add(row)
                try:
                    await session.commit()
                except IntegrityError:
                    # Lost a replay race: the winner holds our key; return it.
                    await session.rollback()
                    winner = (
                        await session.execute(
                            select(CalendarEvent).where(CalendarEvent.event_key == event_key)
                        )
                    ).scalar_one_or_none()
                    if winner is None:
                        raise BookingError("calendar store request failed")
                    shaped = self._shape(winner)
                    self._verify_replay(
                        shaped,
                        application_id=application_id,
                        interviewer_email=interviewer_email,
                        starts_at=starts_at,
                        ends_at=ends_at,
                    )
                    return shaped
                return self._shape(row)
        except (BookingNotFoundError, BookingConflictError):
            raise
        except SQLAlchemyError as exc:
            raise BookingError("calendar store request failed") from exc

    async def add_busy_block(
        self,
        *,
        interviewer_email: str,
        starts_at: datetime,
        ends_at: datetime,
        title: str,
        event_key: str | None = None,
    ) -> dict[str, Any]:
        """Add a personal busy block (same overlap rule; keyed replays return the row)."""
        try:
            async with self._sessions() as session:
                if await session.get(Interviewer, interviewer_email) is None:
                    raise BookingNotFoundError(f"unknown interviewer {interviewer_email!r}")
                if event_key is not None:
                    replay = await self._replay(session, event_key)
                    if replay is not None:
                        return replay
                await self._reject_overlap(
                    session, interviewer_email=interviewer_email, starts_at=starts_at, ends_at=ends_at
                )
                row = CalendarEvent(
                    interviewer_email=interviewer_email,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    kind="busy",
                    title=title,
                    event_key=event_key,
                )
                session.add(row)
                await session.commit()
                return self._shape(row)
        except (BookingNotFoundError, BookingConflictError):
            raise
        except SQLAlchemyError as exc:
            raise BookingError("calendar store request failed") from exc

    async def update_interview(
        self,
        event_id: int,
        *,
        starts_at: datetime | None = None,
        ends_at: datetime | None = None,
        interviewer_email: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        """Reschedule/retitle a booked interview (partial update)."""
        try:
            async with self._sessions() as session:
                row = await session.get(CalendarEvent, event_id)
                if row is None or row.kind != "interview":
                    if row is None:
                        raise BookingNotFoundError(f"no interview {event_id}")
                    raise BookingError(f"event {event_id} is not an interview")
                email = interviewer_email or row.interviewer_email
                if interviewer_email is not None and await session.get(Interviewer, email) is None:
                    raise BookingNotFoundError(f"unknown interviewer {email!r}")
                new_start = starts_at or row.starts_at
                new_end = ends_at or row.ends_at
                if not new_start < new_end:
                    raise BookingError("starts_at must be before end.")
                await self._reject_overlap(
                    session,
                    interviewer_email=email,
                    starts_at=new_start,
                    ends_at=new_end,
                    exclude_id=event_id,
                )
                row.interviewer_email = email
                row.starts_at = new_start
                row.ends_at = new_end
                if title is not None:
                    row.title = title
                await session.commit()
                return self._shape(row)
        except BookingError:
            raise  # noqa: TRY203 (re-raised user-safe as-is, incl. subclasses)
        except SQLAlchemyError as exc:
            raise BookingError("calendar store request failed") from exc

    async def cancel_interview(self, event_id: int) -> dict[str, Any]:
        """Delete a booked interview, freeing its slot."""
        try:
            async with self._sessions() as session:
                row = await session.get(CalendarEvent, event_id)
                if row is None or row.kind != "interview":
                    if row is None:
                        raise BookingNotFoundError(f"no interview {event_id}")
                    raise BookingError(f"event {event_id} is not an interview")
                shaped = self._shape(row)
                await session.delete(row)
                await session.commit()
                return {"status": "cancelled", "interview": shaped}
        except BookingError:
            raise
        except SQLAlchemyError as exc:
            raise BookingError("calendar store request failed") from exc

    async def find_slots(
        self, emails: list[str], start: datetime, end: datetime, duration_mins: int, limit: int = 10
    ) -> dict[str, Any]:
        """Common free windows across interviewers fitting duration_mins."""
        try:
            async with self._sessions() as session:
                known = {r.email for r in (await session.execute(select(Interviewer))).scalars()}
                unknown = [e for e in emails if e not in known]
                if unknown:
                    raise BookingNotFoundError(f"unknown interviewer {unknown[0]!r}")
                rows = (
                    await session.execute(
                        select(CalendarEvent.starts_at, CalendarEvent.ends_at)
                        .where(
                            CalendarEvent.interviewer_email.in_(emails),
                            CalendarEvent.starts_at < end,
                            CalendarEvent.ends_at > start,
                        )
                        .order_by(CalendarEvent.starts_at)
                    )
                ).all()
        except BookingNotFoundError:
            raise
        except SQLAlchemyError as exc:
            raise BookingError("calendar store request failed") from exc
        busy: list[tuple[datetime, datetime]] = []
        for raw_start, raw_end in rows:
            s = raw_start if raw_start.tzinfo else raw_start.replace(tzinfo=timezone.utc)
            e = raw_end if raw_end.tzinfo else raw_end.replace(tzinfo=timezone.utc)
            s, e = max(s, start), min(e, end)
            if s < e and (not busy or s > busy[-1][1]):
                busy.append((s, e))
            elif s < e:
                busy[-1] = (busy[-1][0], max(busy[-1][1], e))
        slots: list[dict[str, str]] = []
        cursor = start
        for s, e in busy:
            if (s - cursor).total_seconds() >= duration_mins * 60:
                slots.append({"starts_at": _iso(cursor), "ends_at": _iso(s)})
            cursor = max(cursor, e)
        if (end - cursor).total_seconds() >= duration_mins * 60:
            slots.append({"starts_at": _iso(cursor), "ends_at": _iso(end)})
        return {"interviewers": emails, "slots": slots[:limit]}

    async def list_interviews(
        self, application_id: str | None = None, limit: int = 50
    ) -> dict[str, Any]:
        try:
            async with self._sessions() as session:
                query = (
                    select(CalendarEvent)
                    .where(CalendarEvent.kind == "interview")
                    .order_by(CalendarEvent.starts_at)
                    .limit(limit)
                )
                if application_id is not None:
                    query = query.where(CalendarEvent.application_id == application_id)
                rows = (await session.execute(query)).scalars()
                return {"interviews": [self._shape(row) for row in rows]}
        except SQLAlchemyError as exc:
            raise BookingError("calendar store request failed") from exc

    @staticmethod
    async def _replay(session, event_key: str) -> dict[str, Any] | None:
        row = (
            await session.execute(select(CalendarEvent).where(CalendarEvent.event_key == event_key))
        ).scalar_one_or_none()
        return BookingStore._shape(row) if row is not None else None

    @staticmethod
    def _verify_replay(
        replay: dict[str, Any],
        *,
        application_id: str | None,
        interviewer_email: str,
        starts_at,
        ends_at,
    ) -> None:
        """Reject a replayed row that isn't the requested booking (key collision)."""
        if (
            replay["application_id"] == application_id
            and replay["interviewer_email"] == interviewer_email
            and replay["starts_at"] == _iso(starts_at)
            and replay["ends_at"] == _iso(ends_at)
        ):
            return
        raise BookingError(
            f"event key {replay['event_key']!r} is already used by a different booking "
            f"(application {replay['application_id']}, {replay['interviewer_email']} "
            f"@ {replay['starts_at']}); book with a fresh event key instead of reusing it"
        )

    @staticmethod
    async def _reject_overlap(
        session, *, interviewer_email: str, starts_at, ends_at, exclude_id: int | None = None
    ) -> None:
        query = select(CalendarEvent).where(
            CalendarEvent.interviewer_email == interviewer_email,
            CalendarEvent.starts_at < ends_at,
            CalendarEvent.ends_at > starts_at,
        )
        if exclude_id is not None:
            query = query.where(CalendarEvent.id != exclude_id)
        clash = (await session.execute(query.limit(1))).scalar_one_or_none()
        if clash is not None:
            raise BookingConflictError(
                f"overlaps {_iso(clash.starts_at)}-{_iso(clash.ends_at)} "
                f"({clash.kind}: {clash.title or 'untitled'})"
            )

    @staticmethod
    def _shape(row: CalendarEvent) -> dict[str, Any]:
        return {
            "id": row.id,
            "interviewer_email": row.interviewer_email,
            "starts_at": _iso(row.starts_at),
            "ends_at": _iso(row.ends_at),
            "kind": row.kind,
            "title": row.title,
            "application_id": row.application_id,
            "job_id": row.job_id,
            "event_key": row.event_key,
        }


def get_booking_store() -> BookingStore:
    """Build a store from settings. Tools call this per invocation (stateless)."""
    settings = get_calendar_settings()
    if not settings.database_url:
        raise BookingError("DATABASE_URL is not configured")
    url = settings.database_url
    if _is_postgres(url):
        # .env carries a libpq-style URL; the async engine needs the
        # asyncpg driver or SQLAlchemy reaches for psycopg (not installed).
        url = to_async_database_url(url)
    return BookingStore(database_url=url)
