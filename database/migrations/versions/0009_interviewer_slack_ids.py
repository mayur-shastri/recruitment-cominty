"""Interviewer Slack member IDs for scope-free DMs."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("interviewers", sa.Column("slack_user_id", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("interviewers", "slack_user_id")
