"""Scheduler-agent trigger (Cominty managed agent, interview coordination).

Fires every time a candidate enters an interview-kind stage. The trigger
message is the contract: stable format the agent's instructions reference,
carrying an idempotency key plus everything needed to start coordinating
(candidate contact, stage, interview plan). Delivery is at-least-once, so
the agent must check existing Harly interviews before acting.
"""

from __future__ import annotations

from typing import Any

from app.services.cominty import ComintyService


class SchedulerNotConfigured(Exception):
    """Scheduler agent ID is not configured; coordination cannot start."""


def _summarize_rounds(rounds: Any) -> str:
    """Compact one-line-per-round plan summary (never raises)."""
    if not isinstance(rounds, list) or not rounds:
        return "none saved"
    lines: list[str] = []
    for entry in rounds:
        try:
            name = str(entry.get("name", "?"))
            window = entry.get("window") or {}
            span = f"{window.get('start', '?')}..{window.get('end', '?')}"
            pool = entry.get("pool") or []
            who = ", ".join(str(p.get("name") or p.get("email", "?")) for p in pool) or "no pool"
            lines.append(f"{name} [{span}] pool: {who}")
        except Exception:
            lines.append("unreadable round (re-read via get_interview_config)")
    return "; ".join(lines)


def build_schedule_message(
    *,
    event_id: str,
    application_id: str,
    job_id: str,
    candidate_id: str,
    candidate_email: str | None,
    stage_id: str,
    stage_name: str | None,
    interview_plan: list | None,
    unreachable: list[str] | None = None,
) -> str:
    """Per-trigger instruction. Must match the format in the agent's instructions."""
    stage = f"{stage_name} ({stage_id})" if stage_name else stage_id
    email = candidate_email or "unknown — ask the Hiring Manager"
    if interview_plan:
        plan = _summarize_rounds(interview_plan)
    else:
        plan = "none saved — ask the Hiring Manager for rounds, windows, and pools first"
    message = (
        f"Schedule interviews for application {application_id} "
        f"(job {job_id}, candidate {candidate_id}). "
        f"Trigger {event_id}: candidate entered stage {stage}. "
        f"Candidate email: {email}. "
        f"Interview plan: {plan}. "
        "Match the stage to a plan round by name; confirm with the Hiring Manager "
        "when ambiguous. Before acting, list the application's existing Harly "
        "interviews with list_interviews — if one already covers this round "
        "(match by title/type), do nothing (this trigger "
        "is at-least-once). Otherwise check interviewer availability with "
        "get_availability on the calendar connection and book with "
        "book_interview inside a free gap, passing this trigger event ID as "
        "the event key. Coordinate with interviewers over Slack via "
        "send_slack_message, and with the candidate over email via "
        "send_email; their replies arrive back in this thread."
    )
    if unreachable:
        message += (
            " Slack cannot reach these pool members — coordinate with them "
            f"out of band: {', '.join(unreachable)}."
        )
    return message


async def start_scheduler_run(
    cominty: ComintyService,
    *,
    agent_id: str,
    event_id: str,
    application_id: str,
    job_id: str,
    candidate_id: str,
    candidate_email: str | None,
    stage_id: str,
    stage_name: str | None,
    interview_plan: list | None,
    unreachable: list[str] | None = None,
):
    """Start a coordination run; reply pending so mappings record first."""
    if not agent_id:
        raise SchedulerNotConfigured("cominty_scheduler_agent_id is not configured")
    message = build_schedule_message(
        event_id=event_id,
        application_id=application_id,
        job_id=job_id,
        candidate_id=candidate_id,
        candidate_email=candidate_email,
        stage_id=stage_id,
        stage_name=stage_name,
        interview_plan=interview_plan,
        unreachable=unreachable,
    )
    return await cominty.start_run(message, name=f"schedule-{application_id}-{stage_id}")


async def trigger_scheduler(
    cominty: ComintyService,
    *,
    agent_id: str,
    event_id: str,
    application_id: str,
    job_id: str,
    candidate_id: str,
    candidate_email: str | None,
    stage_id: str,
    stage_name: str | None,
    interview_plan: list | None,
    unreachable: list[str] | None = None,
) -> tuple[str, str]:
    """Start a fresh coordination thread. Returns (thread_id, reply text)."""
    if not agent_id:
        raise SchedulerNotConfigured("cominty_scheduler_agent_id is not configured")
    message = build_schedule_message(
        event_id=event_id,
        application_id=application_id,
        job_id=job_id,
        candidate_id=candidate_id,
        candidate_email=candidate_email,
        stage_id=stage_id,
        stage_name=stage_name,
        interview_plan=interview_plan,
        unreachable=unreachable,
    )
    thread_id, reply = await cominty.start_thread(message, name=f"schedule-{application_id}-{stage_id}")
    return thread_id, reply
