"""HM gate and thread mapping against a real (SQLite) database."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.services.conversation import (
    get_app_lock,
    get_open_scheduler_thread,
    get_scheduler_trigger,
    get_thread,
    is_hiring_manager,
    record_scheduler_thread,
    record_scheduler_trigger,
    record_thread,
    supersede_app_threads,
)
from recruitment_db.database import Base
from recruitment_db.models import Employee


@pytest.fixture
async def session(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/test.db",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _add_employee(session: AsyncSession, slack_user_id: str, grade: int) -> None:
    session.add(Employee(slack_user_id=slack_user_id, grade=grade))
    await session.commit()


async def test_unknown_user_is_not_hm(session: AsyncSession) -> None:
    assert await is_hiring_manager(session, "U1") is False


async def test_grade_boundary(session: AsyncSession) -> None:
    await _add_employee(session, "U7", 7)
    await _add_employee(session, "U8", 8)
    assert await is_hiring_manager(session, "U7") is False
    assert await is_hiring_manager(session, "U8") is True


async def test_thread_roundtrip(session: AsyncSession) -> None:
    assert await get_thread(session, "U1") is None
    thread = await record_thread(session, slack_user_id="U1", cominty_user_id="user_x", cominty_thread_id="thr_1")
    assert thread.cominty_thread_id == "thr_1"
    assert (await get_thread(session, "U1")).cominty_thread_id == "thr_1"


async def test_concurrent_record_returns_existing(session: AsyncSession) -> None:
    await record_thread(session, slack_user_id="U1", cominty_user_id="user_x", cominty_thread_id="thr_1")
    existing = await record_thread(session, slack_user_id="U1", cominty_user_id="user_x", cominty_thread_id="thr_2")
    assert existing.cominty_thread_id == "thr_1"


async def test_scheduler_trigger_record_idempotent(session: AsyncSession) -> None:
    assert await get_scheduler_trigger(session, "a1", "s9") is None
    first = await record_scheduler_trigger(
        session, application_id="a1", stage_id="s9", cominty_thread_id="thr_1"
    )
    second = await record_scheduler_trigger(
        session, application_id="a1", stage_id="s9", cominty_thread_id="thr_2"
    )
    assert first.id == second.id
    assert second.cominty_thread_id == "thr_1"


async def test_scheduler_thread_latest_open_wins(session: AsyncSession) -> None:
    assert await get_open_scheduler_thread(session, "U9") is None
    await record_scheduler_thread(
        session, slack_user_id="U9", application_id="a1", stage_id="s1", cominty_thread_id="thr_old"
    )
    await record_scheduler_thread(
        session, slack_user_id="U9", application_id="a2", stage_id="s2", cominty_thread_id="thr_new"
    )
    found = await get_open_scheduler_thread(session, "U9")
    assert found is not None and found.cominty_thread_id == "thr_new"
    assert found.application_id == "a2"
    assert await get_open_scheduler_thread(session, "U_other") is None


def test_app_lock_identity() -> None:
    assert get_app_lock("a1") is get_app_lock("a1")
    assert get_app_lock("a1") is not get_app_lock("a2")


async def test_supersede_app_threads(session: AsyncSession) -> None:
    await record_scheduler_thread(
        session, slack_user_id="U9", application_id="a1", stage_id="s1", cominty_thread_id="thr_old"
    )
    await record_scheduler_thread(
        session, slack_user_id="U9", application_id="a1", stage_id="s2", cominty_thread_id="thr_new"
    )
    assert await supersede_app_threads(session, application_id="a1", except_thread_id="thr_new") == 1
    assert await supersede_app_threads(session, application_id="a1", except_thread_id="thr_new") == 0
    found = await get_open_scheduler_thread(session, "U9")
    assert found is not None and found.cominty_thread_id == "thr_new"
