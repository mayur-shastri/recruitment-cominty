"""Candidate email orchestration: token reply-tos, send flow, body extract.

Outbound mail carries a per-coordination `sched-<token>@` reply-to under
the receiving domain; inbound replies route back to the scheduler thread
through the stored token. Tokens are random — no ID-charset assumptions.
"""

from __future__ import annotations

import asyncio
import re
import secrets
from datetime import timezone
from typing import Any

from sqlalchemy import select

from recruitment_db.models import CalendarEvent, CandidateThread, SchedulerTrigger

_REPLY_PREFIX = "sched-"
_STRIP_TAGS = re.compile(r"<[^>]+>")
_UTC = timezone.utc
# The trigger row lands just after the run starts; the agent's first send can
# theoretically beat the commit, so poll briefly before reporting it missing.
_TRIGGER_RETRIES = 5
_TRIGGER_RETRY_DELAY_S = 0.5


class CandidateCommsError(Exception):
    """User-safe candidate-email failure (never includes keys or API internals)."""


def build_reply_to(token: str, domain: str) -> str:
    return f"{_REPLY_PREFIX}{token}@{domain}"


def parse_reply_token(address: str) -> str | None:
    """Token from a reply-to address, or None when it isn't one of ours."""
    local = address.split("@", 1)[0] if "@" in address else ""
    if not local.startswith(_REPLY_PREFIX):
        return None
    token = local[len(_REPLY_PREFIX) :]
    return token or None


def extract_reply_text(email: dict[str, Any]) -> str:
    """Best-effort reply body: text part, else tag-stripped HTML, else empty."""
    text = (email.get("text") or "").strip()
    if text:
        return text
    html = email.get("html") or ""
    return _STRIP_TAGS.sub("", html).replace("&nbsp;", " ").strip()


def _format_when(starts_at) -> str:
    # SQLite drops tzinfo on read; every writer stores UTC-aware values.
    if getattr(starts_at, "tzinfo", None) is None:
        starts_at = starts_at.replace(tzinfo=_UTC)
    return starts_at.astimezone(_UTC).strftime("%b %d, %H:%M UTC")


def append_interview_links(text: str, interviews: list) -> str:
    """Append join links for booked interviews (deduped, skips sent ones).

    Panel rows share one room, so group by link; links the agent already
    pasted stay untouched. No interviews (or nothing new) returns text as-is.
    """
    fresh: dict[str, str] = {}
    for row in interviews:
        url = row.meeting_url
        if not url or url in text or url in fresh:
            continue
        label = row.title or "Interview"
        fresh[url] = f"{label} — {_format_when(row.starts_at)}: {url}"
    if not fresh:
        return text
    lines = "\n".join(fresh.values())
    return f"{text.rstrip()}\n\nJoin your interview here:\n{lines}"


async def interviews_for_application(session_factory, application_id: str) -> list:
    """Booked interviews with links for one application, earliest first."""
    async with session_factory() as session:
        return (
            await session.execute(
                select(CalendarEvent)
                .where(
                    CalendarEvent.kind == "interview",
                    CalendarEvent.application_id == application_id,
                    CalendarEvent.meeting_url.is_not(None),
                )
                .order_by(CalendarEvent.starts_at)
            )
        ).scalars().all()


async def send_candidate_email(
    resend,
    session_factory,
    *,
    from_email: str,
    domain: str,
    to_email: str,
    subject: str,
    text: str,
    application_id: str,
    stage_id: str,
) -> dict[str, str]:
    """Send via a fresh reply-to token. Requires an open coordination.

    The thread row is recorded only after a successful send, so failed
    sends leave nothing behind and the agent can retry cleanly.
    """
    trigger = None
    for _ in range(_TRIGGER_RETRIES):
        async with session_factory() as session:
            trigger = (
                await session.execute(
                    select(SchedulerTrigger).where(
                        SchedulerTrigger.application_id == application_id,
                        SchedulerTrigger.stage_id == stage_id,
                    )
                )
            ).scalar_one_or_none()
        if trigger is not None:
            break
        await asyncio.sleep(_TRIGGER_RETRY_DELAY_S)
    if trigger is None:
        raise CandidateCommsError(
            f"no open coordination for application {application_id} @ {stage_id}"
        )
    thread_id = trigger.cominty_thread_id
    token = secrets.token_urlsafe(9)
    reply_to = build_reply_to(token, domain)
    interviews = await interviews_for_application(session_factory, application_id)
    email_id = await resend.send_email(
        from_email=from_email,
        to_email=to_email,
        subject=subject,
        text=append_interview_links(text, interviews),
        reply_to=reply_to,
    )
    async with session_factory() as session:
        session.add(
            CandidateThread(
                token=token,
                application_id=application_id,
                stage_id=stage_id,
                cominty_thread_id=thread_id,
                candidate_email=to_email,
            )
        )
        await session.commit()
    return {"email_id": email_id, "reply_to": reply_to}
