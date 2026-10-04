"""Unit tests for secure client IP extraction and anti-spoofing logic."""

import ipaddress
from unittest.mock import MagicMock

import pytest
from fastapi import Request

from src.core.client_ip import canonicalize_ip, get_client_ip, is_ip_in_networks

TRUSTED_NETWORKS = [
    ipaddress.ip_network("127.0.0.1/32"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
]


def make_mock_request(
    client_host: str | None = None,
    headers: dict[str, str] | None = None,
) -> Request:
    request = MagicMock(spec=Request)
    if client_host is not None:
        request.client = MagicMock()
        request.client.host = client_host
    else:
        request.client = None

    _headers = headers or {}
    request.headers = MagicMock()
    request.headers.get = MagicMock(side_effect=lambda k, default=None: _headers.get(k, default))
    return request


@pytest.mark.unit
def test_is_ip_in_networks():
    ip_v4 = ipaddress.ip_address("10.1.2.3")
    ip_v4_public = ipaddress.ip_address("93.184.216.34")
    ip_v6_loopback = ipaddress.ip_address("::1")

    assert is_ip_in_networks(ip_v4, TRUSTED_NETWORKS) is True
    assert is_ip_in_networks(ip_v4_public, TRUSTED_NETWORKS) is False
    assert is_ip_in_networks(ip_v6_loopback, TRUSTED_NETWORKS) is True


@pytest.mark.unit
def test_canonicalize_ip_v4():
    ip_v4 = ipaddress.ip_address("192.168.1.1")
    assert canonicalize_ip(ip_v4) == "192.168.1.1"


@pytest.mark.unit
def test_canonicalize_ip_v6_normalizes_variations_to_exploded():
    v6_compressed = ipaddress.ip_address("2001:db8::1")
    v6_uncompressed = ipaddress.ip_address("2001:0db8:0000:0000:0000:0000:0000:0001")
    v6_leading_zeros = ipaddress.ip_address("2001:0db8::0001")

    expected = "2001:0db8:0000:0000:0000:0000:0000:0001"
    assert canonicalize_ip(v6_compressed) == expected
    assert canonicalize_ip(v6_uncompressed) == expected
    assert canonicalize_ip(v6_leading_zeros) == expected


@pytest.mark.unit
def test_untrusted_peer_cannot_spoof_x_forwarded_for():
    """Attacker connecting directly from untrusted public IP cannot spoof client IP via X-Forwarded-For."""
    request = make_mock_request(
        client_host="198.51.100.1",
        headers={"X-Forwarded-For": "8.8.8.8, 1.1.1.1"},
    )
    result = get_client_ip(request, trusted_networks=TRUSTED_NETWORKS)
    assert result == "198.51.100.1"


@pytest.mark.unit
def test_untrusted_peer_cannot_spoof_x_real_ip():
    """Attacker connecting directly from untrusted public IP cannot spoof client IP via X-Real-IP."""
    request = make_mock_request(
        client_host="198.51.100.2",
        headers={"X-Real-IP": "8.8.8.8"},
    )
    result = get_client_ip(request, trusted_networks=TRUSTED_NETWORKS)
    assert result == "198.51.100.2"


@pytest.mark.unit
def test_trusted_proxy_extracts_client_ip():
    """Request routed through a trusted reverse proxy (e.g. 10.0.0.1) parses untrusted client IP."""
    request = make_mock_request(
        client_host="10.0.0.1",
        headers={"X-Forwarded-For": "203.0.113.195"},
    )
    result = get_client_ip(request, trusted_networks=TRUSTED_NETWORKS)
    assert result == "203.0.113.195"


@pytest.mark.unit
def test_trusted_proxy_right_to_left_skips_intermediate_trusted_proxies():
    """Right-to-left traversal skips trusted internal proxies and finds genuine remote client."""
    # Topology: Client (203.0.113.50) -> Edge Proxy (10.0.0.10) -> Internal Mesh (10.0.0.2) -> App (10.0.0.1)
    request = make_mock_request(
        client_host="10.0.0.1",
        headers={"X-Forwarded-For": "203.0.113.50, 10.0.0.10, 10.0.0.2"},
    )
    result = get_client_ip(request, trusted_networks=TRUSTED_NETWORKS)
    assert result == "203.0.113.50"


@pytest.mark.unit
def test_spoofed_prefix_in_forwarded_header_is_ignored():
    """Attacker injected a fake IP into X-Forwarded-For before reaching edge proxy.

    Header looks like: <fake-injected-ip>, <real-client-ip>.
    Right-to-left traversal picks real-client-ip, NOT the injected fake IP.
    """
    request = make_mock_request(
        client_host="10.0.0.1",  # Edge proxy
        headers={"X-Forwarded-For": "1.2.3.4, 198.51.100.77"},
    )
    result = get_client_ip(request, trusted_networks=TRUSTED_NETWORKS)
    assert result == "198.51.100.77"


@pytest.mark.unit
def test_all_hops_trusted_returns_leftmost():
    """When an internal client calls via trusted proxies, the originating internal client is returned."""
    request = make_mock_request(
        client_host="10.0.0.1",
        headers={"X-Forwarded-For": "10.1.2.3, 10.0.0.5"},
    )
    result = get_client_ip(request, trusted_networks=TRUSTED_NETWORKS)
    assert result == "10.1.2.3"


@pytest.mark.unit
def test_trusted_proxy_falls_back_to_x_real_ip():
    """When X-Forwarded-For is missing, trusted proxy's X-Real-IP is used."""
    request = make_mock_request(
        client_host="10.0.0.1",
        headers={"X-Real-IP": "203.0.113.88"},
    )
    result = get_client_ip(request, trusted_networks=TRUSTED_NETWORKS)
    assert result == "203.0.113.88"


@pytest.mark.unit
def test_malformed_ips_in_header_handled_safely():
    """Invalid IP strings and delimiter injection attempts do not crash and fall back to peer host."""
    request = make_mock_request(
        client_host="10.0.0.1",
        headers={"X-Forwarded-For": "malicious;ip\\r\\n, invalid-host"},
    )
    result = get_client_ip(request, trusted_networks=TRUSTED_NETWORKS)
    # Falls back safely to trusted peer IP
    assert result == "10.0.0.1"


@pytest.mark.unit
def test_missing_client_returns_unknown():
    """Request with no client information returns 'unknown'."""
    request = make_mock_request(client_host=None)
    result = get_client_ip(request, trusted_networks=TRUSTED_NETWORKS)
    assert result == "unknown"


@pytest.mark.unit
def test_ipv6_handling():
    """Validates IPv6 format parsing."""
    request = make_mock_request(
        client_host="127.0.0.1",
        headers={"X-Forwarded-For": "2001:db8::1"},
    )
    result = get_client_ip(request, trusted_networks=TRUSTED_NETWORKS)
    assert result == ipaddress.ip_address("2001:db8::1").exploded
