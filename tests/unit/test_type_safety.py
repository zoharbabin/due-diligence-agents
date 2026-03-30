"""Tests for Issue #65 — Model Type Safety.

Validates that string literals are coerced to enum constants by field validators,
and that invalid values are rejected.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dd_agents.models.enums import AgentName, Confidence, Severity
from dd_agents.models.finding import AgentFinding, Finding, Gap

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_citation(**overrides: object) -> dict[str, object]:
    base = {
        "source_type": "file",
        "source_path": "contract.pdf",
        "location": "Section 1",
        "exact_quote": "Lorem ipsum",
    }
    base.update(overrides)
    return base


def _make_finding(**overrides: object) -> dict[str, object]:
    base = {
        "id": "forensic-dd_legal_cust_0001",
        "severity": "P2",
        "category": "termination",
        "title": "Test finding",
        "description": "A test finding",
        "citations": [_make_citation()],
        "confidence": "high",
        "agent": "legal",
        "skill": "forensic-dd",
        "run_id": "run_001",
        "timestamp": "2026-01-01T00:00:00Z",
        "analysis_unit": "Customer A",
    }
    base.update(overrides)
    return base


def _make_agent_finding(**overrides: object) -> dict[str, object]:
    base = {
        "severity": "P1",
        "category": "pricing",
        "title": "Agent finding",
        "description": "A test agent finding",
        "citations": [_make_citation()],
        "confidence": "medium",
    }
    base.update(overrides)
    return base


def _make_gap(**overrides: object) -> dict[str, object]:
    base = {
        "customer": "Customer A",
        "priority": "P2",
        "gap_type": "Missing_Doc",
        "missing_item": "NDA",
        "why_needed": "Required for review",
        "risk_if_missing": "Potential exposure",
        "request_to_company": "Please provide NDA",
        "evidence": "Referenced in MSA",
        "detection_method": "checklist",
        "agent": "legal",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Finding coercion tests
# ---------------------------------------------------------------------------


class TestFindingCoercion:
    def test_string_severity_coerced_to_enum(self) -> None:
        f = Finding(**_make_finding(severity="P2"))
        assert isinstance(f.severity, Severity)
        assert f.severity is Severity.P2

    def test_string_confidence_coerced_to_enum(self) -> None:
        f = Finding(**_make_finding(confidence="high"))
        assert isinstance(f.confidence, Confidence)
        assert f.confidence is Confidence.HIGH

    def test_string_agent_coerced_to_enum(self) -> None:
        f = Finding(**_make_finding(agent="legal"))
        assert isinstance(f.agent, AgentName)
        assert f.agent is AgentName.LEGAL

    def test_enum_severity_passes_through(self) -> None:
        f = Finding(**_make_finding(severity=Severity.P0))
        assert f.severity is Severity.P0

    def test_invalid_severity_rejected(self) -> None:
        with pytest.raises(ValidationError, match="severity"):
            Finding(**_make_finding(severity="INVALID"))

    def test_invalid_confidence_rejected(self) -> None:
        with pytest.raises(ValidationError, match="confidence"):
            Finding(**_make_finding(confidence="INVALID"))

    def test_invalid_agent_rejected(self) -> None:
        with pytest.raises(ValidationError, match="agent"):
            Finding(**_make_finding(agent="nonexistent"))


# ---------------------------------------------------------------------------
# AgentFinding coercion tests
# ---------------------------------------------------------------------------


class TestAgentFindingCoercion:
    def test_string_severity_coerced(self) -> None:
        af = AgentFinding(**_make_agent_finding(severity="P1"))
        assert isinstance(af.severity, Severity)
        assert af.severity is Severity.P1

    def test_string_confidence_coerced(self) -> None:
        af = AgentFinding(**_make_agent_finding(confidence="low"))
        assert isinstance(af.confidence, Confidence)
        assert af.confidence is Confidence.LOW


# ---------------------------------------------------------------------------
# Gap coercion tests
# ---------------------------------------------------------------------------


class TestGapCoercion:
    def test_string_priority_coerced_to_severity_enum(self) -> None:
        g = Gap(**_make_gap(priority="P3"))
        assert isinstance(g.priority, Severity)
        assert g.priority is Severity.P3

    def test_string_agent_coerced_to_enum(self) -> None:
        g = Gap(**_make_gap(agent="finance"))
        assert isinstance(g.agent, AgentName)
        assert g.agent is AgentName.FINANCE

    def test_none_agent_passes(self) -> None:
        g = Gap(**_make_gap(agent=None))
        assert g.agent is None

    def test_invalid_priority_rejected(self) -> None:
        with pytest.raises(ValidationError, match="priority"):
            Gap(**_make_gap(priority="INVALID"))


# ---------------------------------------------------------------------------
# Round-trip tests (serialize + deserialize preserves enum type)
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_finding_round_trip(self) -> None:
        original = Finding(**_make_finding())
        data = original.model_dump()
        restored = Finding.model_validate(data)
        assert isinstance(restored.severity, Severity)
        assert isinstance(restored.confidence, Confidence)
        assert isinstance(restored.agent, AgentName)

    def test_gap_json_round_trip(self) -> None:
        original = Gap(**_make_gap())
        json_str = original.model_dump_json()
        restored = Gap.model_validate_json(json_str)
        assert isinstance(restored.priority, Severity)
        assert restored.priority is original.priority
