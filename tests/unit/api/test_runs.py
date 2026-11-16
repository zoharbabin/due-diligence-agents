"""Run lifecycle: start, stream events, cancel, finish."""

from __future__ import annotations

import json
import sys
import time
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from dd_agents.api.app import create_app
from dd_agents.api.runs import RunManager, RunOptions
from dd_agents.persistence.project_registry import ProjectRegistryManager

from .conftest import AUTH, BASE, TOKEN, VALID_CONFIG

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

FAKE_RUN = r"""
import json, os, sys, time
from pathlib import Path
from dd_agents.orchestrator.events import RunEventLog

room = Path.cwd()
log = RunEventLog(room / "_dd" / "forensic-dd" / "events.jsonl")
log.reset()
rid = "20260101_000000"
log.emit("run_started", run_id=rid, total_steps=3)
log.emit("step_started", run_id=rid, step="inventory", step_number=1)
time.sleep(float(os.environ.get("FAKE_SLEEP", "0")))
merged = room / "_dd" / "forensic-dd" / "runs" / rid / "findings" / "merged"
merged.mkdir(parents=True)
(merged / "subject_a.json").write_text(json.dumps({
    "subject": "Subject A", "subject_safe_name": "subject_a",
    "findings": [{"id": "f1", "severity": "P1", "category": "termination", "title": "T",
                  "description": "d", "citations": [], "confidence": "high", "agent": "legal",
                  "analysis_unit": "Subject A"}],
}))
latest = merged.parents[2] / "latest"
latest.symlink_to(rid)
log.emit("step_completed", run_id=rid, step="inventory", step_number=1)
if os.environ.get("FAKE_FAIL"):
    log.emit("run_failed", run_id=rid, error="boom")
    sys.exit(2)
log.emit("run_completed", run_id=rid)
"""


def _fake_command(sleep: float = 0.0, fail: bool = False) -> object:
    import os

    def factory(config_path: Path, options: RunOptions) -> tuple[list[str], dict[str, str]]:
        env = dict(os.environ)
        env["FAKE_SLEEP"] = str(sleep)
        if fail:
            env["FAKE_FAIL"] = "1"
        return [sys.executable, "-c", FAKE_RUN], env

    return factory


def _make_client(registry_dir: Path, **kw: object) -> TestClient:
    registry = ProjectRegistryManager(registry_dir)
    manager = RunManager(registry, command_factory=_fake_command(**kw))  # type: ignore[arg-type]
    app = create_app(token=TOKEN, registry_dir=registry_dir, run_manager=manager)
    return TestClient(app, base_url=BASE, headers=AUTH)


@pytest.fixture
def project(registry_dir: Path, data_room: Path) -> Iterator[tuple[TestClient, str]]:
    c = _make_client(registry_dir)
    with c:
        assert c.post("/api/projects", json={"name": "Deal", "data_room": str(data_room)}).status_code == 201
        assert c.put("/api/projects/deal/config", json=VALID_CONFIG).status_code == 200
        yield c, "deal"


def _wait_status(c: TestClient, slug: str, want: set[str], timeout: float = 20.0) -> dict[str, object]:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        body: dict[str, object] = c.get(f"/api/projects/{slug}/run").json()
        if body["status"] in want:
            return body
        time.sleep(0.1)
    raise AssertionError(f"status never reached {want}: {body}")


def test_no_run_yet(project: tuple[TestClient, str]) -> None:
    c, slug = project
    assert c.get(f"/api/projects/{slug}/run").json()["status"] == "idle"


def test_start_without_config_is_409(registry_dir: Path, data_room: Path) -> None:
    with _make_client(registry_dir) as c:
        c.post("/api/projects", json={"name": "Deal", "data_room": str(data_room)})
        assert c.post("/api/projects/deal/run", json={}).status_code == 409


def test_start_with_invalid_config_is_422(project: tuple[TestClient, str], data_room: Path) -> None:
    c, slug = project
    (data_room / "deal-config.json").write_text("{}", encoding="utf-8")
    r = c.post(f"/api/projects/{slug}/run", json={})
    assert r.status_code == 422


def test_run_completes_and_updates_registry(project: tuple[TestClient, str]) -> None:
    c, slug = project
    r = c.post(f"/api/projects/{slug}/run", json={"quick_scan": True})
    assert r.status_code == 202, r.text
    done = _wait_status(c, slug, {"completed", "failed"})
    assert done["status"] == "completed"
    entry = c.get(f"/api/projects/{slug}").json()
    assert entry["status"] == "completed"
    assert entry["last_run_id"] == "20260101_000000"
    assert entry["finding_counts"] == {"P1": 1}
    assert entry["total_findings"] == 1


def test_failed_run_is_reported(registry_dir: Path, data_room: Path) -> None:
    with _make_client(registry_dir, fail=True) as c:
        c.post("/api/projects", json={"name": "Deal", "data_room": str(data_room)})
        c.put("/api/projects/deal/config", json=VALID_CONFIG)
        assert c.post("/api/projects/deal/run", json={}).status_code == 202
        body = _wait_status(c, "deal", {"failed", "completed"})
        assert body["status"] == "failed"
        assert c.get("/api/projects/deal").json()["status"] == "failed"


