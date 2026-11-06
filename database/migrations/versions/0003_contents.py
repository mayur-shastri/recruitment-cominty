"""Harly webhook dedupe and resolved resume URLs."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "harly_events",
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_table(
        "application_resumes",
        sa.Column("application_id", sa.String(64), nullable=False),
        sa.Column("resume_url", sa.String(1024), nullable=False),
        sa.Column("file_name", sa.String(256), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column(
            "resolved_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("application_id"),
    )


def downgrade() -> None:
    op.drop_table("application_resumes")
    op.drop_table("harly_events")
