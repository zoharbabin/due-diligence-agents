"""Unit tests for the dd_agents.errors module.

Covers:
- ErrorSeverity and ErrorCategory enums
- PipelineErrorRecord structured record
- ConfigurationError, ExtractionError, AgentOutputParseError, PipelineValidationError
"""

from __future__ import annotations

from dd_agents.errors import (
    AgentOutputParseError,
    ConfigurationError,
    ErrorCategory,
    ErrorSeverity,
    ExtractionError,
    PipelineErrorRecord,
    PipelineValidationError,
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
        assert record.customers_affected == []
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
            customers_affected=["alpha", "bravo"],
            details={"failure_rate": 0.65},
            outcome="fatal",
        )
        assert record.category == ErrorCategory.EXTRACTION
        assert record.severity == ErrorSeverity.FATAL
        assert record.outcome == "fatal"
        assert len(record.customers_affected) == 2

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


class TestConfigurationError:
    def test_is_exception(self) -> None:
        err = ConfigurationError("missing deal-config.json")
        assert isinstance(err, Exception)
        assert str(err) == "missing deal-config.json"


class TestExtractionError:
    def test_is_exception(self) -> None:
        err = ExtractionError("file unreadable after all fallbacks")
        assert isinstance(err, Exception)
        assert str(err) == "file unreadable after all fallbacks"


class TestAgentOutputParseError:
    def test_basic(self) -> None:
        err = AgentOutputParseError("bad JSON", agent_name="legal", raw_output="{broken")
        assert isinstance(err, Exception)
        assert err.agent_name == "legal"
        assert err.raw_output == "{broken"
        assert str(err) == "bad JSON"

    def test_defaults(self) -> None:
        err = AgentOutputParseError("parse failed")
        assert err.agent_name == "unknown"
        assert err.raw_output == ""


class TestPipelineValidationError:
    def test_basic(self) -> None:
        err = PipelineValidationError(
            "numerical audit failed",
            gate="numerical_audit",
            details={"mismatches": 12},
        )
        assert isinstance(err, Exception)
        assert err.gate == "numerical_audit"
        assert err.details == {"mismatches": 12}
        assert str(err) == "numerical audit failed"

    def test_defaults(self) -> None:
        err = PipelineValidationError("gate failed")
        assert err.gate == ""
        assert err.details == {}
