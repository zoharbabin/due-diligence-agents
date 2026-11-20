"""Serve the real API and the built UI with a fake pipeline, for end-to-end tests.

Usage: python serve_fake.py <port> <ui_dir> <registry_dir>
The token is "e2e-token-0123456789". Nothing here is shipped.
"""

from __future__ import annotations

import asyncio
import json
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
from dd_agents.chat.engine import ChatResponse
from dd_agents.llm.cli_provision import CliInstaller
from dd_agents.persistence.project_registry import ProjectRegistryManager
from dd_agents.screening import store
from dd_agents.screening.sources import SOURCES

if TYPE_CHECKING:
    from collections.abc import Callable

TOKEN = "e2e-token-0123456789"
FAKE = Path(__file__).with_name("fake_pipeline.py")
FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
LISTS = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "screening"
SAMPLES = {
    "ofac_sdn": "ofac_sdn_sample.xml",
    "us_csl": "csl_sample.json",
    "uk": "uk_sample.xml",
    "eu": "eu_sample.xml",
}


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


class FakeChat:
    """Answers without an LLM: streams two text chunks after one tool call."""

    finding_count = 4

    def __init__(self, run_dir: Path, project_dir: Path) -> None:
        self.session_cost = 0.0
        self.turn_count = 0

    async def ask(
        self,
        question: str,
        on_text: Callable[[str], None] | None = None,
        on_tool_status: Callable[[str], None] | None = None,
    ) -> ChatResponse:
        if on_tool_status:
            on_tool_status("search_in_file")
        time.sleep(0.2)
        answer = f"Answer to: {question}"
        if on_text:
            on_text(answer[:8])
            on_text(answer[8:])
        self.turn_count += 1
        self.session_cost += 0.25
        return ChatResponse(
            text=answer, tools_used=["search_in_file"], turn_number=self.turn_count, session_cost=self.session_cost
        )

    async def close(self) -> None:
        return None


def fake_download(url: str, **_: object) -> bytes:
    """Serve the synthetic sanctions lists instead of the network."""
    for source_id, source in SOURCES.items():
        if source.url == url:
            return (LISTS / SAMPLES[source_id]).read_bytes()
    raise store.StoreError("unknown list")


async def fake_suggest(room: Path, buyer: str, target: str) -> dict[str, object]:
    """Take a moment, like the model, then return a valid config with a visible marker."""
    await asyncio.sleep(1.5)
    config: dict[str, object] = json.loads((FIXTURES / "deal_config_valid.json").read_text(encoding="utf-8"))
    config["buyer"] = {"name": buyer}
    config["target"] = {"name": target}
    config["deal"] = {"type": "acquisition", "focus_areas": ["Suggested focus area"]}
    return config


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
    os.environ["DD_SCREENING_DIR"] = str(registry_dir / "screening")
    store._download = fake_download  # type: ignore[assignment]
    registry = ProjectRegistryManager(registry_dir)
    app = create_app(
        token=TOKEN,
        registry_dir=registry_dir,
        ui_dir=ui_dir,
        run_manager=RunManager(registry, command_factory=fake_command),
        cli_installer=CliInstaller(registry_dir / "cli", fake_install),
        chat_factory=FakeChat,
        suggester=fake_suggest,
    )
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
