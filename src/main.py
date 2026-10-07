import asyncio
import logging
from typing import Any

from celery.exceptions import CeleryError
from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from kombu.exceptions import OperationalError as KombuOperationalError
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from src.api.deps import SessionDep
from src.api.v1.routes import router as v1_router
from src.core.config import settings
from src.core.error_handlers import register_exception_handlers
from src.infrastructure.redis.client import get_async_redis_client
from src.lifespan import lifespan
from src.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# Swagger UI developer experience configuration
_SWAGGER_UI_PARAMETERS = {
    "persistAuthorization": True,  # Keeps authorization token/key on page refresh
    "displayRequestDuration": True,  # Displays request duration in milliseconds
    "filter": True,  # Adds quick search bar in Swagger UI
    "tryItOutEnabled": True,  # Expands "Try it out" by default
    "docExpansion": "list",  # Collapses operation details for faster scrolling
}

# OpenAPI Tag Metadata for clean grouping in docs
_OPENAPI_TAGS = [
    {
        "name": "Health",
        "description": "Liveness and readiness probes for service health monitoring.",
    },
    {
        "name": "Endpoints",
        "description": "Webhook endpoint destinations, secrets, and configurations.",
    },
    {
        "name": "Events",
        "description": "Ingested webhook events and dispatch status.",
    },
    {
        "name": "Deliveries",
        "description": "Webhook delivery attempts, payloads, and execution history.",
    },
]

_APP_NAME = "Hook Relay API"
_APP_DESCRIPTION = "A high-throughput webhook delivery, retry, and ingestion engine."
_APP_VERSION = "1.0.0"

app = FastAPI(
    title=_APP_NAME,
    description=_APP_DESCRIPTION,
    version=_APP_VERSION,
    lifespan=lifespan,
    docs_url=settings.docs_url,
    redoc_url=settings.redoc_url,
    openapi_url=settings.openapi_url,
    openapi_tags=_OPENAPI_TAGS,
    swagger_ui_parameters=_SWAGGER_UI_PARAMETERS,
)
register_exception_handlers(app)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.allowed_hosts_list,
)
if settings.cors_enabled:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            "X-Request-ID",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
            "Retry-After",
        ],
        max_age=settings.cors_max_age,
    )

app.include_router(v1_router, prefix="/api/v1")


@app.get("/health", tags=["Health"])
def health_check() -> dict[str, Any]:
    return {
        "name": _APP_NAME,
        "version": _APP_VERSION,
        "status": "healthy",
        "docs_url": settings.docs_url,
        "redoc_url": settings.redoc_url,
        "openapi_url": settings.openapi_url,
    }


@app.get("/ready", tags=["Health"])
async def readiness_check(session: SessionDep, response: Response) -> dict[str, Any]:
    """Readiness probe validating connectivity to PostgreSQL and Redis.

    Returns service state as 'up' or 'down'. If any critical dependency is down,
    returns 503 Service Unavailable with descriptive error details.
    """
    _UP_STATUS = "up"
    _DOWN_STATUS = "down"
    _READY_STATUS = "ready"
    _NOT_READY_STATUS = "not_ready"

    services: dict[str, dict[str, Any]] = {
        "database": {
            "status": _UP_STATUS,
            "error_message": None,
        },
        "redis": {
            "status": _UP_STATUS,
            "error_message": None,
        },
    }

    # 1. Check PostgreSQL database connection
    try:
        await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError, TimeoutError) as exc:
        services["database"] = {
            "status": _DOWN_STATUS,
            "error_message": str(exc),
        }

    # 2. Check Redis connection
    try:
        redis_client = get_async_redis_client()
        await redis_client.ping()
    except (RedisError, OSError, TimeoutError) as exc:
        services["redis"] = {
            "status": _DOWN_STATUS,
            "error_message": str(exc),
        }

    ready_status = (
        _READY_STATUS
        if all(service["status"] == _UP_STATUS for service in services.values())
        else _NOT_READY_STATUS
    )

    # 3. If any dependency is down, return 503 Service Unavailable
    if ready_status == _NOT_READY_STATUS:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        logger.warning(
            "Readiness probe failed: %s",
            {
                name: service["error_message"]
                for name, service in services.items()
                if service["status"] == _DOWN_STATUS
            },
        )

    return {
        "name": _APP_NAME,
        "status": ready_status,
        "services": services,
    }


def _ping_celery_workers(timeout: float = 1.0) -> list[dict[str, Any]]:
    """Broadcasts a control ping to active Celery workers without queuing tasks."""
    return celery_app.control.ping(timeout=timeout) or []


@app.get("/celery-health", tags=["Health"])
async def celery_health_check(response: Response) -> dict[str, Any]:
    """Non-blocking health check for the Celery subsystem.

    Verifies broker connectivity and worker presence via broadcast control ping
    without polluting the task queue or blocking application threads.
    """
    error_message: str | None = None
    worker_nodes: list[str] = []

    try:
        worker_responses = await asyncio.to_thread(_ping_celery_workers, timeout=1.0)
        for resp in worker_responses:
            for node, status_dict in resp.items():
                if status_dict.get("ok") == "pong":
                    worker_nodes.append(node)

        if not worker_nodes:
            error_message = "No active Celery workers responded to control ping."

    except (CeleryError, KombuOperationalError, TimeoutError, OSError) as exc:
        error_message = f"Celery broker or worker communication failure: {exc!s}"

    is_healthy = len(worker_nodes) > 0 and error_message is None

    if not is_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "name": "Hook Relay Celery",
        "status": "healthy" if is_healthy else "unhealthy",
        "active_workers_count": len(worker_nodes),
        "workers": worker_nodes,
        "error_message": error_message,
    }
