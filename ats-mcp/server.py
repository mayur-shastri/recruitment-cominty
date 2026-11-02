"""AcmeTech ATS MCP server: recruitment tools for Cominty agents (M2: health only).

Stateless Streamable HTTP (latest MCP spec): every request stands alone, no
server-side session state. All recruitment state lives in Harly/Postgres.

Run locally (from ats-mcp/):  python server.py
MCP endpoint:                 http://127.0.0.1:8002/mcp
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from config import get_mcp_settings

mcp = MCPServer(
    name="acmetech-ats",
    title="AcmeTech ATS",
    description="Recruitment operations over the Harly ATS.",
    version="0.1.0",
)


@mcp.tool(
    name="health",
    description="Health check. Returns 'ok' when the ATS integration is reachable.",
)
def health() -> str:
    """Health check. Returns 'ok' when the ATS integration is reachable."""
    return "ok"


def main() -> None:
    settings = get_mcp_settings()
    mcp.run(
        transport="streamable-http",
        host=settings.mcp_host,
        port=settings.mcp_port,
        stateless_http=True,
    )


if __name__ == "__main__":
    main()
