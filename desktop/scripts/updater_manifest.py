"""Prepare release assets and write the updater manifest (``latest.json``).

Usage: python desktop/scripts/updater_manifest.py <tag> <owner/repo> <assets-dir>

Renames every asset to a name without spaces (GitHub rewrites spaces, which would break the URLs)
and refuses to continue when an updater signature is missing.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

NAME = "due-diligence-agents"
# platform key -> (suffix of the file the updater downloads, final name). A ".sig" sits next to each.
UPDATER_FILES = {
    "darwin-aarch64": (".app.tar.gz", f"{NAME}_{{version}}_aarch64.app.tar.gz"),
    "windows-x86_64": ("-setup.exe", f"{NAME}_{{version}}_x64-setup.exe"),
}


def _slug(name: str) -> str:
    return name.replace("Due Diligence Agents", NAME).replace(" ", "-")


def prepare(directory: Path, tag: str, repo: str) -> dict[str, object]:
    match = re.fullmatch(r"v(\d+\.\d+\.\d+)", tag)
    if not match:
        sys.exit(f"Not a release tag: {tag!r}")
    version = match.group(1)
    for path in sorted(directory.iterdir()):
        if " " in path.name:
            path.rename(directory / _slug(path.name))
    platforms: dict[str, dict[str, str]] = {}
    for platform, (suffix, template) in UPDATER_FILES.items():
        found = [p for p in directory.iterdir() if p.name.endswith(suffix)]
        if len(found) != 1:
            sys.exit(f"Expected one *{suffix} in {directory}, found {len(found)}")
        asset = found[0]
        sig = asset.with_name(asset.name + ".sig")
        if not sig.is_file():
            sys.exit(f"Missing updater signature: {sig.name}")
        final = directory / template.format(version=version)
        if asset != final:
            asset.rename(final)
            sig.rename(final.with_name(final.name + ".sig"))
        sig = final.with_name(final.name + ".sig")
        platforms[platform] = {
            "signature": sig.read_text(encoding="utf-8").strip(),
            "url": f"https://github.com/{repo}/releases/download/{tag}/{final.name}",
        }
    return {
        "version": version,
        "notes": f"https://github.com/{repo}/releases/tag/{tag}",
        "pub_date": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platforms": platforms,
    }


def main() -> None:
    tag, repo, directory = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    manifest = prepare(directory, tag, repo)
    (directory / "latest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
