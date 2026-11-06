# Recruitment backend (Slack <-> Cominty FastAPI bridge). Joins the existing
# shared proxy network; Caddy (Harly CLI-owned) routes to it. No published ports.
# Build context is the repo root (needs ./db and ./backend).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY db ./dblib
RUN pip install --no-cache-dir ./dblib && rm -rf ./dblib
COPY backend/pyproject.toml .
COPY backend/app ./app
RUN pip install --no-cache-dir .

RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
