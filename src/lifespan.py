from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.infrastructure.redis.client import close_redis_pools


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    # Application startup
    yield

    # Application shutdown: gracefully close Redis connection pools
    await close_redis_pools()
