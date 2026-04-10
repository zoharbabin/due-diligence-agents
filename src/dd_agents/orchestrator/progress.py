"""Pipeline progress tracking (Issue #120, Phase 1).

Provides structured progress tracking for the 35-step pipeline,
including per-step timing, agent activity, finding counts, and ETA estimation.
"""

from __future__ import annotations

import time
from typing import Any, TypedDict


class ProgressSnapshot(TypedDict):
    """Snapshot of current pipeline progress state."""

    current_step: int
    total_steps: int
    current_step_name: str
    elapsed_ms: float
    estimated_remaining_ms: float
    finding_counts: dict[str, int]
    agent_progress: dict[str, dict[str, Any]]
    completed_steps: int


class PipelineProgressTracker:
    """Track pipeline execution progress for CLI dashboard.

    Records step start/complete times and agent-level progress,
    then estimates remaining time from historical step durations.
    """

    def __init__(self, total_steps: int = 35) -> None:
        self.total_steps = total_steps
        self.current_step = 0
        self.current_step_name = ""
        self.completed_steps = 0
        self._step_start_time: float = 0.0
        self._pipeline_start_time: float = time.monotonic()
        self._step_durations: list[float] = []
        self._finding_counts: dict[str, int] = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        self._agent_progress: dict[str, dict[str, Any]] = {}

    def start_step(self, step_number: int, step_name: str) -> None:
        """Record the start of a pipeline step."""
        self.current_step = step_number
        self.current_step_name = step_name
        self._step_start_time = time.monotonic()

    def complete_step(self) -> None:
        """Record completion of the current step."""
        if self._step_start_time > 0:
            duration = (time.monotonic() - self._step_start_time) * 1000
            self._step_durations.append(duration)
        self.completed_steps += 1
        self._step_start_time = 0.0

    def update_agent_progress(
        self,
        agent: str,
        subjects_processed: int,
        total_subjects: int,
        current_subject: str = "",
    ) -> None:
        """Update progress for a specific agent."""
        self._agent_progress[agent] = {
            "subjects_processed": subjects_processed,
            "total_subjects": total_subjects,
            "current_subject": current_subject,
            "pct": round(100 * subjects_processed / total_subjects, 1) if total_subjects > 0 else 0.0,
        }

    def update_finding_counts(self, counts: dict[str, int]) -> None:
        """Update cumulative finding counts."""
        self._finding_counts = {**self._finding_counts, **counts}

    def estimate_remaining_ms(self) -> float:
        """Estimate remaining time based on average step duration.

        Returns 0.0 if no history is available.
        """
        if not self._step_durations:
            return 0.0
        avg_duration = sum(self._step_durations) / len(self._step_durations)
        remaining_steps = self.total_steps - self.completed_steps
        return avg_duration * remaining_steps

    @property
    def snapshot(self) -> ProgressSnapshot:
        """Return a snapshot of current progress state."""
        elapsed = (time.monotonic() - self._pipeline_start_time) * 1000
        return ProgressSnapshot(
            current_step=self.current_step,
            total_steps=self.total_steps,
            current_step_name=self.current_step_name,
            elapsed_ms=elapsed,
            estimated_remaining_ms=self.estimate_remaining_ms(),
            finding_counts=dict(self._finding_counts),
            agent_progress=dict(self._agent_progress),
            completed_steps=self.completed_steps,
        )
