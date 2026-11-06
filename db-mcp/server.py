"""AcmeTech scores MCP server: assessment storage for Cominty agents.

Stateless Streamable HTTP (latest MCP spec): every request stands alone, no
server-side session state. Each tool call opens and closes its own short-lived
DB engine; all state lives in Postgres.

Run locally (from db-mcp/):  python server.py
MCP endpoint:                 http://127.0.0.1:8003/mcp
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from config import get_db_mcp_settings
from tools.scores import register_tools as register_score_tools


def health() -> str:
    """Health check. Returns 'ok' when the server is up (no DB probe)."""
    return "ok"


def create_server(profile: str = "all") -> MCPServer:
    """Build the MCP server with tools narrowed by profile (all/read/write)."""
    mcp: Any = MCPServer(
        name="acmetech-dbmcp",
        title="AcmeTech Scores",
        description="Assessment scores and rubrics over Postgres.",
        version="0.1.0",
    )
    mcp.tool(
        name="health",
        description="Health check. Returns 'ok' when the server is up (no DB probe).",
    )(health)
    register_score_tools(mcp, profile)
    return mcp


# Default surface for direct imports and tests; production goes through main().
mcp = create_server()


def main() -> None:
    settings = get_db_mcp_settings()
    create_server(settings.db_mcp_profile).run(
        transport="streamable-http",
        host=settings.db_mcp_host,
        port=settings.db_mcp_port,
        stateless_http=True,
    )


if __name__ == "__main__":
    main()
