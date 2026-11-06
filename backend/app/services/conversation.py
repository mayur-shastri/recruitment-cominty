"""Hiring-manager gate and Slack<->Cominty thread mapping."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from recruitment_db.models import ConversationThread, Employee

MIN_HM_GRADE = 7  # hiring managers are employees with grade *above* this


async def is_hiring_manager(session: AsyncSession, slack_user_id: str) -> bool:
    grade = (
        await session.execute(select(Employee.grade).where(Employee.slack_user_id == slack_user_id))
    ).scalar_one_or_none()
    return grade is not None and grade > MIN_HM_GRADE


async def get_thread(session: AsyncSession, slack_user_id: str) -> ConversationThread | None:
    return (
        await session.execute(select(ConversationThread).where(ConversationThread.slack_user_id == slack_user_id))
    ).scalar_one_or_none()


async def record_thread(
    session: AsyncSession, *, slack_user_id: str, cominty_user_id: str, cominty_thread_id: str
) -> ConversationThread:
    """Insert the mapping; on a concurrent duplicate, return the existing row."""
    thread = ConversationThread(
        slack_user_id=slack_user_id, cominty_user_id=cominty_user_id, cominty_thread_id=cominty_thread_id
    )
    session.add(thread)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await get_thread(session, slack_user_id)
        assert existing is not None  # the conflicting row must exist
        return existing
    return thread
