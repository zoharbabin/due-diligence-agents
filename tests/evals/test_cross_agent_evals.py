"""Cross-agent consistency evaluation tests.

Validates that multiple agents do not contradict each other on the same
contract/subject. Tests include contradiction detection, severity agreement,
and citation conflict checks.
"""

from __future__ import annotations

from typing import Any

import pytest

from .metrics import find_contradictions, find_severity_disagreements

# ---------------------------------------------------------------------------
# Live cross-agent eval tests (require API key)
# ---------------------------------------------------------------------------


@pytest.mark.eval
class TestCrossAgentEvals:
    """Cross-agent consistency tests -- require API key, run on CI main branch only."""

    @pytest.fixture(autouse=True)
    def _skip_without_credentials(self) -> None:
        from .conftest import _has_api_credentials

        if not _has_api_credentials():
            pytest.skip("No API credentials (ANTHROPIC_API_KEY or Bedrock) — skipping live cross-agent eval tests")

    def test_no_contradictions(self, cross_agent_results: dict[str, list[dict[str, Any]]]) -> None:
        """No two agents should have severity gap >= 2 on the same category."""
        contradictions = find_contradictions(cross_agent_results)
        assert len(contradictions) == 0, f"Found {len(contradictions)} contradiction(s): {contradictions}"

    def test_severity_agreement(self, cross_agent_results: dict[str, list[dict[str, Any]]]) -> None:
        """All agents should agree on severity within 1 level for shared categories."""
        disagreements = find_severity_disagreements(cross_agent_results, max_gap=1)
        assert len(disagreements) == 0, f"Found {len(disagreements)} disagreement(s): {disagreements}"


# ---------------------------------------------------------------------------
# Offline contradiction / disagreement detection tests (no API key)
# ---------------------------------------------------------------------------


class TestFindContradictions:
    """Unit tests for cross-agent contradiction detection."""

    def test_no_contradictions_when_empty(self) -> None:
        result = find_contradictions({})
        assert result == []

    def test_no_contradictions_single_agent(self) -> None:
        result = find_contradictions(
            {
                "legal": [
                    {"category": "change_of_control", "severity": "P0"},
                    {"category": "termination", "severity": "P2"},
                ],
            }
        )
        assert result == []

    def test_contradiction_detected(self) -> None:
        results: dict[str, list[dict[str, Any]]] = {
            "legal": [{"category": "change_of_control", "severity": "P0"}],
            "commercial": [{"category": "change_of_control", "severity": "P3"}],
        }
        contradictions = find_contradictions(results)
        assert len(contradictions) == 1
        assert contradictions[0]["category"] == "change_of_control"
        assert contradictions[0]["gap"] >= 2

    def test_no_contradiction_within_one_level(self) -> None:
        results: dict[str, list[dict[str, Any]]] = {
            "legal": [{"category": "termination", "severity": "P1"}],
            "commercial": [{"category": "termination", "severity": "P2"}],
        }
        contradictions = find_contradictions(results)
        assert len(contradictions) == 0

    def test_different_categories_no_contradiction(self) -> None:
        results: dict[str, list[dict[str, Any]]] = {
            "legal": [{"category": "change_of_control", "severity": "P0"}],
            "finance": [{"category": "revenue_recognition", "severity": "P3"}],
        }
        contradictions = find_contradictions(results)
        assert len(contradictions) == 0

    def test_multiple_contradictions(self) -> None:
        results: dict[str, list[dict[str, Any]]] = {
            "legal": [
                {"category": "change_of_control", "severity": "P0"},
                {"category": "termination", "severity": "P0"},
            ],
            "commercial": [
                {"category": "change_of_control", "severity": "P3"},
                {"category": "termination", "severity": "P3"},
            ],
        }
        contradictions = find_contradictions(results)
        assert len(contradictions) == 2

    def test_three_agents_same_category(self) -> None:
        """Three agents on same category: legal P0, finance P1, commercial P3."""
        results: dict[str, list[dict[str, Any]]] = {
            "legal": [{"category": "liability", "severity": "P0"}],
            "finance": [{"category": "liability", "severity": "P1"}],
            "commercial": [{"category": "liability", "severity": "P3"}],
        }
        contradictions = find_contradictions(results)
        # P0 vs P3 = 3, P1 vs P3 = 2 — both are contradictions
        assert len(contradictions) == 2


class TestFindSeverityDisagreements:
    """Unit tests for severity disagreement detection."""

    def test_no_disagreements_when_empty(self) -> None:
        result = find_severity_disagreements({})
        assert result == []

    def test_agreement_within_max_gap(self) -> None:
        results: dict[str, list[dict[str, Any]]] = {
            "legal": [{"category": "termination", "severity": "P1"}],
            "commercial": [{"category": "termination", "severity": "P2"}],
        }
        disagreements = find_severity_disagreements(results, max_gap=1)
        assert len(disagreements) == 0

    def test_disagreement_beyond_max_gap(self) -> None:
        results: dict[str, list[dict[str, Any]]] = {
            "legal": [{"category": "termination", "severity": "P0"}],
            "commercial": [{"category": "termination", "severity": "P2"}],
        }
        disagreements = find_severity_disagreements(results, max_gap=1)
        assert len(disagreements) == 1
        assert disagreements[0]["gap"] == 2

    def test_custom_max_gap(self) -> None:
        results: dict[str, list[dict[str, Any]]] = {
            "legal": [{"category": "termination", "severity": "P0"}],
            "commercial": [{"category": "termination", "severity": "P2"}],
        }
        disagreements = find_severity_disagreements(results, max_gap=2)
        assert len(disagreements) == 0

    def test_three_agents_with_spread(self) -> None:
        results: dict[str, list[dict[str, Any]]] = {
            "legal": [{"category": "liability", "severity": "P0"}],
            "finance": [{"category": "liability", "severity": "P1"}],
            "commercial": [{"category": "liability", "severity": "P3"}],
        }
        disagreements = find_severity_disagreements(results, max_gap=1)
        assert len(disagreements) == 2
