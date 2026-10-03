import logging
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request, Response

from src.core.config import settings
from src.core.context import AuthContext
from src.core.exceptions import RateLimitExceededError
from src.core.rate_limit.bucket import TokenBucket
from src.core.rate_limit.tiers import RateLimitConfig, RateLimitTiers
from src.exceptions.api_key import InvalidAPIKeyFormatError
from src.infrastructure.redis.client import get_async_redis_client
from src.utils.api_key import parse_api_key

logger = logging.getLogger(__name__)


def default_key_extractor(request: Request, tier_name: str) -> str:
    """Extracts rate limit identifier:

    1. Tenant ID (owner_id) from authenticated context if present on request.state
    2. API key ID from Bearer token if present
    3. Client IP address as fallback
    """
    # 1. Tenant identifier from authenticated context
    auth: AuthContext | None = getattr(request.state, "auth", None)
    if auth and getattr(auth, "owner_id", None):
        return f"tenant:{auth.owner_id}:{tier_name}"

    # 2. Key ID from Authorization header
    auth_header: str | None = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.removeprefix("Bearer ").strip()
        try:
            parsed = parse_api_key(token)
            return f"key:{parsed.key_id}:{tier_name}"
        except InvalidAPIKeyFormatError:
            pass

    # 3. Client IP fallback
    forwarded: str | None = request.headers.get("X-Forwarded-For")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    elif request.client and request.client.host:
        client_ip = request.client.host
    else:
        client_ip = "unknown"

    return f"ip:{client_ip}:{tier_name}"


class RateLimiter:
    """FastAPI dependency for declarative Token Bucket rate limiting."""

    def __init__(
        self,
        tier: RateLimitConfig,
        cost: int = 1,
        prefix: str = "rl:inbound",
        fail_open: bool = True,
        key_func: Callable[[Request, str], str] | None = None,
    ) -> None:
        self.tier = tier
        self.cost = cost
        self.prefix = prefix
        self.fail_open = fail_open
        self.key_func = key_func or default_key_extractor

    async def __call__(self, request: Request, response: Response) -> None:
        if not settings.rate_limit_enabled:
            return

        key = self.key_func(request, self.tier.name)
        redis_client = get_async_redis_client()
        bucket = TokenBucket(redis_client, prefix=self.prefix)

        result = await bucket.acquire(
            key=key,
            capacity=self.tier.capacity,
            refill_rate=self.tier.refill_rate,
            cost=self.cost,
            fail_open=self.fail_open,
        )

        # Populate standard RFC 6585 rate limiting telemetry headers
        response.headers["X-RateLimit-Limit"] = str(result.limit)
        response.headers["X-RateLimit-Remaining"] = str(result.remaining)
        response.headers["X-RateLimit-Reset"] = str(result.reset_at)

        if not result.allowed:
            raise RateLimitExceededError(
                message=f"Rate limit exceeded for '{self.tier.name}'. Please retry later.",
                retry_after=result.retry_after,
                limit=result.limit,
                remaining=result.remaining,
                reset=result.reset_at,
            )


# Pre-built FastAPI dependencies for each workload tier
RateLimitIngestDep = Annotated[None, Depends(RateLimiter(RateLimitTiers.INGESTION))]
RateLimitReadsDep = Annotated[None, Depends(RateLimiter(RateLimitTiers.READS))]
RateLimitWritesDep = Annotated[None, Depends(RateLimiter(RateLimitTiers.WRITES))]
RateLimitSensitiveDep = Annotated[None, Depends(RateLimiter(RateLimitTiers.SENSITIVE))]
RateLimitPublicDep = Annotated[None, Depends(RateLimiter(RateLimitTiers.PUBLIC))]
