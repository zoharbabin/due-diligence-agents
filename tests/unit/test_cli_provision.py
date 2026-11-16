"""The Claude CLI provisioner: pinned download, integrity check, safe extract."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import sys
import tarfile
from typing import TYPE_CHECKING, Any

import pytest

from dd_agents.llm import cli_provision as cp

if TYPE_CHECKING:
    from pathlib import Path

BINARY = b"#!/bin/sh\necho fake-claude\n"
NAME = "claude.exe" if sys.platform == "win32" else "claude"


def _tarball(members: dict[str, bytes], *, kind: bytes = tarfile.REGTYPE) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.type = kind
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _integrity(blob: bytes) -> str:
    return "sha512-" + base64.b64encode(hashlib.sha512(blob).digest()).decode()


class _Response(io.BytesIO):
    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


def _pins(blob: bytes, key: str = "test-x64") -> dict[str, Any]:
    entry = {"package": "@anthropic-ai/claude-code-test-x64", "integrity": _integrity(blob)}
    return {"version": "9.9.9", "platforms": {key: entry}}


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "cli"


def _install(root: Path, blob: bytes, pins: dict[str, Any] | None = None, **kw: Any) -> Path:
    seen: list[str] = []

    def opener(url: str) -> _Response:
        seen.append(url)
        return _Response(blob)

    out = cp.install_cli(root, pins=pins or _pins(blob), platform="test-x64", opener=opener, **kw)
    assert seen[0].startswith("https://registry.npmjs.org/@anthropic-ai/claude-code-test-x64/-/")
    return out


def test_installs_the_verified_binary(root: Path) -> None:
    blob = _tarball({f"package/{NAME}": BINARY, "package/LICENSE.md": b"x"})
    path = _install(root, blob)
    assert path == cp.managed_cli_path(root, pins=_pins(blob), platform="test-x64")
    assert path.read_bytes() == BINARY
    if sys.platform != "win32":
        assert path.stat().st_mode & 0o111
    assert not [p for p in root.rglob("*") if p.suffix in {".tmp", ".part"}]


def test_second_install_does_not_download(root: Path) -> None:
    blob = _tarball({f"package/{NAME}": BINARY})
    _install(root, blob)

    def boom(url: str) -> _Response:
        raise AssertionError("must not download again")

    again = cp.install_cli(root, pins=_pins(blob), platform="test-x64", opener=boom)
    assert again.read_bytes() == BINARY


def test_wrong_digest_is_rejected_and_nothing_is_kept(root: Path) -> None:
    blob = _tarball({f"package/{NAME}": BINARY})
    pins = _pins(blob)
    pins["platforms"]["test-x64"]["integrity"] = _integrity(b"something else")
    with pytest.raises(cp.CliProvisionError, match="integrity"):
        _install(root, blob, pins)
    assert cp.managed_cli_path(root, pins=pins, platform="test-x64") is None
    assert not any(p.is_file() for p in root.rglob("*"))


def test_unsupported_platform_is_a_clear_error(root: Path) -> None:
    with pytest.raises(cp.CliProvisionError, match="not supported"):
        cp.install_cli(root, pins=_pins(b"x"), platform="plan9-mips", opener=lambda u: _Response(b""))


def test_archive_without_the_binary_is_rejected(root: Path) -> None:
    blob = _tarball({"package/README.md": b"hi"})
    with pytest.raises(cp.CliProvisionError, match="binary"):
        _install(root, blob)


def test_link_member_is_not_accepted_as_the_binary(root: Path) -> None:
    blob = _tarball({f"package/{NAME}": b""}, kind=tarfile.SYMTYPE)
    with pytest.raises(cp.CliProvisionError, match="binary"):
        _install(root, blob)


def test_progress_is_reported(root: Path) -> None:
    blob = _tarball({f"package/{NAME}": BINARY})
    calls: list[tuple[int, int | None]] = []
    _install(root, blob, on_progress=lambda done, total: calls.append((done, total)))
    assert calls and calls[-1] == (len(blob), len(blob))


def test_old_versions_are_removed_after_success(root: Path) -> None:
    old = root / "1.0.0"
    old.mkdir(parents=True)
    (old / NAME).write_bytes(b"old")
    _install(root, _tarball({f"package/{NAME}": BINARY}))
    assert not old.exists()


def test_only_the_npm_registry_is_used() -> None:
    with pytest.raises(cp.CliProvisionError, match="package"):
        cp.tarball_url({"package": "@evil/pkg", "integrity": "sha512-x"}, "1.0.0")


def test_shipped_pins_are_well_formed() -> None:
    pins = json.loads(cp.PINS_FILE.read_text(encoding="utf-8"))
    assert {"darwin-arm64", "win32-x64"} <= set(pins["platforms"])
    for entry in pins["platforms"].values():
        assert entry["package"].startswith("@anthropic-ai/claude-code-")
        assert base64.b64decode(entry["integrity"].removeprefix("sha512-")).__len__() == 64


def test_resolver_prefers_path_then_managed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from dd_agents.utils import resolve_sdk_cli_path

    managed = tmp_path / NAME
    managed.write_bytes(b"x")
    monkeypatch.delenv("DD_AGENTS_CLI_PATH", raising=False)
    monkeypatch.setattr("shutil.which", lambda _: None)
    monkeypatch.setattr("dd_agents.llm.cli_provision.managed_cli_path", lambda *a, **k: managed)
    assert resolve_sdk_cli_path() == str(managed)
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/claude")
    assert resolve_sdk_cli_path() == "/usr/bin/claude"
