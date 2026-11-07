# Mock interviewer calendar (demo UI + scheduler MCP tools). Joins the existing
# shared proxy network; Caddy (Harly CLI-owned) routes to it. No published ports.
# Build context is the repo root (needs ./db and ./calendar-mock).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY db ./dblib
RUN pip install --no-cache-dir ./dblib && rm -rf ./dblib
COPY calendar-mock/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY calendar-mock/server.py calendar-mock/config.py calendar-mock/ui.py calendar-mock/seed.py ./
COPY calendar-mock/tools ./tools
COPY calendar-mock/services ./services
COPY calendar-mock/static ./static

RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8004

CMD ["python", "server.py"]
