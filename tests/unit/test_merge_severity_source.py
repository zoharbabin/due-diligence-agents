"""Wave 0 — merge stamps severity provenance via the single resolver (AD-3 / §8.1).

Proves every promoted Finding carries ``metadata.provenance.severity_source`` +
``severity_chain``, that user overrides applied at merge are deterministic, that
Finding IDs are unaffected, and that the computed_metrics guard no-ops on
already-resolved findings.
"""

from __future__ import annotations

from typing import Any

from dd_agents.reporting.computed_metrics import ReportDataComputer
from dd_agents.reporting.merge import FindingMerger


def _finding(title: str, severity: str = "P1", category: str = "general", agent: str = "legal") -> dict[str, Any]:
    return {
        "severity": severity,
        "category": category,
        "title": title,
        "description": title,
        "citations": [
            {
                "source_type": "contract",
                "source_path": "doc.pdf",
                "exact_quote": "verbatim quote from the document",
                "location": "Section 1",
            }
        ],
        "confidence": "high",
        "agent": agent,
    }


def test_every_finding_has_severity_source_and_chain() -> None:
    merger = FindingMerger(run_id="r")
    promoted, _dropped = merger._promote_findings([_finding("CoC requires consent")], "Subject A", "subject_a")
    assert promoted
    prov = promoted[0].metadata["provenance"]
    assert "severity_source" in prov
    assert isinstance(prov["severity_chain"], list) and prov["severity_chain"]


def test_finding_id_unchanged_by_resolution() -> None:
    """Resolving severity must not alter the finding's stable id."""
    base = _finding("Competitor CoC clause", severity="P0")
    base["description"] = "change of control restriction applies only to competitors"
    m1 = FindingMerger(run_id="r")
    p1, _ = m1._promote_findings([dict(base)], "Subject A", "subject_a")
    m2 = FindingMerger(run_id="r")
    # Pre-set the severity to the recalibrated value — id must be identical.
    base2 = dict(base, severity="P3")
    p2, _ = m2._promote_findings([base2], "Subject A", "subject_a")
    assert p1[0].id == p2[0].id


def test_user_override_applied_deterministically_at_merge() -> None:
    merger = FindingMerger(
        run_id="r",
        user_overrides_by_agent={"legal": {"change_of_control": "P0"}},
        allow_user_downgrade_of_dealbreakers=False,
    )
    f = _finding("CoC consent", severity="P2", category="change_of_control")
    promoted, _ = merger._promote_findings([f], "Subject A", "subject_a")
    assert str(promoted[0].severity) == "P0"
    assert promoted[0].metadata["provenance"]["severity_source"] == "user_override"


def test_computed_metrics_guard_noops_on_resolved_finding() -> None:
    """A finding already resolved at merge must not be downgraded again."""
    resolved = {
        "severity": "P0",
        "category": "change_of_control",
        "title": "Competitor CoC",
        "description": "change of control for competitors only",
        "metadata": {"provenance": {"severity_source": "llm"}},
    }
    out = ReportDataComputer._recalibrate_severity(resolved)
    assert out["severity"] == "P0"  # guard prevented the competitor-only downgrade


def test_computed_metrics_still_caps_legacy_finding() -> None:
    """Legacy finding without severity_source still gets the recalibration cap."""
    legacy = {
        "severity": "P0",
        "category": "change_of_control",
        "title": "Competitor CoC",
        "description": "change of control for competitors only",
        "metadata": {},
    }
    out = ReportDataComputer._recalibrate_severity(legacy)
    assert out["severity"] == "P3"


def test_contributing_agents_ordering_is_deterministic() -> None:
    """Regression: merged contributing_agents must be sorted (set order was non-deterministic)."""
    merger = FindingMerger(run_id="r")
    # Same finding from multiple agents → they merge; contributing_agents must be sorted.
    findings = [
        _finding("Change of control requires consent", agent=a, category="change_of_control")
        for a in ("legal", "commercial", "finance")
    ]
    merged = merger._deduplicate(findings)
    # Find the merged record carrying contributing_agents.
    contribs = [
        m["metadata"]["contributing_agents"] for m in merged if m.get("metadata", {}).get("contributing_agents")
    ]
    assert contribs, "expected a merged finding with contributing_agents"
    for c in contribs:
        assert c == sorted(c), f"contributing_agents not sorted: {c}"
