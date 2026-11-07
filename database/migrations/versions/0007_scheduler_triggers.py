"""Scheduler trigger markers: exactly one thread per (application, stage)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scheduler_triggers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("application_id", sa.String(64), nullable=False),
        sa.Column("stage_id", sa.String(64), nullable=False),
        sa.Column("cominty_thread_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("application_id", "stage_id", name="uq_scheduler_triggers_app_stage"),
    )
    op.create_index("ix_scheduler_triggers_application_id", "scheduler_triggers", ["application_id"])


def downgrade() -> None:
    op.drop_index("ix_scheduler_triggers_application_id", table_name="scheduler_triggers")
    op.drop_table("scheduler_triggers")
