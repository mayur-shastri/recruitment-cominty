"""Score tools: reads for the Recruiter Agent, writes for the Assessment Agent.

The assessment agent is headless (triggered, no Hiring Manager to quote), so
its writes need no confirmation. HM-plan authoring is the opposite: the
recruiter saves rubrics and interview plans on the HM's behalf, so
save_scoring_criteria and save_interview_config require HM-quoting
confirmation like the ATS decision tools. Least privilege comes from
connection profiles: the assessment agent gets `write` (score writes, no
plan writes), the recruiter gets `read` plus plan authoring, and only dev
runs `all`.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

from services.scores import ScoresError, get_scores_store


def _require_non_blank(value: str | None, field: str) -> None:
    if value is not None and not value.strip():
        raise ToolError(f"{field} must not be blank.")


def _require_total(total: Any) -> None:
    if isinstance(total, bool) or not isinstance(total, (int, float)):
        raise ToolError(f"total_score must be a number 0-100, got {total!r}")
    if not 0 <= total <= 100:
        raise ToolError(f"total_score must be 0-100, got {total}")


def _require_breakdown(breakdown: Any) -> None:
    if not isinstance(breakdown, list) or not breakdown:
        raise ToolError("breakdown must be a non-empty list of {label, score} entries.")
    for entry in breakdown:
        if not isinstance(entry, dict) or not entry.get("label") or not str(entry["label"]).strip():
            raise ToolError("breakdown entries need a non-blank label.")
        score = entry.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise ToolError(f"breakdown entry {entry.get('label')!r} needs a numeric score.")


def _require_confirmation(confirmation: str | None, tool: str) -> None:
    if not confirmation or not confirmation.strip():
        raise ToolError(f"{tool} needs confirmation quoting the Hiring Manager's instruction.")


def _require_criteria(criteria: Any) -> None:
    if not isinstance(criteria, list) or not criteria:
        raise ToolError("criteria must be a non-empty list of {label, max_score} entries.")
    seen: set = set()
    total = 0.0
    for entry in criteria:
        if not isinstance(entry, dict) or not entry.get("label") or not str(entry["label"]).strip():
            raise ToolError("criteria entries need a non-blank label.")
        label = str(entry["label"]).strip()
        if label in seen:
            raise ToolError(f"criteria labels must be unique, got {label!r} twice.")
        seen.add(label)
        ceiling = entry.get("max_score")
        if isinstance(ceiling, bool) or not isinstance(ceiling, (int, float)) or ceiling <= 0:
            raise ToolError(f"criteria entry {label!r} needs a max_score number above 0.")
        total += ceiling
    if abs(total - 100) > 0.01:
        raise ToolError(f"criteria max_scores must sum to 100 (absolute 0-100 scale), got {total}.")


async def get_scoring_criteria(job_id: str) -> dict[str, Any]:
    """Read a job's active scoring rubric (see tool description)."""
    store = get_scores_store()
    try:
        return await store.get_criteria(job_id)
    except ScoresError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await store.aclose()


async def save_scoring_criteria(
    job_id: str,
    criteria: list,
    confirmation: str,
    created_by: str | None = None,
) -> dict[str, Any]:
    """Save the Hiring Manager's scoring rubric for a job (see tool description)."""
    _require_confirmation(confirmation, "save_scoring_criteria")
    _require_non_blank(job_id, "job_id")
    _require_non_blank(created_by, "created_by")
    _require_criteria(criteria)
    store = get_scores_store()
    try:
        return await store.save_criteria(job_id=job_id, criteria=criteria, created_by=created_by)
    except ScoresError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await store.aclose()


async def save_application_score(
    application_id: str,
    job_id: str,
    candidate_id: str,
    total_score: float,
    breakdown: list,
    criteria_version: int,
    rationale: str | None = None,
) -> dict[str, Any]:
    """Save an absolute assessment score (see tool description)."""
    _require_non_blank(application_id, "application_id")
    _require_non_blank(job_id, "job_id")
    _require_non_blank(candidate_id, "candidate_id")
    _require_total(total_score)
    _require_breakdown(breakdown)
    if isinstance(criteria_version, bool) or not isinstance(criteria_version, int) or criteria_version < 1:
        raise ToolError(f"criteria_version must be an integer 1 or more, got {criteria_version!r}")
    store = get_scores_store()
    try:
        return await store.save_score(
            application_id=application_id,
            job_id=job_id,
            candidate_id=candidate_id,
            total_score=total_score,
            breakdown=breakdown,
            criteria_version=criteria_version,
            rationale=rationale,
        )
    except ScoresError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await store.aclose()


