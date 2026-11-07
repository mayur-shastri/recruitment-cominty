"""Comms MCP server definition (mounted by app.main, never run standalone)."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from app.mcp.tools import send_email, send_slack_message


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
    mcp.tool(
        name="send_email",
        description=(
            "Email a candidate about their interview (negotiation welcome). "
            "Required: to_email (the candidate's address from the trigger), "
            "subject, text (plain text; propose 2-3 concrete slots with "
            "dates, times, and timezone), application_id, stage_id. Each "
            "send gets a unique reply-to, so the candidate's replies route "
            "back into this thread automatically — invite a reply with what "
            "works. A coordination for the application+stage must already "
            "exist (the trigger creates it); fails loudly otherwise."
        ),
    )(send_email)
    return mcp
