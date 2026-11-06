"""Application tools (M2.2a: reads; M2.2b: decisions; M3.3: scorecard mirror).

Decision tools require HM-quoting confirmation. create_scorecard is the
exception: it serves headless assessment runs, which have no Hiring Manager
instruction to quote (same rationale as the db-mcp save tool).
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

from services.harly import HarlyError, get_harly_client


def _require_non_blank(value: str | None, field: str) -> None:
    if value is not None and not value.strip():
        raise ToolError(f"{field} must not be blank.")


def _require_confirmation(confirmation: str, tool: str) -> None:
    if not confirmation or not confirmation.strip():
        raise ToolError(f"{tool} needs confirmation quoting the Hiring Manager's instruction.")


async def list_applications(
    job_id: str | None = None,
    status: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> dict[str, Any]:
    """List Harly applications with cursor pagination (see tool description)."""
    if status is not None and not status.strip():
        raise ToolError("status must not be blank.")
    if not 1 <= limit <= 100:
        raise ToolError(f"limit must be 1-100, got {limit}")
    client = get_harly_client()
    try:
        return await client.list_applications(
            job_id=job_id, status=status, limit=limit, cursor=cursor
        )
    except HarlyError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await client.aclose()


async def get_application(application_id: str) -> dict[str, Any]:
    """Get full details of one Harly application (see tool description)."""
    client = get_harly_client()
    try:
        return await client.get_application(application_id)
    except HarlyError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await client.aclose()


async def move_application(application_id: str, to_stage_id: str, confirmation: str) -> dict[str, Any]:
    """Move a Harly application to another pipeline stage (see tool description)."""
    _require_confirmation(confirmation, "move_application")
    _require_non_blank(application_id, "application_id")
    _require_non_blank(to_stage_id, "to_stage_id")
    client = get_harly_client()
    try:
        return await client.move_application(application_id, to_stage_id)
    except HarlyError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await client.aclose()


async def reject_application(application_id: str, confirmation: str) -> dict[str, Any]:
    """Reject a Harly application (see tool description)."""
    _require_confirmation(confirmation, "reject_application")
    client = get_harly_client()
    try:
        return await client.reject_application(application_id)
    except HarlyError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await client.aclose()


async def hire_application(application_id: str, confirmation: str) -> dict[str, Any]:
    """Hire a Harly application (see tool description)."""
    _require_confirmation(confirmation, "hire_application")
    client = get_harly_client()
    try:
        return await client.hire_application(application_id)
    except HarlyError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await client.aclose()


async def create_scorecard(
    candidate_id: str,
    rating: str,
    application_id: str | None = None,
    comment: str | None = None,
    criteria: list | None = None,
) -> dict[str, Any]:
    """Mirror an assessment score into Harly (see tool description)."""
    _require_non_blank(candidate_id, "candidate_id")
    if rating not in ("strong", "mixed", "weak"):
        raise ToolError(f"unknown rating {rating!r}: expected strong, mixed, or weak")
    if criteria is not None:
        for entry in criteria:
            if not isinstance(entry, dict) or not str(entry.get("label", "")).strip():
                raise ToolError("criteria entries need a non-blank label.")
            score = entry.get("score")
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                raise ToolError("criteria entries need a numeric score.")
    kwargs: dict[str, Any] = {}
    if application_id is not None:
        kwargs["application_id"] = application_id
    if comment is not None:
        kwargs["comment"] = comment
    if criteria is not None:
        kwargs["criteria"] = criteria
    client = get_harly_client()
    try:
        return await client.create_scorecard(candidate_id, rating, **kwargs)
    except HarlyError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await client.aclose()


def register_tools(mcp: Any) -> None:
    """Register application tools on the MCP server."""
    mcp.tool(
        name="list_applications",
        description=(
            "List applications in the Harly ATS with cursor pagination. Optional "
            "filters: job_id (UUID of the job, for per-role pipelines), status "
            "(free-form Harly status string). limit 1-100, default 20; pass "
            "next_cursor as cursor for the next page. Returns applications (each "
            "with id, candidateId, jobId, currentStageId, status) plus next_cursor "
            "and has_more. Use with list_job_stages to name the stages."
        ),
    )(list_applications)
    mcp.tool(
        name="get_application",
        description=(
            "Get full details of one Harly application by ID: candidate, job, "
            "current stage, status, source, and applied date."
        ),
    )(get_application)
    mcp.tool(
        name="move_application",
        description=(
            "Move a Harly application to another pipeline stage of its job. "
            "Resolve to_stage_id first with list_job_stages (match the stage "
            "name the Hiring Manager asked for). Requires confirmation: quote "
            "the Hiring Manager's move instruction. Returns the moved application."
        ),
    )(move_application)
    mcp.tool(
        name="reject_application",
        description=(
            "Reject a Harly application (terminal: the candidate leaves the "
            "pipeline). Requires confirmation: quote the Hiring Manager's "
            "rejection instruction. Returns the rejected application."
        ),
    )(reject_application)
    mcp.tool(
        name="hire_application",
        description=(
            "Hire a Harly application (terminal: marks the candidate hired). "
            "Requires confirmation: quote the Hiring Manager's hiring "
            "instruction. Returns the hired application."
        ),
    )(hire_application)
    mcp.tool(
        name="create_scorecard",
        description=(
            "Record an assessment scorecard on a Harly candidate (mirror of the "
            "Postgres score). Assessment-agent only: call after "
            "save_application_score with the same breakdown as criteria "
            "({label, score} entries), the total and rubric version in comment, "
            "and rating mapped from the total (strong/mixed/weak). No "
            "confirmation: headless scoring runs have no Hiring Manager "
            "instruction to quote. Returns the created scorecard."
        ),
    )(create_scorecard)
