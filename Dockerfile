# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # uv: install into the system environment, no per-project venv inside the image
    UV_SYSTEM_PYTHON=1 \
    UV_PROJECT_ENVIRONMENT=/usr/local \
    # Be resilient to slow/flaky networks when pulling wheels.
    UV_HTTP_TIMEOUT=180

WORKDIR /app

# Install uv (the resolver/installer that reads uv.lock).
RUN pip install --upgrade pip uv

# Install dependencies FIRST, from the lockfile, for reproducible builds + layer caching.
# Copying only the manifest + lock means editing app code does NOT reinstall dependencies.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Copy application source, migrations, and scripts.
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY scripts ./scripts

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
