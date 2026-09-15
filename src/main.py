from typing import cast

from celery import Task
from celery.exceptions import OperationalError as CeleryOperationalError
from celery.exceptions import TimeoutError as CeleryTimeoutError
from fastapi import FastAPI
from sqlalchemy import text

from src.api.deps import SessionDep
from src.api.v1.routes import router as v1_router
from src.core.error_handlers import register_exception_handlers
from src.tasks.general import health_check_task

app = FastAPI(
    title="Hook Relay API",
    description="A simple API for relaying webhooks.",
    version="1.0",
)
register_exception_handlers(app)

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
async def readiness_check(session: SessionDep) -> dict[str, str]:
    session.execute(text("SELECT 1"))
    return {
        "name": "hook-relay-api",
        "version": "1.0",
        "status": "ready",
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
