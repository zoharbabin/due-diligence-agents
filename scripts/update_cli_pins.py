"""Pin a Claude CLI version for the desktop app.

Usage: python scripts/update_cli_pins.py [VERSION]   (default: latest on npm)

Reads each platform package's published sha512 digest from the npm registry and
rewrites src/dd_agents/llm/cli_pins.json. Review the diff before committing.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

PINS = Path(__file__).parents[1] / "src" / "dd_agents" / "llm" / "cli_pins.json"
REGISTRY = "https://registry.npmjs.org"


def fetch(path: str) -> dict[str, object]:
    with urllib.request.urlopen(f"{REGISTRY}/{path}", timeout=30) as response:  # noqa: S310
        data: dict[str, object] = json.load(response)
    return data


def main() -> None:
    pins = json.loads(PINS.read_text(encoding="utf-8"))
    version = sys.argv[1] if len(sys.argv) > 1 else str(fetch("@anthropic-ai%2fclaude-code/latest")["version"])
    for key, entry in pins["platforms"].items():
        meta = fetch(f"{entry['package'].replace('/', '%2f')}/{version}")
        dist = meta["dist"]
        assert isinstance(dist, dict)
        entry["integrity"] = dist["integrity"]
        print(f"{key}: {entry['package']}@{version}")
    pins["version"] = version
    PINS.write_text(json.dumps(pins, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