async def get_application_score(application_id: str) -> dict[str, Any]:
    """Read one saved application score (see tool description)."""
    store = get_scores_store()
    try:
        return await store.get_score(application_id)
    except ScoresError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await store.aclose()


def _require_rounds(rounds: Any) -> None:
    if not isinstance(rounds, list) or not rounds:
        raise ToolError("rounds must be a non-empty ordered list of interview rounds.")
    seen: set = set()
    for entry in rounds:
        if not isinstance(entry, dict):
            raise ToolError("each round must be {name, window, pool}.")
        name = entry.get("name")
        if not name or not str(name).strip():
            raise ToolError("each round needs a non-blank name.")
        label = str(name).strip()
        if label in seen:
            raise ToolError(f"round names must be unique, got {label!r} twice.")
        seen.add(label)
        window = entry.get("window")
        if not isinstance(window, dict):
            raise ToolError(f"round {label!r} needs a window of {{start, end}} ISO dates.")
        try:
            start = date.fromisoformat(str(window.get("start")))
            end = date.fromisoformat(str(window.get("end")))
        except (TypeError, ValueError):
            raise ToolError(f"round {label!r} window must be ISO dates (YYYY-MM-DD).") from None
        if start > end:
            raise ToolError(f"round {label!r} window start must not be after end.")
        pool = entry.get("pool")
        if not isinstance(pool, list) or not pool:
            raise ToolError(f"round {label!r} needs a non-empty interviewer pool.")
        for person in pool:
            if not isinstance(person, dict):
                raise ToolError(f"round {label!r} pool entries must be {{name, email}}.")
            if not person.get("name") or not str(person["name"]).strip():
                raise ToolError(f"round {label!r} pool entries need a non-blank name.")
            email = person.get("email")
            parts = str(email).split("@") if isinstance(email, str) else []
            if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
                raise ToolError(f"round {label!r} pool entry {person.get('name')!r} needs a valid email.")


async def save_interview_config(
    job_id: str,
    rounds: list,
    confirmation: str,
    updated_by: str | None = None,
) -> dict[str, Any]:
    """Save the Hiring Manager's interview plan for a job (see tool description)."""
    _require_confirmation(confirmation, "save_interview_config")
    _require_non_blank(job_id, "job_id")
    _require_non_blank(updated_by, "updated_by")
    _require_rounds(rounds)
    store = get_scores_store()
    try:
        return await store.save_interview_config(job_id=job_id, rounds=rounds, updated_by=updated_by)
    except ScoresError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await store.aclose()


async def get_interview_config(job_id: str) -> dict[str, Any]:
    """Read a job's saved interview plan (see tool description)."""
    store = get_scores_store()
    try:
        return await store.get_interview_config(job_id)
    except ScoresError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await store.aclose()


async def get_application_resume(application_id: str) -> dict[str, Any]:
    """Read the resume URL for one application (see tool description)."""
    store = get_scores_store()
    try:
        return await store.get_resume(application_id)
    except ScoresError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await store.aclose()


async def list_top_applications(job_id: str, limit: int = 10) -> dict[str, Any]:
    """List a job's highest-scoring applications (see tool description)."""
    if not 1 <= limit <= 100:
        raise ToolError(f"limit must be 1-100, got {limit}")
    store = get_scores_store()
    try:
        return await store.list_top(job_id, limit)
    except ScoresError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await store.aclose()


