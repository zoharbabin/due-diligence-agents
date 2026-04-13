"""Unit tests for the dd_agents.errors module.

Covers:
- ErrorSeverity and ErrorCategory enums
- PipelineErrorRecord structured record
- BlockingGateError, RecoverableError, AgentFailureError, PartialFailureError
"""

from __future__ import annotations

from dd_agents.errors import (
    AgentFailureError,
    BlockingGateError,
    ErrorCategory,
    ErrorSeverity,
    PartialFailureError,
    PipelineErrorRecord,
    RecoverableError,
)

# ======================================================================
# Enums
# ======================================================================


class TestErrorSeverity:
    def test_values(self) -> None:
        assert ErrorSeverity.FATAL.value == "fatal"
        assert ErrorSeverity.DEGRADED.value == "degraded"
        assert ErrorSeverity.RECOVERED.value == "recovered"
        assert ErrorSeverity.WARNING.value == "warning"

    def test_is_str_enum(self) -> None:
        assert isinstance(ErrorSeverity.FATAL, str)

    def test_member_count(self) -> None:
        assert len(ErrorSeverity) == 4


class TestErrorCategory:
    def test_values(self) -> None:
        assert ErrorCategory.AGENT_FAILURE.value == "agent_failure"
        assert ErrorCategory.EXTRACTION.value == "extraction"
        assert ErrorCategory.CONFIG.value == "config"
        assert ErrorCategory.VALIDATION.value == "validation"

    def test_is_str_enum(self) -> None:
        assert isinstance(ErrorCategory.AGENT_FAILURE, str)

    def test_member_count(self) -> None:
        assert len(ErrorCategory) == 9


# ======================================================================
# PipelineErrorRecord
# ======================================================================


class TestPipelineErrorRecord:
    def test_creation_with_required_fields(self) -> None:
        record = PipelineErrorRecord(
            error_type="agent_failure",
            step="16_run_specialists",
            message="Legal agent crashed",
            recoverable=True,
            recovery_action="re-spawned once",
        )
        assert record.error_type == "agent_failure"
        assert record.step == "16_run_specialists"
        assert record.message == "Legal agent crashed"
        assert record.recoverable is True
        assert record.recovery_action == "re-spawned once"
        assert record.timestamp  # auto-populated
        assert record.subjects_affected == []
        assert record.details == {}

    def test_creation_with_all_fields(self) -> None:
        record = PipelineErrorRecord(
            error_type="blocking_gate",
            step="05_bulk_extraction",
            message="Systemic extraction failure",
            recoverable=False,
            recovery_action="none",
            timestamp="2026-02-25T12:00:00+00:00",
            category=ErrorCategory.EXTRACTION,
            severity=ErrorSeverity.FATAL,
            agent=None,
            subjects_affected=["alpha", "bravo"],
            details={"failure_rate": 0.65},
            outcome="fatal",
        )
        assert record.category == ErrorCategory.EXTRACTION
        assert record.severity == ErrorSeverity.FATAL
        assert record.outcome == "fatal"
        assert len(record.subjects_affected) == 2

    def test_default_timestamp_is_set(self) -> None:
        record = PipelineErrorRecord(
            error_type="timeout",
            step="16_run_specialists",
            message="Agent timed out",
            recoverable=True,
            recovery_action="retried",
        )
        # Should have an ISO-formatted timestamp string
        assert "T" in record.timestamp


# ======================================================================
# Domain exceptions
# ======================================================================


class TestBlockingGateError:
    def test_is_exception(self) -> None:
        err = BlockingGateError("extraction gate failed")
        assert isinstance(err, Exception)
        assert str(err) == "extraction gate failed"


class TestRecoverableError:
    def test_is_exception(self) -> None:
        err = RecoverableError("transient failure")
        assert isinstance(err, Exception)
        assert str(err) == "transient failure"


class TestAgentFailureError:
    def test_inherits_recoverable(self) -> None:
        err = AgentFailureError("agent crashed", agent_name="legal")
        assert isinstance(err, RecoverableError)
        assert isinstance(err, Exception)
        assert err.agent_name == "legal"
        assert str(err) == "agent crashed"

    def test_default_agent_name(self) -> None:
        err = AgentFailureError("crashed")
        assert err.agent_name == "unknown"


class TestPartialFailureError:
    def test_inherits_recoverable(self) -> None:
        err = PartialFailureError(
            "missing subjects",
            agent_name="finance",
            missing_subjects=["alpha", "bravo"],
        )
        assert isinstance(err, RecoverableError)
        assert isinstance(err, Exception)
        assert err.agent_name == "finance"
        assert err.missing_subjects == ["alpha", "bravo"]
        assert str(err) == "missing subjects"

    def test_defaults(self) -> None:
        err = PartialFailureError("partial output")
        assert err.agent_name == "unknown"
        assert err.missing_subjects == []
