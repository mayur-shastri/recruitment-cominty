# Scores MCP server (assessment storage for Cominty agents). Joins the existing
# shared proxy network; Caddy (Harly CLI-owned) routes to it. No published ports.
# Build context is the repo root (needs ./db and ./db-mcp).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY db ./dblib
RUN pip install --no-cache-dir ./dblib && rm -rf ./dblib
COPY db-mcp/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY db-mcp/server.py db-mcp/config.py ./
COPY db-mcp/tools ./tools
COPY db-mcp/services ./services

RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8003

CMD ["python", "server.py"]
