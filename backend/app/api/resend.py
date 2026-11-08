"""Resend inbound endpoint: verify (Svix), dedupe, ack fast, route in background."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.integrations.resend.client import ResendClient
from app.integrations.resend.verification import verify_resend_signature
from app.services.candidate_comms import extract_reply_text, parse_reply_token
from app.services.cominty import ComintyService
from app.services.conversation import get_app_lock
from recruitment_db.models import CandidateThread, ResendEvent

logger = logging.getLogger(__name__)

router = APIRouter()


@dataclass
class ResendRuntime:
    session_factory: async_sessionmaker[AsyncSession]
    webhook_secret: str
    scheduler: ComintyService  # duck-typed for tests
    resend_api_key: str
    resend_from_email: str


def get_resend_runtime(request: Request) -> ResendRuntime:
    return request.app.state.resend_runtime


@router.post("/resend/events")
async def resend_events(
    request: Request, background: BackgroundTasks, runtime: ResendRuntime = Depends(get_resend_runtime)
):
    raw = await request.body()
    headers = request.headers
    if not verify_resend_signature(
        signing_secret=runtime.webhook_secret,
        svix_id=headers.get("svix-id"),
        svix_timestamp=headers.get("svix-timestamp"),
        svix_signature=headers.get("svix-signature"),
        body=raw,
    ):
        return Response(status_code=400)
    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        return Response(status_code=400)
    if not isinstance(event, dict):
        return Response(status_code=400)
    event_id = headers.get("svix-id", "")
    data = event.get("data")
    if not event_id or not isinstance(data, dict):
        return Response(status_code=400)
    async with runtime.session_factory() as session:
        session.add(ResendEvent(event_id=event_id))
        try:
            await session.commit()
        except IntegrityError:
            logger.info("deduped resend event %s", event_id)
            return {"received": True, "duplicate": True}
    background.add_task(_handle_inbound, runtime, event_id, event.get("type"), data)
    return {"received": True}


async def _handle_inbound(runtime: ResendRuntime, event_id: str, event_type: Any, data: dict) -> None:
    try:
        if event_type != "email.received":
            logger.info("ignoring resend event type=%s", event_type)
            return
        await _route_reply(runtime, data)
    except Exception:
        # Release the dedupe row so the Resend retry redelivers as new.
        logger.exception("resend dispatch failed for %s; releasing for redelivery", event_id)
        async with runtime.session_factory() as session:
            await session.execute(delete(ResendEvent).where(ResendEvent.event_id == event_id))
            await session.commit()


async def _route_reply(runtime: ResendRuntime, data: dict) -> None:
    to_addrs = data.get("to") or []
    if isinstance(to_addrs, str):
        to_addrs = [to_addrs]
    token, inbound_to = None, None
    for addr in to_addrs:
        token = parse_reply_token(addr)
        if token is not None:
            inbound_to = addr
            break
    if token is None:
        logger.info("ignoring resend mail: no coordination reply-to in %s", to_addrs)
        return
    email_id = data.get("email_id")
    if not email_id:
        logger.warning("resend mail without email_id; ignoring")
        return
    async with runtime.session_factory() as session:
        thread = (
            await session.execute(select(CandidateThread).where(CandidateThread.token == token))
        ).scalar_one_or_none()
        if thread is None:
            logger.info("ignoring resend mail: unknown coordination token")
            return
        thread_id, candidate_email = thread.cominty_thread_id, thread.candidate_email
        application_id = thread.application_id
    email = await ResendClient(runtime.resend_api_key).get_received_email(email_id)
    text = extract_reply_text(email)
    if not text:
        logger.info("ignoring resend mail %s: empty body", email_id)
        return
    async with get_app_lock(application_id):
        reply = await runtime.scheduler.send_message(
            thread_id, f"Candidate {candidate_email} replied by email:\n\n{text}"
        )
    subject = email.get("subject") or "Interview scheduling"
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    await ResendClient(runtime.resend_api_key).send_email(
        from_email=runtime.resend_from_email,
        to_email=candidate_email,
        subject=subject,
        text=reply.strip() or "(empty reply)",
        reply_to=inbound_to or "",
    )
