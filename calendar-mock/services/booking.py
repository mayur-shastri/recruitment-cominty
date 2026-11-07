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
                    return self._shape(winner)
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
    async def _reject_overlap(session, *, interviewer_email: str, starts_at, ends_at) -> None:
        clash = (
            await session.execute(
                select(CalendarEvent)
                .where(
                    CalendarEvent.interviewer_email == interviewer_email,
                    CalendarEvent.starts_at < ends_at,
                    CalendarEvent.ends_at > starts_at,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
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
