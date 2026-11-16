"""Provider settings pushed by the desktop shell. Held in process memory, never on disk."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from dd_agents.api.routers.settings import SETTABLE_ENV

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient

SECRET = "sk-ant-pushed-secret-123"


@pytest.fixture(autouse=True)
def _restore_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in SETTABLE_ENV:
        monkeypatch.delenv(name, raising=False)


def test_set_and_clear_credentials(client: TestClient) -> None:
    res = client.put("/api/settings/env", json={"values": {"ANTHROPIC_API_KEY": SECRET}})
    assert res.status_code == 200
    assert res.json() == {"set": ["ANTHROPIC_API_KEY"]}
    assert SECRET not in res.text
    assert os.environ["ANTHROPIC_API_KEY"] == SECRET
    assert client.get("/api/doctor").json()["credential_present"] is True

    client.put("/api/settings/env", json={"values": {"ANTHROPIC_API_KEY": ""}})
    assert "ANTHROPIC_API_KEY" not in os.environ
    assert client.get("/api/doctor").json()["credential_present"] is False


def test_unknown_names_are_rejected_and_nothing_is_applied(client: TestClient) -> None:
    res = client.put("/api/settings/env", json={"values": {"ANTHROPIC_API_KEY": SECRET, "PATH": "/tmp/evil"}})
    assert res.status_code == 422
    assert "PATH" in res.text
    assert SECRET not in res.text
    assert "ANTHROPIC_API_KEY" not in os.environ
    assert os.environ["PATH"] != "/tmp/evil"


@pytest.mark.parametrize("value", ["a\nb", "x\x00y", "z" * 5000])
def test_bad_values_are_rejected(client: TestClient, value: str) -> None:
    res = client.put("/api/settings/env", json={"values": {"ANTHROPIC_API_KEY": value}})
    assert res.status_code == 422
    assert "ANTHROPIC_API_KEY" not in os.environ


def test_secret_is_never_written_to_disk(client: TestClient, registry_dir: Path) -> None:
    client.put("/api/settings/env", json={"values": {"ANTHROPIC_API_KEY": SECRET}})
    for f in registry_dir.rglob("*"):
        if f.is_file():
            assert SECRET not in f.read_text(errors="ignore")


def test_get_reports_names_only(client: TestClient) -> None:
    client.put("/api/settings/env", json={"values": {"ANTHROPIC_API_KEY": SECRET, "CLAUDE_CODE_USE_BEDROCK": "1"}})
    res = client.get("/api/settings/env")
    assert res.json() == {"set": ["ANTHROPIC_API_KEY", "CLAUDE_CODE_USE_BEDROCK"], "settable": sorted(SETTABLE_ENV)}
    assert SECRET not in res.text


def test_runs_inherit_the_pushed_env(client: TestClient, tmp_path: Path) -> None:
    from dd_agents.api.runs import RunOptions, default_command

    client.put("/api/settings/env", json={"values": {"ANTHROPIC_API_KEY": SECRET}})
    _, env = default_command(tmp_path / "c.json", RunOptions())
    assert env["ANTHROPIC_API_KEY"] == SECRET
