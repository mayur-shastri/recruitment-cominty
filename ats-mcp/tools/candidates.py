"""Candidate tools for the Recruiter Agent (M2.2a: reads)."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

from services.harly import HarlyError, get_harly_client


async def get_candidate(candidate_id: str) -> dict[str, Any]:
    """Get one Harly candidate by ID (see tool description)."""
    client = get_harly_client()
    try:
        return await client.get_candidate(candidate_id)
    except HarlyError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await client.aclose()


def register_tools(mcp: Any) -> None:
    """Register candidate tools on the MCP server."""
    mcp.tool(
        name="get_candidate",
        description=(
            "Get one Harly candidate by ID: name, email, phone, location, "
            "headline, summary, profile URLs, and education/experience entries."
        ),
    )(get_candidate)
