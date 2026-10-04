"""Unit tests for Anti-SSRF Protection, IP blocklisting, and safe HTTP client."""

import ipaddress
import socket
from unittest.mock import patch

import httpx
import pytest

from src.core.http_client import get_safe_http_client
from src.core.ssrf import (
    AntiSSRFNetworkBackend,
    SSRFSecurityError,
    is_hostname_local,
    is_ip_allowed,
)
from src.exceptions.endpoint import EndpointValidationError
from src.services.endpoint import validate_safe_webhook_url


@pytest.mark.unit
@pytest.mark.parametrize(
    "ip_str",
    [
        "127.0.0.1",
        "127.0.0.2",
        "10.0.0.1",
        "10.255.255.255",
        "172.16.0.1",
        "172.31.255.255",
        "192.168.0.1",
        "192.168.1.100",
        "169.254.169.254",  # AWS/GCP Instance Metadata Service
        "169.254.1.1",
        "0.0.0.0",
        "100.64.0.1",  # Carrier-Grade NAT
        "192.0.2.1",  # TEST-NET-1
        "198.51.100.1",  # TEST-NET-2
        "203.0.113.1",  # TEST-NET-3
        "224.0.0.1",  # Multicast
        "240.0.0.1",  # Reserved
        "::1",  # IPv6 loopback
        "::",  # IPv6 unspecified
        "fc00::1",  # IPv6 Unique Local Address
        "fe80::1",  # IPv6 Link-Local
        "ff02::1",  # IPv6 Multicast
    ],
)
def test_is_ip_allowed_blocks_prohibited_ips(ip_str: str):
    """Ensures all RFC-private, loopback, multicast, and cloud metadata IPs are rejected."""
    ip = ipaddress.ip_address(ip_str)
    assert is_ip_allowed(ip) is False


@pytest.mark.unit
@pytest.mark.parametrize(
    "ip_str",
    [
        "8.8.8.8",
        "1.1.1.1",
        "93.184.216.34",
        "142.250.190.46",
        "2606:4700:4700::1111",
        "2001:4860:4860::8888",
    ],
)
def test_is_ip_allowed_permits_public_ips(ip_str: str):
    """Ensures legitimate public IP addresses are permitted."""
    ip = ipaddress.ip_address(ip_str)
    assert is_ip_allowed(ip) is True


@pytest.mark.unit
@pytest.mark.parametrize(
    "hostname",
    [
        "localhost",
        "LOCALHOST",
        "localhost.localdomain",
        "myhost.local",
        "api.corp.internal",
        "app.localhost",
        "dev.lan",
    ],
)
def test_is_hostname_local_detects_internal_domains(hostname: str):
    """Ensures internal/local hostnames and suffixes are flagged."""
    assert is_hostname_local(hostname) is True


@pytest.mark.unit
@pytest.mark.parametrize(
    "hostname",
    [
        "example.com",
        "api.stripe.com",
        "hooks.slack.com",
        "subdomain.domain.org",
    ],
)
def test_is_hostname_local_allows_public_domains(hostname: str):
    """Ensures legitimate external domains are permitted."""
    assert is_hostname_local(hostname) is False


@pytest.mark.unit
@pytest.mark.parametrize(
    "unsafe_url",
    [
        "http://127.0.0.1/webhook",
        "http://localhost:8080/hook",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/api",
        "http://192.168.1.1/admin",
        "http://app.internal/webhook",
        "ftp://example.com/webhook",
    ],
)
def test_validate_safe_webhook_url_blocks_unsafe_destinations(unsafe_url: str):
    """Ensures endpoint URL registration rejects unsafe and private destinations."""
    with pytest.raises(EndpointValidationError):
        validate_safe_webhook_url(unsafe_url)


@pytest.mark.unit
def test_validate_safe_webhook_url_blocks_dns_resolved_private_ip():
    """Ensures domain names that resolve to private IPs during validation are blocked."""
    with (
        patch("socket.gethostbyname", return_value="10.0.0.1"),
        pytest.raises(EndpointValidationError),
    ):
        validate_safe_webhook_url("https://malicious-domain.com/hook")


@pytest.mark.unit
def test_validate_safe_webhook_url_allows_safe_url():
    """Ensures valid public URLs pass validation."""
    with patch("socket.gethostbyname", return_value="93.184.216.34"):
        # Should execute without raising any exception
        validate_safe_webhook_url("https://example.com/webhook")


@pytest.mark.asyncio
@pytest.mark.unit
async def test_anti_ssrf_network_backend_blocks_local_host():
    """Ensures AntiSSRFNetworkBackend rejects local hostnames immediately at socket connection."""
    backend = AntiSSRFNetworkBackend()
    with pytest.raises(
        SSRFSecurityError, match="Connection to local host 'localhost' is prohibited"
    ):
        await backend.connect_tcp("localhost", 80)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_anti_ssrf_network_backend_blocks_direct_private_ip():
    """Ensures AntiSSRFNetworkBackend rejects direct connections to prohibited IPs."""
    backend = AntiSSRFNetworkBackend()
    with pytest.raises(SSRFSecurityError, match="prohibited"):
        await backend.connect_tcp("169.254.169.254", 80)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_anti_ssrf_network_backend_blocks_dns_rebound_private_ip():
    """Simulates a DNS rebinding attack where getaddrinfo returns a private IP at connection time."""
    backend = AntiSSRFNetworkBackend()

    mock_addr_info = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80)),
    ]

    with (
        patch("asyncio.BaseEventLoop.getaddrinfo", return_value=mock_addr_info),
        pytest.raises(SSRFSecurityError, match="resolves to restricted IP"),
    ):
        await backend.connect_tcp("rebound-attacker-domain.com", 80)


@pytest.mark.unit
def test_get_safe_http_client_configuration():
    """Ensures HTTP client is configured with anti-redirect and anti-SSRF protections."""
    client = get_safe_http_client()
    assert client.follow_redirects is False
    assert isinstance(client._transport, httpx.AsyncHTTPTransport)
