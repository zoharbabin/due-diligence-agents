"""Request guards for the local API.

Only the desktop app on this machine may talk to the server:

* ``Host`` must be a loopback name (blocks DNS rebinding).
* ``Origin``, when present, must equal the server's own origin. There is no CORS.
* Every API route needs the per-launch bearer token.
* Files are served only from registered project directories (``confine_path``).
"""

from __future__ import annotations

import hmac
import json
import secrets
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

MIN_TOKEN_LENGTH = 16
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]"})
# Paths outside /api that still need the token. Everything else outside /api is the static UI.
_PROTECTED_EXACT = frozenset({"/openapi.json", "/docs", "/redoc"})


class PathConfinementError(ValueError):
    """A path resolved outside the allowed directories."""


def new_token() -> str:
    """Return a fresh URL-safe bearer token."""
    return secrets.token_urlsafe(32)


def confine_path(path: str | Path, roots: Iterable[Path]) -> Path:
    """Resolve *path* (relative paths are taken under each root) and require it to sit inside a root.

    Follows symlinks before the check, so a link that points outside is rejected.
    """
    raw = str(path)
    if "\x00" in raw:
        raise PathConfinementError("path contains a NUL byte")
    candidate = Path(raw)
    resolved_roots = [r.resolve() for r in roots]
    options = [candidate] if candidate.is_absolute() else [r / candidate for r in resolved_roots]
    for option in options:
        resolved = option.resolve()
        if any(resolved == r or r in resolved.parents for r in resolved_roots):
            return resolved
    raise PathConfinementError("path is outside the allowed directories")


def _split_host(value: str) -> str:
    """Return the host part of a ``Host`` header (no port), lower-cased."""
    value = value.strip().lower()
    if value.startswith("["):
        end = value.find("]")
        return value[: end + 1] if end != -1 else value
    return value.split(":", 1)[0]


def _origin_matches_host(origin: str, host_header: str) -> bool:
    parts = urlsplit(origin)
    if parts.scheme != "http" or not parts.netloc:
        return False
    return parts.netloc.lower() == host_header.strip().lower()


class SecurityMiddleware:
    """Pure-ASGI guard (no response buffering, so SSE streams stay live)."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        if len(token) < MIN_TOKEN_LENGTH:
            raise ValueError(f"token must be at least {MIN_TOKEN_LENGTH} characters")
        self.app = app
        self._token = token.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        path: str = scope.get("path", "")

        host = headers.get("host", "")
        if _split_host(host) not in LOOPBACK_HOSTS:
            await self._deny(scope, send, 403, "host not allowed")
            return
        origin = headers.get("origin")
        if origin is not None and not _origin_matches_host(origin, host):
            await self._deny(scope, send, 403, "origin not allowed")
            return
        needs_token = path.startswith("/api/") or path == "/api" or path in _PROTECTED_EXACT
        if needs_token and not self._authorized(headers.get("authorization", "")):
            await self._deny(scope, send, 401, "missing or invalid token")
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                extra = [(b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer")]
                if needs_token:
                    extra.append((b"cache-control", b"no-store"))
                message["headers"] = [*message.get("headers", []), *extra]
            await send(message)

        await self.app(scope, receive, send_with_headers)

    def _authorized(self, header: str) -> bool:
        scheme, _, supplied = header.partition(" ")
        if scheme.lower() != "bearer" or not supplied:
            return False
        return hmac.compare_digest(supplied.strip().encode(), self._token)

    @staticmethod
    async def _deny(scope: Scope, send: Send, status: int, reason: str) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        body = json.dumps({"detail": reason}).encode()
        headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
        if status == 401:
            headers.append((b"www-authenticate", b"Bearer"))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})
