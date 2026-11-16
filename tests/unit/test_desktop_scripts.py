"""Pure helpers in the desktop release scripts (no signing happens here)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from types import ModuleType

SCRIPTS = Path(__file__).parents[2] / "desktop" / "scripts"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_macho_detection_ignores_text_and_symlinks(tmp_path: Path) -> None:
    mod: Any = _load("sign_macos")
    thin = tmp_path / "lib.so"
    thin.write_bytes(b"\xcf\xfa\xed\xfe" + b"\0" * 16)
    fat = tmp_path / "fat.dylib"
    fat.write_bytes(b"\xca\xfe\xba\xbe" + b"\0" * 16)
    text = tmp_path / "script.py"
    text.write_text("print(1)")
    link = tmp_path / "link.so"
    link.symlink_to(thin)
    assert mod.is_macho(thin) and mod.is_macho(fat)
    assert not mod.is_macho(text) and not mod.is_macho(link) and not mod.is_macho(tmp_path)


def test_windows_collect_takes_binaries_from_directories(tmp_path: Path) -> None:
    mod: Any = _load("sign_windows")
    (tmp_path / "sub").mkdir()
    for name in ("python.exe", "sub/_ssl.pyd", "sub/vcruntime.DLL", "sub/readme.txt"):
        (tmp_path / name).write_bytes(b"MZ")
    names = {p.name for p in mod.collect([str(tmp_path)])}
    assert names == {"python.exe", "_ssl.pyd", "vcruntime.DLL"}


def test_runtime_pins_cover_both_targets() -> None:
    import json

    pins = json.loads((SCRIPTS.parent / "runtime-pins.json").read_text(encoding="utf-8"))
    assert set(pins["targets"]) == {"aarch64-apple-darwin", "x86_64-pc-windows-msvc"}
    for entry in pins["targets"].values():
        assert len(entry["sha256"]) == 64
        assert pins["python"] in entry["asset"] and pins["release"] in entry["asset"]


def test_tauri_override_adds_signing_only_when_asked() -> None:
    mod: Any = _load("tauri_override")
    assert mod.build("1.2.3", None) == {"version": "1.2.3"}
    signed = mod.build("1.2.3", Path("/ws/desktop/scripts/sign_windows.py"))
    command = signed["bundle"]["windows"]["signCommand"]
    assert command["args"] == ["/ws/desktop/scripts/sign_windows.py", "%1"]
