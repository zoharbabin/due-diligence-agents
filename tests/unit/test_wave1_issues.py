"""Tests for Wave 1 issues: #145, #135, #136, #121, #137, #147.

Covers:
- Finding provenance model and enrichment (#145)
- Discount & pricing analysis (#135)
- Renewal & contract expiry analysis (#136)
- Regulatory & compliance risk assessment (#121)
- Legal entity distribution (#137)
- Contract date timeline (#147)
"""

from __future__ import annotations

from typing import Any

from dd_agents.reporting.computed_metrics import ReportComputedData, ReportDataComputer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _finding(
    title: str = "Test finding",
    severity: str = "P2",
    agent: str = "legal",
    category: str = "uncategorized",
    description: str = "",
    citations: list[dict[str, str]] | None = None,
    confidence: str = "high",
) -> dict[str, Any]:
    return {
        "severity": severity,
        "agent": agent,
        "category": category,
        "title": title,
        "description": description or title,
        "citations": citations or [{"source_type": "contract", "source_path": "a.pdf", "exact_quote": "q"}],
        "confidence": confidence,
    }


def _customer(
    name: str,
    findings: list[dict[str, Any]] | None = None,
    cross_references: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "customer": name,
        "findings": findings or [],
        "gaps": [],
        "cross_references": cross_references or [],
    }


# ===========================================================================
# Issue #145: Audit Trail & Finding Provenance
# ===========================================================================