def register_tools(mcp: Any, profile: str = "all") -> None:
    """Register score tools, narrowed by profile (all/read/write)."""
    specs = [
        (
            "get_scoring_criteria",
            "Read the active scoring rubric for a Harly job (version plus the "
            "criteria list of {label, max_score} entries the Hiring Manager "
            "designed; max_scores always sum to 100). Assessment: call this "
            "before scoring any application so the breakdown matches the "
            "current rubric version. Fails when the job has no active criteria "
            "yet — tell the Hiring Manager to design the rubric first.",
            get_scoring_criteria,
        ),
        (
            "save_scoring_criteria",
            "Save the Hiring Manager's scoring rubric for a Harly job, "
            "creating a new version (old versions deactivate; previously "
            "saved scores keep their old criteria_version). Required: job_id "
            "(resolve a job title first with list_jobs/get_job on the ATS "
            "connection), criteria (non-empty list of {label, max_score} with "
            "unique labels and max_scores summing to 100 for the absolute "
            "0-100 scale), confirmation quoting the Hiring Manager's rubric "
            "instruction. Optional: created_by. Ask the Hiring Manager for "
            "dimensions and weights when missing — never invent the rubric. "
            "Recruiter-agent only (read profile).",
            save_scoring_criteria,
        ),
        (
            "save_application_score",
            "Save an absolute assessment score (0-100) for one Harly application. "
            "Required: application_id, job_id, candidate_id, total_score, "
            "breakdown (non-empty list of {label, score} aligned with the active "
            "rubric), criteria_version (from get_scoring_criteria). Optional: "
            "rationale (short justification). Re-scoring overwrites the previous "
            "row. Assessment-agent only (write profile).",
            save_application_score,
        ),
        (
            "get_application_score",
            "Read one saved application score by Harly application ID: total, "
            "breakdown, criteria version, rationale. Use to check whether an "
            "application was already scored before re-scoring it.",
            get_application_score,
        ),
        (
            "list_top_applications",
            "Answer 'top N candidates for this job'. Takes job_id (resolve a "
            "job title to its ID first with list_jobs on the ATS connection) "
            "and limit 1-100 (default 10). Returns the highest-scoring "
            "applications ordered by total descending, each with application "
            "and candidate IDs, total, breakdown, rationale, and criteria "
            "version. Unscored applications never appear here — say so when "
            "the list is short. Enrich names via get_application/get_candidate "
            "on the ATS connection, present rank plus total plus one line of "
            "rationale each, and offer move/reject next steps.",
            list_top_applications,
        ),
        (
            "get_application_resume",
            "Read the public resume URL for one Harly application (resolved by "
            "the backend pipeline, not by agents). Assessment: call this before "
            "scoring and fetch the file yourself — when it fails, fall back to "
            "the candidate profile and note the gap in the rationale.",
            get_application_resume,
        ),
        (
            "save_interview_config",
            "Save the Hiring Manager's interview plan for a Harly job "
            "(overwrites any previous plan). Required: job_id (resolve a job "
            "title first with list_jobs/get_job on the ATS connection), rounds "
            "(ordered non-empty list of {name, window: {start, end} ISO dates "
            "with start on/before end, pool: non-empty list of {name, email}}), "
            "confirmation quoting the Hiring Manager's interview-plan "
            "instruction. Optional: updated_by. Ask the Hiring Manager for "
            "rounds, windows, and pools when missing — never invent "
            "interviewers or dates. Recruiter-agent only (read profile).",
            save_interview_config,
        ),
        (
            "get_interview_config",
            "Read a job's saved interview plan (rounds with date windows and "
            "interviewer pools). Use before moving an application into an "
            "interview-kind stage: when this fails (no plan saved yet), ask "
            "the Hiring Manager for the rounds, windows, and pools and save "
            "them first.",
            get_interview_config,
        ),
    ]
    if profile == "all":
        wanted = None
    elif profile == "write":
        wanted = {
            "get_scoring_criteria",
            "save_application_score",
            "get_application_score",
            "get_application_resume",
        }
    elif profile == "read":
        # Recruiter: reads plus HM-plan authoring (HM-quoted confirmation).
        # Score writes stay assessment-only; criteria and interview plans
        # stay recruiter-only.
        wanted = {
            "get_scoring_criteria",
            "save_scoring_criteria",
            "get_application_score",
            "list_top_applications",
            "get_application_resume",
            "save_interview_config",
            "get_interview_config",
        }
    else:
        raise ValueError(f"unknown db-mcp profile {profile!r}: expected all, read, or write")
    for name, description, fn in specs:
        if wanted is None or name in wanted:
            mcp.tool(name=name, description=description)(fn)
