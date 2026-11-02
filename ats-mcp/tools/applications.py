"""Application tools for the Recruiter Agent (M2.2a: reads; decisions follow in M2.2b)."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

from services.harly import HarlyError, get_harly_client


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
