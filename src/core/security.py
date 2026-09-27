from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool

from src.api.deps import SessionDep
from src.core.context import APIKeyAuthData, AuthContext
from src.core.exceptions import UnauthorizedError
from src.exceptions.api_key import InvalidAPIKeyFormatError
from src.infrastructure.redis.auth_cache import NOT_FOUND_SENTINEL, auth_cache
from src.infrastructure.redis.client import get_async_redis_client
from src.infrastructure.redis.usage_buffer import APIKeyUsageBuffer
from src.models.api_key import APIKeyStatus
from src.repositories.api_key import APIKeyRepository
from src.utils.api_key import DUMMY_HASH, parse_api_key, verify_secret

bearer_scheme = HTTPBearer(
    auto_error=False,
    description="Bearer token authentication. Provide a valid API key in the Authorization header as 'Bearer <api_key>'.",
)
bearer_credentials = Depends(bearer_scheme)


async def get_auth_context_from_api_key(
    request: Request,
    session: SessionDep,
    credentials: HTTPAuthorizationCredentials | None = bearer_credentials,
) -> AuthContext:
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError()

    try:
        # 1. Parse the API key into key_id and secret_key
        key_id, secret_key = parse_api_key(credentials.credentials)
    except InvalidAPIKeyFormatError:
        raise UnauthorizedError()

    # 2. Check the in-memory cache (L1)
    l1_entry = auth_cache.get_l1(key_id)

    if l1_entry is NOT_FOUND_SENTINEL:
        cached_api_key = None
    elif isinstance(l1_entry, APIKeyAuthData):
        cached_api_key = l1_entry
    else:
        # 3. Check the Redis cache (L2)
        cached_api_key = await auth_cache.get_l2(key_id)

        # 4. Fallback to database via repository
        if cached_api_key is None:
            repo = APIKeyRepository(session)
            cached_api_key = await run_in_threadpool(repo.get_auth_data, key_id=key_id)

            if cached_api_key is not None:
                await auth_cache.set_l2(key_id, cached_api_key)
            else:
                auth_cache.set_l1_negative(key_id)

    # 5. Verify secret against expected hash (constant time comparison)
    expected_hash = cached_api_key.key_hash if cached_api_key is not None else DUMMY_HASH
    is_valid_secret = verify_secret(secret_key=secret_key, expected_hash=expected_hash)

    if cached_api_key is None or not is_valid_secret:
        raise UnauthorizedError()

    if cached_api_key.status != APIKeyStatus.ACTIVE.value:
        raise UnauthorizedError()

    # 6. Record usage in Redis write-behind buffer (sub-millisecond, non-blocking)
    usage_buffer = APIKeyUsageBuffer(get_async_redis_client())
    await usage_buffer.record_usage(cached_api_key.key_id)

    ctx = cached_api_key.to_auth_context()
    request.state.auth = ctx
    return ctx
