"""Scheduler trigger: contract message format + thread start (fakes only)."""

from __future__ import annotations

import pytest

from app.services.scheduler import (
    SchedulerNotConfigured,
    build_schedule_message,
    trigger_scheduler,
)


class FakeCominty:
    def __init__(self) -> None:
        self.calls: list = []

    async def start_thread(self, message: str, *, name=None):
        self.calls.append((message, name))
        return "thr_9", "ACK schedule"

    async def aclose(self) -> None:
        pass


def _message(**overrides) -> str:
    base = {
        "event_id": "e9",
        "application_id": "a1",
        "job_id": "j1",
        "candidate_id": "c1",
        "candidate_email": "cand@test.com",
        "stage_id": "s9",
        "stage_name": "R1 Interview",
        "interview_plan": [
            {
                "name": "R1 Interview",
                "window": {"start": "2026-11-20", "end": "2026-11-27"},
                "pool": [{"name": "Asha", "email": "asha@acme.com"}],
            }
        ],
    }
    base.update(overrides)
    return build_schedule_message(**base)


def test_message_carries_contract() -> None:
    message = _message()
    assert "Schedule interviews for application a1 (job j1, candidate c1)." in message
    assert "Trigger e9" in message
    assert "R1 Interview (s9)" in message
    assert "cand@test.com" in message
    assert "R1 Interview [2026-11-20..2026-11-27] pool: Asha" in message
    assert "at-least-once" in message
    assert "get_availability" in message
    assert "book_interview" in message
    assert "event key" in message
    assert "send_slack_message" in message
    assert "send_email" in message
    assert "replies arrive back in this thread" in message


def test_message_notes_unreachable_members() -> None:
    message = _message(interview_plan=[{"name": "R1"}], unreachable=["ghost@acme.com"])
    assert "out of band" in message
    assert "ghost@acme.com" in message


def test_message_notes_gaps() -> None:
    message = _message(candidate_email=None, stage_name=None, interview_plan=None)
    assert "unknown" in message
    assert "none saved" in message
    assert "entered stage s9." in message


async def test_trigger_starts_named_thread() -> None:
    cominty = FakeCominty()
    thread_id, reply = await trigger_scheduler(
        cominty,
        agent_id="sched_1",
        event_id="e9",
        application_id="a1",
        job_id="j1",
        candidate_id="c1",
        candidate_email="cand@test.com",
        stage_id="s9",
        stage_name="R1 Interview",
        interview_plan=[{"name": "R1"}],
    )
    assert thread_id == "thr_9"
    assert reply == "ACK schedule"
    [(message, name)] = cominty.calls
    assert name == "schedule-a1-s9"
    assert "Trigger e9" in message


async def test_trigger_refuses_without_agent() -> None:
    with pytest.raises(SchedulerNotConfigured, match="not configured"):
        await trigger_scheduler(
            FakeCominty(),
            agent_id="",
            event_id="e9",
            application_id="a1",
            job_id="j1",
            candidate_id="c1",
            candidate_email=None,
            stage_id="s9",
            stage_name=None,
            interview_plan=None,
        )
