# Recruitment MCP server (AcmeTech ATS tools). Joins the existing shared
# proxy network; Caddy (Harly CLI-owned) routes to it. No published ports.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py config.py ./

RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8002

CMD ["python", "server.py"]
