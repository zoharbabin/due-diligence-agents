"""Ask: a per-project chat session streamed over server-sent events. The engine is faked."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from dd_agents.api.app import create_app
from dd_agents.chat.engine import BudgetExhaustedError, ChatResponse

from .conftest import AUTH, BASE, TOKEN

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Callable, Iterator
    from pathlib import Path


class FakeEngine:
    created: list[FakeEngine] = []

    def __init__(self, run_dir: Path, project_dir: Path) -> None:
        self.run_dir = run_dir
        self.project_dir = project_dir
        self.finding_count = 3
        self.session_cost = 0.0
        self.turn_count = 0
        self.closed = False
        self.gate: asyncio.Event | None = None
        self.fail: Exception | None = None
        FakeEngine.created.append(self)

    async def ask(
        self,
        question: str,
        on_text: Callable[[str], None] | None = None,
        on_tool_status: Callable[[str], None] | None = None,
    ) -> ChatResponse:
        if self.gate is not None:
            await self.gate.wait()
        if self.fail:
            raise self.fail
        self.turn_count += 1
        self.session_cost += 0.25
        if on_tool_status:
            on_tool_status("search_in_file")
        if on_text:
            on_text("Hello ")
            on_text("world")
        return ChatResponse(
            text=f"Hello world to: {question}",
            tools_used=["search_in_file"],
            turn_number=self.turn_count,
            estimated_cost=0.25,
            session_cost=self.session_cost,
        )

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def chat_client(registry_dir: Path) -> Iterator[TestClient]:
    FakeEngine.created = []
    app = create_app(token=TOKEN, registry_dir=registry_dir, chat_factory=FakeEngine)
    with TestClient(app, base_url=BASE, headers=AUTH) as c:
        yield c


def _room_with_run(room: Path) -> None:
    run = room / "_dd" / "forensic-dd" / "runs" / "20260101_000000"
    (run / "findings" / "merged").mkdir(parents=True)
    (run.parent / "latest").symlink_to(run.name)


def _project(client: TestClient, room: Path) -> None:
    assert client.post("/api/projects", json={"name": "Deal", "data_room": str(room)}).status_code == 201


def _events(text: str) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = block.splitlines()
        if lines and lines[0].startswith("event:"):
            out.append((lines[0][6:].strip(), json.loads(lines[1][5:])))
    return out


def test_status_before_any_message(chat_client: TestClient, data_room: Path) -> None:
    _room_with_run(data_room)
    _project(chat_client, data_room)
    body = chat_client.get("/api/projects/deal/chat").json()
    assert body["ready"] is True
    assert body["active"] is False
    assert body["max_session_cost"] > 0
    assert FakeEngine.created == []  # reading status never starts the engine


def test_not_ready_without_a_review(chat_client: TestClient, data_room: Path) -> None:
    _project(chat_client, data_room)
    assert chat_client.get("/api/projects/deal/chat").json()["ready"] is False
    r = chat_client.post("/api/projects/deal/chat", json={"question": "hi"})
    assert r.status_code == 409
    assert "review" in r.json()["detail"].lower()


def test_answer_streams_tool_text_and_done(chat_client: TestClient, data_room: Path) -> None:
    _room_with_run(data_room)
    _project(chat_client, data_room)
    r = chat_client.post("/api/projects/deal/chat", json={"question": "Any change of control?"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = _events(r.text)
    assert [e for e, _ in events] == ["tool", "text", "text", "done"]
    assert events[0][1] == {"name": "search_in_file"}
    assert "".join(d["text"] for e, d in events if e == "text") == "Hello world"
    done = events[-1][1]
    assert done["text"] == "Hello world to: Any change of control?"
    assert done["session_cost"] == 0.25
    engine = FakeEngine.created[0]
    assert engine.run_dir.name == "20260101_000000"
    assert engine.project_dir == data_room.resolve()


def test_one_session_is_reused_across_questions(chat_client: TestClient, data_room: Path) -> None:
    _room_with_run(data_room)
    _project(chat_client, data_room)
    chat_client.post("/api/projects/deal/chat", json={"question": "one"})
    chat_client.post("/api/projects/deal/chat", json={"question": "two"})
    assert len(FakeEngine.created) == 1
    status = chat_client.get("/api/projects/deal/chat").json()
    assert (status["active"], status["turn_count"], status["session_cost"]) == (True, 2, 0.5)


def test_errors_arrive_as_an_error_event_and_secrets_are_scrubbed(
    chat_client: TestClient, data_room: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-value-123456")
    _room_with_run(data_room)
    _project(chat_client, data_room)
    chat_client.post("/api/projects/deal/chat", json={"question": "warm up"})
    FakeEngine.created[0].fail = RuntimeError("bad key sk-ant-secret-value-123456")
    events = _events(chat_client.post("/api/projects/deal/chat", json={"question": "x"}).text)
    assert events[-1][0] == "error"
    assert "sk-ant-secret-value-123456" not in events[-1][1]["message"]


def test_budget_exhausted_is_a_readable_error(chat_client: TestClient, data_room: Path) -> None:
    _room_with_run(data_room)
    _project(chat_client, data_room)
    chat_client.post("/api/projects/deal/chat", json={"question": "warm up"})
    FakeEngine.created[0].fail = BudgetExhaustedError("Session budget exhausted ($10.00)")
    events = _events(chat_client.post("/api/projects/deal/chat", json={"question": "x"}).text)
    assert events[-1] == ("error", {"message": "Session budget exhausted ($10.00)"})


def test_blank_and_oversized_questions_are_422(chat_client: TestClient, data_room: Path) -> None:
    _room_with_run(data_room)
    _project(chat_client, data_room)
    assert chat_client.post("/api/projects/deal/chat", json={"question": "   "}).status_code == 422
    assert chat_client.post("/api/projects/deal/chat", json={"question": "x" * 4001}).status_code == 422


def test_delete_closes_the_session_and_is_idempotent(chat_client: TestClient, data_room: Path) -> None:
    _room_with_run(data_room)
    _project(chat_client, data_room)
    chat_client.post("/api/projects/deal/chat", json={"question": "one"})
    assert chat_client.delete("/api/projects/deal/chat").status_code == 204
    assert FakeEngine.created[0].closed is True
    assert chat_client.delete("/api/projects/deal/chat").status_code == 204
    assert chat_client.get("/api/projects/deal/chat").json()["active"] is False


def test_app_shutdown_closes_open_sessions(registry_dir: Path, data_room: Path) -> None:
    FakeEngine.created = []
    app = create_app(token=TOKEN, registry_dir=registry_dir, chat_factory=FakeEngine)
    _room_with_run(data_room)
    with TestClient(app, base_url=BASE, headers=AUTH) as c:
        _project(c, data_room)
        c.post("/api/projects/deal/chat", json={"question": "one"})
    assert FakeEngine.created[0].closed is True


def test_unknown_project_is_404(chat_client: TestClient) -> None:
    assert chat_client.get("/api/projects/none/chat").status_code == 404
    assert chat_client.post("/api/projects/none/chat", json={"question": "x"}).status_code == 404


def test_a_newer_review_starts_a_fresh_session(chat_client: TestClient, data_room: Path) -> None:
    _room_with_run(data_room)
    _project(chat_client, data_room)
    chat_client.post("/api/projects/deal/chat", json={"question": "one"})
    runs = data_room / "_dd" / "forensic-dd" / "runs"
    (runs / "20260202_000000" / "findings" / "merged").mkdir(parents=True)
    (runs / "latest").unlink()
    (runs / "latest").symlink_to("20260202_000000")
    chat_client.post("/api/projects/deal/chat", json={"question": "two"})
    assert len(FakeEngine.created) == 2
    assert FakeEngine.created[0].closed is True
    assert FakeEngine.created[1].run_dir.name == "20260202_000000"
