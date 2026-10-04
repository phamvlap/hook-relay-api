import asyncio
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

app = FastAPI(
    title="Hook Relay API",
    description="A simple API for relaying webhooks.",
    version="1.0",
    lifespan=lifespan,
)
register_exception_handlers(app)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.allowed_hosts_list,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(v1_router, prefix="/api/v1")


@app.get("/health", tags=["Health"])
def health_check() -> dict[str, str]:
    return {
        "name": "hook-relay-api",
        "version": "1.0",
        "status": "healthy",
        "docs_url": "/docs",
        "redoc_url": "/redoc",
    }


@app.get("/ready", tags=["Health"])
async def readiness_check(session: SessionDep, response: Response) -> dict[str, Any]:
    services: dict[str, str] = {
        "database": "connected",
        "redis": "connected",
    }
    is_ready = True

    # 1. Check PostgreSQL database connection
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        services["database"] = "disconnected"
        is_ready = False

    # 2. Check Redis connection
    try:
        redis_client = get_async_redis_client()
        await redis_client.ping()
    except RedisError:
        services["redis"] = "disconnected"
        is_ready = False

    # 3. If any dependency is down, return 503 Service Unavailable
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "name": "hook-relay-api",
            "version": "1.0",
            "status": "not_ready",
            "services": services,
        }

    return {
        "name": "hook-relay-api",
        "version": "1.0",
        "status": "ready",
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
        "name": "hook-relay-celery",
        "version": "1.0",
        "status": "healthy" if is_healthy else "unhealthy",
        "active_workers_count": len(worker_nodes),
        "workers": worker_nodes,
        "error_message": error_message,
    }
