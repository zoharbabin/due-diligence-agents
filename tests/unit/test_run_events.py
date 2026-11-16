"""Run event stream: ``events.jsonl`` written by the engine, read by the desktop API."""

from __future__ import annotations

import json
import threading
from pathlib import Path  # noqa: TC003
from typing import Any

import pytest

from dd_agents.errors import BlockingGateError
from dd_agents.models.events import RUN_EVENT_SCHEMA_VERSION, RunEvent, RunEventType
from dd_agents.orchestrator.engine import PipelineEngine
from dd_agents.orchestrator.events import RunEventLog, read_events
from dd_agents.orchestrator.steps import PipelineStep


class TestRunEventLog:
    def test_emit_writes_one_json_line_per_event(self, tmp_path: Path) -> None:
        log = RunEventLog(tmp_path / "events.jsonl")
        log.emit(RunEventType.RUN_STARTED, run_id="r1", resume_from_step=0)
        log.emit(RunEventType.STEP_STARTED, run_id="r1", step="01_validate_config", step_number=1)
        lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["schema_version"] == RUN_EVENT_SCHEMA_VERSION
        assert first["seq"] == 1
        assert first["type"] == "run_started"
        assert first["data"] == {"resume_from_step": 0}
        assert json.loads(lines[1])["seq"] == 2

    def test_seq_continues_after_reopen(self, tmp_path: Path) -> None:
        path = tmp_path / "events.jsonl"
        RunEventLog(path).emit(RunEventType.RUN_STARTED)
        RunEventLog(path).emit(RunEventType.STEP_STARTED)
        assert [e.seq for e in read_events(path)] == [1, 2]

    def test_reset_truncates_and_restarts_seq(self, tmp_path: Path) -> None:
        log = RunEventLog(tmp_path / "events.jsonl")
        log.emit(RunEventType.RUN_STARTED)
        log.reset()
        log.emit(RunEventType.RUN_STARTED)
        assert [e.seq for e in read_events(tmp_path / "events.jsonl")] == [1]

    def test_concurrent_emit_keeps_every_line_intact(self, tmp_path: Path) -> None:
        log = RunEventLog(tmp_path / "events.jsonl")

        def work(n: int) -> None:
            for i in range(50):
                log.emit(RunEventType.AGENT_PROGRESS, agent=f"a{n}", done=i)

        threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        events = read_events(tmp_path / "events.jsonl")
        assert len(events) == 400
        assert sorted(e.seq for e in events) == list(range(1, 401))

    def test_write_failure_never_raises(self, tmp_path: Path) -> None:
        target = tmp_path / "blocked"
        target.mkdir()  # a directory where the file should be
        log = RunEventLog(target)
        log.emit(RunEventType.RUN_STARTED)  # must not raise

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        log = RunEventLog(tmp_path / "a" / "b" / "events.jsonl")
        log.emit(RunEventType.RUN_STARTED)
        assert (tmp_path / "a" / "b" / "events.jsonl").is_file()


class TestReadEvents:
    def test_after_seq_filters(self, tmp_path: Path) -> None:
        log = RunEventLog(tmp_path / "events.jsonl")
        for _ in range(5):
            log.emit(RunEventType.STEP_STARTED)
        assert [e.seq for e in read_events(tmp_path / "events.jsonl", after_seq=3)] == [4, 5]

    def test_missing_file_is_empty(self, tmp_path: Path) -> None:
        assert read_events(tmp_path / "nope.jsonl") == []

    def test_partial_last_line_is_ignored(self, tmp_path: Path) -> None:
        path = tmp_path / "events.jsonl"
        RunEventLog(path).emit(RunEventType.RUN_STARTED)
        with path.open("a", encoding="utf-8") as fh:
            fh.write('{"schema_version": 1, "seq": 2, "ty')
        assert [e.seq for e in read_events(path)] == [1]

    def test_unknown_future_schema_version_is_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "events.jsonl"
        RunEventLog(path).emit(RunEventType.RUN_STARTED)
        future = {"schema_version": RUN_EVENT_SCHEMA_VERSION + 1, "seq": 2, "ts": "x", "type": "run_started"}
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(future) + "\n")
        assert [e.seq for e in read_events(path)] == [1]

    def test_returns_typed_events(self, tmp_path: Path) -> None:
        RunEventLog(tmp_path / "events.jsonl").emit(RunEventType.COST, total_usd=1.5)
        (event,) = read_events(tmp_path / "events.jsonl")
        assert isinstance(event, RunEvent)
        assert event.type is RunEventType.COST
        assert event.data["total_usd"] == 1.5


