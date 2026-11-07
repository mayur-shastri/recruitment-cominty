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


class HarlyEvent(Base):
    """Harly webhook dedupe: one row per delivery event ID (at-least-once)."""

    __tablename__ = "harly_events"

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ApplicationResume(Base):
    """Resolved public resume URL per application (S3 join; the agent fetches it)."""

    __tablename__ = "application_resumes"

    application_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    resume_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
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


class Interviewer(Base):
    """Mock calendar accounts, keyed by email (the join key from interview-plan pools)."""

    __tablename__ = "interviewers"

    email: Mapped[str] = mapped_column(String(320), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # Plaintext demo password (direct compare). Mock accounts only — never
    # a pattern for real users.
    password: Mapped[str] = mapped_column(String(128), nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SchedulerThread(Base):
    """Open coordinations: interviewer Slack user -> scheduler Cominty thread."""

    __tablename__ = "scheduler_threads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slack_user_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    application_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    stage_id: Mapped[str] = mapped_column(String(64), nullable=False)
    cominty_thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SchedulerTrigger(Base):
    """Fired scheduler triggers: exactly one thread per (application, stage).

    Written after a successful trigger (webhook or sweep path alike), so
    retries still fire but replays and cross-path duplicates do not.
    Re-entry into a stage after leaving it is ignored (known limitation).
    """

    __tablename__ = "scheduler_triggers"
    __table_args__ = (UniqueConstraint("application_id", "stage_id", name="uq_scheduler_triggers_app_stage"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    stage_id: Mapped[str] = mapped_column(String(64), nullable=False)
    cominty_thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CandidateThread(Base):
    """Candidate email coordinations: reply-to token -> scheduler thread."""

    __tablename__ = "candidate_threads"

    token: Mapped[str] = mapped_column(String(32), primary_key=True)
    application_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    stage_id: Mapped[str] = mapped_column(String(64), nullable=False)
    cominty_thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_email: Mapped[str] = mapped_column(String(320), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ResendEvent(Base):
    """Processed Resend webhook event IDs (at-least-once dedupe)."""

    __tablename__ = "resend_events"

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CalendarEvent(Base):
    """Busy blocks (personal) and interview bookings (agent) per interviewer.

    Overlap safety is check-then-insert in the booking service (fine for a
    mock; a Postgres exclusion constraint would break the SQLite test path).
    """

    __tablename__ = "calendar_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    interviewer_email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    application_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_key: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
