"""Secure client IP extraction with trusted proxy validation.

Mitigates Client-Side IP Spoofing by enforcing that proxy headers (X-Forwarded-For,
X-Real-IP) are ONLY trusted when the immediate TCP socket peer is a configured,
trusted reverse proxy. Traverses X-Forwarded-For right-to-left to discard trusted
internal hops and extract the authentic remote client IP.
"""

import ipaddress
import logging
from collections.abc import Sequence

from fastapi import Request

from src.core.config import settings

logger = logging.getLogger(__name__)

_UNKNOWN_IP = "unknown"


def is_ip_in_networks(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
    networks: Sequence[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> bool:
    """Check if an IP address belongs to any of the specified networks."""
    return any(ip in net for net in networks)


def canonicalize_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    """Return a deterministic canonical string representation of an IP address.

    - For IPv6: Returns the 39-character fully uncompressed zero-padded representation
      (`exploded`) to prevent rate limit bypasses via format variations (e.g.,
      '2001:db8::1' vs '2001:0db8::0001').
    - For IPv4: Returns standard dotted-decimal representation (`str(ip)`).
    """
    return ip.exploded if ip.version == 6 else str(ip)


def get_client_ip(
    request: Request,
    trusted_networks: Sequence[ipaddress.IPv4Network | ipaddress.IPv6Network] | None = None,
) -> str:
    """Extracts the verified client IP address from the request.

    Security Rules:
    1. Direct TCP socket peer (request.client.host) is the ground truth.
    2. If direct peer is not in trusted_networks, all proxy headers (X-Forwarded-For,
       X-Real-IP) are IGNORED. The direct socket peer is returned directly to prevent
       client-side spoofing.
    3. If direct peer is a trusted proxy, X-Forwarded-For is parsed from right to left,
       stripping intermediate trusted proxies until the first untrusted IP is reached.
    4. If X-Forwarded-For is missing but X-Real-IP is provided by the trusted proxy,
       X-Real-IP is validated and returned.
    5. All IP strings are parsed through `ipaddress.ip_address` to guarantee valid syntax
       and prevent Redis key injection.
    """
    if not request.client or not request.client.host:
        return _UNKNOWN_IP

    peer_str = request.client.host.strip()

    try:
        peer_ip = ipaddress.ip_address(peer_str)
    except ValueError:
        return _UNKNOWN_IP

    networks = trusted_networks if trusted_networks is not None else settings.trusted_proxy_networks

    # 1. If direct TCP peer is NOT a trusted proxy, reject all proxy headers
    if not is_ip_in_networks(peer_ip, networks):
        return canonicalize_ip(peer_ip)

    # 2. Peer is trusted: inspect X-Forwarded-For
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        raw_hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]

        # Traverse right-to-left: the first untrusted IP is the genuine client
        for hop_str in reversed(raw_hops):
            try:
                hop_ip = ipaddress.ip_address(hop_str)
            except ValueError:
                # Discard invalid IP formats
                continue

            if not is_ip_in_networks(hop_ip, networks):
                return canonicalize_ip(hop_ip)

        # If all hops are within trusted networks, return the leftmost valid hop
        for hop_str in raw_hops:
            try:
                leftmost_ip = ipaddress.ip_address(hop_str)
                return canonicalize_ip(leftmost_ip)
            except ValueError:
                continue

    # 3. Check X-Real-IP if provided by trusted proxy and X-Forwarded-For did not yield client
    real_ip_hdr = request.headers.get("X-Real-IP")
    if real_ip_hdr:
        try:
            real_ip = ipaddress.ip_address(real_ip_hdr.strip())
            return canonicalize_ip(real_ip)
        except ValueError:
            pass

    # 4. Fallback to the trusted peer's own IP
    return canonicalize_ip(peer_ip)
