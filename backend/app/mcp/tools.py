"""Comms tools: agent-facing messaging over bridge-owned integrations.

Slack credentials stay in the bridge; agents reach them only through these
tools (one MCP connection on the scheduler thread).
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver.exceptions import ToolError
from slack_sdk.web.async_client import AsyncWebClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.integrations.resend.client import ResendClient, ResendError
from app.services import candidate_comms
from app.services.candidate_comms import CandidateCommsError
from app.services.interviewer_comms import CommsError, post_interviewer_dm
from recruitment_db.urls import to_async_database_url


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


async def send_email(
    to_email: str, subject: str, text: str, application_id: str, stage_id: str
) -> dict[str, Any]:
    """Email a candidate with an auto-routing reply-to (see tool description)."""
    for field, value in [
        ("to_email", to_email),
        ("subject", subject),
        ("text", text),
        ("application_id", application_id),
        ("stage_id", stage_id),
    ]:
        if not value or not value.strip():
            raise ToolError(f"{field} must not be blank.")
    settings = get_settings()
    if not (
        settings.resend_api_key
        and settings.resend_from_email
        and settings.resend_receiving_domain
        and settings.database_url
    ):
        raise ToolError("candidate email is not configured")
    database_url = settings.database_url
    if database_url.split(":", 1)[0] in {"postgres", "postgresql", "postgresql+asyncpg"}:
        database_url = to_async_database_url(database_url)
    engine = create_async_engine(database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        return await candidate_comms.send_candidate_email(
            ResendClient(settings.resend_api_key),
            factory,
            from_email=settings.resend_from_email,
            domain=settings.resend_receiving_domain,
            to_email=to_email.strip(),
            subject=subject.strip(),
            text=text,
            application_id=application_id.strip(),
            stage_id=stage_id.strip(),
        )
    except (CandidateCommsError, ResendError) as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await engine.dispose()
