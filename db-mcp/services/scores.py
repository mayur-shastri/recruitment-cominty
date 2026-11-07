"""Postgres-backed score/criteria store.

Tools open one store per tool call and close it — stateless by
construction (no shared engines), mirroring the Harly client's shape.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from config import get_db_mcp_settings
from recruitment_db.models import (
    ApplicationResume,
    ApplicationScore,
    JobInterviewConfig,
    ScoringCriteria,
)
from recruitment_db.urls import to_async_database_url


class ScoresError(Exception):
    """Store failure with user-safe details (never includes credentials or SQL internals)."""


class ScoresNotFoundError(ScoresError):
    """Requested criteria or score row does not exist."""


def _is_postgres(url: str) -> bool:
    return url.split(":", 1)[0] in {"postgres", "postgresql", "postgresql+asyncpg"}


class ScoresStore:
    """Score/criteria reads and writes over one short-lived engine."""

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

    async def get_criteria(self, job_id: str) -> dict[str, Any]:
        try:
            async with self._sessions() as session:
                row = (
                    await session.execute(
                        select(ScoringCriteria).where(
                            ScoringCriteria.job_id == job_id, ScoringCriteria.active.is_(True)
                        )
                    )
                ).scalar_one_or_none()
        except SQLAlchemyError as exc:
            raise ScoresError("score store request failed") from exc
        if row is None:
            raise ScoresNotFoundError(f"no active scoring criteria for job {job_id!r}")
        return {"job_id": row.job_id, "version": row.version, "criteria": row.criteria}

    async def save_criteria(
        self, *, job_id: str, criteria: list, created_by: str | None = None
    ) -> dict[str, Any]:
        """Save a new active rubric version for a job; deactivates the old one."""
        try:
            async with self._sessions() as session:
                current_max = (
                    await session.execute(
                        select(func.max(ScoringCriteria.version)).where(
                            ScoringCriteria.job_id == job_id
                        )
                    )
                ).scalar_one_or_none()
                await session.execute(
                    update(ScoringCriteria)
                    .where(
                        ScoringCriteria.job_id == job_id,
                        ScoringCriteria.active.is_(True),
                    )
                    .values(active=False)
                )
                row = ScoringCriteria(
                    job_id=job_id,
                    version=(current_max or 0) + 1,
                    criteria=criteria,
                    active=True,
                    created_by=created_by,
                )
                session.add(row)
                await session.commit()
                return {"job_id": row.job_id, "version": row.version, "criteria": row.criteria}
        except SQLAlchemyError as exc:
            raise ScoresError("score store request failed") from exc

    async def save_score(
        self,
        *,
        application_id: str,
        job_id: str,
        candidate_id: str,
        total_score: float,
        breakdown: list,
        criteria_version: int,
        rationale: str | None = None,
    ) -> dict[str, Any]:
        try:
            async with self._sessions() as session:
                row = await session.get(ApplicationScore, application_id)
                if row is None:
                    row = ApplicationScore(
                        application_id=application_id,
                        job_id=job_id,
                        candidate_id=candidate_id,
                        total_score=total_score,
                        breakdown=breakdown,
                        criteria_version=criteria_version,
                        rationale=rationale,
                    )
                    session.add(row)
                else:
                    row.job_id = job_id
                    row.candidate_id = candidate_id
                    row.total_score = total_score
                    row.breakdown = breakdown
                    row.criteria_version = criteria_version
                    row.rationale = rationale
                await session.commit()
                return self._shape(row)
        except SQLAlchemyError as exc:
            raise ScoresError("score store request failed") from exc

    async def get_score(self, application_id: str) -> dict[str, Any]:
        try:
            async with self._sessions() as session:
                row = await session.get(ApplicationScore, application_id)
                if row is None:
                    raise ScoresNotFoundError(f"no saved score for application {application_id!r}")
                return self._shape(row)
        except ScoresNotFoundError:
            raise
        except SQLAlchemyError as exc:
            raise ScoresError("score store request failed") from exc

    async def list_top(self, job_id: str, limit: int) -> dict[str, Any]:
        try:
            async with self._sessions() as session:
                rows = (
                    await session.execute(
                        select(ApplicationScore)
                        .where(ApplicationScore.job_id == job_id)
                        .order_by(ApplicationScore.total_score.desc())
                        .limit(limit)
                    )
                ).scalars()
                scores = [self._shape(row) for row in rows]
                app_ids = [s["application_id"] for s in scores]
                resume_urls: dict[str, str] = {}
                if app_ids:
                    resume_rows = (
                        await session.execute(
                            select(
                                ApplicationResume.application_id,
                                ApplicationResume.resume_url,
                            ).where(ApplicationResume.application_id.in_(app_ids))
                        )
                    ).all()
                    resume_urls = {app_id: url for app_id, url in resume_rows}
                for entry in scores:
                    entry["resume_url"] = resume_urls.get(entry["application_id"])
                return {"job_id": job_id, "scores": scores}
        except SQLAlchemyError as exc:
            raise ScoresError("score store request failed") from exc

    async def save_interview_config(
        self, *, job_id: str, rounds: list, updated_by: str | None = None
    ) -> dict[str, Any]:
        """Save a job's interview plan, overwriting any previous plan."""
        try:
            async with self._sessions() as session:
                row = await session.get(JobInterviewConfig, job_id)
                if row is None:
                    row = JobInterviewConfig(job_id=job_id, rounds=rounds, updated_by=updated_by)
                    session.add(row)
                else:
                    row.rounds = rounds
                    row.updated_by = updated_by
                await session.commit()
                return {"job_id": row.job_id, "rounds": row.rounds}
        except SQLAlchemyError as exc:
            raise ScoresError("score store request failed") from exc

    async def get_interview_config(self, job_id: str) -> dict[str, Any]:
        try:
            async with self._sessions() as session:
                row = await session.get(JobInterviewConfig, job_id)
                if row is None:
                    raise ScoresNotFoundError(f"no interview plan for job {job_id!r}")
                return {"job_id": row.job_id, "rounds": row.rounds}
        except ScoresNotFoundError:
            raise
        except SQLAlchemyError as exc:
            raise ScoresError("score store request failed") from exc

    async def get_resume(self, application_id: str) -> dict[str, Any]:
        try:
            async with self._sessions() as session:
                row = await session.get(ApplicationResume, application_id)
                if row is None:
                    raise ScoresNotFoundError(f"no resume URL for application {application_id!r}")
                return {
                    "application_id": row.application_id,
                    "resume_url": row.resume_url,
                    "file_name": row.file_name,
                    "file_size": row.file_size,
                }
        except ScoresNotFoundError:
            raise
        except SQLAlchemyError as exc:
            raise ScoresError("score store request failed") from exc

    @staticmethod
    def _shape(row: ApplicationScore) -> dict[str, Any]:
        return {
            "application_id": row.application_id,
            "job_id": row.job_id,
            "candidate_id": row.candidate_id,
            "total_score": row.total_score,
            "breakdown": row.breakdown,
            "criteria_version": row.criteria_version,
            "rationale": row.rationale,
        }


def get_scores_store() -> ScoresStore:
    """Build a store from settings. Tools call this per invocation (stateless)."""
    settings = get_db_mcp_settings()
    if not settings.database_url:
        raise ScoresError("DATABASE_URL is not configured")
    url = settings.database_url
    if _is_postgres(url):
        # .env carries a libpq-style URL; the async engine needs the
        # asyncpg driver or SQLAlchemy reaches for psycopg (not installed).
        url = to_async_database_url(url)
    return ScoresStore(database_url=url)
