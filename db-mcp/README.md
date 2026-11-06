# AcmeTech scores MCP server

Assessment storage for Cominty agents, over stateless Streamable HTTP.

Tools: `health`, `get_scoring_criteria`, `save_application_score`,
`get_application_score`, `list_top_applications`. Set `DB_MCP_PROFILE` to
`read` (Recruiter Agent connection) or `write` (Assessment Agent
connection) to narrow the surface; the default `all` is for dev. Run one
container per profile in production (one Cominty connection each).

## Setup (once)

From the repo root, in the project venv:

```bash
pip install -e ./db
pip install -r db-mcp/requirements.txt
```

No `.env` entries needed beyond the shared `DATABASE_URL` (host, port, and
profile have defaults; override with `DB_MCP_HOST`, `DB_MCP_PORT`,
`DB_MCP_PROFILE`).

## Run locally

```bash
cd db-mcp
python server.py
```

MCP endpoint: `http://127.0.0.1:8003/mcp`

## Test

```bash
cd db-mcp
pytest tests -q
```

## Deploy

Docker files live here: `Dockerfile`, `docker-compose.yml`, `requirements.txt`.
Full runbook: `docs/vps-deploy.md` (VPS + DuckDNS + shared Caddy + Docker).
