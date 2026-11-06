"""Shared tables: employees (HM allowlist), conversation threads, Slack dedupe."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from recruitment_db.database import Base

# JSONB on Postgres, plain JSON on SQLite (tests). Docs are always replaced
# whole, never mutated in place, so no MutableDict tracking is needed.
JSON_DOC = JSON().with_variant(JSONB(), "postgresql")


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slack_user_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    grade: Mapped[int] = mapped_column(Integer, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ConversationThread(Base):
    __tablename__ = "conversation_threads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slack_user_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    cominty_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    cominty_thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SlackEvent(Base):
    __tablename__ = "slack_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ScoringCriteria(Base):
    """Versioned per-job scoring rubrics. One version is active per job."""

    __tablename__ = "scoring_criteria"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    criteria: Mapped[list] = mapped_column(JSON_DOC, nullable=False)
    active: Mapped[bool] = mapped_column(nullable=False, server_default="true")
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (UniqueConstraint("job_id", "version"),)


class ApplicationScore(Base):
    """Absolute assessment scores, one row per Harly application (re-scores overwrite)."""

    __tablename__ = "application_scores"

    application_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    candidate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    total_score: Mapped[float] = mapped_column(Float, nullable=False)
    breakdown: Mapped[list] = mapped_column(JSON_DOC, nullable=False)
    criteria_version: Mapped[int] = mapped_column(Integer, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class JobInterviewConfig(Base):
    """Per-job interview readiness: rounds with date windows and interviewer pools."""

    __tablename__ = "job_interview_config"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    rounds: Mapped[list] = mapped_column(JSON_DOC, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
