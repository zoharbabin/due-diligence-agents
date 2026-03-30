"""Network safety utilities — URL validation and SSRF prevention.

Provides :func:`validate_url` to block requests to private/internal
networks, cloud metadata endpoints, and dangerous URL schemes.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket

logger = logging.getLogger(__name__)

# Schemes considered safe for outbound requests.
_ALLOWED_SCHEMES: frozenset[str] = frozenset({"https"})

# Cloud metadata IPs and hostnames to block unconditionally.
_BLOCKED_HOSTS: frozenset[str] = frozenset(
    {
        "metadata.google.internal",
        "metadata.goog",
        "169.254.169.254",
    }
)

# Match scheme + authority from a URL.
_URL_PARTS_RE = re.compile(
    r"^(?P<scheme>[a-z][a-z0-9+\-.]*?)://(?P<host>[^/:]+)(?::(?P<port>\d+))?(?P<rest>/.*)?$", re.I
)


class UnsafeURLError(ValueError):
    """Raised when a URL targets a blocked destination."""


def validate_url(url: str, *, allow_http: bool = False) -> str:
    """Validate *url* is safe for outbound server-side requests.

    Checks:
    1. Scheme is ``https`` (or ``http`` if *allow_http* is True).
    2. Hostname does not resolve to a private/reserved IP range.
    3. Hostname is not a known cloud metadata endpoint.

    Returns the original *url* unchanged on success.

    Raises:
        UnsafeURLError: if the URL is unsafe.
    """
    m = _URL_PARTS_RE.match(url)
    if not m:
        raise UnsafeURLError(f"Malformed URL: {url!r}")

    scheme = m.group("scheme").lower()
    host = m.group("host").lower()

    # --- scheme check ---
    allowed = _ALLOWED_SCHEMES | ({"http"} if allow_http else set())
    if scheme not in allowed:
        raise UnsafeURLError(f"URL scheme {scheme!r} not allowed (permitted: {', '.join(sorted(allowed))})")

    # --- blocklist check ---
    if host in _BLOCKED_HOSTS:
        raise UnsafeURLError(f"Requests to {host!r} are blocked (cloud metadata endpoint)")

    # --- DNS resolution + private-IP check ---
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"DNS resolution failed for {host!r}: {exc}") from exc

    for _family, _type, _proto, _canonname, sockaddr in infos:
        ip_str = sockaddr[0]
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            raise UnsafeURLError(f"URL host {host!r} resolves to private/reserved address {ip_str}")

    return url
