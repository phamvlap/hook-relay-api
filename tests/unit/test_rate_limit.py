"""Unit tests for Token Bucket rate limiting, tiers, and FastAPI dependencies."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import Request, Response
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import NoScriptError

from src.core.config import settings
from src.core.context import AuthContext
from src.core.exceptions import RateLimitExceededError
from src.core.rate_limit.bucket import RateLimitResult, TokenBucket
from src.core.rate_limit.limiter import RateLimiter, default_key_extractor
from src.core.rate_limit.tiers import RateLimitConfig, RateLimitTierName, RateLimitTiers
from src.models.api_key import APIKeyEnvironment


@pytest.mark.unit
class TestRateLimitTierName:
    def test_tier_name_constants(self):
        assert RateLimitTierName.INGESTION == "ingest"
        assert RateLimitTierName.READS == "reads"
        assert RateLimitTierName.WRITES == "writes"
        assert RateLimitTierName.SENSITIVE == "sensitive"
        assert RateLimitTierName.PUBLIC == "public"


@pytest.mark.unit
class TestRateLimitTiers:
    def test_tier_configurations_have_valid_params(self):
        assert RateLimitTiers.INGESTION.capacity == 100
        assert RateLimitTiers.INGESTION.refill_rate == 50.0
        assert RateLimitTiers.INGESTION.name == RateLimitTierName.INGESTION

        assert RateLimitTiers.READS.capacity == 40
        assert RateLimitTiers.READS.refill_rate == 20.0
        assert RateLimitTiers.READS.name == RateLimitTierName.READS

        assert RateLimitTiers.WRITES.capacity == 20
        assert RateLimitTiers.WRITES.refill_rate == 10.0
        assert RateLimitTiers.WRITES.name == RateLimitTierName.WRITES

        assert RateLimitTiers.SENSITIVE.capacity == 5
        assert RateLimitTiers.SENSITIVE.refill_rate == 2.0
        assert RateLimitTiers.SENSITIVE.name == RateLimitTierName.SENSITIVE

        assert RateLimitTiers.PUBLIC.capacity == 15
        assert RateLimitTiers.PUBLIC.refill_rate == 5.0
        assert RateLimitTiers.PUBLIC.name == RateLimitTierName.PUBLIC

    def test_invalid_tier_config_raises_value_error(self):
        with pytest.raises(ValueError, match="capacity must be greater than 0"):
            RateLimitConfig(capacity=0, refill_rate=10.0, name="invalid")

        with pytest.raises(ValueError, match="refill_rate must be greater than 0"):
            RateLimitConfig(capacity=10, refill_rate=0.0, name="invalid")


@pytest.mark.unit
class TestTokenBucketAsync:
    @pytest.fixture(autouse=True)
    def reset_token_bucket_sha(self):
        TokenBucket.reset_cached_script_sha()
        yield
        TokenBucket.reset_cached_script_sha()

    @pytest.mark.asyncio
    async def test_acquire_allowed_when_tokens_available(self):
        mock_redis = AsyncMock()
        mock_redis.script_load = AsyncMock(return_value="mock_sha")
        mock_redis.evalsha = AsyncMock(return_value=[1, "99.0", "0.0", 1700000010])

        bucket = TokenBucket(redis_client=mock_redis, prefix="rl:test")
        result = await bucket.acquire(
            key="test_key",
            capacity=100,
            refill_rate=50.0,
            cost=1,
        )

        assert isinstance(result, RateLimitResult)
        assert result.allowed is True
        assert result.limit == 100
        assert result.remaining == 99
        assert result.retry_after == 0.0
        assert result.reset_at == 1700000010
        mock_redis.evalsha.assert_called_once()

    @pytest.mark.asyncio
    async def test_acquire_rejected_when_tokens_exhausted(self):
        mock_redis = AsyncMock()
        mock_redis.script_load = AsyncMock(return_value="mock_sha")
        mock_redis.evalsha = AsyncMock(return_value=[0, "0.0", "2.5", 1700000015])

        bucket = TokenBucket(redis_client=mock_redis, prefix="rl:test")
        result = await bucket.acquire(
            key="test_key",
            capacity=100,
            refill_rate=50.0,
            cost=1,
        )

        assert result.allowed is False
        assert result.remaining == 0
        assert result.retry_after == 2.5
        assert result.reset_at == 1700000015

    @pytest.mark.asyncio
    async def test_acquire_handles_no_script_error_and_reloads(self):
        mock_redis = AsyncMock()
        mock_redis.script_load = AsyncMock(return_value="new_sha")
        mock_redis.evalsha = AsyncMock(
            side_effect=[NoScriptError("NOSCRIPT"), [1, "49.0", "0.0", 1700000020]]
        )

        bucket = TokenBucket(redis_client=mock_redis, prefix="rl:test")
        result = await bucket.acquire(
            key="test_key",
            capacity=50,
            refill_rate=25.0,
        )

        assert result.allowed is True
        assert result.remaining == 49
        assert mock_redis.evalsha.call_count == 2
        mock_redis.script_load.assert_called()

    @pytest.mark.asyncio
    async def test_acquire_fail_open_on_redis_error(self):
        mock_redis = AsyncMock()
        mock_redis.script_load = AsyncMock(side_effect=RedisConnectionError("Redis down"))
        mock_redis.evalsha = AsyncMock(side_effect=RedisConnectionError("Redis down"))

        bucket = TokenBucket(redis_client=mock_redis, prefix="rl:test")
        result = await bucket.acquire(
            key="test_key",
            capacity=50,
            refill_rate=25.0,
            fail_open=True,
        )

        assert result.allowed is True
        assert result.limit == 50
        assert result.remaining == 50
        assert result.retry_after == 0.0

    @pytest.mark.asyncio
    async def test_acquire_raises_when_fail_open_disabled(self):
        mock_redis = AsyncMock()
        mock_redis.script_load = AsyncMock(side_effect=RedisConnectionError("Redis down"))
        mock_redis.evalsha = AsyncMock(side_effect=RedisConnectionError("Redis down"))

        bucket = TokenBucket(redis_client=mock_redis, prefix="rl:test")
        with pytest.raises(RedisConnectionError):
            await bucket.acquire(
                key="test_key",
                capacity=50,
                refill_rate=25.0,
                fail_open=False,
            )


@pytest.mark.unit
class TestTokenBucketSync:
    @pytest.fixture(autouse=True)
    def reset_token_bucket_sync_sha(self):
        TokenBucket.reset_cached_script_sha()
        yield
        TokenBucket.reset_cached_script_sha()

    def test_acquire_sync_evaluates_correctly(self):
        mock_redis = MagicMock()
        mock_redis.script_load.return_value = "sync_sha"
        mock_redis.evalsha.return_value = [1, "19.0", "0.0", 1700000005]

        result = TokenBucket.acquire_sync(
            sync_redis=mock_redis,
            key="sync_key",
            capacity=20,
            refill_rate=10.0,
        )

        assert result.allowed is True
        assert result.limit == 20
        assert result.remaining == 19
        assert result.retry_after == 0.0

    def test_acquire_sync_fail_open_on_redis_error(self):
        mock_redis = MagicMock()
        mock_redis.script_load.side_effect = RedisConnectionError("Redis down")
        mock_redis.evalsha.side_effect = RedisConnectionError("Redis down")

        result = TokenBucket.acquire_sync(
            sync_redis=mock_redis,
            key="sync_key",
            capacity=20,
            refill_rate=10.0,
            fail_open=True,
        )

        assert result.allowed is True
        assert result.limit == 20
        assert result.remaining == 20
        assert result.retry_after == 0.0

    def test_acquire_sync_raises_when_fail_open_disabled(self):
        mock_redis = MagicMock()
        mock_redis.script_load.side_effect = RedisConnectionError("Redis down")
        mock_redis.evalsha.side_effect = RedisConnectionError("Redis down")

        with pytest.raises(RedisConnectionError):
            TokenBucket.acquire_sync(
                sync_redis=mock_redis,
                key="sync_key",
                capacity=20,
                refill_rate=10.0,
                fail_open=False,
            )


@pytest.mark.unit
class TestKeyExtractor:
    def test_extract_key_from_auth_context_on_state(self):
        owner_id = uuid4()
        mock_request = MagicMock(spec=Request)
        mock_request.state.auth = AuthContext(
            api_key_id=uuid4(),
            owner_id=owner_id,
            key_id="test_key",
            environment=APIKeyEnvironment.TEST,
        )

        key = default_key_extractor(mock_request, tier_name=RateLimitTierName.INGESTION)
        assert key == f"tenant:{owner_id}:{RateLimitTierName.INGESTION}"

    def test_extract_key_from_ip_fallback(self):
        mock_request = MagicMock(spec=Request)
        mock_request.state = MagicMock()
        mock_request.state.auth = None
        mock_request.headers.get.side_effect = lambda h: (
            "203.0.113.195, 10.0.0.1" if h == "X-Forwarded-For" else None
        )
        mock_request.client.host = "192.168.1.1"

        key = default_key_extractor(mock_request, tier_name=RateLimitTierName.READS)
        assert key == f"ip:203.0.113.195:{RateLimitTierName.READS}"


@pytest.mark.unit
class TestRateLimiterDependency:
    @pytest.mark.asyncio
    async def test_rate_limiter_sets_headers_on_success(self, mocker):
        mock_redis = AsyncMock()
        mock_redis.script_load = AsyncMock(return_value="mock_sha")
        mock_redis.evalsha = AsyncMock(return_value=[1, "39.0", "0.0", 1700000050])
        mocker.patch(
            "src.core.rate_limit.limiter.get_async_redis_client",
            return_value=mock_redis,
        )

        limiter = RateLimiter(tier=RateLimitTiers.READS)
        request = MagicMock(spec=Request)
        request.state.auth = None
        request.headers.get.return_value = None
        request.client.host = "127.0.0.1"

        response = Response()
        await limiter(request, response)

        assert response.headers["X-RateLimit-Limit"] == "40"
        assert response.headers["X-RateLimit-Remaining"] == "39"
        assert response.headers["X-RateLimit-Reset"] == "1700000050"

    @pytest.mark.asyncio
    async def test_rate_limiter_raises_when_quota_exhausted(self, mocker):
        mock_redis = AsyncMock()
        mock_redis.script_load = AsyncMock(return_value="mock_sha")
        mock_redis.evalsha = AsyncMock(return_value=[0, "0.0", "1.75", 1700000060])
        mocker.patch(
            "src.core.rate_limit.limiter.get_async_redis_client",
            return_value=mock_redis,
        )

        limiter = RateLimiter(tier=RateLimitTiers.SENSITIVE)
        request = MagicMock(spec=Request)
        request.state.auth = None
        request.headers.get.return_value = None
        request.client.host = "127.0.0.1"

        response = Response()
        with pytest.raises(RateLimitExceededError) as exc_info:
            await limiter(request, response)

        assert exc_info.value.limit == 5
        assert exc_info.value.remaining == 0
        assert exc_info.value.retry_after == 1.75
        assert exc_info.value.reset == 1700000060

    @pytest.mark.asyncio
    async def test_rate_limiter_bypasses_when_disabled(self, mocker):
        mocker.patch.object(settings, "rate_limit_enabled", False)
        mock_redis = AsyncMock()
        mocker.patch(
            "src.core.rate_limit.limiter.get_async_redis_client",
            return_value=mock_redis,
        )

        limiter = RateLimiter(tier=RateLimitTiers.INGESTION)
        request = MagicMock(spec=Request)
        response = Response()

        await limiter(request, response)
        mock_redis.evalsha.assert_not_called()
