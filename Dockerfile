# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Builder -- wheels are compiled here so the runtime image carries no compiler.
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/ requirements/
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements/prod.txt

# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings.prod

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=app:app . .

# Static files are baked in so the container needs no writable volume for them.
# A throwaway key and host satisfy prod.py's boot-time assertions; neither is
# used at runtime, where the real values come from the environment.
RUN DJANGO_SECRET_KEY=build-only-key-that-is-long-enough-for-the-check-0123456789 \
    DJANGO_ALLOWED_HOSTS=build.invalid \
    DATABASE_URL=sqlite:///build.sqlite3 \
    python manage.py collectstatic --noinput \
    && rm -f build.sqlite3

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

# Uvicorn workers under gunicorn: gunicorn supervises and recycles processes,
# uvicorn speaks ASGI so the same workers serve HTTP and websockets. Long-lived
# sockets mean no request timeout and a generous graceful shutdown.
CMD ["gunicorn", "config.asgi:application", \
     "--worker-class", "uvicorn_worker.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "4", \
     "--timeout", "0", \
     "--graceful-timeout", "30", \
     "--max-requests", "10000", \
     "--max-requests-jitter", "1000", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
