"""Pre-flight check for the desktop app's first-run screen."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from .conftest import AUTH, BASE, TOKEN

if TYPE_CHECKING:
    from pathlib import Path

SECRET = "sk-ant-super-secret-value"
ENV_NAMES = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "AWS_PROFILE",
    "AWS_ACCESS_KEY_ID",
    "AWS_BEARER_TOKEN_BEDROCK",
    "DD_AGENTS_CLI_PATH",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_missing_credential_is_reported_with_names_only(client: TestClient) -> None:
    body = client.get("/api/doctor").json()
    assert body["provider"] == "anthropic"
    assert body["credential_present"] is False
    assert body["credential_env"] == ["ANTHROPIC_API_KEY"]
    assert body["ready"] is False


def test_credential_value_never_leaves_the_server(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    res = client.get("/api/doctor")
    assert res.json()["credential_present"] is True
    assert SECRET not in res.text


def test_gateway_url_is_redacted(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://user:hunter2@gw.example.com:8443/v1?api-key=abc")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", SECRET)
    res = client.get("/api/doctor")
    body = res.json()
    assert body["provider"] == "gateway"
    assert body["base_url"] == "https://gw.example.com:8443/v1"
    assert "hunter2" not in res.text
    assert "abc" not in res.text
    assert SECRET not in res.text


def test_cli_source_env_override(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = tmp_path / "claude"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setenv("DD_AGENTS_CLI_PATH", str(fake))
    body = client.get("/api/doctor").json()
    assert body["cli"] == {"found": True, "source": "env"}
    assert str(fake) not in client.get("/api/doctor").text


def test_probe_reports_result(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dd_agents.api.routers.doctor.probe_provider", lambda: (True, "response chars: 2"))
    assert client.post("/api/doctor/probe").json() == {"ok": True, "detail": "response chars: 2"}


def test_probe_failure_detail_is_scrubbed_of_secrets(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    monkeypatch.setattr("dd_agents.api.routers.doctor.probe_provider", lambda: (False, f"401 for key {SECRET}"))
    res = client.post("/api/doctor/probe")
    assert res.json()["ok"] is False
    assert SECRET not in res.text


def test_doctor_needs_the_token(client: TestClient) -> None:
    assert client.get("/api/doctor", headers={"Authorization": "Bearer nope-nope-nope-nope"}).status_code == 401


def test_managed_cli_counts_as_found(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = tmp_path / "claude"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.delenv("DD_AGENTS_CLI_PATH", raising=False)
    monkeypatch.setattr("shutil.which", lambda _: None)
    monkeypatch.setattr("dd_agents.api.routers.doctor.managed_cli_path", lambda: fake)
    body = client.get("/api/doctor").json()
    assert body["cli"] == {"found": True, "source": "managed"}
    assert str(fake) not in client.get("/api/doctor").text


def test_cli_install_reports_progress_and_finishes(registry_dir: Path) -> None:
    import threading

    from dd_agents.api.app import create_app
    from dd_agents.llm.cli_provision import CliInstaller

    gate = threading.Event()

    def fake_install(root: Path, *, on_progress: Any) -> Path:
        on_progress(5, 10)
        gate.wait(5)
        return root / "claude"

    app = create_app(token=TOKEN, registry_dir=registry_dir, cli_installer=CliInstaller(registry_dir, fake_install))
    with TestClient(app, base_url=BASE, headers=AUTH) as c:
        assert c.get("/api/cli/install").json()["state"] == "idle"
        first = c.post("/api/cli/install")
        assert first.status_code == 202
        assert c.post("/api/cli/install").status_code == 202  # idempotent while running
        for _ in range(100):
            if c.get("/api/cli/install").json()["done"] == 5:
                break
            time.sleep(0.02)
        assert c.get("/api/cli/install").json() == {"state": "downloading", "done": 5, "total": 10, "error": None}
        gate.set()
        for _ in range(100):
            if c.get("/api/cli/install").json()["state"] == "done":
                break
            time.sleep(0.02)
        assert c.get("/api/cli/install").json()["state"] == "done"


def test_cli_install_failure_is_reported_without_a_traceback(registry_dir: Path) -> None:
    from dd_agents.api.app import create_app
    from dd_agents.llm.cli_provision import CliInstaller, CliProvisionError

    def failing(root: Path, *, on_progress: Any) -> Path:
        raise CliProvisionError("The download failed the integrity check.")

    installer = CliInstaller(registry_dir, failing)
    app = create_app(token=TOKEN, registry_dir=registry_dir, cli_installer=installer)
    with TestClient(app, base_url=BASE, headers=AUTH) as c:
        c.post("/api/cli/install")
        for _ in range(100):
            body = c.get("/api/cli/install").json()
            if body["state"] == "error":
                break
            time.sleep(0.02)
        assert body["state"] == "error"
        assert body["error"] == "The download failed the integrity check."
