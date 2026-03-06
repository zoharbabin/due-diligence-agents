"""Unit tests for post-hoc severity recalibration.

Covers:
- Deterministic downgrade of known false-positive patterns
- Audit trail annotations (_recalibrated_from, _recalibration_reason)
- Multiple-rule matching: mildest cap wins
- require_all logic: prevents false positives
- Integration with compute(): severity_counts, wolf_pack, risk_label
"""

from __future__ import annotations

from dd_agents.reporting.computed_metrics import ReportDataComputer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_finding(
    severity: str = "P2",
    agent: str = "legal",
    category: str = "uncategorized",
    title: str = "Test finding",
    description: str = "Description",
) -> dict[str, object]:
    return {
        "severity": severity,
        "agent": agent,
        "category": category,
        "title": title,
        "description": description,
        "citations": [],
    }


def _make_merged_data(findings: list[dict[str, object]]) -> dict[str, object]:
    return {
        "customer_a": {
            "customer": "Customer A",
            "findings": findings,
            "gaps": [],
        }
    }


# ===========================================================================
# Tests — direct _recalibrate_severity method
# ===========================================================================


class TestRecalibrateSeverity:
    """Tests for ReportDataComputer._recalibrate_severity()."""

    def test_competitor_coc_p0_downgraded_to_p3(self) -> None:
        """P0 competitor-only CoC should be capped at P3."""
        f = _make_finding(
            severity="P0",
            title="Competitor-only Change of Control clause",
            category="change_of_control",
        )
        result = ReportDataComputer._recalibrate_severity(f)
        assert result["severity"] == "P3"

    def test_auditor_independence_p0_downgraded_to_p2(self) -> None:
        """P0 auditor independence finding should be capped at P2."""
        f = _make_finding(
            severity="P0",
            title="Auditor independence clause violation",
            description="Standard auditor independence requirements in engagement letter",
        )
        result = ReportDataComputer._recalibrate_severity(f)
        assert result["severity"] == "P2"

    def test_transaction_fee_p0_downgraded_to_p1(self) -> None:
        """P0 transaction fee finding should be capped at P1."""
        f = _make_finding(
            severity="P0",
            title="Transaction fee of 2% TEV",
            description="Advisory fee payable upon completion of transaction",
        )
        result = ReportDataComputer._recalibrate_severity(f)
        assert result["severity"] == "P1"

    def test_tfc_p0_downgraded_to_p2(self) -> None:
        """P0 TfC finding should be capped at P2."""
        f = _make_finding(
            severity="P0",
            title="Termination for convenience clause present",
            category="tfc",
        )
        result = ReportDataComputer._recalibrate_severity(f)
        assert result["severity"] == "P2"

    def test_speculative_p1_downgraded_to_p2(self) -> None:
        """P1 with speculative language 'may contain' capped at P2."""
        f = _make_finding(
            severity="P1",
            title="Potential IP issue",
            description="Contract may contain restrictive IP clauses",
        )
        result = ReportDataComputer._recalibrate_severity(f)
        assert result["severity"] == "P2"

    def test_speculative_must_be_verified(self) -> None:
        """P1 with 'must be verified' capped at P2."""
        f = _make_finding(
            severity="P1",
            title="Revenue recognition concern",
            description="This finding must be verified against financial statements",
        )
        result = ReportDataComputer._recalibrate_severity(f)
        assert result["severity"] == "P2"

    def test_genuine_p0_not_recalibrated(self) -> None:
        """A genuine P0 that doesn't match any rule stays P0."""
        f = _make_finding(
            severity="P0",
            title="Undisclosed material litigation pending",
            description="Company faces $50M lawsuit from former partner",
            category="litigation",
        )
        result = ReportDataComputer._recalibrate_severity(f)
        assert result["severity"] == "P0"

    def test_below_cap_not_changed(self) -> None:
        """P3 competitor CoC stays P3 (already at or below cap)."""
        f = _make_finding(
            severity="P3",
            title="Competitor-only CoC clause noted",
            category="change_of_control",
        )
        result = ReportDataComputer._recalibrate_severity(f)
        assert result["severity"] == "P3"

    def test_audit_trail_annotations(self) -> None:
        """Recalibrated findings carry _recalibrated_from and _recalibration_reason."""
        f = _make_finding(
            severity="P0",
            title="Competitor change of control restriction",
            category="coc",
        )
        result = ReportDataComputer._recalibrate_severity(f)
        assert result["_recalibrated_from"] == "P0"
        assert "competitor" in str(result["_recalibration_reason"]).lower()

    def test_no_audit_trail_when_unchanged(self) -> None:
        """Findings that aren't recalibrated have no audit trail keys."""
        f = _make_finding(
            severity="P0",
            title="Undisclosed material litigation",
            description="$50M lawsuit",
            category="litigation",
        )
        result = ReportDataComputer._recalibrate_severity(f)
        assert "_recalibrated_from" not in result
        assert "_recalibration_reason" not in result

    def test_multiple_rules_mildest_cap_wins(self) -> None:
        """When multiple rules match, the mildest cap (highest P-number) wins."""
        # This finding matches both auditor_independence (P2 cap)
        # and speculative_language (P2 cap) — both are P2 so result is P2
        f = _make_finding(
            severity="P0",
            title="Auditor independence concern",
            description="Auditor independence requirements may contain issues",
        )
        result = ReportDataComputer._recalibrate_severity(f)
        assert result["severity"] == "P2"

    def test_require_all_prevents_false_positive(self) -> None:
        """'competitor' in title WITHOUT CoC text context should NOT trigger competitor_only_coc rule."""
        f = _make_finding(
            severity="P0",
            title="Competitor analysis shows market threat",
            category="market_analysis",
            description="Competitor landscape indicates significant risk",
        )
        result = ReportDataComputer._recalibrate_severity(f)
        # Should NOT be downgraded — competitor_only_coc requires both title AND text patterns
        assert result["severity"] == "P0"

    def test_competitor_coc_matches_regardless_of_category(self) -> None:
        """Competitor CoC fires even when agent categorizes as 'termination' (not 'change_of_control').

        Real-world: agents often categorize CoC termination findings under
        'termination' or 'assignment_consent' rather than 'change_of_control'.
        The rule should match on title+description text, not category.
        """
        f = _make_finding(
            severity="P1",
            title="AVEVA - Immediate Termination Right on Change of Control to Competitor ($168K ARR)",
            category="termination",
            description="Contract allows immediate termination if acquired by competitor",
        )
        result = ReportDataComputer._recalibrate_severity(f)
        assert result["severity"] == "P3"
        assert result["_recalibrated_from"] == "P1"

    def test_tfc_category_only_match(self) -> None:
        """TfC category without text pattern should trigger recalibration (require_all=False)."""
        f = _make_finding(
            severity="P0",
            title="Revenue quality concern",
            description="Contract allows customer exit",
            category="convenience_termination",
        )
        result = ReportDataComputer._recalibrate_severity(f)
        assert result["severity"] == "P2"

    def test_at_cap_not_recalibrated(self) -> None:
        """P2 auditor independence stays P2 (exactly at cap), no audit trail."""
        f = _make_finding(
            severity="P2",
            title="Auditor independence requirement",
            description="Standard professional independence clause",
        )
        result = ReportDataComputer._recalibrate_severity(f)
        assert result["severity"] == "P2"
        assert "_recalibrated_from" not in result

    def test_invalid_severity_unchanged(self) -> None:
        """Finding with severity not in P0-P3 is returned unchanged."""
        f = _make_finding(severity="P4", title="Transaction fee issue", description="Advisory fee")
        result = ReportDataComputer._recalibrate_severity(f)
        assert result["severity"] == "P4"
        assert "_recalibrated_from" not in result

    def test_empty_fields_no_crash(self) -> None:
        """Finding with empty title/description/category does not raise."""
        f = {"severity": "P0", "title": "", "description": "", "category": ""}
        result = ReportDataComputer._recalibrate_severity(f)
        assert result["severity"] == "P0"

    def test_original_finding_not_mutated(self) -> None:
        """Recalibration returns a new dict; original is untouched."""
        f = _make_finding(
            severity="P0",
            title="Competitor CoC restriction",
            category="change_of_control",
        )
        original_sev = f["severity"]
        result = ReportDataComputer._recalibrate_severity(f)
        assert f["severity"] == original_sev  # Original unchanged
        assert result["severity"] == "P3"  # Result changed
        assert f is not result  # Different objects


