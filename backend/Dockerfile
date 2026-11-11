# syntax=docker/dockerfile:1
FROM python:3.11-slim AS builder

WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt ./requirements.txt
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend:/app

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 curl && rm -rf /var/lib/apt/lists/* \
    && addgroup --system --gid 1001 appgroup \
    && adduser --system --uid 1001 --ingroup appgroup appuser

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels /wheels/* && rm -rf /wheels

COPY ml/__init__.py /app/ml/__init__.py
COPY ml/src/__init__.py /app/ml/src/__init__.py
COPY ml/src/loader.py /app/ml/src/loader.py
COPY ml/src/item_cf.py /app/ml/src/item_cf.py
COPY ml/src/user_cf.py /app/ml/src/user_cf.py
COPY ml/src/content_fallback.py /app/ml/src/content_fallback.py
COPY ml/src/popular.py /app/ml/src/popular.py
COPY ml/src/matrix.py /app/ml/src/matrix.py
COPY ml/artifacts /app/ml/artifacts
COPY ml/data/processed /app/ml/data/processed
COPY backend /app/backend

RUN chown -R appuser:appgroup /app
USER appuser

WORKDIR /app/backend
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD sh -c 'curl -fsS "http://127.0.0.1:${PORT:-8000}/api/health" || exit 1'

CMD ["sh", "-c", "alembic upgrade head && python -m app.services.seed && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]

