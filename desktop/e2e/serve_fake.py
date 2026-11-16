"""Serve the real API and the built UI with a fake pipeline, for end-to-end tests.

Usage: python serve_fake.py <port> <ui_dir> <registry_dir>
The token is "e2e-token-0123456789". Nothing here is shipped.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import uvicorn

from dd_agents.api.app import create_app
from dd_agents.api.routers import doctor, settings
from dd_agents.api.runs import RunManager, RunOptions
from dd_agents.llm.cli_provision import CliInstaller
from dd_agents.persistence.project_registry import ProjectRegistryManager

if TYPE_CHECKING:
    from collections.abc import Callable

TOKEN = "e2e-token-0123456789"
FAKE = Path(__file__).with_name("fake_pipeline.py")


def fake_command(config_path: Path, options: RunOptions) -> tuple[list[str], dict[str, str]]:
    return [sys.executable, str(FAKE)], dict(os.environ)


def fake_probe() -> tuple[bool, str]:
    ok = os.environ.get("ANTHROPIC_API_KEY") == "sk-ant-e2e-key-1234"
    return ok, "" if ok else "rejected"


def fake_install(root: Path, *, on_progress: Callable[[int, int | None], None]) -> Path:
    """Pretends to download 4 MB in four steps, then installs a stand-in binary."""
    for step in range(1, 5):
        on_progress(step * 1_000_000, 4_000_000)
        time.sleep(0.4)
    root.mkdir(parents=True, exist_ok=True)
    binary = root / "claude"
    binary.write_text("#!/bin/sh\n")
    return binary


def main() -> None:
    for name in settings.SETTABLE_ENV:  # start from a known state, whatever the developer's shell has
        os.environ.pop(name, None)
    doctor.probe_provider = fake_probe  # type: ignore[assignment]
    port, ui_dir, registry_dir = int(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    # Start like a fresh machine: no CLI anywhere until the fake download "installs" one.
    os.environ.pop("DD_AGENTS_CLI_PATH", None)
    installed = registry_dir / "cli" / "claude"
    doctor._sdk_bundles_cli = lambda: False  # type: ignore[assignment]
    doctor.managed_cli_path = lambda: installed if installed.is_file() else None  # type: ignore[assignment]
    doctor.shutil = SimpleNamespace(which=lambda *_a, **_k: None)  # type: ignore[assignment]
    registry = ProjectRegistryManager(registry_dir)
    app = create_app(
        token=TOKEN,
        registry_dir=registry_dir,
        ui_dir=ui_dir,
        run_manager=RunManager(registry, command_factory=fake_command),
        cli_installer=CliInstaller(registry_dir / "cli", fake_install),
    )
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
