try:
    import httpx

    _default_network_exceptions = [
        httpx.TimeoutException,
        httpx.ConnectError,
        httpx.NetworkError,
        httpx.RemoteProtocolError,
    ]
except ImportError:
    _default_network_exceptions = []

from src.core.retry.backoff import ExponentialBackoff
from src.core.retry.jitter import FullJitter
from src.core.retry.policy import RetryPolicy

# Standard Webhook delivery policy:
# - Exponential backoff starting at 2.0s, factor 2.0, max 3600.0s (1h)
# - Full Jitter: U(0, delay)
# - Handles 408, 429, 5xx status codes
# - Respects Retry-After on 429 and 503 up to 1800s (30m)
# - Retries transient network exceptions
webhook_delivery_policy = RetryPolicy(
    max_retries=5,
    backoff=ExponentialBackoff(base_delay=2.0, factor=2.0, max_delay=3600.0),
    jitter=FullJitter(),
    retryable_exceptions=_default_network_exceptions,
    max_delay=3600.0,
    max_retry_after=1800.0,
)