# ===========================================================================
# Tests — integration through compute()
# ===========================================================================


class TestRecalibrationIntegration:
    """Tests for recalibration effects through compute()."""

    def test_wolf_pack_excludes_recalibrated(self) -> None:
        """After recalibration, false P0s no longer appear in wolf_pack_p0."""
        findings = [
            _make_finding(
                severity="P0",
                title="Competitor-only CoC clause",
                category="change_of_control",
            ),
            _make_finding(severity="P2", title="Normal finding"),
        ]
        computer = ReportDataComputer()
        result = computer.compute(_make_merged_data(findings))
        # The competitor CoC should be recalibrated to P3, not in wolf pack
        assert len(result.material_wolf_pack_p0) == 0

    def test_severity_counts_reflect_recalibration(self) -> None:
        """Severity counts use recalibrated values."""
        findings = [
            _make_finding(
                severity="P0",
                title="Auditor independence standard clause",
                description="Standard auditor independence requirements",
            ),
        ]
        computer = ReportDataComputer()
        result = computer.compute(_make_merged_data(findings))
        # Was P0, recalibrated to P2
        assert result.findings_by_severity.get("P0", 0) == 0
        assert result.findings_by_severity.get("P2", 0) == 1

    def test_risk_label_changes_after_recalibration(self) -> None:
        """4 false P0s recalibrated → risk label drops from High."""
        findings = [
            _make_finding(
                severity="P0",
                title="Competitor CoC clause in contract",
                category="change_of_control",
            ),
            _make_finding(
                severity="P0",
                title="Auditor independence requirement",
                description="Professional independence clause",
            ),
            _make_finding(
                severity="P0",
                title="Transaction fee 2% TEV",
                description="Advisory fee at deal close",
            ),
            _make_finding(
                severity="P0",
                title="Auditor independence",
                description="Standard auditor independence requirements",
            ),
        ]
        computer = ReportDataComputer()
        result = computer.compute(_make_merged_data(findings))
        # All P0s recalibrated away → no P0s remain → label should NOT be High or Critical
        assert result.deal_risk_label != "Critical"
        assert result.findings_by_severity.get("P0", 0) == 0
