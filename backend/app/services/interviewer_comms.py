"""Proactive interviewer DMs: resolve Slack IDs by email, open, and post.

The recruiter flow only ever *replies* to inbound DMs; the scheduler starts
conversations, so it resolves workspace members by email on demand instead
of keeping a parallel directory. Requires the `users:read.email` scope on
top of the chat scopes the bridge already needs.
"""

from __future__ import annotations

from slack_sdk.errors import SlackApiError

_SLACK_MAX_TEXT = 39_000  # mirrors the reply cap in app.api.slack


class CommsError(Exception):
    """User-safe Slack comms failure (never includes tokens or API internals)."""


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
    body = text if len(text) <= _SLACK_MAX_TEXT else text[:_SLACK_MAX_TEXT] + "… [truncated]"
    try:
        opened = await slack.conversations_open(users=user_id)
        channel = ((opened or {}).get("channel") or {}).get("id")
        if not channel:
            raise CommsError(f"could not open a DM with {email}")
        await slack.chat_postMessage(channel=channel, text=body)
    except SlackApiError as exc:
        code = (exc.response or {}).get("error", "")
        raise CommsError(f"Slack DM to {email} failed: {code or 'unknown error'}") from exc
    return {"slack_user_id": user_id, "channel": channel}
