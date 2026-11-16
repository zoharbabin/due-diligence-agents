"""Suggest setup: an LLM-drafted deal config, held as a draft until the user saves it. The LLM is faked."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from dd_agents.api.app import create_app

from .conftest import AUTH, BASE, TOKEN

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

DRAFT = {"buyer": {"name": "Buyer Co"}, "target": {"name": "Target Co"}}


class FakeSuggester:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, str, str]] = []
        self.gate: asyncio.Event | None = None
        self.fail: Exception | None = None

    async def __call__(self, room: Path, buyer: str, target: str) -> dict[str, Any]:
        self.calls.append((room, buyer, target))
        if self.gate is not None:
            await self.gate.wait()
        if self.fail:
            raise self.fail
        return DRAFT


@pytest.fixture
def fake() -> FakeSuggester:
    return FakeSuggester()


@pytest.fixture
def suggest_client(registry_dir: Path, fake: FakeSuggester) -> Iterator[TestClient]:
    app = create_app(token=TOKEN, registry_dir=registry_dir, suggester=fake)
    with TestClient(app, base_url=BASE, headers=AUTH) as c:
        yield c


def _project(client: TestClient, room: Path, *, named: bool = True) -> None:
    assert client.post("/api/projects", json={"name": "Deal", "data_room": str(room)}).status_code == 201
    if named:
        client.app.state.ctx.registry.update_project("deal", buyer="Buyer Co", target="Target Co")  # type: ignore[attr-defined]


def _wait_for(client: TestClient, state: str) -> dict[str, Any]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        body: dict[str, Any] = client.get("/api/projects/deal/config/suggest").json()
        if body["state"] == state:
            return body
        time.sleep(0.02)
    raise AssertionError(f"never reached {state}")


def test_idle_before_any_request(suggest_client: TestClient, data_room: Path) -> None:
    _project(suggest_client, data_room)
    assert suggest_client.get("/api/projects/deal/config/suggest").json() == {"state": "idle"}


def test_draft_is_returned_and_nothing_is_written(
    suggest_client: TestClient, data_room: Path, fake: FakeSuggester
) -> None:
    _project(suggest_client, data_room)
    before = sorted(p.name for p in data_room.iterdir())
    res = suggest_client.post("/api/projects/deal/config/suggest")
    assert res.status_code == 202
    body = _wait_for(suggest_client, "done")
    assert body["config"] == DRAFT
    assert fake.calls == [(data_room, "Buyer Co", "Target Co")]
    assert sorted(p.name for p in data_room.iterdir()) == before


def test_second_request_while_running_gets_409(
    suggest_client: TestClient, data_room: Path, fake: FakeSuggester
) -> None:
    _project(suggest_client, data_room)
    gate = fake.gate = asyncio.Event()
    assert suggest_client.post("/api/projects/deal/config/suggest").status_code == 202
    assert suggest_client.get("/api/projects/deal/config/suggest").json()["state"] == "running"
    assert suggest_client.post("/api/projects/deal/config/suggest").status_code == 409
    suggest_client.portal.call(gate.set)  # type: ignore[union-attr]
    _wait_for(suggest_client, "done")


def test_failure_is_reported_without_secrets(
    suggest_client: TestClient, data_room: Path, fake: FakeSuggester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-value-123456")
    fake.fail = RuntimeError("401 for key sk-ant-secret-value-123456")
    _project(suggest_client, data_room)
    suggest_client.post("/api/projects/deal/config/suggest")
    body = _wait_for(suggest_client, "error")
    assert "sk-ant-secret-value-123456" not in body["error"]
    assert "***" in body["error"]


def test_can_try_again_after_a_failure(suggest_client: TestClient, data_room: Path, fake: FakeSuggester) -> None:
    _project(suggest_client, data_room)
    fake.fail = RuntimeError("provider down")
    suggest_client.post("/api/projects/deal/config/suggest")
    _wait_for(suggest_client, "error")
    fake.fail = None
    assert suggest_client.post("/api/projects/deal/config/suggest").status_code == 202
    assert _wait_for(suggest_client, "done")["config"] == DRAFT


def test_needs_buyer_and_target(suggest_client: TestClient, data_room: Path, fake: FakeSuggester) -> None:
    _project(suggest_client, data_room, named=False)
    res = suggest_client.post("/api/projects/deal/config/suggest")
    assert res.status_code == 409
    assert "buyer" in res.json()["detail"].lower()
    assert fake.calls == []


def test_unknown_project_is_404(suggest_client: TestClient) -> None:
    assert suggest_client.post("/api/projects/nope/config/suggest").status_code == 404
    assert suggest_client.get("/api/projects/nope/config/suggest").status_code == 404


def test_shutdown_does_not_wait_for_a_running_draft(registry_dir: Path, data_room: Path, fake: FakeSuggester) -> None:
    fake.gate = asyncio.Event()  # never released
    app = create_app(token=TOKEN, registry_dir=registry_dir, suggester=fake)
    started = time.monotonic()
    with TestClient(app, base_url=BASE, headers=AUTH) as c:
        _project(c, data_room)
        assert c.post("/api/projects/deal/config/suggest").status_code == 202
    assert time.monotonic() - started < 5


def test_default_suggester_runs_the_auto_config_steps(data_room: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from dd_agents import cli_auto_config
    from dd_agents.api.suggest import default_suggester

    seen: dict[str, Any] = {}

    async def fake_analyze(self: Any, **kwargs: Any) -> dict[str, Any]:
        seen.update(kwargs)
        return {"buyer": {"name": kwargs["buyer"]}, "target": {"name": kwargs["target"]}}

    monkeypatch.setattr(cli_auto_config.DataRoomAnalyzer, "analyze", fake_analyze)
    config = asyncio.run(default_suggester(data_room, "Buyer Co", "Target Co"))
    assert config["buyer"]["name"] == "Buyer Co"
    assert config["config_version"] == "1.0.0"
    assert "contract.txt" in seen["tree_output"]
