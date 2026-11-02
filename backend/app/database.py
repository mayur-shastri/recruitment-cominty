"""Async SQLAlchemy engine/session factory and declarative base."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def create_engine_and_sessions(database_url: str) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        database_url,
        pool_pre_ping=True,
        # Supabase pooler is pgbouncer (transaction mode): server-side prepared
        # statements don't survive across checkouts, so disable the cache.
        connect_args={"statement_cache_size": 0},
    )
    # expire_on_commit=False: committed objects keep their attributes, avoiding
    # lazy-refresh IO outside greenlet context (MissingGreenlet) in async code.
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, factory
