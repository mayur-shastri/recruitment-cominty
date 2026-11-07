# AcmeTech mock interviewer calendar

Demo availability for the scheduler agent: a week-view UI plus MCP tools,
in one process. The scheduler checks interviewer calendars with
`get_availability` and books with `book_interview`, working around existing
busy blocks exactly as it would against a real calendar integration.

Tools: `health`, `list_interviewers`, `get_availability`, `book_interview`,
`list_interviews`. Single consumer (the scheduler agent), so no profiles.

## Setup (once)

From the repo root, in the project venv:

```bash
pip install -e ./db
pip install -r calendar-mock/requirements.txt
alembic -c database/alembic.ini upgrade head   # migration 0004
python calendar-mock/seed.py                   # 3 interviewers + busy blocks
```

No `.env` entries needed beyond the shared `DATABASE_URL` (host, port, and
timezone have defaults; override with `CALENDAR_HOST`, `CALENDAR_PORT`,
`CALENDAR_TIMEZONE`).

## Run

```bash
cd calendar-mock && python server.py
```

- UI: `http://127.0.0.1:8004/` (pick an interviewer, browse the week, add busy blocks)
- MCP: `http://127.0.0.1:8004/mcp` (check with `python scripts/mcp_check.py <url>`)
- Tests: `pytest calendar-mock/tests -q` (or bare `pytest` from the root)

## Deploy

Merge to `main` (run migration 0004 first), add a Caddy block for the new
route, and register the `/mcp` URL as a Cominty MCP connection for the
scheduler agent (`COMINTY_CALENDAR_CONNECTION_ID`):

```caddy
calendar-acmetech.duckdns.org {
    reverse_proxy recruitment-calendar:8004
}
```
