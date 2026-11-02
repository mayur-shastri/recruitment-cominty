"""Application settings, loaded from the repo-root `.env`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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


def to_async_database_url(url: str) -> str:
    """Normalize a Postgres URL for SQLAlchemy's asyncpg driver.

    Accepts libpq-style URLs (including Supabase direct strings) and returns a
    ``postgresql+asyncpg://`` URL, translating ``sslmode`` to asyncpg's ``ssl``.
    """
    parts = urlsplit(url)
    if parts.scheme in {"postgres", "postgresql"}:
        scheme = "postgresql+asyncpg"
    elif parts.scheme == "postgresql+asyncpg":
        scheme = parts.scheme
    else:
        raise ValueError(f"unsupported database scheme: {parts.scheme!r}")
    query = [
        ("ssl" if key == "sslmode" else key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
