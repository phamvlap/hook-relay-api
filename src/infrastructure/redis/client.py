import logging

from redis import ConnectionPool, Redis
from redis.asyncio import ConnectionPool as AsyncConnectionPool
from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import RedisError
from src.core.config import settings

logger = logging.getLogger(__name__)

_async_pool: AsyncConnectionPool | None = None
_sync_pool: ConnectionPool | None = None


def get_async_redis_pool() -> AsyncConnectionPool:
    global _async_pool
    if _async_pool is None:
        _async_pool = AsyncConnectionPool.from_url(
            settings.redis_dsn_str,
            max_connections=50,
            decode_responses=True,
        )
    return _async_pool


def get_async_redis_client() -> AsyncRedis:
    """Returns an async Redis client backed by the global connection pool."""
    return AsyncRedis(connection_pool=get_async_redis_pool())


def get_sync_redis_pool() -> ConnectionPool:
    global _sync_pool
    if _sync_pool is None:
        _sync_pool = ConnectionPool.from_url(
            settings.redis_dsn_str,
            max_connections=20,
            decode_responses=True,
        )
    return _sync_pool


def get_sync_redis_client() -> Redis:
    """Returns a synchronous Redis client backed by the sync connection pool (for Celery / scripts)."""
    return Redis(connection_pool=get_sync_redis_pool())


async def close_redis_pools() -> None:
    """Gracefully closes Redis connection pools during application shutdown."""
    global _async_pool, _sync_pool
    if _async_pool is not None:
        try:
            await _async_pool.disconnect()
            logger.info("Async Redis connection pool closed.")
        except RedisError as e:
            logger.warning("Error disconnecting async Redis pool: %s", e)
        finally:
            _async_pool = None

    if _sync_pool is not None:
        try:
            _sync_pool.disconnect()
            logger.info("Sync Redis connection pool closed.")
        except RedisError as e:
            logger.warning("Error disconnecting sync Redis pool: %s", e)
        finally:
            _sync_pool = None
