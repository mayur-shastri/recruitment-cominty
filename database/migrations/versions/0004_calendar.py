"""Mock interviewer calendar: accounts and busy/interview events."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "interviewers",
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("email"),
    )
    op.create_table(
        "calendar_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("interviewer_email", sa.String(320), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("title", sa.String(256), nullable=True),
        sa.Column("application_id", sa.String(64), nullable=True),
        sa.Column("job_id", sa.String(64), nullable=True),
        sa.Column("event_key", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_key"),
    )
    op.create_index("ix_calendar_events_interviewer_email", "calendar_events", ["interviewer_email"])
    op.create_index("ix_calendar_events_starts_at", "calendar_events", ["starts_at"])


def downgrade() -> None:
    op.drop_index("ix_calendar_events_starts_at", table_name="calendar_events")
    op.drop_index("ix_calendar_events_interviewer_email", table_name="calendar_events")
    op.drop_table("calendar_events")
    op.drop_table("interviewers")
