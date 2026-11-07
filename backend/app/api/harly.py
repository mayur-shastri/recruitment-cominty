"""Harly webhook endpoint: verify, dedupe, ack fast, dispatch in background."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.integrations.harly.verification import verify_harly_signature
from app.services import assessment_pipeline
from recruitment_db.models import HarlyEvent

logger = logging.getLogger(__name__)

router = APIRouter()


@dataclass
class HarlyRuntime:
    session_factory: async_sessionmaker[AsyncSession]
    webhook_secrets: list[str]
    harly_base_url: str
    harly_api_key: str
    assessment: object  # ComintyService (duck-typed for tests)
    assessment_agent_id: str
    scheduler: object  # ComintyService (duck-typed for tests)
    scheduler_agent_id: str
    slack: object  # AsyncWebClient (duck-typed for tests): pool-email resolution
    s3_endpoint: str = ""
    s3_bucket: str = ""
    s3_region: str = "auto"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_workspace_id: str = ""
    s3_public_url: str = ""

    @property
    def s3_configured(self) -> bool:
        return bool(
            self.s3_endpoint
            and self.s3_bucket
            and self.s3_access_key
            and self.s3_secret_key
            and self.s3_workspace_id
            and self.s3_public_url
        )


def get_harly_runtime(request: Request) -> HarlyRuntime:
    return request.app.state.harly_runtime


@router.post("/harly/events")
async def harly_events(
    request: Request, background: BackgroundTasks, runtime: HarlyRuntime = Depends(get_harly_runtime)
):
    raw = await request.body()
    signature = request.headers.get("x-harly-signature-256")
    verified = any(
        verify_harly_signature(secret=secret, body=raw, signature=signature)
        for secret in runtime.webhook_secrets
        if secret
    )
    if not verified:
        return Response(status_code=400)
    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        return Response(status_code=400)
    if not isinstance(event, dict):
        return Response(status_code=400)
    event_id, event_type = event.get("id"), event.get("type")
    data = event.get("data") or {}
    if not event_id or not event_type or not isinstance(data, dict):
        return Response(status_code=400)
    async with runtime.session_factory() as session:
        session.add(HarlyEvent(event_id=event_id, event_type=event_type))
        try:
            await session.commit()
        except IntegrityError:
            logger.info("deduped harly event %s", event_id)
            return {"received": True, "duplicate": True}
    background.add_task(_dispatch, runtime, event_id, event_type, data)
    return {"received": True}


async def _dispatch(runtime: HarlyRuntime, event_id: str, event_type: str, data: dict) -> None:
    try:
        if event_type == "application.created":
            app_id, _, _ = assessment_pipeline.extract_ids(data)
            if not app_id:
                logger.warning("application.created without application id; ignoring")
                return
            await assessment_pipeline.process_new_application(runtime, app_id)
        elif event_type == "application.stage_changed":
            await assessment_pipeline.process_stage_change(runtime, data, event_id=event_id)
        else:
            logger.info("ignoring harly event type=%s", event_type)
    except Exception:
        # Release the dedupe row so the Harly retry redelivers as new.
        logger.exception("harly dispatch failed for %s; releasing for redelivery", event_id)
        async with runtime.session_factory() as session:
            await session.execute(delete(HarlyEvent).where(HarlyEvent.event_id == event_id))
            await session.commit()
