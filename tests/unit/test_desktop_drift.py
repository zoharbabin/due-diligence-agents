"""The desktop shell (Rust) repeats a few contracts from Python. Fail CI when they drift."""

from __future__ import annotations

import json
import re
from pathlib import Path

from dd_agents.api.routers.settings import SETTABLE_ENV

SHELL = Path(__file__).parents[2] / "desktop" / "src-tauri"


def _rust_list(src: str, name: str) -> set[str]:
    m = re.search(rf"{name}: &\[&str\] = &\[(.*?)\];", src, re.S)
    assert m, f"{name} not found"
    return set(re.findall(r'"([A-Z0-9_]+)"', m.group(1)))


def test_keychain_allowlist_matches_the_api_allowlist() -> None:
    src = (SHELL / "src" / "secrets.rs").read_text(encoding="utf-8")
    assert _rust_list(src, "SETTABLE_ENV") == set(SETTABLE_ENV)


def test_every_command_is_declared_registered_and_permitted() -> None:
    build = (SHELL / "build.rs").read_text(encoding="utf-8")
    lib = (SHELL / "src" / "lib.rs").read_text(encoding="utf-8")
    match = re.search(r"commands\(&\[(.*?)\]", build, re.S)
    assert match
    declared = set(re.findall(r'"([a-z_]+)"', match.group(1)))
    registered = set(re.findall(r"generate_handler!\[(.*?)\]", lib, re.S)[0].replace(" ", "").split(","))
    assert declared == registered
    caps = json.loads((SHELL / "capabilities" / "main.json").read_text(encoding="utf-8"))
    allowed = {p.removeprefix("allow-").replace("-", "_") for p in caps["permissions"] if p.startswith("allow-")}
    assert allowed == declared
