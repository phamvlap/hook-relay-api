import logging
import time
from dataclasses import dataclass
from typing import Any

from redis import Redis as SyncRedis
from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import NoScriptError, RedisError

from src.core.rate_limit.lua_scripts import TOKEN_BUCKET_LUA

logger = logging.getLogger(__name__)

# Module-level cached SHA digests across instances
_async_script_sha: str | None = None
_sync_script_sha: str | None = None


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    """Represents the evaluation outcome of a token bucket rate limit request."""

    allowed: bool
    limit: int
    remaining: int
    retry_after: float
    reset_at: int


class TokenBucket:
    """High-performance Redis-backed atomic Token Bucket rate limiter.

    Executes an atomic Lua script in Redis that replenishes tokens based on elapsed
    time and consumes requested tokens in a single network round-trip.
    """

    def __init__(self, redis_client: AsyncRedis, prefix: str = "rl") -> None:
        self.redis = redis_client
        self.prefix = prefix

    @classmethod
    def reset_cached_script_sha(cls) -> None:
        """Resets cached Lua script SHA digests (useful for testing and Redis failovers)."""
        global _async_script_sha, _sync_script_sha
        _async_script_sha = None
        _sync_script_sha = None

    async def _get_script_sha(self) -> str:
        global _async_script_sha
        if _async_script_sha is None:
            _async_script_sha = await self.redis.script_load(TOKEN_BUCKET_LUA)
        return _async_script_sha

    async def acquire(
        self,
        *,
        key: str,
        capacity: int,
        refill_rate: float,
        cost: int = 1,
        fail_open: bool = True,
    ) -> RateLimitResult:
        """Asynchronously requests tokens from the specified bucket.

        Args:
            key: Unique bucket identifier (e.g. 'inbound:tenant:<uuid>:ingest').
            capacity: Maximum bucket burst capacity.
            refill_rate: Refill rate in tokens per second.
            cost: Number of tokens requested.
            fail_open: If True, allows requests upon Redis failures to avoid blocking traffic.

        Returns:
            RateLimitResult containing rate limit decision and quota telemetry.
        """
        redis_key = f"{self.prefix}:{key}"
        try:
            sha = await self._get_script_sha()
            try:
                raw_res = await self.redis.evalsha(
                    sha,
                    1,
                    redis_key,
                    str(capacity),
                    str(refill_rate),
                    str(cost),
                )
            except NoScriptError:
                global _async_script_sha
                _async_script_sha = await self.redis.script_load(TOKEN_BUCKET_LUA)
                raw_res = await self.redis.evalsha(
                    _async_script_sha,
                    1,
                    redis_key,
                    str(capacity),
                    str(refill_rate),
                    str(cost),
                )

            res = list(raw_res) if isinstance(raw_res, (list, tuple)) else []
            if len(res) >= 4:
                allowed = bool(int(res[0]))
                remaining = max(0, int(float(res[1])))
                retry_after = max(0.0, float(res[2]))
                reset_at = int(res[3])
            else:
                # Fallback in case of unexpected mock or malformed response
                allowed = True
                remaining = capacity
                retry_after = 0.0
                reset_at = int(time.time()) + 1

            return RateLimitResult(
                allowed=allowed,
                limit=capacity,
                remaining=remaining,
                retry_after=retry_after,
                reset_at=reset_at,
            )

        except (RedisError, Exception) as e:
            logger.warning("TokenBucket async error for key '%s': %s", redis_key, e)
            if fail_open:
                return RateLimitResult(
                    allowed=True,
                    limit=capacity,
                    remaining=capacity,
                    retry_after=0.0,
                    reset_at=int(time.time()) + 1,
                )
            raise

    @classmethod
    def acquire_sync(
        cls,
        sync_redis: SyncRedis,
        key: str,
        capacity: int,
        refill_rate: float,
        cost: int = 1,
        prefix: str = "rl",
        fail_open: bool = True,
    ) -> RateLimitResult:
        """Synchronously requests tokens from the bucket (for Celery workers & sync jobs)."""
        global _sync_script_sha
        redis_key = f"{prefix}:{key}"
        try:
            if _sync_script_sha is None:
                _sync_script_sha = sync_redis.script_load(TOKEN_BUCKET_LUA)

            try:
                raw_res: Any = sync_redis.evalsha(
                    _sync_script_sha,
                    1,
                    redis_key,
                    str(capacity),
                    str(refill_rate),
                    str(cost),
                )
            except NoScriptError:
                _sync_script_sha = sync_redis.script_load(TOKEN_BUCKET_LUA)
                raw_res = sync_redis.evalsha(
                    _sync_script_sha,
                    1,
                    redis_key,
                    str(capacity),
                    str(refill_rate),
                    str(cost),
                )

            res = list(raw_res) if isinstance(raw_res, (list, tuple)) else []
            if len(res) >= 4:
                allowed = bool(int(res[0]))
                remaining = max(0, int(float(res[1])))
                retry_after = max(0.0, float(res[2]))
                reset_at = int(res[3])
            else:
                allowed = True
                remaining = capacity
                retry_after = 0.0
                reset_at = int(time.time()) + 1

            return RateLimitResult(
                allowed=allowed,
                limit=capacity,
                remaining=remaining,
                retry_after=retry_after,
                reset_at=reset_at,
            )

        except (RedisError, Exception) as e:
            logger.warning("TokenBucket sync error for key '%s': %s", redis_key, e)
            if fail_open:
                return RateLimitResult(
                    allowed=True,
                    limit=capacity,
                    remaining=capacity,
                    retry_after=0.0,
                    reset_at=int(time.time()) + 1,
                )
            raise
