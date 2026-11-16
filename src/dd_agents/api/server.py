"""Start the local API: loopback only, random port, per-launch token."""

from __future__ import annotations

import json
import socket
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, BinaryIO

import uvicorn

from dd_agents.api.app import create_app

if TYPE_CHECKING:
    from pathlib import Path

HOST = "127.0.0.1"
READY_PREFIX = "DD_AGENTS_LISTENING "


@dataclass
class ServerHandle:
    server: uvicorn.Server
    sock: socket.socket
    token: str

    @property
    def port(self) -> int:
        return int(self.sock.getsockname()[1])


def prepare(
    *,
    token: str,
    port: int = 0,
    ui_dir: Path | None = None,
    registry_dir: Path | None = None,
) -> ServerHandle:
    """Bind first, then build the server. Port 0 asks the OS for a free port, so there is no race."""
    app = create_app(token=token, registry_dir=registry_dir, ui_dir=ui_dir)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((HOST, port))
        sock.listen(128)
    except OSError:
        sock.close()
        raise
    config = uvicorn.Config(app, log_level="warning", access_log=False, lifespan="on")
    return ServerHandle(uvicorn.Server(config), sock, token)


def ready_line(handle: ServerHandle, *, show_token: bool) -> str:
    """One line the desktop shell reads from stdout. The token is shown only in browser dev mode."""
    payload: dict[str, object] = {"port": handle.port, "host": HOST}
    if show_token:
        payload["token"] = handle.token
    return READY_PREFIX + json.dumps(payload)


def watch_stdin(stream: BinaryIO, server: uvicorn.Server) -> threading.Thread:
    """Exit when the parent closes our stdin. Covers a crashed or force-killed shell."""

    def _wait() -> None:
        try:
            while stream.read(4096):
                pass
        except (OSError, ValueError):
            pass
        server.should_exit = True

    t = threading.Thread(target=_wait, name="stdin-watch", daemon=True)
    t.start()
    return t
