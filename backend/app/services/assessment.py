"""Assessment-agent trigger (Cominty managed agent, headless scoring runs)."""

from __future__ import annotations

from app.services.cominty import ComintyService


class AssessmentNotConfigured(Exception):
    """Assessment agent ID is not configured; scoring runs cannot start."""


def build_score_message(*, application_id: str, job_id: str, candidate_id: str) -> str:
    """Per-run instruction. Must match the format in the agent's instructions."""
    return f"Score application {application_id} for job {job_id} (candidate {candidate_id})."


async def trigger_assessment(
    cominty: ComintyService,
    *,
    agent_id: str,
    application_id: str,
    job_id: str,
    candidate_id: str,
) -> str:
    """Start a fresh scoring thread. Returns the agent's reply text."""
    if not agent_id:
        raise AssessmentNotConfigured("cominty_assessment_agent_id is not configured")
    message = build_score_message(
        application_id=application_id, job_id=job_id, candidate_id=candidate_id
    )
    _, reply = await cominty.start_thread(message, name=f"assess-{application_id}")
    return reply
