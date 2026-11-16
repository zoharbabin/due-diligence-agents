"""Run event schema: one JSON line per event in ``_dd/forensic-dd/events.jsonl``.

The engine writes these. The desktop app (and any other reader) tails them
to show live progress. Bump ``RUN_EVENT_SCHEMA_VERSION`` on any breaking change.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

RUN_EVENT_SCHEMA_VERSION = 1


class RunEventType(StrEnum):
    """Kinds of events the engine emits."""

    RUN_STARTED = "run_started"
    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    STEP_FAILED = "step_failed"
    AGENT_STARTED = "agent_started"
    AGENT_PROGRESS = "agent_progress"
    AGENT_COMPLETED = "agent_completed"
    FINDING_COUNTS = "finding_counts"
    COST = "cost"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"


class RunEvent(BaseModel):
    """One line of ``events.jsonl``."""

    schema_version: int = Field(default=RUN_EVENT_SCHEMA_VERSION, description="Event format version")
    seq: int = Field(description="1-based, strictly increasing within one run")
    ts: str = Field(description="UTC ISO-8601 timestamp")
    type: RunEventType
    run_id: str = Field(default="", description="Empty until the run id is assigned (step 2)")
    step: str | None = Field(default=None, description="Step name, e.g. 05_bulk_extraction")
    step_number: int | None = Field(default=None, description="1-based step number")
    data: dict[str, Any] = Field(default_factory=dict, description="Event-specific payload")
