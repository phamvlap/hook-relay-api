from fastapi import FastAPI
from sqlalchemy import text

from src.api.deps import SessionDep
from src.api.v1.routes.endpoint import router as endpoint_router

app = FastAPI()

app.include_router(endpoint_router, prefix="/api/v1")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {
        "name": "hook-relay-api",
        "version": "1.0",
        "status": "healthy",
        "docs": "/docs",
        "redoc": "/redoc",
    }


@app.get("/ready")
async def readiness_check(session: SessionDep) -> dict[str, str]:
    session.execute(text("SELECT 1"))
    return {
        "name": "hook-relay-api",
        "version": "1.0",
        "status": "ready",
    }
