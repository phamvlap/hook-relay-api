# syntax=docker/dockerfile:1
ARG PYTHON_VERSION=3.13-slim

# Stage 1: Builder (Dependency installation & Bytecode compilation)
FROM python:${PYTHON_VERSION} AS builder

# Prevent writing .pyc files during package install, buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Grab the official standalone uv binary (no pip overhead, zero extra build layers)
COPY --from=ghcr.io/astral-sh/uv:0.6.5 /uv /uvx /bin/

WORKDIR /app

# Cache dependency layer: Copy only dependency manifests first
# (README.md is required by setuptools / pyproject.toml package metadata)
COPY pyproject.toml uv.lock README.md ./

# Install external dependencies into /app/.venv without the project root package
# BuildKit cache mount prevents re-downloading wheels across local/CI builds
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Copy application source code and database migration files
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./

# Install the project into the virtual environment with precompiled bytecode
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Stage 2: Final (Minimal Production Runtime)
FROM python:${PYTHON_VERSION} AS final

# Standard production environment variables
# Note: Fly.io secrets are injected as environment variables at runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app" \
    PORT=8000

# Create dedicated non-root user and ensure ownership of the application directory
RUN groupadd -r --gid 10001 appuser && \
    useradd -r --uid 10001 --gid 10001 -d /app -s /sbin/nologin -c "Application User" appuser && \
    mkdir -p /app && \
    chown -R appuser:appuser /app

WORKDIR /app

# Copy virtual environment and application code directly with correct ownership
# (Single-step copy avoids duplicate layers in the union filesystem)
COPY --chown=appuser:appuser --from=builder /app/.venv /app/.venv
COPY --chown=appuser:appuser --from=builder /app/src /app/src
COPY --chown=appuser:appuser --from=builder /app/alembic /app/alembic
COPY --chown=appuser:appuser --from=builder /app/alembic.ini /app/alembic.ini

# Switch to non-privileged user for security
USER appuser

# Expose default application port
EXPOSE 8000

# Default web command: FastAPI via Uvicorn
# Note: Fly.io can override this command in fly.toml for workers or scheduler
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
