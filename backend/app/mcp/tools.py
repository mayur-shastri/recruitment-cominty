"""Comms tools: agent-facing messaging over bridge-owned integrations.

Slack credentials stay in the bridge; agents reach them only through these
tools (one MCP connection on the scheduler thread).
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver.exceptions import ToolError
from slack_sdk.web.async_client import AsyncWebClient

from app.config import get_settings
from app.services.interviewer_comms import CommsError, post_interviewer_dm


def get_slack_client() -> AsyncWebClient:
    """Build a client from settings. Tools call this per invocation.

    AsyncWebClient holds no shared session (one httpx client per request),
    so per-call construction leaks nothing and closes nothing.
    """
    token = get_settings().slack_bot_token
    if not token:
        raise CommsError("SLACK_BOT_TOKEN is not configured")
    return AsyncWebClient(token=token)


async def send_slack_message(interviewer_email: str, text: str) -> dict[str, Any]:
    """DM a workspace member by email (see tool description)."""
    if not interviewer_email or not interviewer_email.strip():
        raise ToolError("interviewer_email must not be blank.")
    if not text or not text.strip():
        raise ToolError("text must not be blank.")
    try:
        return await post_interviewer_dm(get_slack_client(), interviewer_email.strip(), text)
    except CommsError as exc:
        raise ToolError(str(exc)) from exc
