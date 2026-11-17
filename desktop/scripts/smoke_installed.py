"""Smoke test of an INSTALLED desktop app (macOS app folder or Windows install folder).

    python smoke_installed.py RESOURCES_DIR APP SERVICE_LOG

APP is the .app folder on macOS and the .exe on Windows.

1. Start the bundled service the way the app does and call it.
2. Start the real app, check it starts its own service and writes the service log.
3. Kill the app the hard way. The service must stop by itself.

Needs no model and no network. Standard library only.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

READY_PREFIX = "DD_AGENTS_LISTENING "
WINDOWS = sys.platform == "win32"


def ready_port(line: str) -> int | None:
    """Port from the server's one-line ready message, or None."""
    if not line.startswith(READY_PREFIX):
        return None
    try:
        port = json.loads(line[len(READY_PREFIX) :])["port"]
    except (ValueError, KeyError, TypeError):
        return None
    return port if isinstance(port, int) and 0 < port < 65536 else None


def bundle_paths(resources: Path) -> tuple[Path, Path]:
    """The bundled Python and UI folder, as the app finds them."""
    python = resources / "python" / ("python.exe" if WINDOWS else "bin/python3")
    ui = resources / "ui"
    if not python.is_file():
        raise SystemExit(f"python not found at {python}")
    if not (ui / "index.html").is_file():
        raise SystemExit(f"UI not found at {ui}")
    return python, ui


def snapshot(root: Path) -> set[str]:
    """Every path under the bundle, relative to it."""
    return {path.relative_to(root).as_posix() for path in root.rglob("*")}


def check_untouched(root: Path, before: set[str]) -> None:
    """A signed app must not add files to itself while it runs. That breaks the signature."""
    added = sorted(snapshot(root) - before)
    if added:
        raise SystemExit(f"the app changed its own bundle, {len(added)} new files, for example {added[:3]}")


def step(message: str) -> None:
    print(f"[smoke] {message}", flush=True)


def get(port: int, path: str, token: str | None) -> int:
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return int(response.status)
    except urllib.error.HTTPError as err:
        return err.code


def service_pids() -> set[int]:
    """Processes running `dd_agents serve`."""
    if WINDOWS:
        script = (
            "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*dd_agents*serve*' } "
            "| ForEach-Object { $_.ProcessId }"
        )
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True).stdout
    else:
        out = subprocess.run(["pgrep", "-f", "dd_agents serve"], capture_output=True, text=True).stdout
    return {int(p) for p in out.split() if p.isdigit()}


def wait_until(check: Any, seconds: float, what: str) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.5)
    raise SystemExit(f"timed out after {seconds:.0f}s: {what}")


def check_service(python: Path, ui: Path, base_dir: Path) -> None:
    token = "smoke-" + os.urandom(8).hex()
    env = {
        **os.environ,
        "DD_API_TOKEN": token,
        "DD_BASE_DIR": str(base_dir),
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    proc = subprocess.Popen(
        [str(python), "-m", "dd_agents", "serve", "--port", "0", "--exit-on-stdin-close", "--ui-dir", str(ui)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        assert proc.stdout is not None
        deadline = time.monotonic() + 90
        port = None
        while port is None and time.monotonic() < deadline:
            line = proc.stdout.readline()
            if not line and proc.poll() is not None:
                raise SystemExit("the bundled service exited before it was ready")
            port = ready_port(line)
        if port is None:
            raise SystemExit("the bundled service did not report a port in 90 s")
        step(f"bundled service is up on {port}")
        if get(port, "/api/health", token) != 200:
            raise SystemExit("/api/health with the token did not return 200")
        if get(port, "/api/projects", None) not in (401, 403):
            raise SystemExit("/api/projects without a token was not refused")
        if get(port, "/", None) != 200:
            raise SystemExit("the service did not serve the UI")
        step("health, token check and UI are fine")
        assert proc.stdin is not None
        proc.stdin.close()
        wait_until(lambda: proc.poll() is not None, 20, "the service to stop when its stdin closes")
        step("service stops when its stdin closes")
    finally:
        if proc.poll() is None:
            proc.kill()


def app_pids() -> set[int]:
    """Processes of the desktop app itself."""
    if WINDOWS:
        script = "Get-Process -Name due-diligence-agents -ErrorAction SilentlyContinue | ForEach-Object { $_.Id }"
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True).stdout
    else:
        out = subprocess.run(
            ["pgrep", "-f", "Contents/MacOS/due-diligence-agents"], capture_output=True, text=True
        ).stdout
    return {int(p) for p in out.split() if p.isdigit()}


def launch(app: Path, base_dir: Path) -> None:
    """Start the app like a user would. On macOS that is through LaunchServices, which gives it a window session."""
    if WINDOWS:
        env = {**os.environ, "DD_BASE_DIR": str(base_dir)}
        subprocess.Popen([str(app)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.run(["open", "-n", str(app), "--env", f"DD_BASE_DIR={base_dir}"], check=True)


def kill(pid: int) -> None:
    if WINDOWS:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    else:
        os.kill(pid, signal.SIGKILL)


def check_app(app: Path, log: Path, base_dir: Path) -> None:
    before_app, before_service = app_pids(), service_pids()
    log.unlink(missing_ok=True)
    launch(app, base_dir)
    try:
        wait_until(lambda: service_pids() - before_service, 90, "the app to start its service")
        started = service_pids() - before_service
        step(f"the app started its service (pid {sorted(started)})")
        wait_until(log.is_file, 10, f"the service log at {log}")
        step("service log exists")
        for pid in app_pids() - before_app:
            kill(pid)
        wait_until(lambda: not (service_pids() & started), 30, "the service to stop after the app was killed")
        step("service stops by itself after the app is killed")
    finally:
        for pid in app_pids() - before_app:
            kill(pid)


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    resources, app, log = (Path(arg) for arg in sys.argv[1:])
    python, ui = bundle_paths(resources)
    if not app.exists():
        raise SystemExit(f"app not found at {app}")
    before = snapshot(resources)
    with tempfile.TemporaryDirectory(prefix="dd-smoke-") as tmp:
        check_service(python, ui, Path(tmp) / "service")
        check_app(app, log, Path(tmp) / "app")
    check_untouched(resources, before)
    step("the bundle was not changed while it ran")
    step("OK")


if __name__ == "__main__":
    main()
