"""Seed an employee row (demo HM allowlist). Run from the repo root:

    python scripts/seed_employee.py U12345678 8 --name "Jane Doe"

Your Slack member ID: profile -> More actions -> Copy member ID.
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.config import get_settings, to_async_database_url
from app.database import create_engine_and_sessions
from app.models import Employee


async def main() -> None:
    args = parse_args()
    settings = get_settings()
    engine, factory = create_engine_and_sessions(to_async_database_url(settings.database_url))
    try:
        async with factory() as session:
            existing = (
                await session.execute(select(Employee).where(Employee.slack_user_id == args.slack_user_id))
            ).scalar_one_or_none()
            if existing is None:
                session.add(
                    Employee(slack_user_id=args.slack_user_id, grade=args.grade, display_name=args.name)
                )
            else:
                existing.grade = args.grade
                if args.name:
                    existing.display_name = args.name
            await session.commit()
    finally:
        await engine.dispose()
    print(f"employee {args.slack_user_id} saved with grade {args.grade}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed an employee row.")
    parser.add_argument("slack_user_id", help="Slack member ID (e.g. U12345678)")
    parser.add_argument("grade", type=int, help="Employee grade (hiring managers: above 7)")
    parser.add_argument("--name", default=None, help="Display name")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main())
