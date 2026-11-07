"""Comms MCP server definition (mounted by app.main, never run standalone)."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from app.mcp.tools import send_slack_message


def health() -> str:
    """Health check. Returns 'ok' when the server is up (no dependency probe)."""
    return "ok"


def create_comms_mcp() -> MCPServer:
    """Build the comms MCP server (single consumer: the scheduler agent)."""
    mcp: Any = MCPServer(
        name="acmetech-comms",
        title="AcmeTech Comms",
        description="Bridge-owned messaging for the scheduler agent.",
        version="0.1.0",
    )
    mcp.tool(
        name="health",
        description="Health check. Returns 'ok' when the server is up (no dependency probe).",
    )(health)
    mcp.tool(
        name="send_slack_message",
        description=(
            "DM a workspace member by email (resolves the Slack user, opens "
            "the DM, posts). Required: interviewer_email (must belong to a "
            "real workspace member — demo addresses fail lookup), text "
            "(the message; keep it short and actionable). Replies arrive "
            "back in this thread automatically — say that follow-ups are "
            "welcome. Fails loudly on unknown emails."
        ),
    )(send_slack_message)
    return mcp
