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


def test_tauri_override_enables_updater_artifacts_only_when_asked() -> None:
    mod: Any = _load("tauri_override")
    assert "createUpdaterArtifacts" not in str(mod.build("1.2.3", None))
    config = mod.build("1.2.3", None, updater=True)
    assert config["bundle"]["createUpdaterArtifacts"] is True
    both = mod.build("1.2.3", Path("/ws/s.py"), updater=True)
    assert both["bundle"]["createUpdaterArtifacts"] is True
    assert "signCommand" in both["bundle"]["windows"]


def _updater_inputs(root: Path) -> None:
    files = {
        "Due Diligence Agents.app.tar.gz": b"mac-update",
        "Due Diligence Agents.app.tar.gz.sig": b"MAC-SIG\n",
        "Due Diligence Agents_1.2.3_aarch64.dmg": b"dmg",
        "Due Diligence Agents_1.2.3_x64-setup.exe": b"win-update",
        "Due Diligence Agents_1.2.3_x64-setup.exe.sig": b"WIN-SIG",
    }
    for name, data in files.items():
        (root / name).write_bytes(data)


def test_updater_manifest_names_files_without_spaces_and_signs_urls(tmp_path: Path) -> None:
    mod: Any = _load("updater_manifest")
    _updater_inputs(tmp_path)
    manifest = mod.prepare(tmp_path, "v1.2.3", "owner/repo")
    names = sorted(p.name for p in tmp_path.iterdir())
    assert all(" " not in n for n in names)
    assert "due-diligence-agents_1.2.3_aarch64.dmg" in names
    assert manifest["version"] == "1.2.3"
    mac = manifest["platforms"]["darwin-aarch64"]
    assert mac["signature"] == "MAC-SIG"
    assert (
        mac["url"]
        == "https://github.com/owner/repo/releases/download/v1.2.3/due-diligence-agents_1.2.3_aarch64.app.tar.gz"
    )
    win = manifest["platforms"]["windows-x86_64"]
    assert win["signature"] == "WIN-SIG"
    assert win["url"].endswith("/v1.2.3/due-diligence-agents_1.2.3_x64-setup.exe")


def test_updater_manifest_refuses_a_missing_signature(tmp_path: Path) -> None:
    import pytest

    mod: Any = _load("updater_manifest")
    _updater_inputs(tmp_path)
    (tmp_path / "Due Diligence Agents_1.2.3_x64-setup.exe.sig").unlink()
    with pytest.raises(SystemExit):
        mod.prepare(tmp_path, "v1.2.3", "owner/repo")


def test_updater_manifest_rejects_a_bad_tag(tmp_path: Path) -> None:
    import pytest

    mod: Any = _load("updater_manifest")
    with pytest.raises(SystemExit):
        mod.prepare(tmp_path, "main", "owner/repo")


def test_runtime_drops_only_packages_that_no_code_imports() -> None:
    """The desktop runtime removes magika and its model runtime. Only office_convert may mention them."""
    import re

    mod: Any = _load("build_runtime")
    assert {"magika", "onnxruntime"} <= set(mod.UNUSED_PACKAGES)
    src = Path(__file__).parents[2] / "src" / "dd_agents"
    importers = {
        p.relative_to(src).as_posix()
        for p in src.rglob("*.py")
        for name in mod.UNUSED_PACKAGES
        if re.search(rf"^\s*(from|import)\s+{name}\b", p.read_text(encoding="utf-8"), re.MULTILINE)
    }
    assert importers <= {"extraction/office_convert.py"}


def _assets(tmp_path: Path, version: str = "1.2.3") -> None:
    (tmp_path / f"due-diligence-agents_{version}_aarch64.dmg").write_bytes(b"dmg bytes")
    (tmp_path / f"due-diligence-agents_{version}_x64-setup.exe").write_bytes(b"exe bytes")


def test_package_manifests_name_the_release_files_and_their_hashes(tmp_path: Path) -> None:
    import hashlib

    mod: Any = _load("package_manifests")
    _assets(tmp_path)
    mod.write(tmp_path, "v1.2.3", "someone/repo")
    cask = (tmp_path / "due-diligence-agents.rb").read_text(encoding="utf-8")
    assert 'version "1.2.3"' in cask
    assert hashlib.sha256(b"dmg bytes").hexdigest() in cask
    assert (
        "https://github.com/someone/repo/releases/download/v#{version}/due-diligence-agents_#{version}_aarch64.dmg"
        in cask
    )
    assert "depends_on arch: :arm64" in cask and 'app "Due Diligence Agents.app"' in cask
    installer = (tmp_path / "zoharbabin.DueDiligenceAgents.installer.yaml").read_text(encoding="utf-8")
    assert hashlib.sha256(b"exe bytes").hexdigest().upper() in installer
    assert "releases/download/v1.2.3/due-diligence-agents_1.2.3_x64-setup.exe" in installer
    assert "InstallerType: nullsoft" in installer and "Scope: user" in installer
    version = (tmp_path / "zoharbabin.DueDiligenceAgents.yaml").read_text(encoding="utf-8")
    assert "PackageVersion: 1.2.3" in version
    locale = (tmp_path / "zoharbabin.DueDiligenceAgents.locale.en-US.yaml").read_text(encoding="utf-8")
    assert "License: Apache-2.0" in locale


def test_package_manifests_need_both_installers(tmp_path: Path) -> None:
    import pytest

    mod: Any = _load("package_manifests")
    (tmp_path / "due-diligence-agents_1.2.3_aarch64.dmg").write_bytes(b"x")
    with pytest.raises(SystemExit):
        mod.write(tmp_path, "v1.2.3", "someone/repo")


def test_package_manifests_reject_a_bad_tag(tmp_path: Path) -> None:
    import pytest

    mod: Any = _load("package_manifests")
    _assets(tmp_path)
    with pytest.raises(SystemExit):
        mod.write(tmp_path, "main", "someone/repo")


def test_installed_app_smoke_reads_the_ready_line_and_the_bundle_layout(tmp_path: Path) -> None:
    mod: Any = _load("smoke_installed")
    assert mod.ready_port('DD_AGENTS_LISTENING {"port": 51234, "host": "127.0.0.1"}\n') == 51234
    assert mod.ready_port("something else") is None
    assert mod.ready_port("DD_AGENTS_LISTENING not-json") is None

    for rel in ("python/bin/python3", "python/python.exe", "ui/index.html"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x")
    python, ui = mod.bundle_paths(tmp_path)
    assert python.name in {"python3", "python.exe"} and ui == tmp_path / "ui"


def test_installed_app_smoke_names_what_is_missing(tmp_path: Path) -> None:
    import pytest

    mod: Any = _load("smoke_installed")
    with pytest.raises(SystemExit, match="python"):
        mod.bundle_paths(tmp_path)
