"""Sign every Mach-O file in a directory tree with a Developer ID identity.

Usage: python desktop/scripts/sign_macos.py <tree> "<identity>"

The embedded Python runtime holds hundreds of .so and .dylib files. Apple's
notary service rejects the app if any of them is unsigned or lacks the hardened
runtime, and Tauri does not sign nested resources. Run this before ``tauri build``.
"""

from __future__ import annotations

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MAGIC = {
    b"\xfe\xed\xfa\xce",
    b"\xfe\xed\xfa\xcf",
    b"\xce\xfa\xed\xfe",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
}


def is_macho(path: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    with path.open("rb") as handle:
        return handle.read(4) in MAGIC


def sign(path: Path, identity: str) -> None:
    subprocess.run(
        ["codesign", "--force", "--options", "runtime", "--timestamp", "--sign", identity, str(path)],
        check=True,
        capture_output=True,
        text=True,
    )


def main() -> None:
    tree, identity = Path(sys.argv[1]), sys.argv[2]
    files = sorted(p for p in tree.rglob("*") if is_macho(p))
    if not files:
        raise SystemExit(f"No Mach-O files found under {tree}")
    with ThreadPoolExecutor(max_workers=8) as pool:
        for future in [pool.submit(sign, p, identity) for p in files]:
            future.result()
    for path in files:
        subprocess.run(["codesign", "--verify", "--strict", str(path)], check=True)
    print(f"signed {len(files)} files")


if __name__ == "__main__":
    main()
