"""Job tools for the Recruiter Agent (M2.1a: reads; writes follow in M2.1b/c)."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

from services.harly import HarlyError, get_harly_client

_JOB_STATUSES = ("draft", "open", "closed")


async def list_jobs(
    status: str | None = None, limit: int = 20, cursor: str | None = None
) -> dict[str, Any]:
    """List Harly jobs with cursor pagination (see tool description)."""
    if status is not None and status not in _JOB_STATUSES:
        raise ToolError(f"unknown status {status!r}: expected one of {', '.join(_JOB_STATUSES)}")
    if not 1 <= limit <= 100:
        raise ToolError(f"limit must be 1-100, got {limit}")
    client = get_harly_client()
    try:
        return await client.list_jobs(status=status, limit=limit, cursor=cursor)
    except HarlyError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await client.aclose()


async def get_job(job_id: str) -> dict[str, Any]:
    """Get full details of one Harly job (see tool description)."""
    client = get_harly_client()
    try:
        return await client.get_job(job_id)
    except HarlyError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await client.aclose()


async def list_job_stages(job_id: str) -> dict[str, Any]:
    """List a job's ordered pipeline stages (see tool description)."""
    client = get_harly_client()
    try:
        return await client.list_job_stages(job_id)
    except HarlyError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await client.aclose()


def register_tools(mcp: Any) -> None:
    """Register job tools on an MCPServer (or compatible stub in tests)."""
    mcp.tool(
        name="list_jobs",
        description=(
            "List jobs in the Harly ATS, optionally filtered by status "
            "(draft, open, closed). Results are cursor-paginated: pass the "
            "returned next_cursor to fetch the next page while has_more is true. "
            "Use to report the hiring pipeline or find a job's ID."
        ),
    )(list_jobs)
    mcp.tool(
        name="get_job",
        description=(
            "Get full details of one Harly job by ID: title, description, "
            "requirements, location, employment/workplace type, salary, keywords, "
            "status, timestamps. Use before describing a role or acting on it."
        ),
    )(get_job)
    mcp.tool(
        name="list_job_stages",
        description=(
            "List the ordered pipeline stages of a Harly job (id, name, order, "
            "kind such as applied/screening/interview/offer/hired). Use to explain "
            "the hiring process or to resolve the stage ID a later application "
            "move needs."
        ),
    )(list_job_stages)
