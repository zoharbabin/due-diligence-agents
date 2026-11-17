"""Build the Python runtime that the desktop app ships.

Usage: python desktop/scripts/build_runtime.py [--out DIR]

Downloads the pinned python-build-standalone archive for this machine, checks
its SHA-256, unpacks it to ``<out>/python``, installs dd-agents from this
checkout into it, and strips what the app does not need. Run it on each target
OS: the installed wheels are platform specific. The Claude CLI that the SDK
wheel bundles is removed, because the app downloads its own pinned copy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PINS = ROOT / "desktop" / "runtime-pins.json"
BASE_URL = "https://github.com/astral-sh/python-build-standalone/releases/download"


def host_target() -> str:
    machine = platform.machine().lower()
    if sys.platform == "darwin" and machine in {"arm64", "aarch64"}:
        return "aarch64-apple-darwin"
    if sys.platform == "win32" and machine in {"amd64", "x86_64"}:
        return "x86_64-pc-windows-msvc"
    raise SystemExit(f"Unsupported build machine: {sys.platform}/{machine}")


def python_exe(runtime: Path) -> Path:
    return runtime / "python.exe" if sys.platform == "win32" else runtime / "bin" / "python3"


def fetch(release: str, asset: str, sha256: str, cache: Path) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / asset
    if not archive.is_file():
        part = archive.with_suffix(".part")
        with (
            urllib.request.urlopen(f"{BASE_URL}/{release}/{asset.replace('+', '%2B')}", timeout=120) as r,
            part.open("wb") as f,
        ):  # noqa: S310
            shutil.copyfileobj(r, f)
        part.replace(archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != sha256:
        archive.unlink()
        raise SystemExit(f"SHA-256 mismatch for {asset}: got {digest}")
    return archive


# Pulled in by markitdown through magika, which only guesses file types. dd-agents does that itself
# (extraction/file_type.py) and loads markitdown with a stand-in (extraction/office_convert.py).
# Together about 100 MB. flatbuffers and protobuf are only needed by onnxruntime.
UNUSED_PACKAGES = ("magika", "onnxruntime", "flatbuffers", "protobuf")


def prune(runtime: Path) -> None:
    for site in runtime.rglob("site-packages"):
        shutil.rmtree(site / "claude_agent_sdk" / "_bundled", ignore_errors=True)
        for leftover in site.glob("pip*"):
            shutil.rmtree(leftover, ignore_errors=True) if leftover.is_dir() else leftover.unlink()
    for cache in runtime.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


def compile_bytecode(runtime: Path, py: Path) -> None:
    """Make the .pyc files now, before the app is signed.

    A signed app must not change when it runs. Without this, Python writes .pyc files into the bundle on
    first start and the signature seal breaks. Hash-based and unchecked: valid after any copy or update.
    The tcl folder holds Tk sample scripts that do not compile and never run, so it is skipped.
    """
    skip = r"[\\/]tcl[\\/]"
    cmd = [str(py), "-m", "compileall", "-q", "-j", "0", "-x", skip, "--invalidation-mode", "unchecked-hash"]
    subprocess.run([*cmd, str(runtime)], check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "desktop" / "src-tauri" / "resources")
    out: Path = parser.parse_args().out
    pins = json.loads(PINS.read_text(encoding="utf-8"))
    entry = pins["targets"][host_target()]
    archive = fetch(pins["release"], entry["asset"], entry["sha256"], ROOT / "desktop" / ".cache")

    runtime = out / "python"
    shutil.rmtree(runtime, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as tar:
        tar.extractall(out, filter="data")
    py = python_exe(runtime)
    subprocess.run([str(py), "-m", "pip", "install", "--no-warn-script-location", f"{ROOT}[app,pdf]"], check=True)
    subprocess.run([str(py), "-m", "pip", "uninstall", "--yes", *UNUSED_PACKAGES], check=True)
    frozen = subprocess.run([str(py), "-m", "pip", "freeze"], check=True, capture_output=True, text=True).stdout
    (out / "runtime-packages.txt").write_text(frozen, encoding="utf-8")
    smoke = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    check = (
        "import dd_agents.api.app, dd_agents.cli\n"
        "from dd_agents.extraction.office_convert import _load_markitdown\n"
        "_load_markitdown()"
    )
    subprocess.run([str(py), "-I", "-c", check], check=True, env=smoke)
    prune(runtime)
    compile_bytecode(runtime, py)
    size = sum(p.stat().st_size for p in runtime.rglob("*") if p.is_file())
    print(f"runtime ready: {runtime} ({size / 1_048_576:.0f} MB)")


if __name__ == "__main__":
    main()
