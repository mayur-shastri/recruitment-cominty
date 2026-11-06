# AcmeTech recruitment shared DB layer

Single source of truth for Postgres models, the declarative base, the
async engine factory, and the asyncpg URL helper. Consumed by the
backend, db-mcp, Alembic migrations (`database/migrations/`), and
`scripts/`. This package depends only on SQLAlchemy + asyncpg — no web,
settings, or service code, and it never imports the services back.

Install (repo root, project venv):

```bash
pip install -e ./db
```
