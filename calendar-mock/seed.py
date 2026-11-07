"""Seed the interviewer calendar: 3 accounts plus a realistic work week.

Idempotent: accounts are upserted, and each seed block carries an
event_key so re-runs replay instead of duplicating.

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
    ("mayur2k03+asha@gmail.com", "Asha Patel", "asha123"),
    ("shastrimayur2993+ravi@gmail.com", "Ravi Kumar", "ravi123"),
    ("wilson69966996+mei@gmail.com", "Mei Chen", "mei123"),
]

# Per-interviewer weekday blocks: weekday (0=Mon) -> [(start, end, title)].
# Deliberately leaves shared gaps (e.g. Wed 11-12, Friday afternoons) where
# the scheduler agent can place interviews.
PATTERNS = {
    "mayur2k03+asha@gmail.com": {
        0: [("09:00", "09:30", "Team standup"), ("09:30", "11:30", "Deep work: hiring plan"),
            ("12:30", "13:30", "Lunch"), ("14:00", "15:00", "1:1 with Ravi"), ("16:00", "17:00", "Resume review")],
        1: [("09:00", "10:00", "Deep work"), ("12:00", "13:00", "Lunch"),
            ("13:00", "14:00", "Product sync"), ("15:30", "16:30", "1:1 with Mei")],
        2: [("09:30", "10:30", "Interview panel prep"), ("12:30", "13:30", "Lunch"),
            ("14:00", "17:00", "No-meeting block: project work")],
        3: [("09:00", "09:30", "Team standup"), ("10:00", "12:00", "Deep work"),
            ("12:30", "13:30", "Lunch"), ("16:00", "17:00", "Offer review")],
        4: [("09:00", "10:00", "Weekly wrap"), ("12:30", "13:30", "Lunch")],
    },
    "shastrimayur2993+ravi@gmail.com": {
        0: [("10:00", "11:00", "Standup + code reviews"), ("12:00", "13:00", "Lunch"),
            ("14:00", "15:00", "Architecture review"), ("15:30", "16:30", "1:1 with Asha")],
        1: [("09:00", "12:00", "Customer workshops"), ("12:00", "13:00", "Lunch"),
            ("14:00", "16:00", "Customer workshops"), ("16:30", "17:30", "Debrief")],
        2: [("10:00", "11:00", "Standup + code reviews"), ("12:00", "13:00", "Lunch"),
            ("13:30", "15:30", "Sprint planning")],
        3: [("09:00", "10:00", "Hiring sync"), ("12:00", "13:00", "Lunch"), ("13:00", "17:00", "Customer onsite")],
        4: [("10:00", "11:00", "Team demo"), ("12:00", "13:00", "Lunch")],
    },
    "wilson69966996+mei@gmail.com": {
        0: [("09:00", "10:00", "Sprint planning"), ("11:00", "12:00", "Design review"),
            ("12:00", "13:00", "Lunch"), ("15:00", "16:00", "1:1 with Asha")],
        1: [("09:00", "09:30", "Standup"), ("12:00", "13:00", "Lunch"), ("14:00", "15:00", "Portfolio review")],
        2: [("09:00", "11:00", "Focus: scorecards"), ("12:00", "13:00", "Lunch"),
            ("13:00", "14:00", "Hiring sync"), ("16:00", "17:00", "Gym")],
        3: [("09:00", "09:30", "Standup"), ("12:00", "13:00", "Lunch"), ("14:30", "15:30", "Mentor session")],
        4: [("09:30", "10:30", "Retrospective"), ("12:00", "13:00", "Lunch")],
    },
}


def _next_monday(today: datetime) -> datetime:
    days_ahead = (7 - today.weekday()) % 7 or 7
    return (today + timedelta(days=days_ahead)).replace(hour=0, minute=0, second=0, microsecond=0)


def _at(day: datetime, hm: str) -> datetime:
    hour, minute = (int(p) for p in hm.split(":"))
    return day.replace(hour=hour, minute=minute)


async def seed(store: BookingStore) -> dict[str, int]:
    """Seed accounts and busy blocks. Returns rows present per table."""
    async with store._session() as session:
        have = {r.email: r for r in (await session.execute(select(Interviewer))).scalars()}
        for email, name, password in INTERVIEWERS:
            if email not in have:
                session.add(Interviewer(email=email, name=name, password=password))
            elif have[email].password != password:
                have[email].password = password
        await session.commit()

    blocks = 0
    monday = _next_monday(datetime.now(timezone.utc))
    for email, days in PATTERNS.items():
        for weekday, slots in days.items():
            day = monday + timedelta(days=weekday)
            for i, (sh, eh, title) in enumerate(slots):
                await store.add_busy_block(
                    interviewer_email=email,
                    starts_at=_at(day, sh),
                    ends_at=_at(day, eh),
                    title=title,
                    event_key=f"seed:v2:{email}:{day.date().isoformat()}:{i}",
                )
                blocks += 1
    return {"interviewers": len(INTERVIEWERS), "blocks": blocks}


async def main() -> None:
    store = get_booking_store()
    try:
        result = await seed(store)
        print(f"seeded {result['interviewers']} interviewers + {result['blocks']} busy blocks")
        for email, name, password in INTERVIEWERS:
            print(f"  {name} <{email}>  password: {password}")
    finally:
        await store.aclose()


if __name__ == "__main__":
    asyncio.run(main())
