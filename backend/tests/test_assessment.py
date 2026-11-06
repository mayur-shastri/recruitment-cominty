"""Assessment trigger: message contract and configuration gate."""

from __future__ import annotations

import pytest

from app.services.assessment import AssessmentNotConfigured, build_score_message, trigger_assessment


class FakeCominty:
    def __init__(self) -> None:
        self.calls: list = []

    async def start_thread(self, message: str, *, name=None):
        self.calls.append((message, name))
        return "thr_1", "SCORED a1 total=80"


def test_message_contract() -> None:
    assert (
        build_score_message(application_id="a1", job_id="j1", candidate_id="c1")
        == "Score application a1 for job j1 (candidate c1)."
    )


async def test_trigger_starts_named_thread() -> None:
    cominty = FakeCominty()
    reply = await trigger_assessment(
        cominty, agent_id="agent_1", application_id="a1", job_id="j1", candidate_id="c1"
    )
    assert reply == "SCORED a1 total=80"
    [(message, name)] = cominty.calls
    assert message == "Score application a1 for job j1 (candidate c1)."
    assert name == "assess-a1"


async def test_trigger_refuses_without_agent() -> None:
    with pytest.raises(AssessmentNotConfigured, match="not configured"):
        await trigger_assessment(
            FakeCominty(), agent_id="", application_id="a1", job_id="j1", candidate_id="c1"
        )
