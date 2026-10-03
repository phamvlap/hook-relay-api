from typing import Any, cast

from celery import Task
from celery.exceptions import OperationalError as CeleryOperationalError
from celery.exceptions import TimeoutError as CeleryTimeoutError
from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
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
from src.tasks.general import health_check_task

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


@app.get("/celery-health", tags=["Health"])
def celery_health_check() -> dict[str, str | None]:
    task = cast(Task, health_check_task)
    try:
        result = task.delay().get(timeout=2)
        error_message = None
    except (CeleryTimeoutError, CeleryOperationalError) as e:
        result = "unhealthy"
        error_message = str(e)

    return {
        "name": "hook-relay-celery",
        "version": "1.0",
        "status": "healthy" if str(result) == "healthy" else "unhealthy",
        "error_message": error_message,
    }
