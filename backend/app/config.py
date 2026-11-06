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

    database_url: str

    slack_bot_token: str
    slack_signing_secret: str

    cominty_api_key: str
    cominty_user_id: str
    cominty_recruiter_agent_id: str
    cominty_timeout_s: float = 300.0


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
