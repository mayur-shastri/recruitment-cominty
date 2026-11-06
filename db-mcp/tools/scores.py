"""Score tools: reads for the Recruiter Agent, writes for the Assessment Agent.

No confirmation quoting here (unlike the ATS tools): the assessment agent is
headless — webhook-triggered, with no Hiring Manager instruction to quote.
Least privilege comes from connection profiles instead: the assessment agent
gets the `write` profile, the recruiter gets `read`, and only dev runs `all`.
"""

from __future__ import annotations

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


async def get_scoring_criteria(job_id: str) -> dict[str, Any]:
    """Read a job's active scoring rubric (see tool description)."""
    store = get_scores_store()
    try:
        return await store.get_criteria(job_id)
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
            "designed). Assessment: call this before scoring any application so "
            "the breakdown matches the current rubric version. Fails when the "
            "job has no active criteria yet.",
            get_scoring_criteria,
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
            "List a job's highest-scoring applications, ordered by total "
            "descending. Takes job_id (resolve a job title to its ID first with "
            "list_jobs on the ATS connection) and limit 1-100 (default 10). "
            "Returns each application's id, candidate, total, breakdown, and "
            "criteria version. Unscored applications never appear here.",
            list_top_applications,
        ),
    ]
    if profile == "all":
        wanted = None
    elif profile == "write":
        wanted = {"get_scoring_criteria", "save_application_score", "get_application_score"}
    elif profile == "read":
        wanted = {"get_scoring_criteria", "get_application_score", "list_top_applications"}
    else:
        raise ValueError(f"unknown db-mcp profile {profile!r}: expected all, read, or write")
    for name, description, fn in specs:
        if wanted is None or name in wanted:
            mcp.tool(name=name, description=description)(fn)
