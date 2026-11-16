"""Sign Windows files with Azure Artifact Signing, through Microsoft's signtool and dlib.

Usage: python desktop/scripts/sign_windows.py <file-or-dir> [<file-or-dir> ...]

Directories are searched for .exe, .dll and .pyd files. Tauri calls this for
the app and the installer (see ``--config`` in desktop.yml). Environment:
``SIGNTOOL`` (path to signtool.exe), ``ACS_DLIB`` (Azure.CodeSigning.Dlib.dll),
``ACS_METADATA`` (metadata.json with endpoint, account and profile), plus the
Azure service principal variables the dlib reads.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SUFFIXES = {".exe", ".dll", ".pyd"}
BATCH = 40
TIMESTAMP = "http://timestamp.acs.microsoft.com"


def collect(args: list[str]) -> list[Path]:
    files: list[Path] = []
    for arg in args:
        path = Path(arg)
        if path.is_dir():
            files += [p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in SUFFIXES]
        else:
            files.append(path)
    return sorted(files)


def sign(files: list[Path]) -> None:
    base = [
        os.environ["SIGNTOOL"],
        "sign",
        "/v",
        "/fd",
        "SHA256",
        "/tr",
        TIMESTAMP,
        "/td",
        "SHA256",
        "/dlib",
        os.environ["ACS_DLIB"],
        "/dmdf",
        os.environ["ACS_METADATA"],
    ]
    for start in range(0, len(files), BATCH):
        subprocess.run([*base, *map(str, files[start : start + BATCH])], check=True)


def main() -> None:
    files = collect(sys.argv[1:])
    if not files:
        raise SystemExit("Nothing to sign")
    sign(files)
    print(f"signed {len(files)} files")


if __name__ == "__main__":
    main()
