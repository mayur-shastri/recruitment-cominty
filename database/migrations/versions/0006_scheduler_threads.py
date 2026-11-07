"""Scheduler coordination threads for interviewer reply routing."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scheduler_threads",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("slack_user_id", sa.String(32), nullable=False),
        sa.Column("application_id", sa.String(64), nullable=False),
        sa.Column("stage_id", sa.String(64), nullable=False),
        sa.Column("cominty_thread_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), server_default="open", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scheduler_threads_slack_user_id", "scheduler_threads", ["slack_user_id"])
    op.create_index("ix_scheduler_threads_application_id", "scheduler_threads", ["application_id"])


def downgrade() -> None:
    op.drop_index("ix_scheduler_threads_application_id", table_name="scheduler_threads")
    op.drop_index("ix_scheduler_threads_slack_user_id", table_name="scheduler_threads")
    op.drop_table("scheduler_threads")
