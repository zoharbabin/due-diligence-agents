"""Download the pinned Claude CLI on first run.

The desktop app does not ship the CLI. It fetches the platform package that
Anthropic publishes to npm, checks the SHA-512 digest pinned in
``cli_pins.json``, and keeps the one binary in a per-user folder. The binary is
never modified or re-signed. Bump the pins with ``scripts/update_cli_pins.py``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform as _platform
import re
import shutil
import sys
import tarfile
import tempfile
import threading
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import IO, Any

PINS_FILE = Path(__file__).with_name("cli_pins.json")
REGISTRY = "https://registry.npmjs.org"
MAX_DOWNLOAD_BYTES = 1 << 30
_CHUNK = 1 << 20
_PACKAGE_RE = re.compile(r"^@anthropic-ai/(claude-code-[a-z0-9-]+)$")

Progress = Callable[[int, "int | None"], None]
Opener = Callable[[str], Any]


class CliProvisionError(RuntimeError):
    """The CLI could not be installed. The message is safe to show to the user."""


def managed_root() -> Path:
    base = Path(os.environ.get("DD_BASE_DIR", "~/.dd-projects")).expanduser()
    return base / ".cli"


def platform_key() -> str:
    system = {"darwin": "darwin", "win32": "win32"}.get(sys.platform, "linux")
    machine = _platform.machine().lower()
    arch = "arm64" if machine in {"arm64", "aarch64"} else "x64" if machine in {"x86_64", "amd64"} else machine
    return f"{system}-{arch}"


def _binary_name() -> str:
    return "claude.exe" if sys.platform == "win32" else "claude"


def load_pins() -> dict[str, Any]:
    pins: dict[str, Any] = json.loads(PINS_FILE.read_text(encoding="utf-8"))
    return pins


def tarball_url(entry: dict[str, Any], version: str) -> str:
    match = _PACKAGE_RE.match(str(entry.get("package", "")))
    if match is None:
        raise CliProvisionError("The pinned package is not an Anthropic Claude Code package.")
    return f"{REGISTRY}/{entry['package']}/-/{match.group(1)}-{version}.tgz"


def managed_cli_path(
    root: Path | None = None, *, pins: dict[str, Any] | None = None, platform: str | None = None
) -> Path | None:
    """Path of the installed pinned CLI, or ``None`` if it is not installed."""
    pins = pins or load_pins()
    if (platform or platform_key()) not in pins["platforms"]:
        return None
    path = (root or managed_root()) / str(pins["version"]) / _binary_name()
    return path if path.is_file() else None


def _download(url: str, dest: IO[bytes], expected: str, opener: Opener, on_progress: Progress | None) -> None:
    digest = hashlib.sha512()
    done = 0
    try:
        with opener(url) as response:
            length = response.headers.get("Content-Length")
            total = int(length) if length and length.isdigit() else None
            while chunk := response.read(_CHUNK):
                done += len(chunk)
                if done > MAX_DOWNLOAD_BYTES:
                    raise CliProvisionError("The download is larger than expected.")
                digest.update(chunk)
                dest.write(chunk)
                if on_progress:
                    on_progress(done, total)
    except OSError as exc:
        raise CliProvisionError(f"The download failed: {exc}") from exc
    if "sha512-" + base64.b64encode(digest.digest()).decode() != expected:
        raise CliProvisionError("The download failed the integrity check and was discarded.")


def _extract_binary(archive: Path, dest: Path) -> None:
    wanted = f"package/{_binary_name()}"
    try:
        with tarfile.open(archive, mode="r:gz") as tar:
            for member in tar:
                if member.name != wanted:
                    continue
                if not member.isreg():
                    break
                source = tar.extractfile(member)
                if source is None:
                    break
                with dest.open("wb") as out:
                    shutil.copyfileobj(source, out, _CHUNK)
                return
    except (tarfile.TarError, OSError) as exc:
        raise CliProvisionError(f"The package could not be unpacked: {exc}") from exc
    raise CliProvisionError("The package does not contain the Claude CLI binary.")


def install_cli(
    root: Path,
    *,
    pins: dict[str, Any] | None = None,
    platform: str | None = None,
    opener: Opener | None = None,
    on_progress: Progress | None = None,
) -> Path:
    """Install the pinned CLI under ``root``. Safe to call again: it is a no-op once installed."""
    pins = pins or load_pins()
    key = platform or platform_key()
    entry = pins["platforms"].get(key)
    if entry is None:
        raise CliProvisionError(f"The Claude CLI download is not supported on {key}.")
    existing = managed_cli_path(root, pins=pins, platform=key)
    if existing is not None:
        return existing

    version = str(pins["version"])
    url = tarball_url(entry, version)
    if not url.startswith(REGISTRY + "/"):
        raise CliProvisionError("Refusing to download from an unexpected host.")
    root.mkdir(parents=True, exist_ok=True)
    final = root / version / _binary_name()
    final.parent.mkdir(parents=True, exist_ok=True)
    fetch = opener or (lambda u: urllib.request.urlopen(u, timeout=60))  # noqa: S310 - https URL checked above

    with tempfile.TemporaryDirectory(dir=root, prefix=".tmp-") as tmp:
        archive = Path(tmp) / "package.tgz"
        staged = Path(tmp) / _binary_name()
        with archive.open("wb") as handle:
            _download(url, handle, str(entry["integrity"]), fetch, on_progress)
        _extract_binary(archive, staged)
        if sys.platform != "win32":
            staged.chmod(0o755)
        os.replace(staged, final)

    for old in root.iterdir():
        if old.is_dir() and old.name != version and not old.name.startswith(".tmp-"):
            shutil.rmtree(old, ignore_errors=True)
    return final


class CliInstaller:
    """Runs one install at a time in a thread and exposes its state for polling."""

    def __init__(self, root: Path | None = None, install: Callable[..., Path] = install_cli) -> None:
        self._root = root
        self._install = install
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state: dict[str, Any] = {"state": "idle", "done": 0, "total": None, "error": None}

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return dict(self._state)
            self._state = {"state": "downloading", "done": 0, "total": None, "error": None}
            self._thread = threading.Thread(target=self._run, name="cli-install", daemon=True)
            self._thread.start()
            return dict(self._state)

    def _progress(self, done: int, total: int | None) -> None:
        with self._lock:
            self._state.update(done=done, total=total)

    def _run(self) -> None:
        try:
            self._install(self._root or managed_root(), on_progress=self._progress)
        except CliProvisionError as exc:
            result: dict[str, Any] = {"state": "error", "error": str(exc)}
        except Exception as exc:  # noqa: BLE001 - never let the thread die silently
            result = {"state": "error", "error": f"Unexpected error: {type(exc).__name__}"}
        else:
            result = {"state": "done", "error": None}
        with self._lock:
            self._state.update(result)
