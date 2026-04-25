# Toronto Blue Jays Statcast API — FastAPI (Fly.io)
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY config.py .
COPY data_source ./data_source
COPY backend ./backend
COPY data/statcast_local ./data/statcast_local

# Ephemeral cache dirs (overridden when a Fly volume is mounted at /data)
RUN mkdir -p .cache/statcast_frames .cache/weekly_cache .cache/pitcher_stats

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
