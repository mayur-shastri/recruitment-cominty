"""Hiring-manager gate and Slack<->Cominty thread mapping."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from recruitment_db.models import ConversationThread, Employee, SchedulerThread, SchedulerTrigger

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


async def record_scheduler_thread(
    session: AsyncSession,
    *,
    slack_user_id: str,
    application_id: str,
    stage_id: str,
    cominty_thread_id: str,
) -> SchedulerThread:
    """Open a coordination row so the interviewer's replies route to the thread."""
    row = SchedulerThread(
        slack_user_id=slack_user_id,
        application_id=application_id,
        stage_id=stage_id,
        cominty_thread_id=cominty_thread_id,
        status="open",
    )
    session.add(row)
    await session.commit()
    return row


async def get_scheduler_trigger(
    session: AsyncSession, application_id: str, stage_id: str
) -> SchedulerTrigger | None:
    return (
        await session.execute(
            select(SchedulerTrigger).where(
                SchedulerTrigger.application_id == application_id,
                SchedulerTrigger.stage_id == stage_id,
            )
        )
    ).scalar_one_or_none()


async def record_scheduler_trigger(
    session: AsyncSession, *, application_id: str, stage_id: str, cominty_thread_id: str
) -> SchedulerTrigger:
    """Mark (application, stage) triggered; on a race, return the winner's row."""
    row = SchedulerTrigger(
        application_id=application_id, stage_id=stage_id, cominty_thread_id=cominty_thread_id
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await get_scheduler_trigger(session, application_id, stage_id)
        assert existing is not None  # the conflicting row must exist
        return existing
    return row


async def delete_scheduler_trigger(
    session_factory, *, application_id: str, stage_id: str, cominty_thread_id: str
) -> None:
    """Compensate a failed run: remove only this thread's trigger rows."""
    async with session_factory() as session:
        await session.execute(
            delete(SchedulerThread).where(
                SchedulerThread.application_id == application_id,
                SchedulerThread.stage_id == stage_id,
                SchedulerThread.cominty_thread_id == cominty_thread_id,
            )
        )
        await session.execute(
            delete(SchedulerTrigger).where(
                SchedulerTrigger.application_id == application_id,
                SchedulerTrigger.stage_id == stage_id,
                SchedulerTrigger.cominty_thread_id == cominty_thread_id,
            )
        )
        await session.commit()


async def get_open_scheduler_thread(
    session: AsyncSession, slack_user_id: str
) -> SchedulerThread | None:
    """Latest open coordination for a Slack user (None when the user has none)."""
    return (
        await session.execute(
            select(SchedulerThread)
            .where(
                SchedulerThread.slack_user_id == slack_user_id,
                SchedulerThread.status == "open",
            )
            .order_by(SchedulerThread.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
