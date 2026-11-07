"""M3.3 pipelines: new-application resume resolution + interview-stage scheduler hook.

URL resolution failures never block scoring: the agent falls back to profile
data. Agent-trigger failures DO propagate (the receiver drops the dedupe row
so the Harly retry redelivers; the agent's own idempotency check makes that
safe).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import select

from app.integrations.harly.client import HarlyReadError, HarlyReads
from app.services import resumes
from app.services.assessment import trigger_assessment
from app.services.conversation import record_scheduler_thread
from app.services.interviewer_comms import CommsError, resolve_slack_id
from app.services.scheduler import trigger_scheduler
from recruitment_db.models import (
    ApplicationResume,
    ApplicationScore,
    JobInterviewConfig,
    ScoringCriteria,
)

logger = logging.getLogger(__name__)

# Polling fallback (Harly webhooks are broken upstream): each sweep reads at
# most MAX_PAGES x PAGE_SIZE applications and triggers scoring for the ones
# with no score, no in-flight pipeline run, and active criteria for the job.
POLL_PAGE_SIZE = 100
POLL_MAX_PAGES = 3


def extract_ids(data: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    """Best-effort (application_id, candidate_id, job_id) from a webhook payload."""
    nested = data.get("application") if isinstance(data.get("application"), dict) else {}
    app_id = data.get("applicationId") or data.get("id") or nested.get("id")
    cand_id = data.get("candidateId") or nested.get("candidateId")
    job_id = data.get("jobId") or nested.get("jobId")
    norm = lambda v: str(v) if v else None
    return norm(app_id), norm(cand_id), norm(job_id)


async def _store_resume_url(
    session_factory, *, application_id: str, resume_url: str, file_name: str, file_size: int
) -> None:
    async with session_factory() as session:
        row = await session.get(ApplicationResume, application_id)
        if row is None:
            session.add(
                ApplicationResume(
                    application_id=application_id,
                    resume_url=resume_url,
                    file_name=file_name,
                    file_size=file_size,
                )
            )
        else:
            row.resume_url = resume_url
            row.file_name = file_name
            row.file_size = file_size
        await session.commit()


async def _resolve_resume_url(
    runtime, *, candidate_id: str, application_id: str
) -> tuple[str | None, str, int, str]:
    """Join the candidate's resume file to its S3 key.

    Returns (key_or_None, file_name, file_size, status).
    """
    reads = HarlyReads(runtime.harly_base_url, runtime.harly_api_key)
    files = await reads.list_candidate_files(candidate_id)
    target = resumes.pick_resume_file(files)
    if target is None:
        logger.info("no resume files for candidate %s; profile-only scoring", candidate_id)
        return None, "", 0, "skipped:no-files"
    if not runtime.s3_configured:
        logger.info("s3 not configured; profile-only scoring for %s", application_id)
        return None, "", 0, "skipped:no-s3"
    file_name = str(target.get("fileName", ""))
    try:
        file_size = int(target.get("fileSize") or 0)
    except (TypeError, ValueError):
        logger.warning("unusable fileSize for %s; profile-only", file_name)
        return None, file_name, 0, "skipped:bad-size"
    s3 = resumes.build_s3_client(
        runtime.s3_endpoint, runtime.s3_region, runtime.s3_access_key, runtime.s3_secret_key
    )
    key = await resumes.find_resume_key(
        s3,
        bucket=runtime.s3_bucket,
        prefix=f"workspaces/{runtime.s3_workspace_id}/resumes/",
        file_name=file_name,
        file_size=file_size,
    )
    if key is None:
        logger.warning("s3 join found no object for %s; profile-only", file_name)
        return None, file_name, file_size, "unmatched"
    return key, file_name, file_size, "resolved"


async def process_new_application(runtime, application_id: str) -> dict[str, Any]:
    """Resolve the resume URL (best effort), then trigger the scoring agent."""
    reads = HarlyReads(runtime.harly_base_url, runtime.harly_api_key)
    application = await reads.get_application(application_id)
    candidate_id = application.get("candidateId")
    job_id = application.get("jobId")
    if not candidate_id or not job_id:
        raise HarlyReadError(f"application {application_id} missing candidate/job")

    resume_status = "skipped"
    try:
        key, file_name, file_size, resume_status = await _resolve_resume_url(
            runtime, candidate_id=candidate_id, application_id=application_id
        )
        if key is not None:
            await _store_resume_url(
                runtime.session_factory,
                application_id=application_id,
                resume_url=f"{runtime.s3_public_url}/{key}",
                file_name=file_name,
                file_size=file_size,
            )
    except Exception:
        logger.exception("resume resolution failed for %s; continuing profile-only", application_id)

    reply = await trigger_assessment(
        runtime.assessment,
        agent_id=runtime.assessment_agent_id,
        application_id=application_id,
        job_id=job_id,
        candidate_id=candidate_id,
    )
    logger.info("assessment triggered for %s: %.80s", application_id, reply)
    return {"status": "triggered", "resume": resume_status, "reply_prefix": reply[:80]}


async def process_stage_change(runtime, data: dict[str, Any], *, event_id: str) -> dict[str, Any]:
    """Fire the scheduler trigger when a candidate enters an interview-kind stage."""
    application_id, candidate_id, job_id = extract_ids(data)
    if not application_id:
        logger.warning("stage_changed without application id; ignoring")
        return {"status": "ignored", "reason": "no application id"}
    reads = HarlyReads(runtime.harly_base_url, runtime.harly_api_key)
    application = await reads.get_application(application_id)
    stage_id = application.get("currentStageId")
    job_id = job_id or application.get("jobId")
    candidate_id = candidate_id or application.get("candidateId")
    kind, stage_name = None, None
    if stage_id and job_id:
        for stage in await reads.list_job_stages(job_id):
            if stage.get("id") == stage_id:
                kind = stage.get("kind")
                stage_name = stage.get("name")
                break
    if kind != "interview":
        logger.info("stage_changed to kind=%s; no scheduler action", kind)
        return {"status": "ignored", "kind": kind}
    if not job_id or not candidate_id or not stage_id:
        raise HarlyReadError(f"application {application_id} missing job/candidate/stage")

    candidate_email: str | None = None
    try:
        candidate = await reads.get_candidate(candidate_id)
        email = candidate.get("email")
        candidate_email = str(email).strip() if email else None
    except Exception:
        logger.warning("candidate email lookup failed for %s; scheduler gap noted", candidate_id)
    interview_plan: list | None = None
    try:
        async with runtime.session_factory() as session:
            row = await session.get(JobInterviewConfig, job_id)
            interview_plan = list(row.rounds) if row is not None else None
    except Exception:
        logger.exception("interview plan lookup failed for job %s", job_id)

    resolved, unreachable = await _resolve_pool_members(runtime, interview_plan)
    thread_id, reply = await trigger_scheduler(
        runtime.scheduler,
        agent_id=runtime.scheduler_agent_id,
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
    if resolved:
        async with runtime.session_factory() as session:
            for email, slack_user_id in resolved.items():
                await record_scheduler_thread(
                    session,
                    slack_user_id=slack_user_id,
                    application_id=application_id,
                    stage_id=stage_id,
                    cominty_thread_id=thread_id,
                )
    logger.info("scheduler triggered for %s @ %s: %.80s", application_id, stage_id, reply)
    return {
        "status": "scheduler_triggered",
        "application_id": application_id,
        "job_id": job_id,
        "stage_id": stage_id,
        "plan": interview_plan is not None,
        "email": candidate_email is not None,
        "coordinations": len(resolved),
        "unreachable": unreachable,
        "reply_prefix": reply[:80],
    }


def _pool_emails(interview_plan: list | None) -> list[str]:
    """Deduped pool emails across rounds (defensive: plans are HM-authored)."""
    emails: list[str] = []
    for entry in interview_plan or []:
        pool = entry.get("pool") if isinstance(entry, dict) else None
        for person in pool or []:
            email = person.get("email") if isinstance(person, dict) else None
            if isinstance(email, str) and email.strip() and email not in emails:
                emails.append(email.strip())
    return emails


async def _resolve_pool_members(
    runtime, interview_plan: list | None
) -> tuple[dict[str, str], list[str]]:
    """Resolve pool emails to Slack users. Per-email soft fail, never raises."""
    resolved: dict[str, str] = {}
    unreachable: list[str] = []
    for email in _pool_emails(interview_plan):
        try:
            resolved[email] = await resolve_slack_id(runtime.slack, email)
        except CommsError as exc:
            logger.warning("scheduler coordination skipping %s: %s", email, exc)
            unreachable.append(email)
        except Exception:
            logger.exception("scheduler coordination lookup failed for %s", email)
            unreachable.append(email)
    return resolved, unreachable


async def sweep_unscored_applications(
    runtime, *, max_pages: int = POLL_MAX_PAGES, page_size: int = POLL_PAGE_SIZE
) -> dict[str, Any]:
    """One poll sweep: trigger scoring for unscored applications.

    Skips (without triggering) applications that already have a score, have a
    resume row (pipeline ran; the agent may still be scoring), or whose job
    has no active criteria (retried on a later sweep, once criteria exist).
    Per-application failures are isolated; a dead Harly skips the sweep.
    """
    counts: dict[str, Any] = {
        "checked": 0,
        "triggered": 0,
        "skipped_scored": 0,
        "skipped_inflight": 0,
        "skipped_no_criteria": 0,
        "failed": 0,
    }
    if not runtime.assessment_agent_id:
        logger.warning("assessment poll skipped: assessment agent not configured")
        return {"status": "skipped", "reason": "no assessment agent", **counts}
    try:
        reads = HarlyReads(runtime.harly_base_url, runtime.harly_api_key)
    except HarlyReadError:
        logger.warning("assessment poll skipped: harly api not configured")
        return {"status": "skipped", "reason": "harly not configured", **counts}
    try:
        apps: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(max_pages):
            page, cursor = await reads.list_applications(limit=page_size, cursor=cursor)
            apps.extend(page)
            if not cursor:
                break
    except HarlyReadError:
        logger.exception("assessment poll: harly list failed; retrying next sweep")
        return {"status": "error", "reason": "harly list failed", **counts}

    pairs = [(a.get("id"), a.get("jobId")) for a in apps]
    pairs = [(str(i), str(j)) for i, j in pairs if i and j]
    if not pairs:
        logger.info("assessment poll: no applications seen")
        return {"status": "ok", **counts}
    app_ids = sorted({i for i, _ in pairs})
    job_ids = sorted({j for _, j in pairs})
    async with runtime.session_factory() as session:
        scored = set(
            (
                await session.execute(
                    select(ApplicationScore.application_id).where(
                        ApplicationScore.application_id.in_(app_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        inflight = set(
            (
                await session.execute(
                    select(ApplicationResume.application_id).where(
                        ApplicationResume.application_id.in_(app_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        criteria_jobs = set(
            (
                await session.execute(
                    select(ScoringCriteria.job_id).where(
                        ScoringCriteria.job_id.in_(job_ids),
                        ScoringCriteria.active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )

    for app_id, job_id in pairs:
        counts["checked"] += 1
        if app_id in scored:
            counts["skipped_scored"] += 1
            continue
        if app_id in inflight:
            counts["skipped_inflight"] += 1
            continue
        if job_id not in criteria_jobs:
            counts["skipped_no_criteria"] += 1
            continue
        try:
            await process_new_application(runtime, app_id)
        except Exception:
            logger.exception("assessment poll: trigger failed for %s", app_id)
            counts["failed"] += 1
            continue
        counts["triggered"] += 1
    logger.info(
        "assessment poll: checked=%d triggered=%d scored=%d inflight=%d no_criteria=%d failed=%d",
        counts["checked"],
        counts["triggered"],
        counts["skipped_scored"],
        counts["skipped_inflight"],
        counts["skipped_no_criteria"],
        counts["failed"],
    )
    return {"status": "ok", **counts}


async def run_poll_loop(runtime, *, interval_s: float) -> None:
    """Sweep immediately, then every interval; only cancellation stops it."""
    while True:
        try:
            await sweep_unscored_applications(runtime)
        except Exception:
            logger.exception("assessment poll sweep failed; retrying in %ss", interval_s)
        await asyncio.sleep(interval_s)