def test_second_start_while_running_is_409(registry_dir: Path, data_room: Path) -> None:
    with _make_client(registry_dir, sleep=30) as c:
        c.post("/api/projects", json={"name": "Deal", "data_room": str(data_room)})
        c.put("/api/projects/deal/config", json=VALID_CONFIG)
        assert c.post("/api/projects/deal/run", json={}).status_code == 202
        assert c.post("/api/projects/deal/run", json={}).status_code == 409
        assert c.post("/api/projects/deal/run/cancel").status_code == 200
        _wait_status(c, "deal", {"cancelled"})


def test_cancel_kills_process_and_marks_cancelled(registry_dir: Path, data_room: Path) -> None:
    with _make_client(registry_dir, sleep=30) as c:
        c.post("/api/projects", json={"name": "Deal", "data_room": str(data_room)})
        c.put("/api/projects/deal/config", json=VALID_CONFIG)
        c.post("/api/projects/deal/run", json={})
        pid = c.get("/api/projects/deal/run").json()["pid"]
        assert pid
        assert c.post("/api/projects/deal/run/cancel").status_code == 200
        body = _wait_status(c, "deal", {"cancelled"})
        assert body["status"] == "cancelled"
        with pytest.raises(ProcessLookupError):
            import os

            os.kill(pid, 0)
        assert c.get("/api/projects/deal").json()["status"] == "cancelled"


def test_cancel_when_idle_is_409(project: tuple[TestClient, str]) -> None:
    c, slug = project
    assert c.post(f"/api/projects/{slug}/run/cancel").status_code == 409


def test_bad_run_options_are_422(project: tuple[TestClient, str]) -> None:
    c, slug = project
    assert c.post(f"/api/projects/{slug}/run", json={"mode": "turbo"}).status_code == 422
    assert c.post(f"/api/projects/{slug}/run", json={"resume_from": 99}).status_code == 422
    assert c.post(f"/api/projects/{slug}/run", json={"model_overrides": {"legal": "--evil"}}).status_code == 422


def test_events_snapshot_and_after(project: tuple[TestClient, str]) -> None:
    c, slug = project
    c.post(f"/api/projects/{slug}/run", json={})
    _wait_status(c, slug, {"completed"})
    events = c.get(f"/api/projects/{slug}/events").json()
    types = [e["type"] for e in events]
    assert types[0] == "run_started"
    assert types[-1] == "run_completed"
    later = c.get(f"/api/projects/{slug}/events", params={"after": events[1]["seq"]}).json()
    assert [e["seq"] for e in later] == [e["seq"] for e in events[2:]]


def test_event_stream_replays_and_ends_on_terminal(project: tuple[TestClient, str]) -> None:
    c, slug = project
    c.post(f"/api/projects/{slug}/run", json={})
    got: list[dict[str, object]] = []
    with c.stream("GET", f"/api/projects/{slug}/events/stream") as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("data: "):
                got.append(json.loads(line[6:]))
    assert got[0]["type"] == "run_started"
    assert got[-1]["type"] == "run_completed"
    seqs = [int(str(e["seq"])) for e in got]
    assert seqs == sorted(seqs)


def test_stream_resumes_with_last_event_id(project: tuple[TestClient, str]) -> None:
    c, slug = project
    c.post(f"/api/projects/{slug}/run", json={})
    _wait_status(c, slug, {"completed"})
    all_events = c.get(f"/api/projects/{slug}/events").json()
    got: list[int] = []
    with c.stream(
        "GET", f"/api/projects/{slug}/events/stream", headers={"Last-Event-ID": str(all_events[1]["seq"])}
    ) as r:
        for line in r.iter_lines():
            if line.startswith("id: "):
                got.append(int(line[4:]))
    assert got == [e["seq"] for e in all_events[2:]]


def test_stream_with_no_run_closes(project: tuple[TestClient, str]) -> None:
    c, slug = project
    with c.stream("GET", f"/api/projects/{slug}/events/stream") as r:
        assert list(r.iter_lines()) in ([], [""])


def test_runs_listing(project: tuple[TestClient, str]) -> None:
    c, slug = project
    c.post(f"/api/projects/{slug}/run", json={})
    _wait_status(c, slug, {"completed"})
    runs = c.get(f"/api/projects/{slug}/runs").json()
    assert runs[0]["run_id"] == "20260101_000000"
    assert runs[0]["is_latest"] is True


def test_stale_running_projects_are_reset_on_startup(registry_dir: Path, data_room: Path) -> None:
    registry = ProjectRegistryManager(registry_dir)
    registry.add_project("Deal", data_room)
    registry.update_project("deal", status="running", locked_by=2_000_000_000)
    RunManager(registry)
    got = registry.get_project("deal")
    assert got is not None
    assert got.status == "failed"
    assert got.locked_by is None
