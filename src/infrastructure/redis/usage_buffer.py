import logging
from datetime import UTC, datetime
from uuid import uuid4

import redis
from redis import RedisError
from redis.asyncio import Redis as AsyncRedis

logger = logging.getLogger(__name__)

BUFFER_KEY = "buffer:api_keys:last_used"
PROCESSING_PREFIX = "buffer:api_keys:last_used:processing"


class APIKeyUsageBuffer:
    """Buffers API key last_used_at timestamps in Redis to avoid per-request database writes.

    Incoming requests record their usage into a Redis Hash in sub-millisecond time.
    A scheduled Celery task atomically drains the hash and executes a single bulk
    SQL update against PostgreSQL.
    """

    def __init__(self, async_client: AsyncRedis) -> None:
        self._async_client = async_client

    async def record_usage(self, key_id: str, *, timestamp: datetime | None = None) -> None:
        """Records the last used timestamp for an API key into Redis.

        Fails gracefully if Redis is temporarily unreachable to ensure authentication
        is never blocked.
        """
        ts = (timestamp or datetime.now(UTC)).isoformat()
        try:
            await self._async_client.hset(BUFFER_KEY, key_id, ts)
        except RedisError as e:
            logger.warning("Failed to buffer API key usage for %s: %s", key_id, e)

    @staticmethod
    def drain_sync(sync_client: redis.Redis) -> dict[str, datetime]:
        """Atomically drains all buffered API key usage entries.

        Uses an atomic RENAME to a unique processing key so incoming concurrent
        requests immediately write to a fresh buffer without data loss or race conditions.
        """
        try:
            if not sync_client.exists(BUFFER_KEY):
                return {}

            processing_key = f"{PROCESSING_PREFIX}:{uuid4().hex}"
            try:
                sync_client.rename(BUFFER_KEY, processing_key)
            except redis.ResponseError:
                # Key might have been drained by another concurrent worker
                return {}

            data: dict[bytes | str, bytes | str] = sync_client.hgetall(processing_key)
            sync_client.delete(processing_key)

            usages: dict[str, datetime] = {}
            for key_id, ts in data.items():
                ts_str = ts.decode("utf-8") if isinstance(ts, bytes) else ts
                key_id_str = key_id.decode("utf-8") if isinstance(key_id, bytes) else key_id

                try:
                    usages[key_id_str] = datetime.fromisoformat(ts_str)
                except ValueError:
                    logger.warning("Invalid timestamp in usage buffer for %s: %s", key_id, ts_str)

            return usages

        except RedisError as e:
            logger.error("Failed to drain API key usage buffer: %s", e)
            return {}
