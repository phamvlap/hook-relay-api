"""HTTP Client Infrastructure and Connection Lifecycle Management.

Provides connection-pooled HTTPX clients with configurable policies and Anti-SSRF protection.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpcore
import httpx

from src.core.ssrf import AntiSSRFNetworkBackend

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HTTPClientConfig:
    """Connection pool and timeout settings for outbound HTTP clients."""

    connect_timeout: float = 4.0
    read_timeout: float = 10.0
    write_timeout: float = 5.0
    pool_timeout: float = 5.0
    max_connections: int = 100
    max_keepalive_connections: int = 20
    keepalive_expiry: float = 30.0


def create_anti_ssrf_transport(config: HTTPClientConfig | None = None) -> httpx.AsyncHTTPTransport:
    """Creates an AsyncHTTPTransport wired with AntiSSRFNetworkBackend."""
    cfg = config or HTTPClientConfig()
    limits = httpx.Limits(
        max_connections=cfg.max_connections,
        max_keepalive_connections=cfg.max_keepalive_connections,
        keepalive_expiry=cfg.keepalive_expiry,
    )
    pool = httpcore.AsyncConnectionPool(
        max_connections=limits.max_connections,
        max_keepalive_connections=limits.max_keepalive_connections,
        keepalive_expiry=limits.keepalive_expiry,
        http1=True,
        http2=False,
        network_backend=AntiSSRFNetworkBackend(),
    )
    transport = httpx.AsyncHTTPTransport(limits=limits)
    transport._pool = pool
    return transport


_SAFE_HTTP_CLIENT: httpx.AsyncClient | None = None


def get_safe_http_client(config: HTTPClientConfig | None = None) -> httpx.AsyncClient:
    """Returns a shared, pooled AsyncClient with Anti-SSRF protection.

    Enforces:
    - Transport-level IP pinning and DNS validation
    - follow_redirects=False (prevents redirect-based SSRF)
    - Strict connection and read timeouts
    """
    global _SAFE_HTTP_CLIENT
    if _SAFE_HTTP_CLIENT is None or _SAFE_HTTP_CLIENT.is_closed:
        cfg = config or HTTPClientConfig()
        transport = create_anti_ssrf_transport(cfg)
        _SAFE_HTTP_CLIENT = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(
                timeout=cfg.read_timeout + cfg.connect_timeout,
                connect=cfg.connect_timeout,
                read=cfg.read_timeout,
                write=cfg.write_timeout,
                pool=cfg.pool_timeout,
            ),
            follow_redirects=False,
        )
    return _SAFE_HTTP_CLIENT


async def close_safe_http_client() -> None:
    """Gracefully closes the shared HTTP client during application shutdown."""
    global _SAFE_HTTP_CLIENT
    if _SAFE_HTTP_CLIENT is not None and not _SAFE_HTTP_CLIENT.is_closed:
        try:
            await _SAFE_HTTP_CLIENT.aclose()
            logger.info("Safe HTTP client connection pool closed.")
        except (TimeoutError, ConnectionError) as e:
            logger.warning("Error closing safe HTTP client: %s", e)
        finally:
            _SAFE_HTTP_CLIENT = None
