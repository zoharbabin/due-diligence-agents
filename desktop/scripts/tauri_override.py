"""Print a Tauri config override as JSON, for ``tauri build --config <file>``.

Usage: python desktop/scripts/tauri_override.py <version> [--windows-sign-script PATH] [--updater]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def build(version: str, windows_sign_script: Path | None, *, updater: bool = False) -> dict[str, object]:
    """``updater`` needs ``TAURI_SIGNING_PRIVATE_KEY`` in the environment, so only release builds set it."""
    config: dict[str, object] = {"version": version}
    bundle: dict[str, object] = {}
    if windows_sign_script is not None:
        sign = {"cmd": "python", "args": [windows_sign_script.as_posix(), "%1"]}
        bundle["windows"] = {"signCommand": sign}
    if updater:
        bundle["createUpdaterArtifacts"] = True
    if bundle:
        config["bundle"] = bundle
    return config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("version")
    parser.add_argument("--windows-sign-script", type=Path)
    parser.add_argument("--updater", action="store_true")
    args = parser.parse_args()
    print(json.dumps(build(args.version, args.windows_sign_script, updater=args.updater)))


if __name__ == "__main__":
    main()
