"""Interview meeting links on calendar events (backfilled for existing rows)."""

from __future__ import annotations

import secrets
import string

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_MEET_BASE = "https://meet.acmetech.com"


def _generate_meeting_url() -> str:
    # Self-contained copy of recruitment_db.meetings.generate_meeting_url:
    # migrations must not import app code that can drift later.
    room = "-".join(
        "".join(secrets.choice(string.ascii_lowercase) for _ in range(n)) for n in (3, 4, 3)
    )
    return f"{_MEET_BASE}/{room}"


def upgrade() -> None:
    op.add_column("calendar_events", sa.Column("meeting_url", sa.String(512), nullable=True))
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id FROM calendar_events WHERE kind = 'interview' AND meeting_url IS NULL"
        )
    ).all()
    for (event_id,) in rows:
        conn.execute(
            sa.text("UPDATE calendar_events SET meeting_url = :url WHERE id = :id"),
            {"url": _generate_meeting_url(), "id": event_id},
        )


def downgrade() -> None:
    op.drop_column("calendar_events", "meeting_url")
