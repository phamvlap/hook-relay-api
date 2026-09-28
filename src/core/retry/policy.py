from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta

from src.core.retry.backoff import BackoffStrategy, ExponentialBackoff
from src.core.retry.jitter import FullJitter, JitterStrategy
from src.core.retry.parser import parse_retry_after


class RetryPolicy:
    """Configurable retry policy with support for backoff, jitter, and Retry-After headers."""

    def __init__(
        self,
        max_retries: int = 5,
        backoff: BackoffStrategy | None = None,
        jitter: JitterStrategy | None = None,
        retryable_statuses: set[int] | None = None,
        retry_after_statuses: set[int] | None = None,
        retryable_exceptions: Sequence[type[Exception]] | None = None,
        max_delay: float = 3600.0,
        max_retry_after: float = 1800.0,
    ) -> None:
        self.max_retries = max_retries
        self.backoff = backoff or ExponentialBackoff()
        self.jitter = jitter or FullJitter()
        self.max_delay = max_delay
        self.max_retry_after = min(max_retry_after, max_delay)

        # HTTP status codes indicating transient downstream conditions
        self.retryable_statuses = retryable_statuses or {
            408,  # Request Timeout
            429,  # Too Many Requests
            500,  # Internal Server Error
            502,  # Bad Gateway
            503,  # Service Unavailable
            504,  # Gateway Timeout
        }

        # Status codes where Retry-After header will be respected if present
        self.retry_after_statuses = retry_after_statuses or {
            429,  # Too Many Requests
            503,  # Service Unavailable
        }

        self.retryable_exceptions = tuple(retryable_exceptions or ())

    def should_retry(
        self,
        *,
        current_retry_count: int,
        status_code: int | None = None,
        exception: Exception | None = None,
        custom_max_retries: int | None = None,
    ) -> bool:
        """Determines if the attempt is eligible for another retry."""
        max_retries = custom_max_retries if custom_max_retries is not None else self.max_retries
        if current_retry_count >= max_retries:
            return False

        if status_code is not None:
            return status_code in self.retryable_statuses or (500 <= status_code < 600)

        if exception is not None:
            return isinstance(exception, self.retryable_exceptions)

        return False

    def compute_delay(
        self,
        *,
        retry_count: int,
        status_code: int | None = None,
        headers: Mapping[str, str] | dict[str, str] | None = None,
    ) -> float:
        """Computes next retry delay in seconds.

        Priority:
        1. If status_code is in retry_after_statuses and a valid Retry-After
           header is provided, use that parsed delay clamped to max_retry_after.
        2. Otherwise, calculate deterministic backoff and apply the configured jitter.
        """
        if status_code and status_code in self.retry_after_statuses and headers:
            # Check case-insensitively for Retry-After
            retry_after_val = None
            for key, value in headers.items():
                if key.lower() == "retry-after":
                    retry_after_val = value
                    break

            if retry_after_val:
                parsed_delay = parse_retry_after(retry_after_val)
                if parsed_delay is not None:
                    return min(parsed_delay, self.max_retry_after)

        raw_delay = self.backoff.calculate(retry_count)
        base_delay = getattr(self.backoff, "base_delay", 1.0)
        jittered_delay = self.jitter.apply(delay=raw_delay, base_delay=base_delay)

        return min(max(0.0, jittered_delay), self.max_delay)

    def compute_next_retry_time(
        self,
        *,
        delay_seconds: float,
        from_time: datetime | None = None,
    ) -> datetime:
        """Returns the UTC timestamp when the retry should occur."""
        start = from_time or datetime.now(tz=UTC)
        return start + timedelta(seconds=delay_seconds)
