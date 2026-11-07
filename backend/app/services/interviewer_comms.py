"""Proactive interviewer DMs: stored Slack ID first, email lookup fallback.

The recruiter flow only ever *replies* to inbound DMs; the scheduler starts
conversations. When the admin stored a member ID on the interviewer row, DMs
post straight to it (chat:write only — no open, no lookup). Otherwise the
legacy path resolves by email (needs the `users:read.email` scope) and opens
the DM (needs `im:write`; falls back to a direct post without it).
"""

from __future__ import annotations

from slack_sdk.errors import SlackApiError

from app.services.slack_format import to_slack_mrkdwn
from recruitment_db.models import Interviewer

_SLACK_MAX_TEXT = 39_000  # mirrors the reply cap in app.api.slack


class CommsError(Exception):
    """User-safe Slack comms failure (never includes tokens or API internals)."""


async def resolve_stored_slack_id(session_factory, email: str) -> str | None:
    """Admin-set Slack member ID for an interviewer email, if any."""
    async with session_factory() as session:
        row = await session.get(Interviewer, email)
        return row.slack_user_id if row and row.slack_user_id else None


def _truncate(text: str) -> str:
    return text if len(text) <= _SLACK_MAX_TEXT else text[:_SLACK_MAX_TEXT] + "… [truncated]"


async def post_dm_by_id(slack, user_id: str, text: str) -> dict[str, str]:
    """Post straight to a user ID (Slack auto-opens the DM; chat:write only)."""
    if not text or not text.strip():
        raise CommsError("message text must not be blank.")
    try:
        resp = await slack.chat_postMessage(channel=user_id, text=to_slack_mrkdwn(_truncate(text)))
    except SlackApiError as exc:
        code = (exc.response or {}).get("error", "")
        raise CommsError(f"Slack DM failed: {code or 'unknown error'}") from exc
    return {"slack_user_id": user_id, "channel": (resp or {}).get("channel") or user_id}


async def resolve_slack_id(slack, email: str) -> str:
    """Workspace user ID for an email. Raises CommsError when unresolvable."""
    try:
        resp = await slack.users_lookupByEmail(email=email)
    except SlackApiError as exc:
        code = (exc.response or {}).get("error", "")
        if code == "users_not_found":
            raise CommsError(f"no Slack user for {email}") from exc
        if code == "missing_scope":
            raise CommsError(
                "Slack app is missing the users:read.email scope; cannot resolve "
                f"{email} to a workspace member"
            ) from exc
        raise CommsError(f"Slack lookup failed for {email}: {code or 'unknown error'}") from exc
    user_id = ((resp or {}).get("user") or {}).get("id")
    if not user_id:
        raise CommsError(f"no Slack user for {email}")
    return user_id


async def post_interviewer_dm(slack, email: str, text: str) -> dict[str, str]:
    """Open (or reuse) a DM with the email's owner and post. Returns IDs."""
    if not text or not text.strip():
        raise CommsError("message text must not be blank.")
    user_id = await resolve_slack_id(slack, email)
    try:
        opened = await slack.conversations_open(users=user_id)
    except SlackApiError as exc:
        if (exc.response or {}).get("error") == "missing_scope":
            return await post_dm_by_id(slack, user_id, text)
        code = (exc.response or {}).get("error", "")
        raise CommsError(f"Slack DM to {email} failed: {code or 'unknown error'}") from exc
    channel = ((opened or {}).get("channel") or {}).get("id")
    if not channel:
        raise CommsError(f"could not open a DM with {email}")
    try:
        await slack.chat_postMessage(channel=channel, text=to_slack_mrkdwn(_truncate(text)))
    except SlackApiError as exc:
        code = (exc.response or {}).get("error", "")
        raise CommsError(f"Slack DM to {email} failed: {code or 'unknown error'}") from exc
    return {"slack_user_id": user_id, "channel": channel}
