"""Global fixtures for unit and integration testing."""

import os
from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Pre-load .env.test before any application imports
# ---------------------------------------------------------------------------
_env_test_file = Path(__file__).resolve().parent.parent / ".env.test"
if _env_test_file.exists():
    load_dotenv(_env_test_file, override=True)

os.environ.setdefault("ENVIRONMENT", "test")

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from src.api.deps import get_db
from src.core.config import settings
from src.core.context import AuthContext
from src.core.security import get_auth_context_from_api_key
from src.database.db import Base
from src.main import app as application
from src.models.api_key import APIKeyEnvironment
from src.models.owner import Owner

_CLIENT_BASE_URL = "http://testserver"


# ---------------------------------------------------------------------------
# 1. Database Fixtures (Transactional Rollback Pattern)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def db_engine():
    """Session-scoped database engine.

    Connects to the test database and builds the schema once for the test session.
    Protects against running tests against remote/production databases by default.
    """
    # Safety guard: Prevent accidental test execution against remote cloud DBs
    if settings.environment == "production" and os.getenv("ALLOW_REMOTE_TEST_DB") != "true":
        raise RuntimeError(
            "SAFETY GUARD: Attempted to run database tests against a remote production database!\n"
            f"Current DSN points to: {settings.db_host} (database: {settings.db_name})\n"
            "Please create a .env.test file pointing to a local test database (e.g. localhost:5432/hook_relay_test),\n"
            "or set ALLOW_REMOTE_TEST_DB=true if this is intentional."
        )

    # Automatically create the test database on the server if it doesn't exist
    url = make_url(settings.postgres_dsn_str)
    db_name = url.database
    if db_name:
        admin_url = url.set(database="postgres")
        admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        try:
            with admin_engine.connect() as conn:
                exists = conn.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :dbname"),
                    {"dbname": db_name},
                ).scalar()
                if not exists:
                    conn.execute(text(f'CREATE DATABASE "{db_name}"'))
        except (OperationalError, ProgrammingError):
            # If user lacks permission to create db, continue and let normal connection report error
            pass
        finally:
            admin_engine.dispose()

    sync_engine = create_engine(
        settings.postgres_dsn_str,
        pool_pre_ping=True,
    )
    # Ensure tables exist
    Base.metadata.create_all(bind=sync_engine)
    sync_engine.dispose()

    engine = create_async_engine(
        settings.postgres_async_dsn_str,
        poolclass=NullPool,
        connect_args={
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
        },
    )
    yield engine
    engine.sync_engine.dispose()


@pytest.fixture
def app() -> Generator[FastAPI]:
    """FastAPI application instance with safe dependency overrides.

    Cleans up all overrides in a finally block to prevent test leakage.
    """
    yield application

    # Guarantee dependency overrides are cleared after each test
    application.dependency_overrides.clear()


@pytest.fixture(scope="function")
async def db_session(db_engine, app: FastAPI) -> AsyncGenerator[AsyncSession]:
    """Provides an isolated database session per test via transactional rollback.

    Uses SQLAlchemy 2.0's native join_transaction_mode='create_savepoint'.
    All commits, rollbacks, and nested transaction context managers (with session.begin_nested())
    inside application services operate within SAVEPOINTs, leaving the outer test
    transaction completely untouched and cleanly rolled back at test teardown.
    """
    connection = await db_engine.connect()
    transaction = await connection.begin()

    session = AsyncSession(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )

    # Hook the isolated test session into FastAPI's get_db dependency
    app.dependency_overrides[get_db] = lambda: session

    try:
        yield session
    finally:
        await session.close()
        if transaction.is_active:
            await transaction.rollback()
        await connection.close()


# ---------------------------------------------------------------------------
# 3. HTTP Clients (Async & Sync)
# ---------------------------------------------------------------------------
@pytest.fixture
async def async_client(app: FastAPI) -> AsyncGenerator[AsyncClient]:
    """Asynchronous HTTP client using httpx.ASGITransport for async endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url=_CLIENT_BASE_URL) as client:
        yield client


@pytest.fixture
def sync_client(app: FastAPI) -> Generator[TestClient]:
    """Synchronous HTTP client for testing endpoints with Starlette TestClient."""
    with TestClient(app, base_url=_CLIENT_BASE_URL) as client:
        yield client


# ---------------------------------------------------------------------------
# 4. Authentication Mocks
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_auth_context() -> AuthContext:
    """Fixture providing a mock AuthContext matching src.core.context."""
    return AuthContext(
        api_key_id=uuid4(),
        owner_id=uuid4(),
        key_id="test_key_id_12345",
        environment=APIKeyEnvironment.TEST,
    )


@pytest.fixture
def authenticated_client(app: FastAPI, mock_auth_context: AuthContext) -> FastAPI:
    """Bypasses API key authentication by overriding get_auth_context_from_api_key."""

    def _override(request: Request) -> AuthContext:
        request.state.auth = mock_auth_context
        return mock_auth_context

    app.dependency_overrides[get_auth_context_from_api_key] = _override
    return app


@pytest.fixture
async def test_owner(db_session: AsyncSession) -> Owner:
    """Creates and persists an Owner in the test database within the transactional rollback."""
    owner = Owner()
    db_session.add(owner)
    await db_session.flush()
    return owner


@pytest.fixture
def test_owner_auth(app: FastAPI, test_owner: Any) -> AuthContext:
    """Provides an AuthContext referencing the real persisted test_owner."""
    auth_ctx = AuthContext(
        api_key_id=uuid4(),
        owner_id=test_owner.id,
        key_id="test_key_persisted_owner",
        environment=APIKeyEnvironment.TEST,
    )

    def _override(request: Request) -> AuthContext:
        request.state.auth = auth_ctx
        return auth_ctx

    app.dependency_overrides[get_auth_context_from_api_key] = _override
    return auth_ctx


# ---------------------------------------------------------------------------
# 5. External Services Mocks (Redis & Celery)
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def mock_external_services(mocker):
    """Safeguards tests from real Redis or Celery broker connections.

    Applied automatically to all tests.
    """
    # Mock Redis client
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.script_load = AsyncMock(return_value="mock_script_sha")
    mock_redis.evalsha = AsyncMock(return_value=[1, "100", "0.0", 1800000000])
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.setex = AsyncMock(return_value=True)
    mock_redis.hset = AsyncMock(return_value=1)

    # Comprehensive patch: definition site, connection pool, and all consumer modules
    mocker.patch(
        "src.infrastructure.redis.client.get_async_redis_client",
        return_value=mock_redis,
    )
    mocker.patch(
        "src.infrastructure.redis.client.get_async_redis_pool",
        return_value=MagicMock(),
    )
    # mocker.patch(
    #     "src.core.rate_limit.limiter.get_async_redis_client",
    #     return_value=mock_redis,
    # )
    mocker.patch(
        "src.core.security.get_async_redis_client",
        return_value=mock_redis,
    )
    mocker.patch(
        "src.main.get_async_redis_client",
        return_value=mock_redis,
    )
    mocker.patch(
        "src.infrastructure.redis.auth_cache.get_async_redis_client",
        return_value=mock_redis,
    )
    mocker.patch(
        "src.infrastructure.redis.client.close_redis_pools",
        new_callable=AsyncMock,
    )

    # Mock Celery health check task
    mock_celery_task = MagicMock()
    mock_async_result = MagicMock()
    mock_async_result.get.return_value = "pong"
    mock_celery_task.apply_async.return_value = mock_async_result
    mocker.patch("src.main.health_check_task", mock_celery_task)

    return {
        "redis": mock_redis,
        "celery": mock_celery_task,
    }
