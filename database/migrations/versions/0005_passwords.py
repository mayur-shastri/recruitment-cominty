"""Demo login passwords for mock interviewer accounts."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("interviewers", sa.Column("password", sa.String(128), server_default="", nullable=False))


def downgrade() -> None:
    op.drop_column("interviewers", "password")
