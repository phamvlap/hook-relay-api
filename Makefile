help:
	@echo "Available commands:"
	@echo "  make install            Install dependencies"
	@echo "  make dev-install        Install development dependencies and pre-commit hooks"
	@echo "  make run                Run the application"
	@echo "  make celery-worker      Start the Celery worker"
	@echo "  make celery-beat        Start the Celery beat scheduler"
	@echo "  make init-migrations    Initialize Alembic migrations"
	@echo "  make make-migrations    Create a new migration (provide a message with 'make make-migrations message=\"your message\"')"
	@echo "  make migrate            Apply database migrations"
	@echo "  make downgrade          Revert the last database migration"
	@echo "  make test               Run all pytest tests"
	@echo "  make test-unit          Run unit tests"
	@echo "  make test-api           Run API route tests"
	@echo "  make test-cov           Run tests with coverage report"

# Dependency management
install:
	uv sync

dev-install:
	uv sync --all-extras
# 	.venv/bin/pre-commit install

# Run the application
run:
	uv run uvicorn src.main:app --reload

celery-worker:
	uv run celery -A src.tasks.celery_app worker --loglevel=info

celery-beat:
	uv run celery -A src.tasks.celery_app beat --loglevel=info

# Database migrations
init-migrations:
	alembic init alembic

make-migrations:
	@if [ -z "$(message)" ]; then \
		echo "Error: Please provide a migration message using 'make make-migrations message=\"your message\"'"; \
		exit 1; \
	fi
	alembic revision --autogenerate -m "$(message)"

migrate:
	alembic upgrade head

downgrade:
	alembic downgrade -1

# Tests
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
