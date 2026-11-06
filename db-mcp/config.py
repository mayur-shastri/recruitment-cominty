"""DB MCP server settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root (this file is db-mcp/config.py).
_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class DbMcpSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    db_mcp_host: str = "127.0.0.1"
    db_mcp_port: int = 8003
    # Tool profile: all (dev), write (assessment agent), read (recruiter agent).
    db_mcp_profile: str = "all"
    database_url: str


@lru_cache
def get_db_mcp_settings() -> DbMcpSettings:
    return DbMcpSettings()  # type: ignore[call-arg]
