help:
	@echo "Available commands:"
	@echo "  make install            Install dependencies"
	@echo "  make dev-install        Install development dependencies and pre-commit hooks"
	@echo "  make run                Run the application"
	@echo "  make init-migrations    Initialize Alembic migrations"
	@echo "  make make-migrations    Create a new migration (provide a message with 'make make-migrations message=\"your message\"')"
	@echo "  make migrate            Apply database migrations"
	@echo "  make downgrade          Revert the last database migration"

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
