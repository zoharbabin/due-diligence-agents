"""Serve the real API and the built UI with a fake pipeline, for end-to-end tests.

Usage: python serve_fake.py <port> <ui_dir> <registry_dir>
The token is "e2e-token-0123456789". Nothing here is shipped.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn

from dd_agents.api.app import create_app
from dd_agents.api.routers import doctor, settings
from dd_agents.api.runs import RunManager, RunOptions
from dd_agents.persistence.project_registry import ProjectRegistryManager

TOKEN = "e2e-token-0123456789"
FAKE = Path(__file__).with_name("fake_pipeline.py")


def fake_command(config_path: Path, options: RunOptions) -> tuple[list[str], dict[str, str]]:
    return [sys.executable, str(FAKE)], dict(os.environ)


def fake_probe() -> tuple[bool, str]:
    ok = os.environ.get("ANTHROPIC_API_KEY") == "sk-ant-e2e-key-1234"
    return ok, "" if ok else "rejected"


def main() -> None:
    for name in settings.SETTABLE_ENV:  # start from a known state, whatever the developer's shell has
        os.environ.pop(name, None)
    doctor.probe_provider = fake_probe  # type: ignore[assignment]
    port, ui_dir, registry_dir = int(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    registry = ProjectRegistryManager(registry_dir)
    app = create_app(token=TOKEN, registry_dir=registry_dir, ui_dir=ui_dir, run_manager=RunManager(registry, command_factory=fake_command))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
