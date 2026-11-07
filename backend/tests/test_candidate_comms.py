"""Candidate comms service: reply-to tokens, send orchestration, body extract."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from recruitment_db.database import Base
from recruitment_db.models import CandidateThread, SchedulerTrigger
from app.services.candidate_comms import (
    CandidateCommsError,
    build_reply_to,
    extract_reply_text,
    parse_reply_token,
    send_candidate_email,
)


class FakeResend:
    def __init__(self) -> None:
        self.sends: list = []

    async def send_email(self, *, from_email, to_email, subject, text, reply_to):
        self.sends.append(
            {
                "from_email": from_email,
                "to_email": to_email,
                "subject": subject,
                "text": text,
                "reply_to": reply_to,
            }
        )
        return "email_1"


@pytest.fixture
async def factory(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/cand.db",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def test_reply_to_round_trip() -> None:
    addr = build_reply_to("tok_abc-12", "in.test.dev")
    assert addr == "sched-tok_abc-12@in.test.dev"
    assert parse_reply_token(addr) == "tok_abc-12"
    assert parse_reply_token("someone@in.test.dev") is None
    assert parse_reply_token("not-an-address") is None


def test_extract_reply_text_prefers_text() -> None:
    assert extract_reply_text({"text": "Tue works", "html": "<p>no</p>"}) == "Tue works"


def test_extract_reply_text_strips_html_fallback() -> None:
    assert extract_reply_text({"text": None, "html": "<p>Tue <b>works</b></p>"}) == "Tue works"
    assert extract_reply_text({"text": "  ", "html": None}) == ""


async def test_send_records_thread(factory) -> None:
    async with factory() as session:
        session.add(
            SchedulerTrigger(application_id="a1", stage_id="s9", cominty_thread_id="thr_1")
        )
        await session.commit()
    resend = FakeResend()
    result = await send_candidate_email(
        resend,
        factory,
        from_email="Acme <sched@test.dev>",
        domain="in.test.dev",
        to_email="cand@test.com",
        subject="R1 options",
        text="Tue or Wed?",
        application_id="a1",
        stage_id="s9",
    )
    assert result["email_id"] == "email_1"
    assert result["reply_to"].endswith("@in.test.dev")
    token = parse_reply_token(result["reply_to"])
    assert token
    async with factory() as session:
        row = (
            await session.execute(select(CandidateThread).where(CandidateThread.token == token))
        ).scalar_one()
        assert (row.application_id, row.stage_id, row.cominty_thread_id) == ("a1", "s9", "thr_1")
    assert resend.sends[0]["reply_to"] == result["reply_to"]


async def test_send_requires_coordination(factory, monkeypatch) -> None:
    import asyncio

    async def instant(_delay: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", instant)
    resend = FakeResend()
    with pytest.raises(CandidateCommsError, match="no open coordination"):
        await send_candidate_email(
            resend,
            factory,
            from_email="Acme <sched@test.dev>",
            domain="in.test.dev",
            to_email="cand@test.com",
            subject="R1",
            text="hi",
            application_id="a9",
            stage_id="s9",
        )
    assert resend.sends == []
