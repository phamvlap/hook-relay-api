import hashlib
import hmac
import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis import RedisError
from redis.asyncio import ConnectionPool, Redis
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from src.api.deps import SessionDep
from src.core.config import settings
from src.core.exceptions import UnauthorizedError
from src.exceptions.api_key import InvalidAPIKeyFormatError
from src.models.api_key import APIKey, APIKeyEnvironment, APIKeyStatus

bearer_scheme = HTTPBearer(
    auto_error=False,
    description="Bearer token authentication. Provide a valid API key in the Authorization header as 'Bearer <api_key>'.",
)
bearer_credentials = Depends(bearer_scheme)

_KEY_PREFIX = "hr"


def parse_api_key(raw_key: str) -> tuple[str, str]:
    parts = raw_key.strip().split("_", 3)

    if len(parts) != 4 or parts[0] != _KEY_PREFIX or parts[1] not in APIKeyEnvironment.values():
        raise InvalidAPIKeyFormatError("Malformed API key format")

    _, _, key_id, secret_key = parts

    return key_id, secret_key


def hash_secret(secret: str) -> str:
    return hmac.new(
        key=settings.api_key_pepper_value.encode(),
        msg=secret.encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()


def verify_secret(secret_key: str, expected_hash: str) -> bool:
    computed_hash = hash_secret(secret_key)
    return hmac.compare_digest(computed_hash, expected_hash)


@dataclass(frozen=True, slots=True)
class AuthContext:
    api_key_id: UUID
    owner_id: UUID | str
    key_id: str
    environment: APIKeyEnvironment


@dataclass(frozen=True, slots=True)
class CachedAuthData:
    api_key_id: UUID
    owner_id: UUID
    key_id: str
    key_hash: str
    status: APIKeyStatus
    environment: APIKeyEnvironment

    def to_auth_context(self) -> AuthContext:
        return AuthContext(
            api_key_id=self.api_key_id,
            owner_id=self.owner_id,
            key_id=self.key_id,
            environment=self.environment,
        )

    def to_json(self) -> str:
        return json.dumps(
            {
                "api_key_id": str(self.api_key_id),
                "owner_id": str(self.owner_id),
                "key_id": self.key_id,
                "key_hash": self.key_hash,
                "status": self.status.value,
                "environment": self.environment.value,
            }
        )

    @classmethod
    def from_json(cls, payload: str | bytes) -> "CachedAuthData | None":
        try:
            json_data = json.loads(payload)

            return cls(
                api_key_id=UUID(json_data["api_key_id"]),
                owner_id=UUID(json_data["owner_id"]),
                key_id=json_data["key_id"],
                key_hash=json_data["key_hash"],
                status=APIKeyStatus(json_data["status"]),
                environment=APIKeyEnvironment(json_data["environment"]),
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            return None


_CACHE_REDIS_PREFIX = "auth:api_key"  # Prefix for Redis keys used in the authentication cache
_CACHE_REDIS_TTL_SECONDS = 600  # TTL for Redis cache entries (10 minutes)
_CACHE_IN_MEMORY_TTL_SECONDS = 20  # TTL for in-memory cache entries (20 seconds)
_CACHE_IN_MEMORY_MAX_ENTRIES = 5000  # Maximum number of entries in the in-memory cache
_DUMMY_HASH = "0" * 64  # Dummy hash for timing attack mitigation
_CACHE_NEGATIVE_TTL_SECONDS = 30  # TTL for negative cache entries (not found in DB)
_NOT_FOUND_SENTINEL = object()  # Sentinel value for negative cache entries


class LRUCache:
    def __init__(self, max_size: int) -> None:
        self.max_size = max_size
        self._cache: OrderedDict[str, tuple[float, CachedAuthData | object]] = OrderedDict()

    def get(self, key: str) -> CachedAuthData | object | None:
        entry = self._cache.get(key)
        if entry is None:
            return None

        expires_at, cached_data = entry
        if time.monotonic() > expires_at:
            self._cache.pop(key, None)
            return None

        self._cache.move_to_end(key)
        return cached_data

    def set(self, key: str, data: CachedAuthData | object, ttl: float) -> None:
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
    def __init__(self) -> None:
        self._l1_cache = LRUCache(max_size=_CACHE_IN_MEMORY_MAX_ENTRIES)
        self._redis_cache: Redis | None = None
        self._redis_pool: ConnectionPool | None = None

    def get_redis_cache(self) -> Redis:
        if self._redis_cache is None:
            self._redis_pool = ConnectionPool.from_url(
                settings.redis_dsn_str,
                max_connections=20,
                decode_responses=True,
            )
            self._redis_cache = Redis(connection_pool=self._redis_pool)
        return self._redis_cache

    async def aclose(self) -> None:
        if self._redis_cache is not None:
            await self._redis_cache.close()
            self._redis_cache = None

        if self._redis_pool is not None:
            await self._redis_pool.disconnect()
            self._redis_pool = None

    def _cache_key(self, key_id: str) -> str:
        return f"{_CACHE_REDIS_PREFIX}:{key_id}"

    def get_l1(self, key_id: str) -> CachedAuthData | object | None:
        return self._l1_cache.get(key_id)

    def set_l1(self, key_id: str, data: CachedAuthData) -> None:
        self._l1_cache.set(key_id, data, ttl=_CACHE_IN_MEMORY_TTL_SECONDS)

    def set_l1_negative(self, key_id: str) -> None:
        self._l1_cache.set(key_id, _NOT_FOUND_SENTINEL, ttl=_CACHE_NEGATIVE_TTL_SECONDS)

    async def get_l2(self, key_id: str) -> CachedAuthData | None:
        try:
            redis_cache = self.get_redis_cache()
            cached_json = await redis_cache.get(self._cache_key(key_id))
        except RedisError:
            return None

        if not cached_json:
            return None

        data = CachedAuthData.from_json(cached_json)
        if data is not None:
            self.set_l1(key_id, data)
        return data

    async def set_l2(self, key_id: str, data: CachedAuthData) -> None:
        self.set_l1(key_id, data)

        try:
            redis_cache = self.get_redis_cache()
            await redis_cache.setex(
                self._cache_key(key_id),
                _CACHE_REDIS_TTL_SECONDS,
                data.to_json(),
            )
        except RedisError:
            pass

    async def delete(self, key_id: str) -> None:
        self._l1_cache.delete(key_id)

        try:
            redis_cache = self.get_redis_cache()
            await redis_cache.delete(self._cache_key(key_id))
        except RedisError:
            pass


def _query_api_key(session: Session, key_id: str) -> CachedAuthData | None:
    stmt = select(APIKey).where(
        APIKey.key_id == key_id,
        APIKey.deleted_at.is_(None),
    )
    api_key = session.scalars(stmt).first()

    if api_key is None:
        return None

    return CachedAuthData(
        api_key_id=api_key.id,
        owner_id=api_key.owner_id,
        key_id=api_key.key_id,
        key_hash=api_key.key_hash,
        status=api_key.status,
        environment=api_key.environment,
    )


auth_cache = AuthCache()


async def get_auth_context_from_api_key(
    request: Request,
    session: SessionDep,
    credentials: HTTPAuthorizationCredentials | None = bearer_credentials,
) -> AuthContext:
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError()

    try:
        # Parse the API key to extract its components
        key_id, secret_key = parse_api_key(credentials.credentials)
    except InvalidAPIKeyFormatError:
        raise UnauthorizedError()

    # Check the in-memory cache (L1) for the API key data
    l1_entry = auth_cache.get_l1(key_id)

    # Negative cache hit: API key not found in L1 cache
    if l1_entry is _NOT_FOUND_SENTINEL:
        cached_api_key = None

    # Positive cache hit: API key found in L1 cache
    elif isinstance(l1_entry, CachedAuthData):
        cached_api_key = l1_entry

    else:
        # Check the Redis cache (L2) for the API key data
        cached_api_key = await auth_cache.get_l2(key_id)

        # Check the database fallback if not found in L2 cache
        if cached_api_key is None:
            cached_api_key = await run_in_threadpool(_query_api_key, session, key_id=key_id)

            # Set the API key data in both L1 and L2 caches if found, or set negative cache if not found
            if cached_api_key is not None:
                await auth_cache.set_l2(key_id, cached_api_key)
            else:
                auth_cache.set_l1_negative(key_id)

    # Verify the provided secret key against the expected hash from the cached API key data
    expected_hash = cached_api_key.key_hash if cached_api_key is not None else _DUMMY_HASH
    is_valid_secret = verify_secret(secret_key=secret_key, expected_hash=expected_hash)

    if cached_api_key is None or not is_valid_secret:
        raise UnauthorizedError()

    if cached_api_key.status != APIKeyStatus.ACTIVE.value:
        raise UnauthorizedError()

    ctx = cached_api_key.to_auth_context()
    request.state.auth = ctx
    return ctx
