"""FastAPI application: Slack <-> Cominty bridge. Run from the repo root:

    uvicorn app.main:app --reload
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from cominty_sdk import AgentCapabilities, AsyncCominty, McpCapability, WebCapability
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from slack_sdk.web.async_client import AsyncWebClient
from sqlalchemy import text

from app.api.harly import HarlyRuntime, router as harly_router
from app.api.resend import ResendRuntime, router as resend_router
from app.api.slack import Runtime, router as slack_router
from app.config import get_settings
from app.logging_setup import setup_logging
from app.mcp.server import create_comms_mcp
from app.services.assessment_pipeline import run_poll_loop
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
    assessment_connections = [
        c for c in [ATS_CONNECTION_ID, settings.cominty_db_mcp_connection_id] if c
    ]
    # Scheduler toolset: ATS (interviews) + DB (plans) + calendar
    # (availability/booking) + comms (Slack DMs). Empty connection IDs drop
    # out until Cominty registration lands.
    scheduler_connections = [
        c
        for c in [
            *assessment_connections,
            settings.cominty_calendar_connection_id,
            settings.cominty_comms_connection_id,
        ]
        if c
    ]
    if not hasattr(app.state, "runtime"):
        # Fail fast here (bad credentials/ids) rather than on the first DM.
        engine, session_factory = create_engine_and_sessions(to_async_database_url(settings.database_url))
        client = AsyncCominty(
            api_token=settings.cominty_api_key,
            user_id=settings.cominty_user_id,
            timeout=settings.cominty_timeout_s,
        )
        # One Slack client shared by the DM runtime and the Harly runtime
        # (pool-email resolution for scheduler coordinations).
        slack_client: Any = AsyncWebClient(token=settings.slack_bot_token)
        # Capabilities freeze for a thread's lifetime at start; existing threads
        # are unaffected. Register the `harly_ats` integration in Cominty before a
        # NEW thread starts, or the start call fails validation server-side.
        # Recruiter gets ATS + the (un-split, all-profile) DB connection:
        # criteria/config authoring and top-N all run through HM chat.
        # Demo posture: tool descriptions steer agents to their tools;
        # no profile/container split until real enforcement is needed.
        recruiter_connections = [
            c for c in [ATS_CONNECTION_ID, settings.cominty_db_mcp_connection_id] if c
        ]
        recruiter_capabilities = AgentCapabilities(mcp=McpCapability(activation="always", connections=recruiter_connections))
        scheduler_service = ComintyService(
            AsyncCominty(
                api_token=settings.cominty_api_key,
                user_id=settings.cominty_user_id,
                timeout=settings.cominty_timeout_s,
            ),
            agent_id=settings.cominty_scheduler_agent_id,
            thread_capabilities=AgentCapabilities(
                mcp=McpCapability(activation="always", connections=scheduler_connections),
            ),
        )
        app.state.runtime = Runtime(
            engine=engine,
            session_factory=session_factory,
            cominty=ComintyService(
                client,
                agent_id=settings.cominty_recruiter_agent_id,
                thread_capabilities=recruiter_capabilities,
            ),
            scheduler=scheduler_service,
            cominty_user_id=settings.cominty_user_id,
            slack=slack_client,
            signing_secret=settings.slack_signing_secret,
        )
        logger.info("bridge ready (env=%s)", settings.app_env)
    if not hasattr(app.state, "harly_runtime"):
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
            scheduler=app.state.runtime.scheduler,
            scheduler_agent_id=settings.cominty_scheduler_agent_id,
            slack=app.state.runtime.slack,
            s3_endpoint=settings.harly_s3_endpoint,
            s3_bucket=settings.harly_s3_bucket,
            s3_region=settings.harly_s3_region,
            s3_access_key=settings.harly_s3_access_key_id,
            s3_secret_key=settings.harly_s3_secret_access_key,
            s3_workspace_id=settings.harly_s3_workspace_id,
            s3_public_url=settings.harly_s3_public_url,
        )
    if not hasattr(app.state, "resend_runtime"):
        app.state.resend_runtime = ResendRuntime(
            session_factory=app.state.runtime.session_factory,
            webhook_secret=settings.resend_webhook_secret,
            scheduler=app.state.runtime.scheduler,
            resend_api_key=settings.resend_api_key,
            resend_from_email=settings.resend_from_email,
        )
    if settings.assessment_poll_enabled and not hasattr(app.state, "poll_task"):
        app.state.poll_task = asyncio.create_task(
            run_poll_loop(
                app.state.harly_runtime, interval_s=settings.assessment_poll_interval_s
            )
        )
        logger.info("assessment poll every %ss", settings.assessment_poll_interval_s)
    yield
    poll_task = getattr(app.state, "poll_task", None)
    if poll_task is not None:
        poll_task.cancel()
        with suppress(asyncio.CancelledError):
            await poll_task
    runtime = getattr(app.state, "runtime", None)
    if runtime is not None:
        await runtime.cominty.aclose()
        await runtime.engine.dispose()
    harly_runtime = getattr(app.state, "harly_runtime", None)
    if harly_runtime is not None:
        await harly_runtime.assessment.aclose()
        await harly_runtime.scheduler.aclose()


def _mcp_host() -> str:
    """Bind host for the mounted MCP app (falls back for settings-less envs).

    Import/collection time has no .env in CI, so settings may not validate
    there — loopback keeps DNS-rebinding protection on. Production sets
    BACKEND_HOST=0.0.0.0 via compose, matching the standalone MCP servers.
    """
    try:
        return get_settings().backend_host
    except ValidationError:
        return "127.0.0.1"


def create_app() -> FastAPI:
    comms_app = create_comms_mcp().streamable_http_app(stateless_http=True, host=_mcp_host())

    @asynccontextmanager
    async def app_lifespan(app: FastAPI):
        async with lifespan(app):
            # Mounted apps don't run their own lifespan; without this the MCP
            # session manager's task group never initializes and /mcp 500s.
            async with comms_app.router.lifespan_context(comms_app):
                yield

    app = FastAPI(title="AcmeTech Recruitment", lifespan=app_lifespan)
    app.include_router(slack_router)
    app.include_router(harly_router)
    app.include_router(resend_router)

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

    # Mounted last: the "/" prefix would otherwise swallow later routes.
    app.mount("/", comms_app)
    return app


app = create_app()
