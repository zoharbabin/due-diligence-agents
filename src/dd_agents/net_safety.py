"""Network safety utilities — URL validation and SSRF prevention.

Provides :func:`validate_url` to block requests to private/internal
networks, cloud metadata endpoints, and dangerous URL schemes.

Also provides :func:`resolve_and_validate` which returns the validated
IP addresses so callers can connect directly, preventing DNS rebinding.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Schemes considered safe for outbound requests.
_ALLOWED_SCHEMES: frozenset[str] = frozenset({"https"})

# Cloud metadata IPs and hostnames to block unconditionally.
_BLOCKED_HOSTS: frozenset[str] = frozenset(
    {
        "metadata.google.internal",
        "metadata.goog",
        "169.254.169.254",
        "169.254.170.2",  # AWS ECS task metadata
    }
)


class UnsafeURLError(ValueError):
    """Raised when a URL targets a blocked destination."""


def _is_unsafe_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if *addr* is a private, loopback, link-local, reserved, or multicast address.

    Also detects IPv4-mapped IPv6 addresses (e.g., ``::ffff:127.0.0.1``)
    by extracting and re-checking the embedded IPv4 address.
    """
    if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast:
        return True
    # Check IPv4-mapped IPv6 addresses (::ffff:x.x.x.x)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        return _is_unsafe_ip(addr.ipv4_mapped)
    return False


def _extract_host(url: str) -> tuple[str, str]:
    """Parse URL and return (scheme, hostname), stripping userinfo and percent-encoding.

    Uses ``urllib.parse.urlparse`` for robust parsing, which correctly
    handles ``userinfo@host``, percent-encoded hostnames, and bracket
    notation for IPv6 literal addresses.

    Raises:
        UnsafeURLError: if the URL is malformed or contains no hostname.
    """
    try:
        parsed = urlparse(url)
    except Exception as exc:
        raise UnsafeURLError(f"Malformed URL: {url!r}") from exc

    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()

    if not scheme or not host:
        raise UnsafeURLError(f"Malformed URL (missing scheme or host): {url!r}")

    return scheme, host


def _resolve_and_check(host: str) -> list[str]:
    """Resolve *host* via DNS and validate all returned IPs are safe.

    Returns the list of safe resolved IP strings.

    Raises:
        UnsafeURLError: if DNS fails or any IP is private/reserved.
    """
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"DNS resolution failed for {host!r}: {exc}") from exc

    resolved_ips: list[str] = []
    for _family, _type, _proto, _canonname, sockaddr in infos:
        ip_str = str(sockaddr[0])
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if _is_unsafe_ip(addr):
            raise UnsafeURLError(f"URL host {host!r} resolves to private/reserved address {ip_str}")
        resolved_ips.append(ip_str)

    return resolved_ips


def _validate_common(url: str, *, allow_http: bool = False) -> tuple[str, list[str]]:
    """Shared validation logic for :func:`validate_url` and :func:`resolve_and_validate`.

    Returns (url, resolved_ips) on success.

    Raises:
        UnsafeURLError: if the URL is unsafe.
    """
    scheme, host = _extract_host(url)

    # Scheme check
    allowed = _ALLOWED_SCHEMES | ({"http"} if allow_http else set())
    if scheme not in allowed:
        raise UnsafeURLError(f"URL scheme {scheme!r} not allowed (permitted: {', '.join(sorted(allowed))})")

    # Reject userinfo (credentials in URL)
    parsed = urlparse(url)
    if parsed.username or parsed.password:
        raise UnsafeURLError("URLs with embedded credentials (userinfo) are not allowed")

    # Blocklist check
    if host in _BLOCKED_HOSTS:
        raise UnsafeURLError(f"Requests to {host!r} are blocked (cloud metadata endpoint)")

    # DNS resolution + private-IP check
    resolved = _resolve_and_check(host)
    return url, resolved


def validate_url(url: str, *, allow_http: bool = False) -> str:
    """Validate *url* is safe for outbound server-side requests.

    Checks:
    1. Scheme is ``https`` (or ``http`` if *allow_http* is True).
    2. No userinfo component (``user:pass@host`` is rejected).
    3. Hostname does not resolve to a private/reserved IP range.
    4. Hostname is not a known cloud metadata endpoint.
    5. IPv4-mapped IPv6 and multicast addresses are blocked.

    Returns the original *url* unchanged on success.

    Raises:
        UnsafeURLError: if the URL is unsafe.
    """
    validated_url, _resolved = _validate_common(url, allow_http=allow_http)
    return validated_url


def resolve_and_validate(url: str, *, allow_http: bool = False) -> tuple[str, list[str]]:
    """Validate *url* and return (url, resolved_ips).

    This is the preferred API for callers that will make an HTTP request
    after validation.  By returning the resolved IPs, the caller can
    connect to a specific IP (via Host header override) to prevent
    DNS rebinding attacks where a second DNS lookup could return a
    different (internal) address.

    Returns:
        (url, resolved_ips) — the original URL and the list of safe IP addresses.

    Raises:
        UnsafeURLError: if the URL is unsafe.
    """
    return _validate_common(url, allow_http=allow_http)
