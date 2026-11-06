"""Shared Postgres layer for AcmeTech recruitment services.

Single source of truth for table models (`recruitment_db.models`), the
declarative base and engine factory (`recruitment_db.database`), and the
asyncpg URL normalizer (`recruitment_db.urls`). Imported by the backend,
db-mcp, Alembic migrations, and scripts — never the other way around.
"""
