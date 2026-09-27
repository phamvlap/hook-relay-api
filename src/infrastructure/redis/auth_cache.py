import logging
import time
from collections import OrderedDict

from redis import RedisError
from src.core.context import APIKeyAuthData
from src.infrastructure.redis.client import get_async_redis_client

logger = logging.getLogger(__name__)

_CACHE_REDIS_PREFIX = "auth:api_key"
_CACHE_REDIS_TTL_SECONDS = 600  # 10 minutes in Redis
_CACHE_IN_MEMORY_TTL_SECONDS = 20  # 20 seconds in local memory
_CACHE_IN_MEMORY_MAX_ENTRIES = 5000
_CACHE_NEGATIVE_TTL_SECONDS = 30  # 30 seconds for not-found keys
_NOT_FOUND_SENTINEL = object()
NOT_FOUND_SENTINEL = _NOT_FOUND_SENTINEL


class LRUCache:
    """Thread-safe in-memory LRU cache with monotonic TTL expiration."""

    def __init__(self, max_size: int) -> None:
        self.max_size = max_size
        self._cache: OrderedDict[str, tuple[float, APIKeyAuthData | object]] = OrderedDict()

    def get(self, key: str) -> APIKeyAuthData | object | None:
        entry = self._cache.get(key)
        if entry is None:
            return None

        expires_at, cached_data = entry
        if time.monotonic() > expires_at:
            self._cache.pop(key, None)
            return None

        self._cache.move_to_end(key)
        return cached_data

    def set(self, key: str, data: APIKeyAuthData | object, ttl: float) -> None:
        if key in self._cache:
            self._cache.move_to_end(key)
        elif len(self._cache) >= self.max_size:
            self._cache.popitem(last=False)

        self._cache[key] = (time.monotonic() + ttl, data)

    def delete(self, key: str) -> None:
        self._cache.pop(key, None)

    def clear(self) -> None:
        self._cache.clear()


class AuthCache:
    """Multi-tiered (L1 In-Memory LRU + L2 Redis) cache for API Key authentication data."""

    def __init__(self) -> None:
        self._l1_cache = LRUCache(max_size=_CACHE_IN_MEMORY_MAX_ENTRIES)

    @staticmethod
    def _cache_key(key_id: str) -> str:
        return f"{_CACHE_REDIS_PREFIX}:{key_id}"

    def get_l1(self, key_id: str) -> APIKeyAuthData | object | None:
        return self._l1_cache.get(key_id)

    def set_l1(self, key_id: str, data: APIKeyAuthData) -> None:
        self._l1_cache.set(key_id, data, ttl=_CACHE_IN_MEMORY_TTL_SECONDS)

    def set_l1_negative(self, key_id: str) -> None:
        self._l1_cache.set(key_id, _NOT_FOUND_SENTINEL, ttl=_CACHE_NEGATIVE_TTL_SECONDS)

    async def get_l2(self, key_id: str) -> APIKeyAuthData | None:
        try:
            redis_client = get_async_redis_client()
            cached_json = await redis_client.get(self._cache_key(key_id))
        except RedisError as e:
            logger.warning("Redis L2 cache read error for key %s: %s", key_id, e)
            return None

        if not cached_json:
            return None

        data = APIKeyAuthData.from_json(cached_json)
        if data is not None:
            self.set_l1(key_id, data)
        return data

    async def set_l2(self, key_id: str, data: APIKeyAuthData) -> None:
        self.set_l1(key_id, data)
        try:
            redis_client = get_async_redis_client()
            await redis_client.setex(
                self._cache_key(key_id),
                _CACHE_REDIS_TTL_SECONDS,
                data.to_json(),
            )
        except RedisError as e:
            logger.warning("Redis L2 cache write error for key %s: %s", key_id, e)

    async def invalidate(self, key_id: str) -> None:
        """Invalidates both L1 and L2 cache entries (e.g. upon API key revocation)."""
        self._l1_cache.delete(key_id)
        try:
            redis_client = get_async_redis_client()
            await redis_client.delete(self._cache_key(key_id))
        except RedisError as e:
            logger.warning("Redis L2 cache invalidation error for key %s: %s", key_id, e)


auth_cache = AuthCache()
