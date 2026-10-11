.DEFAULT_GOAL := help

IMAGE_NAME ?= hook-relay-api
IMAGE_TAG ?= latest
PORT ?= 8000

.PHONY: help install dev-install lint lint-fix format format-check pre-commit clean \
        run celery-worker celery-beat flower init-migrations make-migrations migrate downgrade \
        test test-unit test-api test-integration test-cov \
        docker-build docker-run docker-worker docker-beat docker-migrate docker-cli docker-clean

help:
	@echo "Hook Relay API - Development Commands"
	@echo "======================================"
	@echo ""
	@echo "Dependencies:"
	@echo "  make install             Install dependencies via uv"
	@echo "  make dev-install         Install all dependencies and configure pre-commit hooks"
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint                Run Ruff linter checks"
	@echo "  make lint-fix            Run Ruff linter and auto-fix violations"
	@echo "  make format              Format code with Ruff and fix lint errors"
	@echo "  make format-check        Check formatting without modifying files (CI mode)"
	@echo "  make pre-commit          Run pre-commit hooks on all files"
	@echo "  make clean               Remove caches, coverage files, and build artifacts"
	@echo ""
	@echo "Application & Services:"
	@echo "  make run                 Start FastAPI development server with reload"
	@echo "  make celery-worker       Start Celery worker process"
	@echo "  make celery-beat         Start Celery beat periodic scheduler"
	@echo "  make flower              Start Celery Flower web monitor dashboard (port 5555)"
	@echo ""
	@echo "Docker Operations:"
	@echo "  make docker-build        Build optimized multi-stage Docker image"
	@echo "  make docker-run          Run FastAPI web server container (port $(PORT))"
	@echo "  make docker-worker       Run Celery worker container"
	@echo "  make docker-beat         Run Celery beat periodic scheduler container"
	@echo "  make docker-migrate      Run database migrations inside Docker"
	@echo "  make docker-cli          Run CLI inside Docker (e.g. make docker-cli cmd=\"--help\")"
	@echo "  make docker-clean        Stop and remove all running project containers"
	@echo ""
	@echo "Database Migrations:"
	@echo "  make init-migrations     Initialize Alembic migrations directory"
	@echo "  make make-migrations     Create a new migration (message=\"your message\")"
	@echo "  make migrate             Apply all pending database migrations"
	@echo "  make downgrade           Revert the most recent database migration"
	@echo ""
	@echo "Testing:"
	@echo "  make test                Run all test suites"
	@echo "  make test-unit           Run unit tests only"
	@echo "  make test-api            Run API route tests"
	@echo "  make test-integration    Run integration tests"
	@echo "  make test-cov            Run tests with terminal & HTML coverage report"

# ---------------------------------------------------------------------------
# Dependency management
# ---------------------------------------------------------------------------
install:
	uv sync

dev-install:
	uv sync --all-extras
	uv run pre-commit install

# ---------------------------------------------------------------------------
# Linting and formatting
# ---------------------------------------------------------------------------
lint:
	uv run ruff check .

lint-fix:
	uv run ruff check --fix .

format:
	uv run ruff check --fix .
	uv run ruff format .

format-check:
	uv run ruff format --check .
	uv run ruff check .

pre-commit:
	uv run pre-commit run --all-files

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	rm -rf htmlcov/ .coverage coverage.xml celerybeat-schedule build/ dist/ *.egg-info

# ---------------------------------------------------------------------------
# Application execution
# ---------------------------------------------------------------------------
run:
	uv run uvicorn src.main:app --reload

celery-worker:
	uv run celery -A src.tasks.celery_app worker --loglevel=info

celery-beat:
	uv run celery -A src.tasks.celery_app beat --loglevel=info

flower:
	uv run celery -A src.tasks.celery_app flower --port=$(or $(port),5555)

# ---------------------------------------------------------------------------
# Docker operations
# ---------------------------------------------------------------------------
docker-build:
	docker build -t $(IMAGE_NAME):$(IMAGE_TAG) .

docker-run:
	docker run --rm -it -p $(PORT):8000 --env-file .env --name $(IMAGE_NAME)-web $(IMAGE_NAME):$(IMAGE_TAG)

docker-worker:
	docker run --rm -it --env-file .env --name $(IMAGE_NAME)-worker $(IMAGE_NAME):$(IMAGE_TAG) celery -A src.tasks.celery_app worker --loglevel=info

docker-beat:
	docker run --rm -it --env-file .env --name $(IMAGE_NAME)-beat $(IMAGE_NAME):$(IMAGE_TAG) celery -A src.tasks.celery_app beat --loglevel=info

docker-migrate:
	docker run --rm -it --env-file .env $(IMAGE_NAME):$(IMAGE_TAG) alembic upgrade head

docker-cli:
	docker run --rm -it --env-file .env $(IMAGE_NAME):$(IMAGE_TAG) hook-relay-cli $(cmd)

docker-clean:
	docker stop $(IMAGE_NAME)-web $(IMAGE_NAME)-worker $(IMAGE_NAME)-beat 2>/dev/null || true
	docker rm $(IMAGE_NAME)-web $(IMAGE_NAME)-worker $(IMAGE_NAME)-beat 2>/dev/null || true

# ---------------------------------------------------------------------------
# Database migrations
# ---------------------------------------------------------------------------
init-migrations:
	uv run alembic init alembic

make-migrations:
	@if [ -z "$(message)" ]; then \
		echo "Error: Please provide a migration message using 'make make-migrations message=\"your message\"'"; \
		exit 1; \
	fi
	uv run alembic revision --autogenerate -m "$(message)"

migrate:
	uv run alembic upgrade head

downgrade:
	uv run alembic downgrade -1

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------
test:
	uv run pytest

test-unit:
	uv run pytest -m unit

test-api:
	uv run pytest -m api

test-integration:
	uv run pytest -m integration

test-cov:
	uv run pytest --cov=src --cov-report=term-missing --cov-report=html
