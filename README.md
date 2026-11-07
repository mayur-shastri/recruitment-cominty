# AcmeTech Recruitment Operations

AI-operated recruitment department: Hiring Managers talk to a Recruiter Agent
over Slack; a FastAPI bridge connects Slack to Cominty managed agents; Harly
remains the ATS system of record.

## Layout

- `backend/` — FastAPI bridge (`app/`), tests (`tests/`)
- `db/` — shared Postgres layer (`recruitment_db` package: models, engine, URL helper)
- `ats-mcp/` — ATS MCP server (Milestone 2)
- `db-mcp/` — scores MCP server (assessment storage)
- `calendar-mock/` — mock interviewer calendar (demo UI + scheduler MCP tools)
- `database/migrations/` — Alembic migrations (lands with backend foundation)
- `docs/` — reference material dropped in from external docs

## Milestone 1: Slack <-> Cominty Recruiter Agent

Setup (in WSL, from the repo root):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ./db -e 'backend[dev]'
cp .env.example .env  # then fill in values; never commit .env
```

Migrate: `alembic -c database/alembic.ini upgrade head`
Run from the repo root: `uvicorn app.main:app --reload`
Test: `pytest backend/tests -q`

Deploy (VPS + Docker + Caddy): see `docs/vps-deploy.md`.

## Scheduler coordination

The scheduler agent books interviews and negotiates with interviewers:

- Calendar ops live on `calendar-mock` (`find_common_slots`,
  `book_interview`, `update_interview`, `cancel_interview`, plus reads).
- Slack DMs go through the bridge: `send_slack_message` is served from the
  backend's own `/mcp` (no new Caddy route — same public backend URL).
  Register it in Cominty as the scheduler's comms connection
  (`COMINTY_COMMS_CONNECTION_ID`).
- The Slack app needs the `users:read.email` scope (new) so pool emails
  resolve to workspace members at trigger time. Members it cannot resolve
  are named in the trigger message for out-of-band coordination.
- Interviewer replies route back into the open coordination thread
  (`scheduler_threads`, migration 0006). HMs always reach the recruiter
  agent instead, even mid-coordination; one active coordination per
  interviewer is assumed (latest open row wins).
