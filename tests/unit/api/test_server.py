"""``dd-agents serve``: loopback socket, ready line, stdin-close shutdown."""

from __future__ import annotations

import json
import os
import threading
import time
from typing import TYPE_CHECKING

import httpx
from click.testing import CliRunner

from dd_agents.api.server import READY_PREFIX, prepare, ready_line, watch_stdin
from dd_agents.cli import main

from .conftest import TOKEN

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _run_in_thread(handle: object) -> threading.Thread:
    from dd_agents.api.server import ServerHandle

    assert isinstance(handle, ServerHandle)
    t = threading.Thread(target=lambda: handle.server.run(sockets=[handle.sock]), daemon=True)
    t.start()
    deadline = time.monotonic() + 10
    while not handle.server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert handle.server.started
    return t


def test_binds_loopback_on_a_random_port(tmp_path: Path) -> None:
    handle = prepare(token=TOKEN, registry_dir=tmp_path)
    try:
        host, port = handle.sock.getsockname()[:2]
        assert host == "127.0.0.1"
        assert port == handle.port > 0
        t = _run_in_thread(handle)
        r = httpx.get(f"http://127.0.0.1:{handle.port}/api/health", headers={"Authorization": f"Bearer {TOKEN}"})
        assert r.status_code == 200
        assert httpx.get(f"http://127.0.0.1:{handle.port}/api/health").status_code == 401
        handle.server.should_exit = True
        t.join(timeout=10)
        assert not t.is_alive()
    finally:
        handle.sock.close()


def test_ready_line_is_one_json_line_without_the_token(tmp_path: Path) -> None:
    handle = prepare(token=TOKEN, registry_dir=tmp_path)
    try:
        line = ready_line(handle, show_token=False)
        assert line.startswith(READY_PREFIX)
        payload = json.loads(line[len(READY_PREFIX) :])
        assert payload == {"port": handle.port, "host": "127.0.0.1"}
        assert TOKEN not in line
        assert json.loads(ready_line(handle, show_token=True)[len(READY_PREFIX) :])["token"] == TOKEN
    finally:
        handle.sock.close()


class _FakeServer:
    should_exit = False


def test_stdin_close_stops_the_server() -> None:
    r, w = os.pipe()
    fake = _FakeServer()
    t = watch_stdin(os.fdopen(r, "rb"), fake)  # type: ignore[arg-type]  # test double for uvicorn.Server
    time.sleep(0.1)
    assert fake.should_exit is False
    os.close(w)
    t.join(timeout=5)
    assert fake.should_exit is True


def test_stdin_data_does_not_stop_the_server() -> None:
    r, w = os.pipe()
    fake = _FakeServer()
    watch_stdin(os.fdopen(r, "rb"), fake)  # type: ignore[arg-type]  # test double for uvicorn.Server
    os.write(w, b"hello")
    time.sleep(0.2)
    assert fake.should_exit is False
    os.close(w)


def test_cli_has_no_host_option() -> None:
    result = CliRunner().invoke(main, ["serve", "--help"])
    assert result.exit_code == 0
    assert "--host" not in result.output
    assert "--exit-on-stdin-close" in result.output


def test_short_token_env_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DD_API_TOKEN", "short")
    result = CliRunner().invoke(main, ["serve"])
    assert result.exit_code != 0
    assert "token" in result.output.lower()
