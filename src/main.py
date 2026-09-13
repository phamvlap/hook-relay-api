from fastapi import FastAPI
from sqlalchemy import text

from api.deps import SessionDep

app = FastAPI()


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
