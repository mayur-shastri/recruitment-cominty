"""Slack Events API endpoint: verify, dedupe, ack fast, process in background."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.integrations.slack.verification import verify_slack_signature
from recruitment_db.models import SlackEvent
from app.services.cominty import ComintyService, ComintyServiceError
from app.services.conversation import get_thread, is_hiring_manager, record_thread

logger = logging.getLogger(__name__)

router = APIRouter()

_SLACK_MAX_TEXT = 39_000


@dataclass
class Runtime:
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    cominty: ComintyService
    cominty_user_id: str
    slack: Any  # AsyncWebClient (duck-typed for tests)
    signing_secret: str


def get_runtime(request: Request) -> Runtime:
    return request.app.state.runtime


@router.post("/slack/events")
async def slack_events(
    request: Request, background: BackgroundTasks, runtime: Runtime = Depends(get_runtime)
):
    raw = await request.body()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return Response(status_code=400)

    signature = request.headers.get("x-slack-signature", "")
    timestamp = request.headers.get("x-slack-request-timestamp", "")
    if not verify_slack_signature(
        signing_secret=runtime.signing_secret, timestamp=timestamp, body=raw, signature=signature
    ):
        return Response(status_code=401)

    if payload.get("type") == "url_verification":
        challenge = payload.get("challenge")
        if not challenge:
            return Response(status_code=400)
        return {"challenge": challenge}

    if payload.get("type") != "event_callback":
        logger.info("ignoring slack payload type=%s", payload.get("type"))
        return {"ok": True}

    event_id = payload.get("event_id")
    event = payload.get("event") or {}
    if not event_id or not _is_dm_user_message(event):
        logger.info(
            "ignoring slack event: event_id=%s type=%s subtype=%s channel_type=%s has_bot=%s has_user=%s",
            event_id,
            event.get("type"),
            event.get("subtype"),
            event.get("channel_type"),
            "bot_id" in event,
            bool(event.get("user")),
        )
        return {"ok": True}

    async with runtime.session_factory() as session:
        session.add(SlackEvent(event_id=event_id))
        try:
            await session.commit()
        except IntegrityError:
            logger.info("deduped slack event %s", event_id)
            return {"ok": True, "deduped": True}

    background.add_task(
        _handle_dm,
        runtime,
        channel=event["channel"],
        user=event["user"],
        text=event.get("text", ""),
        event_id=event_id,
    )
    return {"ok": True}


def _is_dm_user_message(event: dict) -> bool:
    return (
        event.get("type") == "message"
        and event.get("channel_type") == "im"
        and event.get("subtype") is None
        and "bot_id" not in event
        and bool(event.get("user"))
        and bool(event.get("channel"))
    )


async def _handle_dm(runtime: Runtime, *, channel: str, user: str, text: str, event_id: str) -> None:
    if not text.strip():
        await runtime.slack.chat_postMessage(channel=channel, text="I can only work with text messages for now.")
        return
    async with runtime.session_factory() as session:
        if not await is_hiring_manager(session, user):
            logger.info("ignoring slack event %s: user is not a hiring manager", event_id)
            return
        existing = await get_thread(session, user)
        try:
            if existing is None:
                thread_id, reply = await runtime.cominty.start_thread(text, name=f"slack:{user}")
                await record_thread(
                    session,
                    slack_user_id=user,
                    cominty_user_id=runtime.cominty_user_id,
                    cominty_thread_id=thread_id,
                )
            else:
                reply = await runtime.cominty.send_message(existing.cominty_thread_id, text)
        except ComintyServiceError as exc:
            logger.exception("cominty request failed (transient=%s)", exc.transient)
            reply = "Sorry — I couldn't reach the recruiting agent just now. Please try again in a bit."
    reply = reply.strip() or "(empty reply)"
    if len(reply) > _SLACK_MAX_TEXT:
        reply = reply[:_SLACK_MAX_TEXT] + "… [truncated]"
    await runtime.slack.chat_postMessage(channel=channel, text=reply)
