"""M3.3 pipelines: new-application resume resolution + interview-stage scheduler hook.

URL resolution failures never block scoring: the agent falls back to profile
data. Agent-trigger failures DO propagate (the receiver drops the dedupe row
so the Harly retry redelivers; the agent's own idempotency check makes that
safe).
"""

from __future__ import annotations

import logging
from typing import Any

from app.integrations.harly.client import HarlyReadError, HarlyReads
from app.services import resumes
from app.services.assessment import trigger_assessment
from recruitment_db.models import ApplicationResume

logger = logging.getLogger(__name__)


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


async def process_stage_change(runtime, data: dict[str, Any]) -> dict[str, Any]:
    """Route interview-stage moves to the scheduler hook (M3.6 builds it)."""
    application_id, _, job_id = extract_ids(data)
    if not application_id:
        logger.warning("stage_changed without application id; ignoring")
        return {"status": "ignored", "reason": "no application id"}
    reads = HarlyReads(runtime.harly_base_url, runtime.harly_api_key)
    application = await reads.get_application(application_id)
    stage_id = application.get("currentStageId")
    job_id = job_id or application.get("jobId")
    kind = None
    if stage_id and job_id:
        for stage in await reads.list_job_stages(job_id):
            if stage.get("id") == stage_id:
                kind = stage.get("kind")
                break
    if kind != "interview":
        logger.info("stage_changed to kind=%s; no scheduler action", kind)
        return {"status": "ignored", "kind": kind}
    logger.info(
        "scheduler hook: application %s entered interview stage (M3.6 TODO)", application_id
    )
    return {"status": "scheduler_queued", "application_id": application_id, "job_id": job_id}
