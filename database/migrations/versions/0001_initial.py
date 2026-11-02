"""Initial tables: employees, conversation_threads, slack_events."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "employees",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("slack_user_id", sa.String(32), nullable=False),
        sa.Column("grade", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slack_user_id"),
    )
    op.create_index("ix_employees_slack_user_id", "employees", ["slack_user_id"])

    op.create_table(
        "conversation_threads",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("slack_user_id", sa.String(32), nullable=False),
        sa.Column("cominty_user_id", sa.String(64), nullable=False),
        sa.Column("cominty_thread_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slack_user_id"),
    )
    op.create_index("ix_conversation_threads_slack_user_id", "conversation_threads", ["slack_user_id"])

    op.create_table(
        "slack_events",
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
    )


def downgrade() -> None:
    op.drop_table("slack_events")
    op.drop_index("ix_conversation_threads_slack_user_id", table_name="conversation_threads")
    op.drop_table("conversation_threads")
    op.drop_index("ix_employees_slack_user_id", table_name="employees")
    op.drop_table("employees")
