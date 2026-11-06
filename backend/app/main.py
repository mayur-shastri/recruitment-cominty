"""FastAPI application: Slack <-> Cominty bridge. Run from the repo root:

    uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from cominty_sdk import AgentCapabilities, AsyncCominty, McpCapability, WebCapability
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slack_sdk.web.async_client import AsyncWebClient
from sqlalchemy import text

from app.api.harly import HarlyRuntime, router as harly_router
from app.api.slack import Runtime, router as slack_router
from app.config import get_settings
from app.logging_setup import setup_logging
from app.services.cominty import ATS_CONNECTION_ID, ComintyService
from recruitment_db.database import create_engine_and_sessions
from recruitment_db.urls import to_async_database_url

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(
        settings.log_level,
        secrets=[
            settings.slack_bot_token,
            settings.slack_signing_secret,
            settings.cominty_api_key,
            settings.harly_api_key,
            settings.harly_webhook_secret_application_created,
            settings.harly_webhook_secret_stage_changed,
            settings.harly_s3_secret_access_key,
        ],
    )
    if not hasattr(app.state, "runtime"):
        # Fail fast here (bad credentials/ids) rather than on the first DM.
        engine, session_factory = create_engine_and_sessions(to_async_database_url(settings.database_url))
        client = AsyncCominty(
            api_token=settings.cominty_api_key,
            user_id=settings.cominty_user_id,
            timeout=settings.cominty_timeout_s,
        )
        # Capabilities freeze for a thread's lifetime at start; existing threads
        # are unaffected. Register the `harly_ats` integration in Cominty before a
        # NEW thread starts, or the start call fails validation server-side.
        recruiter_capabilities = AgentCapabilities(mcp=McpCapability(activation="always", connections=[ATS_CONNECTION_ID]))
        app.state.runtime = Runtime(
            engine=engine,
            session_factory=session_factory,
            cominty=ComintyService(
                client,
                agent_id=settings.cominty_recruiter_agent_id,
                thread_capabilities=recruiter_capabilities,
            ),
            cominty_user_id=settings.cominty_user_id,
            slack=AsyncWebClient(token=settings.slack_bot_token),
            signing_secret=settings.slack_signing_secret,
        )
        logger.info("bridge ready (env=%s)", settings.app_env)
    if not hasattr(app.state, "harly_runtime"):
        assessment_connections = [
            c for c in [ATS_CONNECTION_ID, settings.cominty_db_mcp_connection_id] if c
        ]
        # Web stays on: the agent fetches resume URLs itself (no in-house OCR).
        assessment_client = AsyncCominty(
            api_token=settings.cominty_api_key,
            user_id=settings.cominty_user_id,
            timeout=settings.cominty_timeout_s,
        )
        app.state.harly_runtime = HarlyRuntime(
            session_factory=app.state.runtime.session_factory,
            webhook_secrets=[
                settings.harly_webhook_secret_application_created,
                settings.harly_webhook_secret_stage_changed,
            ],
            harly_base_url=settings.harly_base_url,
            harly_api_key=settings.harly_api_key,
            assessment=ComintyService(
                assessment_client,
                agent_id=settings.cominty_assessment_agent_id,
                thread_capabilities=AgentCapabilities(
                    web=WebCapability(activation="always"),
                    mcp=McpCapability(activation="always", connections=assessment_connections),
                ),
            ),
            assessment_agent_id=settings.cominty_assessment_agent_id,
            s3_endpoint=settings.harly_s3_endpoint,
            s3_bucket=settings.harly_s3_bucket,
            s3_region=settings.harly_s3_region,
            s3_access_key=settings.harly_s3_access_key_id,
            s3_secret_key=settings.harly_s3_secret_access_key,
            s3_workspace_id=settings.harly_s3_workspace_id,
            s3_public_url=settings.harly_s3_public_url,
        )
    yield
    runtime = getattr(app.state, "runtime", None)
    if runtime is not None:
        await runtime.cominty.aclose()
        await runtime.engine.dispose()
    harly_runtime = getattr(app.state, "harly_runtime", None)
    if harly_runtime is not None:
        await harly_runtime.assessment.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="AcmeTech Recruitment", lifespan=lifespan)
    app.include_router(slack_router)
    app.include_router(harly_router)

    @app.get("/health")
    async def health(request: Request):
        runtime = getattr(request.app.state, "runtime", None)
        if runtime is None:
            return JSONResponse(status_code=503, content={"status": "starting"})
        try:
            async with runtime.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            logger.exception("health check: database unreachable")
            return JSONResponse(status_code=503, content={"status": "degraded", "db": "unreachable"})
        return {"status": "ok"}

    return app


app = create_app()
