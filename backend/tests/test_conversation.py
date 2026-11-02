"""HM gate and thread mapping against a real (SQLite) database."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.database import Base
from app.models import Employee
from app.services.conversation import get_thread, is_hiring_manager, record_thread


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
