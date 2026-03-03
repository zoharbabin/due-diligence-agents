"""Error taxonomy for the forensic DD pipeline.

Defines structured error records, severity/category enums, and domain-specific
exception classes used throughout the pipeline.  These are distinct from the
``PipelineError`` in ``orchestrator.state`` (which is a runtime exception) and
the config-related errors in ``config.py``.

Reference: ``docs/plan/12-error-recovery.md`` section 1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ErrorSeverity(StrEnum):
    """How severely the error impacts the pipeline."""

    FATAL = "fatal"
    DEGRADED = "degraded"
    RECOVERED = "recovered"
    WARNING = "warning"


class ErrorCategory(StrEnum):
    """Classification for error tracking and metrics."""

    AGENT_FAILURE = "agent_failure"
    AGENT_PARTIAL = "agent_partial"
    AGENT_TIMEOUT = "agent_timeout"
    AGENT_CONTEXT = "agent_context"
    EXTRACTION = "extraction"
    ENTITY_RESOLUTION = "entity_resolution"
    CONFIG = "config"
    CONCURRENCY = "concurrency"
    VALIDATION = "validation"


# ---------------------------------------------------------------------------
# Structured error record
# ---------------------------------------------------------------------------


@dataclass
class PipelineErrorRecord:
    """Structured error record for the error recovery system.

    Every error encountered during a pipeline run is captured as one of
    these records and appended to the run's error log.
    """

    error_type: str  # "blocking_gate", "agent_failure", "partial_failure", "parse_failure", "timeout"
    step: str
    message: str
    recoverable: bool
    recovery_action: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    category: ErrorCategory | None = None
    severity: ErrorSeverity | None = None
    agent: str | None = None
    customers_affected: list[str] = field(default_factory=list)
    details: dict[str, object] = field(default_factory=dict)
    outcome: str = ""  # "recovered", "degraded", "fatal"


# ---------------------------------------------------------------------------
# Domain-specific exceptions
# ---------------------------------------------------------------------------


class ConfigurationError(Exception):
    """Raised for missing or invalid configuration files.

    This covers cases where ``deal-config.json`` is absent, contains
    invalid JSON, or fails schema validation.  Distinct from the
    ``ConfigError`` hierarchy in ``dd_agents.config`` which is used
    exclusively by the config-loader module.
    """


class ExtractionError(Exception):
    """Raised for document extraction failures.

    Covers individual file extraction failures as well as systemic
    extraction issues (>50 % failure rate).
    """


class AgentOutputParseError(Exception):
    """Raised when an agent's output cannot be parsed.

    Agents are expected to produce well-formed JSON matching the
    schema defined in ``models/``.  This exception signals that the
    raw output could not be deserialised or validated.
    """

    def __init__(self, message: str, *, agent_name: str = "unknown", raw_output: str = "") -> None:
        super().__init__(message)
        self.agent_name = agent_name
        self.raw_output = raw_output


class PipelineValidationError(Exception):
    """Raised for validation gate failures.

    Distinct from Pydantic's ``ValidationError``.  This exception is
    used when a pipeline validation gate (numerical audit, QA audit,
    post-generation validation, etc.) fails.
    """

    def __init__(self, message: str, *, gate: str = "", details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.gate = gate
        self.details = details or {}