class TestFindingProvenance:
    """Tests for finding provenance metadata enrichment."""

    def test_provenance_fields_exist(self) -> None:
        """ReportComputedData should have provenance_stats field."""
        data = ReportComputedData()
        assert hasattr(data, "provenance_stats")

    def test_provenance_stats_populated(self) -> None:
        """compute() should populate provenance statistics."""
        merged = {
            "a": _customer(
                "A",
                findings=[
                    _finding("F1", confidence="high"),
                    _finding("F2", confidence="low"),
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        stats = result.provenance_stats
        assert stats["total_findings"] == 2
        assert stats["high_confidence_pct"] == 50.0

    def test_provenance_agents_tracked(self) -> None:
        """Provenance should track which agents contributed findings."""
        merged = {
            "a": _customer(
                "A",
                findings=[
                    _finding("F1", agent="legal"),
                    _finding("F2", agent="finance"),
                    _finding("F3", agent="legal"),
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        stats = result.provenance_stats
        assert stats["agent_contribution"]["legal"] == 2
        assert stats["agent_contribution"]["finance"] == 1

    def test_provenance_recalibrated_count(self) -> None:
        """Recalibrated findings should be tracked in provenance."""
        merged = {
            "a": _customer(
                "A",
                findings=[
                    _finding(
                        "Competitor CoC clause triggers concern",
                        severity="P0",
                        category="change_of_control",
                        description="competitor change of control clause",
                    ),
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert isinstance(result.provenance_stats["recalibrated_count"], int)


# ===========================================================================
# Issue #135: Discount & Pricing Analysis
# ===========================================================================


class TestDiscountAnalysis:
    """Tests for discount and pricing analysis metrics."""

    def test_discount_fields_exist(self) -> None:
        data = ReportComputedData()
        assert hasattr(data, "discount_analysis")

    def test_discount_extraction_from_findings(self) -> None:
        """Discount mentions in findings should be extracted."""
        merged = {
            "a": _customer(
                "A",
                findings=[
                    _finding(
                        "Customer receives 30% discount on list price",
                        category="discount",
                        agent="finance",
                        description="Enterprise discount of 30% applied to $100K contract",
                    ),
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        analysis = result.discount_analysis
        assert analysis["total_pricing_findings"] >= 1

    def test_discount_empty_when_no_pricing(self) -> None:
        """Empty discount analysis when no pricing findings."""
        merged = {"a": _customer("A")}
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.discount_analysis["customers_with_discounts"] == 0

    def test_discount_distribution_buckets(self) -> None:
        """Discount distribution should have standard buckets."""
        data = ReportComputedData()
        buckets = data.discount_analysis.get("distribution", {})
        assert isinstance(buckets, dict)


# ===========================================================================
# Issue #136: Renewal & Contract Expiry Analysis
# ===========================================================================


class TestRenewalAnalysis:
    """Tests for renewal and contract expiry analysis."""

    def test_renewal_fields_exist(self) -> None:
        data = ReportComputedData()
        assert hasattr(data, "renewal_analysis")

    def test_renewal_type_detection(self) -> None:
        """Renewal type (auto/manual) should be detected from findings."""
        merged = {
            "a": _customer(
                "A",
                findings=[
                    _finding(
                        "Auto-renewal clause with 30-day notice",
                        category="renewal",
                        agent="commercial",
                        description="Contract auto-renews annually with 30-day notice period",
                    ),
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        analysis = result.renewal_analysis
        assert analysis["total_renewal_findings"] >= 1
        assert analysis["auto_renew_count"] >= 1

    def test_evergreen_clause_detected(self) -> None:
        """Evergreen contract clauses should be detected as renewals."""
        merged = {
            "a": _customer(
                "A",
                findings=[
                    _finding(
                        "Evergreen clause with no termination date",
                        category="renewal",
                        agent="commercial",
                        description="Contract is evergreen with perpetual auto-renewal",
                    ),
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.renewal_analysis["total_renewal_findings"] >= 1

    def test_renewal_empty_state(self) -> None:
        merged = {"a": _customer("A")}
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.renewal_analysis["total_renewal_findings"] == 0

    def test_renewal_escalation_detection(self) -> None:
        """Price escalation caps should be detected."""
        merged = {
            "a": _customer(
                "A",
                findings=[
                    _finding(
                        "Renewal price escalation capped at 3% annually",
                        category="renewal",
                        agent="commercial",
                        description="Annual renewal price increase limited to 3% per contract terms",
                    ),
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.renewal_analysis["escalation_cap_count"] >= 1


# ===========================================================================
# Issue #121: Regulatory & Compliance Risk Assessment
# ===========================================================================


class TestComplianceAnalysis:
    """Tests for regulatory and compliance risk metrics."""

    def test_compliance_fields_exist(self) -> None:
        data = ReportComputedData()
        assert hasattr(data, "compliance_analysis")

    def test_dpa_coverage_computation(self) -> None:
        """DPA coverage percentage should be computed."""
        merged = {
            "a": _customer(
                "A",
                findings=[
                    _finding(
                        "DPA in place and valid",
                        category="dpa",
                        agent="legal",
                        description="Data Processing Agreement executed and current",
                    ),
                ],
            ),
            "b": _customer(
                "B",
                findings=[
                    _finding(
                        "Missing DPA for EU data processing",
                        category="dpa",
                        agent="legal",
                        severity="P1",
                        description="No DPA on file despite EU personal data processing",
                    ),
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        analysis = result.compliance_analysis
        assert "dpa_findings_count" in analysis

    def test_jurisdiction_distribution(self) -> None:
        """Jurisdiction analysis should track governing law distribution."""
        merged = {
            "a": _customer(
                "A",
                findings=[
                    _finding(
                        "Governed by Delaware law",
                        category="governing_law",
                        agent="legal",
                    ),
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        analysis = result.compliance_analysis
        assert "jurisdiction_findings_count" in analysis

    def test_compliance_empty_state(self) -> None:
        merged = {"a": _customer("A")}
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.compliance_analysis["dpa_findings_count"] == 0


# ===========================================================================
# Issue #137: Legal Entity Distribution
# ===========================================================================


class TestEntityDistribution:
    """Tests for legal entity distribution and migration risk."""

    def test_entity_fields_exist(self) -> None:
        data = ReportComputedData()
        assert hasattr(data, "entity_distribution")

    def test_entity_detection_from_findings(self) -> None:
        """Legal entities should be detected from findings."""
        merged = {
            "a": _customer(
                "A",
                findings=[
                    _finding(
                        "Contract signed by TargetCo LLC",
                        category="governance",
                        agent="legal",
                        description="Agreement between TargetCo LLC and Customer A",
                    ),
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        analysis = result.entity_distribution
        assert "total_entities_mentioned" in analysis

    def test_entity_empty_state(self) -> None:
        merged = {"a": _customer("A")}
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.entity_distribution["total_entities_mentioned"] == 0


# ===========================================================================
# Issue #147: Contract Date Timeline
# ===========================================================================


class TestContractTimeline:
    """Tests for contract date timeline analysis."""

    def test_timeline_fields_exist(self) -> None:
        data = ReportComputedData()
        assert hasattr(data, "contract_timeline")

    def test_timeline_date_extraction(self) -> None:
        """Contract dates should be extracted from findings."""
        merged = {
            "a": _customer(
                "A",
                findings=[
                    _finding(
                        "Contract expires December 2026",
                        category="termination",
                        agent="commercial",
                        description="MSA term expires on 2026-12-31",
                    ),
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        timeline = result.contract_timeline
        assert "date_mentions_count" in timeline

    def test_timeline_empty_state(self) -> None:
        merged = {"a": _customer("A")}
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.contract_timeline["date_mentions_count"] == 0


# ===========================================================================
# HTML Renderer Tests
# ===========================================================================


class TestNewRenderers:
    """Tests for new HTML section renderers."""

    def test_discount_renderer_exists(self) -> None:
        from dd_agents.reporting.html_discount import DiscountAnalysisRenderer

        computed = ReportComputedData()
        renderer = DiscountAnalysisRenderer(computed, {}, {})
        result = renderer.render()
        assert result == ""  # Empty when no data

    def test_renewal_renderer_exists(self) -> None:
        from dd_agents.reporting.html_renewal import RenewalAnalysisRenderer

        computed = ReportComputedData()
        renderer = RenewalAnalysisRenderer(computed, {}, {})
        result = renderer.render()
        assert result == ""

    def test_compliance_renderer_exists(self) -> None:
        from dd_agents.reporting.html_compliance import ComplianceRenderer

        computed = ReportComputedData()
        renderer = ComplianceRenderer(computed, {}, {})
        result = renderer.render()
        assert result == ""

    def test_entity_renderer_exists(self) -> None:
        from dd_agents.reporting.html_entity import EntityDistributionRenderer

        computed = ReportComputedData()
        renderer = EntityDistributionRenderer(computed, {}, {})
        result = renderer.render()
        assert result == ""

    def test_timeline_renderer_exists(self) -> None:
        from dd_agents.reporting.html_timeline import TimelineRenderer

        computed = ReportComputedData()
        renderer = TimelineRenderer(computed, {}, {})
        result = renderer.render()
        assert result == ""

    def test_discount_renderer_with_data(self) -> None:
        from dd_agents.reporting.html_discount import DiscountAnalysisRenderer

        computed = ReportComputedData(
            discount_analysis={
                "customers_with_discounts": 3,
                "total_pricing_findings": 5,
                "distribution": {"0-10%": 1, "10-25%": 1, "25-50%": 1, ">50%": 0},
                "findings": [
                    {"title": "30% discount", "severity": "P2", "_customer": "A", "agent": "finance"},
                ],
            },
        )
        renderer = DiscountAnalysisRenderer(computed, {}, {})
        result = renderer.render()
        assert "sec-discount" in result
        assert "Discount" in result

    def test_compliance_renderer_with_data(self) -> None:
        from dd_agents.reporting.html_compliance import ComplianceRenderer

        computed = ReportComputedData(
            compliance_analysis={
                "dpa_findings_count": 5,
                "jurisdiction_findings_count": 3,
                "regulatory_findings_count": 2,
                "total_compliance_findings": 10,
                "findings": [
                    {"title": "Missing DPA", "severity": "P1", "_customer": "A", "agent": "legal"},
                ],
            },
        )
        renderer = ComplianceRenderer(computed, {}, {})
        result = renderer.render()
        assert "sec-compliance" in result

    def test_renewal_renderer_with_data(self) -> None:
        from dd_agents.reporting.html_renewal import RenewalAnalysisRenderer

        computed = ReportComputedData(
            renewal_analysis={
                "total_renewal_findings": 5,
                "auto_renew_count": 3,
                "manual_renew_count": 1,
                "escalation_cap_count": 2,
                "findings": [
                    {"title": "Auto-renewal", "severity": "P2", "_customer": "A", "agent": "commercial"},
                ],
            },
        )
        renderer = RenewalAnalysisRenderer(computed, {}, {})
        result = renderer.render()
        assert "sec-renewal" in result

    def test_renderers_escape_html(self) -> None:
        """All renderers should HTML-escape user-controlled strings."""
        from dd_agents.reporting.html_discount import DiscountAnalysisRenderer

        computed = ReportComputedData(
            discount_analysis={
                "customers_with_discounts": 1,
                "total_pricing_findings": 1,
                "distribution": {},
                "findings": [
                    {
                        "title": "<script>alert('xss')</script>",
                        "severity": "P2",
                        "_customer": "Evil<Corp",
                        "agent": "finance",
                    },
                ],
            },
        )
        renderer = DiscountAnalysisRenderer(computed, {}, {})
        result = renderer.render()
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_compliance_renderer_escapes_html(self) -> None:
        """Compliance renderer should HTML-escape user-controlled strings."""
        from dd_agents.reporting.html_compliance import ComplianceRenderer

        computed = ReportComputedData(
            compliance_analysis={
                "total_compliance_findings": 1,
                "dpa_findings_count": 0,
                "jurisdiction_findings_count": 0,
                "regulatory_findings_count": 0,
                "findings": [
                    {
                        "title": "<img onerror=alert(1)>",
                        "severity": "P1",
                        "_customer": "Evil<Corp",
                    },
                ],
            },
        )
        renderer = ComplianceRenderer(computed, {}, {})
        result = renderer.render()
        assert "<img onerror" not in result

    def test_renewal_renderer_escapes_html(self) -> None:
        """Renewal renderer should HTML-escape user-controlled strings."""
        from dd_agents.reporting.html_renewal import RenewalAnalysisRenderer

        computed = ReportComputedData(
            renewal_analysis={
                "total_renewal_findings": 1,
                "auto_renew_count": 0,
                "manual_renew_count": 0,
                "escalation_cap_count": 0,
                "findings": [
                    {
                        "title": "<script>xss</script>",
                        "severity": "P2",
                        "_customer": "Test&Co",
                        "agent": "commercial",
                    },
                ],
            },
        )
        renderer = RenewalAnalysisRenderer(computed, {}, {})
        result = renderer.render()
        assert "<script>" not in result

    def test_entity_renderer_escapes_html(self) -> None:
        """Entity renderer should HTML-escape user-controlled strings."""
        from dd_agents.reporting.html_entity import EntityDistributionRenderer

        computed = ReportComputedData(
            entity_distribution={
                "entity_findings_count": 1,
                "total_entities_mentioned": 1,
                "findings": [
                    {
                        "title": "<b onmouseover=alert(1)>",
                        "severity": "P2",
                        "_customer": "A",
                    },
                ],
            },
        )
        renderer = EntityDistributionRenderer(computed, {}, {})
        result = renderer.render()
        assert "<b onmouseover" not in result

    def test_timeline_renderer_escapes_html(self) -> None:
        """Timeline renderer should HTML-escape user-controlled strings."""
        from dd_agents.reporting.html_timeline import TimelineRenderer

        computed = ReportComputedData(
            contract_timeline={
                "expiry_findings_count": 1,
                "date_mentions_count": 1,
                "findings": [
                    {
                        "title": "<script>alert('xss')</script>",
                        "severity": "P2",
                        "_customer": "X",
                    },
                ],
            },
        )
        renderer = TimelineRenderer(computed, {}, {})
        result = renderer.render()
        assert "<script>" not in result


# ===========================================================================
# New valid categories for agents
# ===========================================================================


class TestNewCategories:
    """Test that new categories are registered in validate_finding."""

    def test_regulatory_category(self) -> None:
        from dd_agents.tools.validate_finding import VALID_CATEGORIES

        assert "regulatory" in VALID_CATEGORIES

    def test_renewal_category(self) -> None:
        from dd_agents.tools.validate_finding import VALID_CATEGORIES

        assert "renewal" in VALID_CATEGORIES

    def test_discount_category(self) -> None:
        from dd_agents.tools.validate_finding import VALID_CATEGORIES

        assert "discount" in VALID_CATEGORIES

    def test_legal_entity_category(self) -> None:
        """legal_entity should be a valid finding category."""
        from dd_agents.tools.validate_finding import VALID_CATEGORIES

        assert "legal_entity" in VALID_CATEGORIES

    def test_contract_timeline_category(self) -> None:
        from dd_agents.tools.validate_finding import VALID_CATEGORIES

        assert "contract_timeline" in VALID_CATEGORIES


# ===========================================================================
# Strengthened analysis method tests (audit findings)
# ===========================================================================


class TestDiscountAnalysisStrengthened:
    """Precise tests for discount distribution bucketing and edge cases."""

    def test_discount_bucket_10_pct(self) -> None:
        """10% discount should go in 0-10% bucket."""
        merged = {
            "a": _customer(
                "A",
                findings=[
                    _finding(
                        "Customer receives 10% discount on subscription",
                        category="discount",
                        agent="finance",
                        description="Standard enterprise pricing applied",
                    ),
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        dist = result.discount_analysis.get("distribution", {})
        assert dist.get("0-10%", 0) >= 1

    def test_discount_bucket_25_pct(self) -> None:
        """25% discount should go in 10-25% bucket."""
        merged = {
            "a": _customer(
                "A",
                findings=[
                    _finding(
                        "Customer receives 25% discount on renewal",
                        category="discount",
                        agent="finance",
                        description="Standard enterprise pricing applied",
                    ),
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        dist = result.discount_analysis.get("distribution", {})
        assert dist.get("10-25%", 0) >= 1

    def test_no_discount_keyword_no_match(self) -> None:
        """Finding without pricing keywords should not be counted."""
        merged = {
            "a": _customer(
                "A",
                findings=[_finding("Change of control clause", category="coc", agent="legal")],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.discount_analysis["total_pricing_findings"] == 0

    def test_rebate_keyword_match(self) -> None:
        """Rebate keyword should be detected as pricing finding."""
        merged = {
            "a": _customer(
                "A",
                findings=[
                    _finding(
                        "Annual rebate program for volume customers",
                        category="discount",
                        agent="finance",
                        description="Quarterly rebate of 5% on spend over $100K",
                    ),
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.discount_analysis["total_pricing_findings"] == 1


class TestRenewalAnalysisStrengthened:
    """Precise tests for renewal classification logic."""

    def test_auto_renewal_counted(self) -> None:
        """Auto-renewal finding should increment auto count."""
        merged = {
            "a": _customer(
                "A",
                findings=[
                    _finding(
                        "Contract auto-renews annually",
                        category="renewal",
                        agent="commercial",
                        description="Auto-renewal clause with 30-day notice",
                    ),
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.renewal_analysis["auto_renew_count"] == 1
        assert result.renewal_analysis["manual_renew_count"] == 0

    def test_manual_renewal_counted(self) -> None:
        """Manual renewal finding should increment manual count."""
        merged = {
            "a": _customer(
                "A",
                findings=[
                    _finding(
                        "Manual renewal required before term end",
                        category="renewal",
                        agent="commercial",
                        description="Contract requires manual renewal by customer",
                    ),
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.renewal_analysis["manual_renew_count"] == 1
        assert result.renewal_analysis["auto_renew_count"] == 0

    def test_expiry_keyword_detection(self) -> None:
        """'expir' should match 'expires', 'expiration', 'expiry'."""
        for word in ["expires", "expiration date", "contract expiry"]:
            merged = {
                "a": _customer(
                    "A",
                    findings=[_finding(f"Contract {word} December 2026", agent="commercial")],
                ),
            }
            computer = ReportDataComputer()
            result = computer.compute(merged)
            assert result.renewal_analysis["total_renewal_findings"] >= 1, f"Failed for: {word}"


class TestComplianceAnalysisStrengthened:
    """Precise tests for compliance finding classification."""

    def test_dpa_category_match(self) -> None:
        """Finding with 'dpa' in text should be counted as DPA finding."""
        merged = {
            "a": _customer(
                "A",
                findings=[
                    _finding(
                        "Missing DPA for EU data transfers",
                        category="dpa",
                        agent="legal",
                        description="No DPA on file despite EU personal data processing",
                    ),
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.compliance_analysis["dpa_findings_count"] >= 1

    def test_jurisdiction_keyword_match(self) -> None:
        """Jurisdiction keywords should be classified correctly."""
        merged = {
            "a": _customer(
                "A",
                findings=[
                    _finding(
                        "Governed by Delaware law",
                        category="governing_law",
                        agent="legal",
                        description="Contract specifies governing law as State of Delaware",
                    ),
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.compliance_analysis["jurisdiction_findings_count"] >= 1

    def test_regulatory_keyword_fcpa(self) -> None:
        """FCPA should be detected as regulatory finding."""
        merged = {
            "a": _customer(
                "A",
                findings=[
                    _finding(
                        "FCPA compliance clause present",
                        category="regulatory",
                        agent="legal",
                        description="Foreign Corrupt Practices Act compliance provisions",
                    ),
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.compliance_analysis["regulatory_findings_count"] >= 1

    def test_non_compliance_finding_excluded(self) -> None:
        """Finding without compliance keywords should not be counted."""
        merged = {
            "a": _customer(
                "A",
                findings=[_finding("Change of control clause", category="coc", agent="legal")],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.compliance_analysis["total_compliance_findings"] == 0


class TestEntityDistributionStrengthened:
    """Precise tests for entity distribution logic."""

    def test_subsidiary_keyword_detected(self) -> None:
        """'subsidiary' in finding should count as entity finding."""
        merged = {
            "a": _customer(
                "A",
                findings=[
                    _finding(
                        "Contract signed by subsidiary entity",
                        category="governance",
                        agent="legal",
                        description="Agreement executed by wholly-owned subsidiary",
                    ),
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.entity_distribution["entity_findings_count"] >= 1

    def test_non_entity_finding_excluded(self) -> None:
        """Finding without entity keywords should not be counted."""
        merged = {
            "a": _customer(
                "A",
                findings=[
                    _finding(
                        "Pricing below market rate",
                        category="discount",
                        agent="finance",
                    ),
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.entity_distribution["entity_findings_count"] == 0


class TestTimelineStrengthened:
    """Precise tests for date regex and timeline extraction."""

    def test_iso_date_detected(self) -> None:
        """ISO format 2026-12-31 should be detected."""
        merged = {
            "a": _customer(
                "A",
                findings=[
                    _finding(
                        "Contract term ends 2026-12-31",
                        category="termination",
                        agent="commercial",
                        description="MSA expires on 2026-12-31",
                    ),
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.contract_timeline["date_mentions_count"] >= 1

    def test_us_date_detected(self) -> None:
        """US format 12/31/2026 should be detected."""
        merged = {
            "a": _customer(
                "A",
                findings=[
                    _finding(
                        "Contract expires 12/31/2026",
                        category="termination",
                        agent="commercial",
                        description="Term ends on 12/31/2026",
                    ),
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.contract_timeline["date_mentions_count"] >= 1

    def test_month_name_date_detected(self) -> None:
        """Month name format 'December 2026' should be detected."""
        merged = {
            "a": _customer(
                "A",
                findings=[
                    _finding(
                        "Renewal scheduled for December 2026",
                        category="renewal",
                        agent="commercial",
                        description="Next renewal period is December 2026",
                    ),
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.contract_timeline["date_mentions_count"] >= 1

    def test_month_day_year_detected(self) -> None:
        """'January 15, 2025' format should be detected."""
        merged = {
            "a": _customer(
                "A",
                findings=[
                    _finding(
                        "Contract signed January 15, 2025",
                        category="contract_timeline",
                        agent="commercial",
                        description="Effective date January 15, 2025",
                    ),
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.contract_timeline["date_mentions_count"] >= 1

    def test_no_dates_zero_count(self) -> None:
        """Finding without dates should not increment date count."""
        merged = {
            "a": _customer(
                "A",
                findings=[
                    _finding(
                        "Contract has unusual terms",
                        category="contract_timeline",
                        agent="commercial",
                        description="Unusual termination provisions noted",
                    ),
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.contract_timeline["date_mentions_count"] == 0


class TestSemanticDedupStrengthened:
    """Additional semantic dedup tests from audit findings."""

    def test_empty_source_path_blocks_merge(self) -> None:
        """Findings with empty source_path should not merge."""
        from dd_agents.reporting.merge import FindingMerger

        findings = [
            {
                "severity": "P1",
                "category": "coc",
                "title": "Change of control clause",
                "description": "CoC clause found",
                "citations": [{"source_type": "contract", "source_path": "", "exact_quote": "q", "location": ""}],
                "confidence": "high",
                "agent": "legal",
            },
            {
                "severity": "P1",
                "category": "coc",
                "title": "Change of control clause",
                "description": "CoC clause found",
                "citations": [{"source_type": "contract", "source_path": "", "exact_quote": "q", "location": ""}],
                "confidence": "high",
                "agent": "commercial",
            },
        ]
        merger = FindingMerger()
        result = merger._semantic_dedup(findings)
        assert len(result) == 2  # Should NOT merge when document unknown

    def test_same_agent_not_merged(self) -> None:
        """Findings from same agent should NOT merge even with similar titles."""
        from dd_agents.reporting.merge import FindingMerger

        findings = [
            {
                "severity": "P1",
                "category": "coc",
                "title": "Change of control clause in section 5",
                "description": "CoC in section 5",
                "citations": [
                    {"source_type": "contract", "source_path": "a.pdf", "exact_quote": "q", "location": "p1"}
                ],
                "confidence": "high",
                "agent": "legal",
            },
            {
                "severity": "P2",
                "category": "coc",
                "title": "Change of control clause in section 7",
                "description": "CoC in section 7",
                "citations": [
                    {"source_type": "contract", "source_path": "a.pdf", "exact_quote": "q", "location": "p2"}
                ],
                "confidence": "high",
                "agent": "legal",
            },
        ]
        merger = FindingMerger()
        result = merger._semantic_dedup(findings)
        assert len(result) == 2  # Same agent — must NOT merge


class TestNoiseClassificationStrengthened:
    """Tests for noise pattern precision after audit fix."""

    def test_consent_not_available_is_material(self) -> None:
        """'consent not available' should NOT be noise — it's a material DD finding."""
        from dd_agents.reporting.computed_metrics import _is_noise_finding

        f = _finding(
            "Change of control consent not available from Customer X",
            category="coc",
            agent="legal",
            description="Customer has not provided consent for assignment",
        )
        assert not _is_noise_finding(f)

    def test_file_not_available_is_noise(self) -> None:
        """'file not available' should be noise."""
        from dd_agents.reporting.computed_metrics import _is_noise_finding

        f = _finding(
            "Contract file not available for review",
            category="uncategorized",
            agent="legal",
            description="File not available in data room",
        )
        assert _is_noise_finding(f)

    def test_dq_pattern_does_not_match_real_finding(self) -> None:
        """'Cannot verify AR aging' should NOT be data quality (it's about AR quality)."""
        from dd_agents.reporting.computed_metrics import _is_data_quality_finding

        f = _finding(
            "Cannot verify AR aging due to payment delays",
            category="finance",
            agent="finance",
            description="Accounts receivable aging schedule inconsistent",
        )
        assert not _is_data_quality_finding(f)

    def test_dq_pattern_matches_data_gap(self) -> None:
        """'data unavailable' should be data quality finding."""
        from dd_agents.reporting.computed_metrics import _is_data_quality_finding

        f = _finding(
            "Revenue data unavailable for analysis",
            category="uncategorized",
            agent="finance",
            description="FY2026 revenue waterfall data unavailable",
        )
        assert _is_data_quality_finding(f)
