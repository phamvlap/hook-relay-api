"""API integration tests for general/system endpoints:

- GET /health
- GET /ready
- GET /celery-health
- 404 Route handling
"""

from unittest.mock import AsyncMock

import pytest
from celery.exceptions import OperationalError as CeleryOperationalError
from fastapi import FastAPI
from httpx import AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.exc import OperationalError as SQLAlchemyOperationalError

from src.api.deps import get_db
from src.main import _APP_NAME, _APP_VERSION


# ---------------------------------------------------------------------------
# GET /health Tests
# ---------------------------------------------------------------------------
@pytest.mark.api
async def test_health_check_returns_healthy(async_client: AsyncClient):
    """Verifies that /health endpoint is available and returns 200 OK with metadata."""
    response = await async_client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == _APP_NAME
    assert data["status"] == "healthy"
    assert data["version"] == _APP_VERSION
    assert data["docs_url"] == "/docs"
    assert data["redoc_url"] == "/redoc"
    assert data["openapi_url"] == "/openapi.json"


# ---------------------------------------------------------------------------
# GET /ready Tests
# ---------------------------------------------------------------------------
@pytest.mark.api
async def test_readiness_check_success(
    app: FastAPI,
    async_client: AsyncClient,
    mocker,
):
    """Verifies that /ready returns 200 when both DB and Redis are reachable."""
    # Mock DB session execution of 'SELECT 1'
    mock_session = AsyncMock()
    mock_session.execute.return_value = None
    app.dependency_overrides[get_db] = lambda: mock_session

    # Mock Redis client ping
    mock_redis = AsyncMock()
    mock_redis.ping.return_value = True
    mocker.patch(
        "src.main.get_async_redis_client",
        return_value=mock_redis,
    )

    response = await async_client.get("/ready")

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == _APP_NAME
    assert data["status"] == "ready"
    assert "services" in data
    assert data["services"]["database"] == {
        "status": "up",
        "error_message": None,
    }
    assert data["services"]["redis"] == {
        "status": "up",
        "error_message": None,
    }
    mock_session.execute.assert_awaited_once()
    mock_redis.ping.assert_awaited_once()


@pytest.mark.api
async def test_readiness_check_fails_on_db_disconnect(
    app: FastAPI,
    async_client: AsyncClient,
    mocker,
):
    """Verifies that /ready returns 503 and marks database as down with error message."""
    mock_session = AsyncMock()
    mock_session.execute.side_effect = SQLAlchemyOperationalError(
        statement="SELECT 1",
        params={},
        orig=Exception("Connection refused"),
    )
    app.dependency_overrides[get_db] = lambda: mock_session

    # Redis is still reachable
    mock_redis = AsyncMock()
    mock_redis.ping.return_value = True
    mocker.patch("src.main.get_async_redis_client", return_value=mock_redis)

    response = await async_client.get("/ready")

    assert response.status_code == 503
    data = response.json()
    assert data["name"] == _APP_NAME
    assert data["status"] == "not_ready"
    assert "services" in data
    assert data["services"]["database"]["status"] == "down"
    assert "Connection refused" in data["services"]["database"]["error_message"]
    assert data["services"]["redis"] == {
        "status": "up",
        "error_message": None,
    }


@pytest.mark.api
async def test_readiness_check_fails_on_redis_disconnect(
    app: FastAPI,
    async_client: AsyncClient,
    mocker,
):
    """Verifies that /ready returns 503 and marks redis as down with error message."""
    # DB is reachable
    mock_session = AsyncMock()
    mock_session.execute.return_value = None
    app.dependency_overrides[get_db] = lambda: mock_session

    # Redis is unreachable
    mock_redis = AsyncMock()
    mock_redis.ping.side_effect = RedisConnectionError("Redis connection refused")
    mocker.patch("src.main.get_async_redis_client", return_value=mock_redis)

    response = await async_client.get("/ready")

    assert response.status_code == 503
    data = response.json()
    assert data["name"] == _APP_NAME
    assert data["status"] == "not_ready"
    assert "services" in data
    assert data["services"]["database"] == {
        "status": "up",
        "error_message": None,
    }
    assert data["services"]["redis"]["status"] == "down"
    assert "Redis connection refused" in data["services"]["redis"]["error_message"]


