"""Candidate email coordinations and Resend webhook dedupe."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "candidate_threads",
        sa.Column("token", sa.String(32), nullable=False),
        sa.Column("application_id", sa.String(64), nullable=False),
        sa.Column("stage_id", sa.String(64), nullable=False),
        sa.Column("cominty_thread_id", sa.String(64), nullable=False),
        sa.Column("candidate_email", sa.String(320), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("token"),
    )
    op.create_index(
        "ix_candidate_threads_application_id", "candidate_threads", ["application_id"]
    )
    op.create_table(
        "resend_events",
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
    )


def downgrade() -> None:
    op.drop_table("resend_events")
    op.drop_index("ix_candidate_threads_application_id", table_name="candidate_threads")
    op.drop_table("candidate_threads")
