# AcmeTech ATS MCP server

Recruitment tools for Cominty agents, over stateless Streamable HTTP.

M2 exposes one tool: `health`. Artifact tools (jobs, applications, …) land in
later milestones under `tools/`.

## Setup (once)

From the repo root, in the project venv:

```bash
pip install "mcp>=2.3" httpx pydantic-settings
```

No `.env` entries needed for M2 (host/port/log have defaults; override with
`MCP_HOST`, `MCP_PORT`, `LOG_LEVEL`).

## Run locally

```bash
cd ats-mcp
python server.py
```

MCP endpoint: `http://127.0.0.1:8002/mcp`

## Test

```bash
cd ats-mcp
pytest tests -q
```

## Deploy

Docker files live here: `Dockerfile`, `docker-compose.yml`, `requirements.txt`,
`Caddyfile.snippet`. Full runbook: `docs/vps-deploy.md` (VPS + DuckDNS + shared
Caddy + Docker).
