"""MCP server settings. Harly/DB settings land with the jobs milestone."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root (this file is ats-mcp/config.py).
_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class McpSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8002


@lru_cache
def get_mcp_settings() -> McpSettings:
    return McpSettings()  # type: ignore[call-arg]
