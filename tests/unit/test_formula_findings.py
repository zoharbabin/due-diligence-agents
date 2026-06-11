"""Tests for routing formula-integrity issues into the findings index (Issue #245).

Covers the pure `formula_findings()` builder and the merger's
`inject_formula_findings()` (idempotent, parity-safe, severity pre-resolved).
"""

from __future__ import annotations

from typing import Any

from dd_agents.extraction.formula_audit import formula_findings
from dd_agents.models.finding import Finding, MergedSubjectOutput
from dd_agents.reporting.merge import FindingMerger


def _report(issues: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "files_scanned": 1,
        "files_with_formulas": 1,
        "files_with_issues": 1 if issues else 0,
        "total_issues": len(issues),
        "by_kind": {},
        "issues": issues,
        "truncated": False,
    }


_ISSUES = [
    {"file": "Acme/model.xlsx", "sheet": "P&L", "cell": "B5", "kind": "hardcoded_override", "detail": "Hardcoded 1234"},
    {"file": "Acme/model.xlsx", "sheet": "P&L", "cell": "C3", "kind": "circular_reference", "detail": "self-ref"},
    {"file": "Acme/m.xlsx", "sheet": "S", "cell": "A1", "kind": "broken_external_link", "detail": "ext link"},
]


class TestFormulaFindingsBuilder:
    def test_empty_report_yields_no_findings(self) -> None:
        out = formula_findings(_report([]), run_id="r", subject="S", subject_safe_name="_m", timestamp="t")
        assert out == []

    def test_one_finding_per_issue_with_severity_map(self) -> None:
        out = formula_findings(
            _report(_ISSUES),
            run_id="r",
            subject="Financial models",
            subject_safe_name="_model_integrity",
            timestamp="t",
        )
        assert len(out) == 3
        by_kind = {f["metadata"]["kind"]: f for f in out}  # type: ignore[index]
        assert by_kind["hardcoded_override"]["severity"] == "P2"
        assert by_kind["circular_reference"]["severity"] == "P2"
        assert by_kind["broken_external_link"]["severity"] == "P3"

    def test_finding_is_valid_and_cites_exact_cell(self) -> None:
        out = formula_findings(
            _report(_ISSUES[:1]),
            run_id="r",
            subject="Financial models",
            subject_safe_name="_model_integrity",
            timestamp="t",
        )
        f = Finding.model_validate(out[0])  # must validate against the Finding contract
        assert f.agent == "finance"
        assert f.citations[0].source_path == "Acme/model.xlsx"
        assert f.citations[0].location == "P&L!B5"

    def test_severity_source_stamped_for_recalibration_guard(self) -> None:
        out = formula_findings(
            _report(_ISSUES[:1]),
            run_id="r",
            subject="Financial models",
            subject_safe_name="_model_integrity",
            timestamp="t",
        )
        prov = out[0]["metadata"]["provenance"]  # type: ignore[index]
        assert prov["severity_source"] == "formula_auditor"

    def test_ids_are_deterministic(self) -> None:
        a = formula_findings(_report(_ISSUES), run_id="r1", subject="S", subject_safe_name="_m", timestamp="t1")
        b = formula_findings(_report(_ISSUES), run_id="r2", subject="S", subject_safe_name="_m", timestamp="t2")
        # ids are content-derived, independent of run_id/timestamp.
        assert [f["id"] for f in a] == [f["id"] for f in b]


class TestInjectFormulaFindings:
    def _merger(self) -> FindingMerger:
        return FindingMerger(run_id="r1", config_hash="h", prompt_version="1.0.0")

    def test_creates_synthetic_subject_and_persists_findings(self) -> None:
        merged: dict[str, MergedSubjectOutput] = {}
        n = self._merger().inject_formula_findings(merged, _report(_ISSUES))
        assert n == 3
        assert "_model_integrity" in merged
        assert len(merged["_model_integrity"].findings) == 3
        assert merged["_model_integrity"].findings[0].agent == "finance"

    def test_idempotent_under_resume(self) -> None:
        merged: dict[str, MergedSubjectOutput] = {}
        m = self._merger()
        m.inject_formula_findings(merged, _report(_ISSUES))
        n2 = m.inject_formula_findings(merged, _report(_ISSUES))  # second pass
        assert n2 == 0
        assert len(merged["_model_integrity"].findings) == 3

    def test_empty_report_is_noop(self) -> None:
        merged: dict[str, MergedSubjectOutput] = {}
        n = self._merger().inject_formula_findings(merged, _report([]))
        assert n == 0
        assert merged == {}

    def test_findings_survive_recalibration_guard(self) -> None:
        # The recalibration guard must NO-OP on a finding with severity_source set,
        # preserving the formula auditor's severity.
        from dd_agents.reporting.computed_metrics import ReportDataComputer

        merged: dict[str, MergedSubjectOutput] = {}
        self._merger().inject_formula_findings(merged, _report(_ISSUES[:1]))
        raw = merged["_model_integrity"].findings[0].model_dump()
        out = ReportDataComputer._recalibrate_severity(raw)
        assert out["severity"] == "P2"  # unchanged by the read-only guard
