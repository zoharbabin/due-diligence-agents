"""Print a Tauri config override as JSON, for ``tauri build --config <file>``.

Usage: python desktop/scripts/tauri_override.py <version> [--windows-sign-script PATH]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def build(version: str, windows_sign_script: Path | None) -> dict[str, object]:
    config: dict[str, object] = {"version": version}
    if windows_sign_script is not None:
        sign = {"cmd": "python", "args": [windows_sign_script.as_posix(), "%1"]}
        config["bundle"] = {"windows": {"signCommand": sign}}
    return config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("version")
    parser.add_argument("--windows-sign-script", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.version, args.windows_sign_script)))


if __name__ == "__main__":
    main()
