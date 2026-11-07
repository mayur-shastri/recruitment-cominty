"""Seed the mock calendar: 3 interviewers plus next week's busy blocks.

Idempotent: interviewers are skipped when present, and each seed block
carries an event_key so re-runs replay instead of duplicating.

Usage (repo root, project venv):  python calendar-mock/seed.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Flat-layout isolation (mirrors the test preambles): these names may already
# be bound to another suite's modules in combined pytest runs, which would
# shadow this service's own modules (including transitive `config` imports).
# Harmless standalone.
for _mod in [
    m for m in list(sys.modules) if m.split(".", 1)[0] in {"config", "server", "tools", "services", "ui"}
]:
    del sys.modules[_mod]

from sqlalchemy import select  # noqa: E402

from recruitment_db.models import Interviewer  # noqa: E402
from services.booking import BookingStore, get_booking_store  # noqa: E402

INTERVIEWERS = [
    ("asha.patel@acme.tech", "Asha Patel"),
    ("ravi.kumar@acme.tech", "Ravi Kumar"),
    ("mei.chen@acme.tech", "Mei Chen"),
]

# Per-interviewer weekday patterns: (start_hour, end_hour, title).
PATTERNS = {
    "asha.patel@acme.tech": [(9, 11, "Deep work"), (12, 13, "Lunch"), (15, 16, "Team sync")],
    "ravi.kumar@acme.tech": [(10, 11, "Standup + reviews"), (13, 14, "Lunch"), (16, 18, "Customer calls")],
    "mei.chen@acme.tech": [(9, 10, "Planning"), (12, 13, "Lunch")],
}


def _next_monday(today: datetime) -> datetime:
    days_ahead = (7 - today.weekday()) % 7 or 7
    return (today + timedelta(days=days_ahead)).replace(hour=0, minute=0, second=0, microsecond=0)


async def seed(store: BookingStore) -> dict[str, int]:
    """Seed interviewers and busy blocks. Returns rows present per table."""
    async with store._session() as session:
        have = {r.email for r in (await session.execute(select(Interviewer))).scalars()}
        for email, name in INTERVIEWERS:
            if email not in have:
                session.add(Interviewer(email=email, name=name))
        await session.commit()

    blocks = 0
    monday = _next_monday(datetime.now(timezone.utc))
    for email, _ in INTERVIEWERS:
        for day_offset in range(5):
            day = monday + timedelta(days=day_offset)
            for i, (sh, eh, title) in enumerate(PATTERNS[email]):
                await store.add_busy_block(
                    interviewer_email=email,
                    starts_at=day.replace(hour=sh),
                    ends_at=day.replace(hour=eh),
                    title=title,
                    event_key=f"seed:{email}:{day.date().isoformat()}:{i}",
                )
                blocks += 1
    return {"interviewers": len(INTERVIEWERS), "blocks": blocks}


async def main() -> None:
    store = get_booking_store()
    try:
        result = await seed(store)
        print(f"seeded {result['interviewers']} interviewers + {result['blocks']} busy blocks")
    finally:
        await store.aclose()


if __name__ == "__main__":
    asyncio.run(main())
