"""Run manager: one ``dd-agents run`` subprocess per project.

The pipeline runs in its own process so a crash, a cancel or a quit never takes the
API server down, and the server never holds pipeline memory. Progress comes from the
run's ``events.jsonl`` (see ``dd_agents.orchestrator.events``).
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Literal

from pydantic import BaseModel, Field, field_validator

from dd_agents.api.projects_util import SKILL_DIR
from dd_agents.config import load_deal_config
from dd_agents.models.project import ProjectEntry
from dd_agents.persistence.project_registry import ProjectRegistryManager

logger = logging.getLogger(__name__)

RunStatus = Literal["idle", "running", "completed", "failed", "cancelled"]
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]*$")
_AGENT_RE = re.compile(r"^[a-z][a-z0-9_]*$")
EVENTS_NAME = "events.jsonl"
OUTPUT_LOG_NAME = "last-run-output.log"


class RunOptions(BaseModel):
    """Per-run switches. Mirrors the ``dd-agents run`` flags."""

    mode: Literal["full", "incremental"] | None = None
    resume_from: int = Field(default=0, ge=0, le=39)
    quick_scan: bool = False
    no_knowledge: bool = False
    no_narrative: bool = False
    model_profile: Literal["economy", "standard", "premium"] | None = None
    model_overrides: dict[str, str] = Field(default_factory=dict)

    @field_validator("model_overrides")
    @classmethod
    def _check_overrides(cls, v: dict[str, str]) -> dict[str, str]:
        for agent, model in v.items():
            if not _AGENT_RE.match(agent) or not _MODEL_RE.match(model):
                raise ValueError(f"invalid model override {agent!r}={model!r}")
        return v


CommandFactory = Callable[[Path, RunOptions], tuple[list[str], dict[str, str]]]


def default_command(config_path: Path, options: RunOptions) -> tuple[list[str], dict[str, str]]:
    """Build ``python -m dd_agents run ...`` with the current interpreter and environment."""
    argv = [sys.executable, "-m", "dd_agents", "run", str(config_path)]
    if options.mode:
        argv += ["--mode", options.mode]
    if options.resume_from:
        argv += ["--resume-from", str(options.resume_from)]
    for flag, on in (
        ("--quick-scan", options.quick_scan),
        ("--no-knowledge", options.no_knowledge),
        ("--no-narrative", options.no_narrative),
    ):
        if on:
            argv.append(flag)
    if options.model_profile:
        argv += ["--model-profile", options.model_profile]
    for agent, model in options.model_overrides.items():
        argv += ["--model-override", f"{agent}={model}"]
    return argv, dict(os.environ)


# Windows only: own process group so Ctrl+Break reaches the run, and no console window.
_CREATE_FLAGS = (
    getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if os.name == "nt"
    else 0
)


class RunConflictError(RuntimeError):
    """A run is already active, or none is."""


class RunConfigError(RuntimeError):
    """The project has no usable config."""

    def __init__(self, message: str, *, missing: bool = False) -> None:
        super().__init__(message)
        self.missing = missing


@dataclass
class RunHandle:
    slug: str
    process: subprocess.Popen[bytes]
    started_at: str
    base_seq: int
    status: RunStatus = "running"
    cancelled: bool = False
    finished_at: str | None = None
    exit_code: int | None = None
    run_id: str = ""
    done: threading.Event = field(default_factory=threading.Event)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class RunManager:
    def __init__(
        self,
        registry: ProjectRegistryManager,
        command_factory: CommandFactory = default_command,
        kill_grace: float = 10.0,
    ) -> None:
        self._registry = registry
        self._command = command_factory
        self._kill_grace = kill_grace
        self._handles: dict[str, RunHandle] = {}
        self._lock = threading.Lock()
        self._reset_stale()

    def _reset_stale(self) -> None:
        """A project left ``running`` by a dead server must not block new runs."""
        for p in self._registry.list_projects():
            if p.status == "running" and not (p.locked_by and pid_alive(p.locked_by)):
                self._registry.update_project(p.slug, status="failed", locked_by=None)

    # -- queries -----------------------------------------------------------

    def is_running(self, slug: str) -> bool:
        h = self._handles.get(slug)
        return h is not None and h.status == "running"

    def handle(self, slug: str) -> RunHandle | None:
        return self._handles.get(slug)

    def state(self, entry: ProjectEntry) -> dict[str, object]:
        h = self._handles.get(entry.slug)
        if h is not None:
            return {
                "status": h.status,
                "pid": h.process.pid if h.status == "running" else None,
                "run_id": h.run_id or entry.last_run_id or "",
                "started_at": h.started_at,
                "finished_at": h.finished_at,
                "exit_code": h.exit_code,
            }
        status: RunStatus = "idle"
        if entry.status == "completed":
            status = "completed"
        elif entry.status == "failed":
            status = "failed"
        elif entry.status == "cancelled":
            status = "cancelled"
        return {
            "status": status,
            "pid": None,
            "run_id": entry.last_run_id or "",
            "started_at": None,
            "finished_at": entry.last_run_at,
            "exit_code": None,
        }

    # -- control -----------------------------------------------------------

    def start(self, entry: ProjectEntry, config_path: Path, options: RunOptions) -> RunHandle:
        if not config_path.is_file():
            raise RunConfigError("This project has no deal config. Save one first.", missing=True)
        load_deal_config(config_path)  # raises ConfigError subclasses; the router maps them to 422
        room = Path(entry.path)
        skill = room / SKILL_DIR
        with self._lock:
            if self.is_running(entry.slug):
                raise RunConflictError("A run is already in progress for this project")
            skill.mkdir(parents=True, exist_ok=True)
            events = skill / EVENTS_NAME
            if options.resume_from == 0:
                events.write_text("", encoding="utf-8")
            base_seq = _last_seq(events)
            argv, env = self._command(config_path, options)
            out = open(skill / OUTPUT_LOG_NAME, "wb")  # noqa: SIM115  (closed in the watcher)
            try:
                process = subprocess.Popen(  # noqa: S603
                    argv,
                    cwd=room,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    creationflags=_CREATE_FLAGS,
                    start_new_session=os.name != "nt",
                )
            except OSError:
                out.close()
                raise
            handle = RunHandle(entry.slug, process, _now(), base_seq)
            self._handles[entry.slug] = handle
            self._registry.update_project(entry.slug, status="running", locked_by=process.pid)
        threading.Thread(target=self._watch, args=(entry, handle, out), name=f"run-{entry.slug}", daemon=True).start()
        return handle

    def cancel(self, slug: str) -> None:
        with self._lock:
            h = self._handles.get(slug)
            if h is None or h.status != "running":
                raise RunConflictError("No run is in progress")
            h.cancelled = True
        _terminate(h.process, self._kill_grace)

    def shutdown(self) -> None:
        """Stop active runs when the server exits."""
        for h in list(self._handles.values()):
            if h.status == "running":
                h.cancelled = True
                _terminate(h.process, min(self._kill_grace, 5.0))
        for h in list(self._handles.values()):
            h.done.wait(timeout=10)

    # -- internals ---------------------------------------------------------

    def _watch(self, entry: ProjectEntry, handle: RunHandle, out: IO[bytes]) -> None:
        code = handle.process.wait()
        with contextlib.suppress(OSError):
            out.close()
        handle.exit_code = code
        handle.finished_at = _now()
        handle.run_id = _run_id(Path(entry.path))
        status: RunStatus = "cancelled" if handle.cancelled else ("completed" if code == 0 else "failed")
        try:
            self._finish(entry, handle.run_id, status)
        except Exception:  # never leave the handle stuck in "running"
            logger.exception("Could not record run result for %s", entry.slug)
        finally:
            handle.status = status
            handle.done.set()

    def _finish(self, entry: ProjectEntry, run_id: str, status: RunStatus) -> None:
        if status == "completed":
            from dd_agents.api.findings_io import summarize_run

            summary = summarize_run(Path(entry.path) / SKILL_DIR / "runs" / run_id)
            self._registry.sync_project_from_run(
                entry.slug,
                run_id,
                total_subjects=summary.subjects,
                total_findings=summary.total,
                finding_counts=summary.by_severity,
                risk_score=summary.risk_score,
            )
            self._registry.update_project(entry.slug, locked_by=None)
        else:
            self._registry.update_project(entry.slug, status=status, locked_by=None)


def _last_seq(events: Path) -> int:
    from dd_agents.orchestrator.events import read_events

    items = read_events(events)
    return items[-1].seq if items else 0


def _run_id(room: Path) -> str:
    """Run id from the last event that carries one, else the ``latest`` symlink."""
    from dd_agents.orchestrator.events import read_events

    for event in reversed(read_events(room / SKILL_DIR / EVENTS_NAME)):
        if event.run_id:
            return event.run_id
    latest = room / SKILL_DIR / "runs" / "latest"
    return latest.resolve().name if latest.exists() else ""


def _terminate(process: subprocess.Popen[bytes], grace: float) -> None:
    """Interrupt the whole process group, then kill it if it ignores the request."""
    if process.poll() is not None:
        return
    if os.name == "nt":  # pragma: no cover  (Windows path is covered by the desktop CI job)
        os.kill(process.pid, getattr(signal, "CTRL_BREAK_EVENT", signal.SIGTERM))
    else:
        _signal_group(process.pid, signal.SIGINT)

    def _reaper() -> None:
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline and process.poll() is None:
            time.sleep(0.1)
        if process.poll() is None:
            if os.name == "nt":  # pragma: no cover
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], check=False, capture_output=True)  # noqa: S603, S607
                return
        else:
            time.sleep(1.0)  # let children that got the same interrupt finish on their own
        if os.name != "nt":
            _signal_group(process.pid, signal.SIGKILL)  # anything still in the group

    threading.Thread(target=_reaper, name="run-reaper", daemon=True).start()


def _signal_group(pid: int, sig: int) -> None:
    """``start_new_session`` makes the child its own group leader, so pgid == pid."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, sig)