def _engine(tmp_path: Path) -> PipelineEngine:
    config = tmp_path / "deal-config.json"
    config.write_text("{}", encoding="utf-8")
    return PipelineEngine(tmp_path, config)


def _stub_registry(engine: PipelineEngine, fail_at: PipelineStep | None = None, exc: Exception | None = None) -> None:
    async def ok(state: Any) -> Any:
        return state

    async def boom(state: Any) -> Any:
        assert exc is not None
        raise exc

    engine._step_registry = {s: (boom if s is fail_at else ok) for s in PipelineStep}  # type: ignore[misc]  # test stub


@pytest.mark.asyncio
class TestEngineEmitsEvents:
    async def test_full_run_event_sequence(self, tmp_path: Path) -> None:
        engine = _engine(tmp_path)
        _stub_registry(engine)
        await engine.run()
        events = read_events(engine.events.path)
        types = [e.type for e in events]
        assert types[0] is RunEventType.RUN_STARTED
        assert types[-1] is RunEventType.RUN_COMPLETED
        assert types.count(RunEventType.STEP_STARTED) == len(PipelineStep)
        assert types.count(RunEventType.STEP_COMPLETED) == len(PipelineStep)
        last_step = [e for e in events if e.type is RunEventType.STEP_COMPLETED][-1]
        assert last_step.data["completed_steps"] == len(PipelineStep)
        assert "total_cost_usd" in last_step.data

    async def test_blocking_gate_failure_emits_step_and_run_failed(self, tmp_path: Path) -> None:
        engine = _engine(tmp_path)
        _stub_registry(engine, fail_at=PipelineStep.COVERAGE_GATE, exc=BlockingGateError("coverage too low"))
        with pytest.raises(BlockingGateError):
            await engine.run()
        events = read_events(engine.events.path)
        failed = [e for e in events if e.type is RunEventType.STEP_FAILED]
        assert len(failed) == 1
        assert failed[0].data["blocking_gate"] is True
        assert "coverage too low" in failed[0].data["error"]
        assert events[-1].type is RunEventType.RUN_FAILED

    async def test_unexpected_error_is_reported_then_reraised(self, tmp_path: Path) -> None:
        engine = _engine(tmp_path)
        _stub_registry(engine, fail_at=PipelineStep.BUILD_INVENTORY, exc=RuntimeError("disk on fire"))
        with pytest.raises(RuntimeError, match="disk on fire"):
            await engine.run()
        events = read_events(engine.events.path)
        assert events[-1].type is RunEventType.RUN_FAILED
        assert events[-1].data["error_type"] == "RuntimeError"

    async def test_fresh_run_truncates_previous_events(self, tmp_path: Path) -> None:
        engine = _engine(tmp_path)
        _stub_registry(engine)
        await engine.run()
        first = len(read_events(engine.events.path))
        engine2 = _engine(tmp_path)
        _stub_registry(engine2)
        await engine2.run()
        assert len(read_events(engine2.events.path)) == first


@pytest.mark.asyncio
async def test_agent_progress_watcher_reports_per_subject_files(tmp_path: Path) -> None:
    import asyncio

    engine = _engine(tmp_path)
    findings = tmp_path / "findings"
    (findings / "legal").mkdir(parents=True)
    state = engine.state
    state.run_id = "run_x"
    task = asyncio.create_task(engine._watch_agent_progress(state, findings, ["legal"], 3, interval_s=0.01))
    await asyncio.sleep(0.05)
    (findings / "legal" / "subject_a.json").write_text("{}", encoding="utf-8")
    (findings / "legal" / "subject_b.json").write_text("{}", encoding="utf-8")
    await asyncio.sleep(0.1)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    progress = [e for e in read_events(engine.events.path) if e.type is RunEventType.AGENT_PROGRESS]
    assert [e.data["subjects_done"] for e in progress][-1] == 2
    assert all(e.data["total_subjects"] == 3 and e.data["agent"] == "legal" for e in progress)
    assert len({e.data["subjects_done"] for e in progress}) == len(progress)  # only emits on change
