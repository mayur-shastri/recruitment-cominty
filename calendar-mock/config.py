"""Calendar mock settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root (this file is calendar-mock/config.py).
_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class CalendarSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    calendar_host: str = "127.0.0.1"
    calendar_port: int = 8004
    # Single demo timezone for seed data and UI display (IANA name).
    calendar_timezone: str = "UTC"
    database_url: str


@lru_cache
def get_calendar_settings() -> CalendarSettings:
    return CalendarSettings()  # type: ignore[call-arg]
