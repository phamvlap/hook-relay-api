from fastapi import FastAPI
from sqlalchemy import text

from src.api.deps import SessionDep
from src.api.v1.routes import router as v1_router

app = FastAPI(
    title="Hook Relay API",
    description="A simple API for relaying webhooks.",
    version="1.0",
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
async def readiness_check(session: SessionDep) -> dict[str, str]:
    session.execute(text("SELECT 1"))
    return {
        "name": "hook-relay-api",
        "version": "1.0",
        "status": "ready",
    }
