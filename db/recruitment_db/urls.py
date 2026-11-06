"""Database URL helpers (no settings dependency; pure functions)."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


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
