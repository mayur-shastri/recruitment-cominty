"""Application settings, loaded from the repo-root `.env`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


# Repo root (this file is backend/app/config.py), so .env is found
# regardless of which directory commands run from.
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    # Bind host, mirrored into the mounted MCP app's DNS-rebinding default:
    # loopback keeps protection on, 0.0.0.0 (containers) disables it — the
    # same behavior as the standalone .run() MCP servers.
    backend_host: str = "127.0.0.1"

    database_url: str

    slack_bot_token: str
    slack_signing_secret: str

    cominty_api_key: str
    cominty_user_id: str
    cominty_recruiter_agent_id: str
    cominty_timeout_s: float = 300.0
    # Assessment pipeline (M3.3). Empty means "not configured": the trigger
    # refuses with a clear error instead of failing the whole bridge.
    cominty_assessment_agent_id: str = ""
    cominty_db_mcp_connection_id: str = ""
    # Scheduler trigger (M3.6). Empty means "not configured": interview-stage
    # triggers refuse with a clear error instead of failing the receiver.
    cominty_scheduler_agent_id: str = ""
    # Mock calendar MCP connection for the scheduler's availability tools.
    cominty_calendar_connection_id: str = ""
    # Comms MCP connection (this bridge's own /mcp): scheduler's Slack tools.
    cominty_comms_connection_id: str = ""
    # Polling fallback: sweep unscored applications every interval (Harly
    # webhooks are broken upstream). Disable to rely on webhooks alone.
    assessment_poll_enabled: bool = True
    assessment_poll_interval_s: float = 300.0

    # Harly API reads + webhook verification for the assessment pipeline.
    harly_base_url: str = ""
    harly_api_key: str = ""
    harly_webhook_secret_application_created: str = ""
    harly_webhook_secret_stage_changed: str = ""

    # Harly resume storage (R2) for the in-house extraction pipeline.
    harly_s3_endpoint: str = ""
    harly_s3_bucket: str = ""
    harly_s3_region: str = "auto"
    harly_s3_access_key_id: str = ""
    harly_s3_secret_access_key: str = ""
    harly_s3_workspace_id: str = ""
    harly_s3_public_url: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