@pytest.mark.api
async def test_readiness_check_fails_when_both_disconnect(
    app: FastAPI,
    async_client: AsyncClient,
    mocker,
):
    """Verifies that /ready returns 503 and marks both services as down with error messages."""
    mock_session = AsyncMock()
    mock_session.execute.side_effect = SQLAlchemyOperationalError(
        statement="SELECT 1",
        params={},
        orig=Exception("Connection refused"),
    )
    app.dependency_overrides[get_db] = lambda: mock_session

    mock_redis = AsyncMock()
    mock_redis.ping.side_effect = RedisConnectionError("Redis connection refused")
    mocker.patch("src.main.get_async_redis_client", return_value=mock_redis)

    response = await async_client.get("/ready")

    assert response.status_code == 503
    data = response.json()
    assert data["name"] == _APP_NAME
    assert data["status"] == "not_ready"
    assert "services" in data
    assert data["services"]["database"]["status"] == "down"
    assert "Connection refused" in data["services"]["database"]["error_message"]
    assert data["services"]["redis"]["status"] == "down"
    assert "Redis connection refused" in data["services"]["redis"]["error_message"]


# ---------------------------------------------------------------------------
# GET /celery-health Tests
# ---------------------------------------------------------------------------
@pytest.mark.api
async def test_celery_health_check_healthy(async_client: AsyncClient, mocker):
    """Verifies that /celery-health returns 200 OK and healthy when Celery workers respond."""
    mocker.patch(
        "src.main._ping_celery_workers",
        return_value=[{"celery@worker1": {"ok": "pong"}}],
    )

    response = await async_client.get("/celery-health")

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Hook Relay Celery"
    assert data["status"] == "healthy"
    assert data["active_workers_count"] == 1
    assert "celery@worker1" in data["workers"]
    assert data["error_message"] is None


@pytest.mark.api
async def test_celery_health_check_no_workers_returns_503(async_client: AsyncClient, mocker):
    """Verifies that /celery-health returns 503 Service Unavailable when no workers respond."""
    mocker.patch(
        "src.main._ping_celery_workers",
        return_value=[],
    )

    response = await async_client.get("/celery-health")

    assert response.status_code == 503
    data = response.json()
    assert data["name"] == "Hook Relay Celery"
    assert data["status"] == "unhealthy"
    assert data["active_workers_count"] == 0
    assert "No active Celery workers" in data["error_message"]


@pytest.mark.api
async def test_celery_health_check_operational_error_returns_503(
    async_client: AsyncClient,
    mocker,
):
    """Verifies that /celery-health returns 503 Service Unavailable on broker operational error."""
    mocker.patch(
        "src.main._ping_celery_workers",
        side_effect=CeleryOperationalError("Cannot connect to broker"),
    )

    response = await async_client.get("/celery-health")

    assert response.status_code == 503
    data = response.json()
    assert data["name"] == "Hook Relay Celery"
    assert data["status"] == "unhealthy"
    assert "Cannot connect to broker" in data["error_message"]


# ---------------------------------------------------------------------------
# 404 Route & Middleware Handling
# ---------------------------------------------------------------------------
@pytest.mark.api
async def test_nonexistent_route_returns_404(async_client: AsyncClient):
    """Verifies that invalid routes return custom 404 error envelope."""
    response = await async_client.get("/api/v1/non-existent-route")
    assert response.status_code == 404
    data = response.json()
    assert "error" in data
    assert "message" in data["error"]


@pytest.mark.api
async def test_cors_preflight_headers_returned(async_client: AsyncClient):
    """Verifies that CORS middleware returns appropriate headers on OPTIONS requests."""
    response = await async_client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert "access-control-allow-origin" in response.headers
