"""Unit tests for the complete retry subsystem:

- Backoff algorithms (Fixed, Linear, Exponential)
- Jitter strategies (NoJitter, FullJitter, EqualJitter, AdditiveJitter)
- Retry-After header parsing
- RetryPolicy decision logic & delay computation
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from src.core.retry.backoff import ExponentialBackoff, FixedBackoff, LinearBackoff
from src.core.retry.jitter import (
    AdditiveJitter,
    EqualJitter,
    FullJitter,
    NoJitter,
    create_jitter_strategy,
)
from src.core.retry.parser import parse_retry_after
from src.core.retry.policy import RetryPolicy
from src.core.retry.presets import webhook_delivery_policy


# ---------------------------------------------------------------------------
# Backoff Algorithms
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestBackoffAlgorithms:
    def test_fixed_backoff_always_constant(self):
        backoff = FixedBackoff(delay=10.0)
        assert backoff.calculate(0) == 10.0
        assert backoff.calculate(1) == 10.0
        assert backoff.calculate(5) == 10.0

    def test_linear_backoff_increments_linearly(self):
        backoff = LinearBackoff(base_delay=2.0, max_delay=10.0)
        # base_delay * (attempt + 1)
        assert backoff.calculate(0) == 2.0
        assert backoff.calculate(1) == 4.0
        assert backoff.calculate(2) == 6.0
        assert backoff.calculate(4) == 10.0
        # Clamped to max_delay
        assert backoff.calculate(10) == 10.0

    def test_exponential_backoff_doubles_and_clamps(self):
        backoff = ExponentialBackoff(base_delay=1.0, factor=2.0, max_delay=30.0)
        # base_delay * (factor ** attempt)
        assert backoff.calculate(0) == 1.0
        assert backoff.calculate(1) == 2.0
        assert backoff.calculate(2) == 4.0
        assert backoff.calculate(3) == 8.0
        assert backoff.calculate(4) == 16.0
        # Clamped to max_delay
        assert backoff.calculate(5) == 30.0


# ---------------------------------------------------------------------------
# Jitter Strategies
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestJitterStrategies:
    def test_no_jitter_returns_exact_delay(self):
        jitter = NoJitter()
        assert jitter.apply(delay=15.0) == 15.0
        assert jitter.apply(delay=0.0) == 0.0

    def test_full_jitter_bounds(self):
        jitter = FullJitter()
        delay = 10.0
        for _ in range(50):
            res = jitter.apply(delay=delay)
            assert 0.0 <= res <= delay

    def test_equal_jitter_bounds(self):
        jitter = EqualJitter()
        delay = 10.0
        for _ in range(50):
            res = jitter.apply(delay=delay)
            # Equal jitter is delay/2 + U(0, delay/2) -> between 5.0 and 10.0
            assert 5.0 <= res <= delay

    def test_additive_jitter_bounds(self):
        jitter = AdditiveJitter(max_jitter=2.0)
        delay = 10.0
        for _ in range(50):
            res = jitter.apply(delay=delay)
            # delay + U(0, max_jitter) -> between 10.0 and 12.0
            assert 10.0 <= res <= 12.0

    def test_create_jitter_strategy_factory(self):
        assert isinstance(create_jitter_strategy("none"), NoJitter)
        assert isinstance(create_jitter_strategy("full"), FullJitter)
        assert isinstance(create_jitter_strategy("equal"), EqualJitter)
        assert isinstance(
            create_jitter_strategy("additive", max_additive_jitter=1.5), AdditiveJitter
        )


# ---------------------------------------------------------------------------
# Retry-After Header Parsing
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestRetryAfterParsing:
    def test_parse_integer_and_float_seconds(self):
        assert parse_retry_after("120") == 120.0
        assert parse_retry_after("45.5") == 45.5
        assert parse_retry_after("0") == 0.0
        assert parse_retry_after("-10") == 0.0  # Clamped to 0

    def test_parse_http_date(self):
        now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
        target = now + timedelta(seconds=60)
        # RFC 2822 format: "Thu, 01 Oct 2026 12:01:00 GMT"
        http_date_str = target.strftime("%a, %d %b %Y %H:%M:%S GMT")

        delay = parse_retry_after(http_date_str, now=now)
        assert delay is not None
        assert round(delay) == 60

    def test_parse_invalid_or_empty_returns_none(self):
        assert parse_retry_after(None) is None
        assert parse_retry_after("") is None
        assert parse_retry_after("invalid-date-string") is None


# ---------------------------------------------------------------------------
# RetryPolicy Decision Logic & Computation
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestRetryPolicy:
    def test_should_retry_status_codes(self):
        policy = RetryPolicy(max_retries=3)

        # Retryable: 500, 502, 503, 504, 408, 429
        assert policy.should_retry(current_retry_count=0, status_code=500) is True
        assert policy.should_retry(current_retry_count=1, status_code=429) is True
        assert policy.should_retry(current_retry_count=2, status_code=504) is True

        # Reached limit
        assert policy.should_retry(current_retry_count=3, status_code=500) is False

        # Non-retryable
        assert policy.should_retry(current_retry_count=0, status_code=400) is False
        assert policy.should_retry(current_retry_count=0, status_code=404) is False
        assert policy.should_retry(current_retry_count=0, status_code=200) is False

    def test_should_retry_custom_exceptions(self):
        policy = RetryPolicy(
            max_retries=3,
            retryable_exceptions=[ConnectionError, TimeoutError],
        )

        assert policy.should_retry(current_retry_count=0, exception=ConnectionError()) is True
        assert policy.should_retry(current_retry_count=0, exception=TimeoutError()) is True
        assert policy.should_retry(current_retry_count=0, exception=ValueError()) is False

    def test_compute_delay_with_deterministic_jitter(self):
        # Using NoJitter for deterministic delay testing
        policy = RetryPolicy(
            backoff=ExponentialBackoff(base_delay=2.0, factor=2.0),
            jitter=NoJitter(),
        )

        assert policy.compute_delay(retry_count=0) == 2.0
        assert policy.compute_delay(retry_count=1) == 4.0
        assert policy.compute_delay(retry_count=2) == 8.0

    def test_compute_delay_respects_retry_after_header(self):
        policy = RetryPolicy(
            backoff=FixedBackoff(delay=5.0),
            jitter=NoJitter(),
            max_retry_after=60.0,
        )

        headers = {"Retry-After": "25"}
        # For 429 Too Many Requests, Retry-After header should take precedence
        delay = policy.compute_delay(retry_count=0, status_code=429, headers=headers)
        assert delay == 25.0

        # Clamped to max_retry_after
        headers_large = {"Retry-After": "300"}
        delay_clamped = policy.compute_delay(retry_count=0, status_code=429, headers=headers_large)
        assert delay_clamped == 60.0

    def test_compute_next_retry_time(self):
        policy = RetryPolicy()
        start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        next_time = policy.compute_next_retry_time(delay_seconds=30.0, from_time=start)

        assert next_time == start + timedelta(seconds=30)


@pytest.mark.unit
class TestRetryPresets:
    def test_webhook_delivery_policy_preset(self):

        assert webhook_delivery_policy.max_retries == 5
        assert webhook_delivery_policy.max_delay == 3600.0
        assert webhook_delivery_policy.max_retry_after == 1800.0

        # Retries on network exceptions
        assert (
            webhook_delivery_policy.should_retry(
                current_retry_count=0,
                exception=httpx.ConnectError("Connection refused"),
            )
            is True
        )
        assert (
            webhook_delivery_policy.should_retry(
                current_retry_count=0,
                exception=httpx.TimeoutException("Read timeout"),
            )
            is True
        )

        # Retries on transient status codes
        assert webhook_delivery_policy.should_retry(current_retry_count=0, status_code=503) is True
        assert webhook_delivery_policy.should_retry(current_retry_count=0, status_code=429) is True

        # Stops after max retries
        assert webhook_delivery_policy.should_retry(current_retry_count=5, status_code=500) is False
