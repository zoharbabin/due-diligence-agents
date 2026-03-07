"""Tests for semantic finding deduplication (Issue #150)."""

from __future__ import annotations

from typing import Any

from dd_agents.reporting.merge import FindingMerger


def _finding(
    title: str,
    description: str = "",
    agent: str = "legal",
    severity: str = "P1",
    source_path: str = "",
    location: str = "",
    confidence: str = "high",
) -> dict[str, Any]:
    return {
        "severity": severity,
        "category": "general",
        "title": title,
        "description": description or title,
        "citations": [
            {
                "source_type": "contract",
                "source_path": source_path or "doc.pdf",
                "exact_quote": "test quote",
                "location": location,
            }
        ],
        "confidence": confidence,
        "agent": agent,
    }


class TestSemanticDedup:
    """Tests for semantic similarity deduplication."""

    def test_exact_duplicate_titles_merged(self) -> None:
        """Identical titles from different agents should merge."""
        findings = [
            _finding("Change of control requires consent", agent="legal", source_path="a.pdf", location="p1"),
            _finding("Change of control requires consent", agent="commercial", source_path="a.pdf", location="p1"),
        ]
        merger = FindingMerger()
        result = merger._deduplicate(findings)
        assert len(result) == 1

    def test_semantically_similar_titles_merged(self) -> None:
        """Nearly identical titles from different agents on same doc should merge."""
        findings = [
            _finding(
                "Change of control requires board consent for assignment",
                agent="legal",
                source_path="msa.pdf",
                location="p5",
            ),
            _finding(
                "Change of control requires consent before assignment",
                agent="commercial",
                source_path="msa.pdf",
                location="p3",
            ),
        ]
        merger = FindingMerger()
        result = merger._semantic_dedup(findings)
        assert len(result) < len(findings)

    def test_different_findings_not_merged(self) -> None:
        """Genuinely different findings must not be merged."""
        findings = [
            _finding("Change of control requires board consent", agent="legal"),
            _finding("Financial audit reveals revenue restatement", agent="finance"),
        ]
        merger = FindingMerger()
        result = merger._semantic_dedup(findings)
        assert len(result) == 2

    def test_corroboration_badge_added(self) -> None:
        """When 2+ agents find same issue, corroboration metadata is added."""
        findings = [
            _finding("CoC clause found", agent="legal", source_path="a.pdf", location="p1"),
            _finding("CoC clause found", agent="commercial", source_path="a.pdf", location="p1"),
        ]
        merger = FindingMerger()
        result = merger._deduplicate(findings)
        assert len(result) == 1
        meta = result[0].get("metadata", {})
        agents = meta.get("contributing_agents", [])
        assert len(agents) >= 2

    def test_semantic_dedup_preserves_highest_severity(self) -> None:
        """When merging semantically similar findings, keep highest severity."""
        findings = [
            _finding(
                "Termination for convenience clause in section 12", agent="legal", severity="P0", source_path="msa.pdf"
            ),
            _finding(
                "Termination for convenience clause found in section 12",
                agent="commercial",
                severity="P2",
                source_path="msa.pdf",
            ),
        ]
        merger = FindingMerger()
        result = merger._semantic_dedup(findings)
        assert len(result) == 1
        assert result[0]["severity"] == "P0"

    def test_empty_input(self) -> None:
        merger = FindingMerger()
        assert merger._semantic_dedup([]) == []

    def test_single_finding(self) -> None:
        merger = FindingMerger()
        findings = [_finding("Only one finding")]
        result = merger._semantic_dedup(findings)
        assert len(result) == 1
