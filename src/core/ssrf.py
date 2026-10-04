"""Anti-SSRF Security Policies and Network Backend.

Provides IP address blocklisting and atomic IP pinning at connection time
to eliminate DNS rebinding, internal VPC port scanning, and cloud metadata theft.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from collections.abc import Iterable

import anyio
import httpcore
from httpcore._backends.anyio import AnyIOBackend, AnyIOStream
from httpcore._backends.base import SOCKET_OPTION, AsyncNetworkStream

from src.core.exceptions import ValidationError

logger = logging.getLogger(__name__)

# Complete RFC private, loopback, link-local, multicast, and cloud metadata CIDRs
DISALLOWED_IP_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    # IPv4 Private & Special ranges (RFC 1918, RFC 3927, RFC 1122, etc.)
    ipaddress.ip_network("0.0.0.0/8"),  # Current network (only valid as source)
    ipaddress.ip_network("10.0.0.0/8"),  # Private-Use (RFC 1918)
    ipaddress.ip_network("100.64.0.0/10"),  # Shared Address Space (Carrier-Grade NAT)
    ipaddress.ip_network("127.0.0.0/8"),  # Loopback
    ipaddress.ip_network("169.254.0.0/16"),  # Link-Local (Cloud metadata: 169.254.169.254)
    ipaddress.ip_network("172.16.0.0/12"),  # Private-Use (RFC 1918)
    ipaddress.ip_network("192.0.0.0/24"),  # IETF Protocol Assignments
    ipaddress.ip_network("192.0.2.0/24"),  # Documentation (TEST-NET-1)
    ipaddress.ip_network("192.88.99.0/24"),  # 6to4 Relay Anycast
    ipaddress.ip_network("192.168.0.0/16"),  # Private-Use (RFC 1918)
    ipaddress.ip_network("198.18.0.0/15"),  # Network Interconnect Benchmarking
    ipaddress.ip_network("198.51.100.0/24"),  # Documentation (TEST-NET-2)
    ipaddress.ip_network("203.0.113.0/24"),  # Documentation (TEST-NET-3)
    ipaddress.ip_network("224.0.0.0/4"),  # Multicast
    ipaddress.ip_network("240.0.0.0/4"),  # Reserved for Future Use
    ipaddress.ip_network("255.255.255.255/32"),  # Limited Broadcast
    # IPv6 Ranges
    ipaddress.ip_network("::/128"),  # Unspecified address
    ipaddress.ip_network("::1/128"),  # Loopback
    ipaddress.ip_network("::ffff:0:0/96"),  # IPv4-mapped IPv6
    ipaddress.ip_network("64:ff9b::/96"),  # IPv4/IPv6 translation
    ipaddress.ip_network("100::/64"),  # Discard prefix
    ipaddress.ip_network("2001:db8::/32"),  # Documentation
    ipaddress.ip_network("fc00::/7"),  # Unique Local Addresses (ULA - private)
    ipaddress.ip_network("fe80::/10"),  # Link-Local Unicast (includes cloud metadata)
    ipaddress.ip_network("ff00::/8"),  # Multicast
)

_LOCAL_HOSTNAMES = frozenset({"localhost", "localhost.localdomain", "broadcasthost"})
_LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan")


class SSRFSecurityError(ValidationError):
    """Raised when an outbound connection targets a prohibited destination."""

    def __init__(self, message: str = "Destination IP address is prohibited.") -> None:
        super().__init__(message)


def is_hostname_local(hostname: str) -> bool:
    """Checks whether the hostname is a local domain or matches internal suffixes."""
    normalized = hostname.lower().strip()
    return normalized in _LOCAL_HOSTNAMES or normalized.endswith(_LOCAL_SUFFIXES)


def is_ip_allowed(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Verifies that the target IP does not belong to any prohibited network."""
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        return False

    for network in DISALLOWED_IP_NETWORKS:
        if ip in network:
            return False

    return True


class AntiSSRFNetworkBackend(AnyIOBackend):
    """Socket backend performing atomic DNS resolution, IP filtering, and IP pinning."""

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[SOCKET_OPTION] | None = None,
    ) -> AsyncNetworkStream:
        # 1. Reject localhost / local hostname strings immediately
        if is_hostname_local(host):
            raise SSRFSecurityError(f"Connection to local host '{host}' is prohibited.")

        # 2. Check if host is already an IP address literal
        try:
            direct_ip = ipaddress.ip_address(host)
            if not is_ip_allowed(direct_ip):
                logger.warning("Blocked SSRF attempt: Direct connection to forbidden IP '%s'", host)
                raise SSRFSecurityError(f"Connection to IP address '{host}' is prohibited.")
            pinned_ip = str(direct_ip)
        except ValueError:
            # 3. Domain name: resolve DNS asynchronously
            try:
                loop = asyncio.get_running_loop()
                addr_info = await loop.getaddrinfo(
                    host,
                    port,
                    family=socket.AF_UNSPEC,
                    type=socket.SOCK_STREAM,
                )
            except socket.gaierror as exc:
                logger.warning("DNS resolution failed for webhook host '%s': %s", host, exc)
                raise httpcore.ConnectError(f"DNS resolution failed for host '{host}'") from exc

            if not addr_info:
                raise httpcore.ConnectError(f"No IP addresses resolved for host '{host}'")

            # Validate all resolved IP addresses
            validated_ips: list[str] = []
            for _, _, _, _, sockaddr in addr_info:
                ip_str = str(sockaddr[0])
                try:
                    ip_obj = ipaddress.ip_address(ip_str)
                except ValueError:
                    continue

                if not is_ip_allowed(ip_obj):
                    logger.warning(
                        "Blocked SSRF attempt: Host '%s' resolved to forbidden IP '%s'",
                        host,
                        ip_str,
                    )
                    raise SSRFSecurityError(
                        f"Destination host '{host}' resolves to restricted IP: {ip_str}"
                    )

                validated_ips.append(ip_str)

            if not validated_ips:
                raise SSRFSecurityError(f"No valid public IP addresses available for host '{host}'")

            pinned_ip = validated_ips[0]

        # 4. Open TCP stream directly to the pinned IP address
        if socket_options is None:
            socket_options = []

        try:
            with anyio.fail_after(timeout):
                stream: anyio.abc.ByteStream = await anyio.connect_tcp(
                    remote_host=pinned_ip,
                    remote_port=port,
                    local_host=local_address,
                )
                for option in socket_options:
                    stream._raw_socket.setsockopt(*option)  # type: ignore[attr-defined]
        except TimeoutError as exc:
            raise httpcore.ConnectTimeout(str(exc)) from exc
        except (OSError, anyio.BrokenResourceError) as exc:
            raise httpcore.ConnectError(str(exc)) from exc

        return AnyIOStream(stream)
