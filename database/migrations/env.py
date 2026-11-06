"""Alembic environment (async). Run from the repo root:

    alembic -c database/alembic.ini upgrade head
"""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

import recruitment_db.models  # noqa: F401 - register models on Base.metadata
from app.config import get_settings
from recruitment_db.database import Base
from recruitment_db.urls import to_async_database_url

config = context.config
# NOTE: the URL intentionally never passes through alembic's ConfigParser
# (get_section() interpolates `%`, corrupting URL-encoded passwords). env.py
# reads DATABASE_URL from app settings directly, like the app and scripts.
DATABASE_URL = to_async_database_url(get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(DATABASE_URL, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
