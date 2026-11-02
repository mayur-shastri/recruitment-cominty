# AcmeTech Recruitment Operations

AI-operated recruitment department: Hiring Managers talk to a Recruiter Agent
over Slack; a FastAPI bridge connects Slack to Cominty managed agents; Harly
remains the ATS system of record.

## Layout

- `backend/` — FastAPI bridge (`app/`), tests (`tests/`)
- `ats-mcp/` — ATS MCP server (Milestone 2)
- `database/migrations/` — Alembic migrations (lands with backend foundation)
- `docs/` — reference material dropped in from external docs

## Milestone 1: Slack <-> Cominty Recruiter Agent

Setup (in WSL, from the repo root):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e 'backend[dev]'
cp .env.example .env  # then fill in values; never commit .env
```

Migrate: `alembic -c database/alembic.ini upgrade head`
Run from the repo root: `uvicorn app.main:app --reload`
Test: `pytest backend/tests -q`
