"""AcmeTech mock interviewer calendar: week-view UI plus scheduler MCP tools.

One process, two surfaces: FastAPI serves the demo UI and its JSON API,
and the stateless Streamable HTTP MCP app mounts underneath (its /mcp
route only matches after the UI routes, so both coexist).

Run locally (from calendar-mock/):  python server.py
UI:                                 http://127.0.0.1:8004/
MCP endpoint:                       http://127.0.0.1:8004/mcp
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from mcp.server.mcpserver import MCPServer

import ui
from config import get_calendar_settings
from tools.calendar import register_tools as register_calendar_tools


def health() -> str:
    """Health check. Returns 'ok' when the server is up (no DB probe)."""
    return "ok"


def create_mcp() -> MCPServer:
    """Build the MCP server (single consumer: the scheduler agent)."""
    mcp: Any = MCPServer(
        name="acmetech-calendar",
        title="AcmeTech Mock Calendar",
        description="Mock interviewer availability and booking.",
        version="0.1.0",
    )
    mcp.tool(
        name="health",
        description="Health check. Returns 'ok' when the server is up (no DB probe).",
    )(health)
    register_calendar_tools(mcp)
    return mcp


# Default surface for direct imports and tests; production goes through main().
mcp = create_mcp()


def create_app(host: str = "127.0.0.1") -> FastAPI:
    """FastAPI app with the UI routes first and the MCP app mounted last.

    `host` feeds the MCP factory's DNS-rebinding default: loopback keeps
    protection on, anything else (e.g. 0.0.0.0 in containers) disables it —
    the same behavior as the standalone .run() servers.
    """
    mcp_app = mcp.streamable_http_app(stateless_http=True, host=host)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Mounted apps don't run their own lifespan; without this the MCP
        # session manager's task group never initializes and /mcp 500s.
        async with mcp_app.router.lifespan_context(mcp_app):
            yield

    app = FastAPI(title="AcmeTech Mock Calendar", lifespan=lifespan)
    app.include_router(ui.router)
    app.mount("/", mcp_app)
    return app


def main() -> None:
    import uvicorn

    settings = get_calendar_settings()
    uvicorn.run(
        create_app(host=settings.calendar_host),
        host=settings.calendar_host,
        port=settings.calendar_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
