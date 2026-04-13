"""Tests for Wave 2 metric enhancements.

Covers:
- Issue #115: SaaS NRR/GRR estimation, expansion/contraction signals
- Issue #135: Discount avg/max, top discounted, float parsing
- Issue #136: Evergreen count, expiry distribution
- Issue #121: DPA coverage, top jurisdictions
- Issue #137: Entity names, migration risk score
- Issue #147: Cliff risk, earliest/latest expiry
- Issue #156: Insurance & liability analysis
- Issue #158: IP & license risk analysis
- Issue #103: Cross-domain risk correlation
- Issue #116: Valuation impact bridge
"""

from __future__ import annotations

from typing import Any

import pytest

from dd_agents.reporting.computed_metrics import ReportComputedData, ReportDataComputer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_finding(
    severity: str = "P2",
    agent: str = "legal",
    category: str = "uncategorized",
    title: str = "Test finding",
    description: str = "Description",
    subject_safe_name: str = "",
    subject: str = "",
) -> dict[str, Any]:
    f: dict[str, Any] = {
        "severity": severity,
        "agent": agent,
        "category": category,
        "title": title,
        "description": description,
        "citations": [],
    }
    if subject_safe_name:
        f["_subject_safe_name"] = subject_safe_name
    if subject:
        f["_subject"] = subject
    return f


def _make_merged(
    subjects: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if subjects is not None:
        return subjects
    return {
        "subject_a": {
            "subject": "Subject A",
            "findings": [_make_finding(severity="P1", agent="legal")],
            "gaps": [],
        }
    }


# ===========================================================================
# Tests
# ===========================================================================


class TestSaaSMetricsEnhanced:
    """Issue #115: NRR/GRR estimation, expansion/contraction signals, benchmarks."""

    def test_nrr_grr_defaults_no_signals(self) -> None:
        """With no expansion/contraction signals, NRR should be 100 and GRR 100."""
        merged = {"a": {"subject": "A", "findings": [], "gaps": []}}
        result = ReportDataComputer().compute(merged)
        assert result.saas_metrics["nrr_estimate"] == 100.0
        assert result.saas_metrics["grr_estimate"] == 100.0

    def test_expansion_signals_increase_nrr(self) -> None:
        """Expansion keywords should increase NRR estimate."""
        merged = {
            "a": {
                "subject": "A",
                "findings": [
                    _make_finding(title="Subject upsell opportunity"),
                    _make_finding(title="Cross-sell motion identified"),
                    _make_finding(title="Expansion revenue growing"),
                ],
                "gaps": [],
            }
        }
        result = ReportDataComputer().compute(merged)
        assert result.saas_metrics["expansion_signals"] == 3
        assert result.saas_metrics["nrr_estimate"] > 100.0

    def test_contraction_signals_decrease_nrr_and_grr(self) -> None:
        """Contraction keywords should decrease NRR and GRR."""
        merged = {
            "a": {
                "subject": "A",
                "findings": [
                    _make_finding(title="Customer churn risk identified"),
                    _make_finding(title="Downgrade to lower tier"),
                ],
                "gaps": [],
            }
        }
        result = ReportDataComputer().compute(merged)
        assert result.saas_metrics["contraction_signals"] == 2
        assert result.saas_metrics["nrr_estimate"] < 100.0
        assert result.saas_metrics["grr_estimate"] < 100.0

    def test_nrr_capped_at_bounds(self) -> None:
        """NRR should be capped at 70-150 range."""
        # Many contraction signals to push below 70
        merged = {
            "a": {
                "subject": "A",
                "findings": [
                    _make_finding(title=f"Churn risk {i}", description="cancellation likely") for i in range(20)
                ],
                "gaps": [],
            }
        }
        result = ReportDataComputer().compute(merged)
        assert result.saas_metrics["nrr_estimate"] == 70.0

    def test_benchmarks_present(self) -> None:
        """Benchmarks dict should contain top_quartile, median, concerning."""
        merged = {"a": {"subject": "A", "findings": [], "gaps": []}}
        result = ReportDataComputer().compute(merged)
        benchmarks = result.saas_metrics["benchmarks"]
        assert "top_quartile" in benchmarks
        assert "median" in benchmarks
        assert "concerning" in benchmarks

    def test_rule_of_40_present(self) -> None:
        """Rule of 40 score should be computed from NRR."""
        merged = {"a": {"subject": "A", "findings": [], "gaps": []}}
        result = ReportDataComputer().compute(merged)
        # NRR=100 → growth=0 → Rule of 40 = 0
        assert result.saas_metrics["rule_of_40_score"] == 0.0

    def test_logo_retention_defaults_100(self) -> None:
        """With no churn signals, logo retention should be 100%."""
        merged = {"a": {"subject": "A", "findings": [], "gaps": []}}
        result = ReportDataComputer().compute(merged)
        assert result.saas_metrics["logo_retention_pct"] == 100.0

    def test_clv_estimate_present(self) -> None:
        """CLV estimate should be computed when revenue data exists."""
        merged = {"a": {"subject": "A", "findings": [], "gaps": []}}
        result = ReportDataComputer().compute(merged)
        assert "clv_estimate" in result.saas_metrics

    def test_logo_retention_decreases_with_churn(self) -> None:
        """Churn signals should decrease logo retention below 100%."""
        merged = {
            "a": {
                "subject": "A",
                "findings": [
                    _make_finding(title=f"Churn risk {i}", description="cancellation likely") for i in range(5)
                ],
                "gaps": [],
            }
        }
        result = ReportDataComputer().compute(merged)
        assert result.saas_metrics["logo_retention_pct"] < 100.0


class TestDiscountEnhanced:
    """Issue #135: avg_discount, max_discount, top_discounted, float parsing."""

    def test_float_discount_parsing(self) -> None:
        """Fractional percentages like 7.5% should be parsed correctly."""
        findings = [
            _make_finding(
                title="7.5% discount off list price",
                subject_safe_name="cust_a",
            ),
        ]
        result = ReportDataComputer._compute_discount_analysis(findings)
        assert result["avg_discount_pct"] == pytest.approx(7.5)
        assert result["max_discount_pct"] == pytest.approx(7.5)

    def test_avg_and_max_discount(self) -> None:
        """Average and max discount should be computed correctly."""
        findings = [
            _make_finding(title="10% discount off", subject_safe_name="a"),
            _make_finding(title="30% discount below list", subject_safe_name="b"),
        ]
        result = ReportDataComputer._compute_discount_analysis(findings)
        assert result["avg_discount_pct"] == pytest.approx(20.0)
        assert result["max_discount_pct"] == pytest.approx(30.0)

    def test_top_discounted_entities(self) -> None:
        """Top discounted should return entities sorted by discount %."""
        findings = [
            _make_finding(title="15% discount off", subject_safe_name="low"),
            _make_finding(title="40% discount below", subject_safe_name="high"),
            _make_finding(title="25% discount off", subject_safe_name="mid"),
        ]
        result = ReportDataComputer._compute_discount_analysis(findings)
        top = result["top_discounted"]
        assert len(top) == 3
        assert top[0]["entity"] == "high"
        assert top[0]["discount_pct"] == pytest.approx(40.0)

    def test_no_discounts_returns_zero(self) -> None:
        """When no discount findings, avg and max should be 0."""
        result = ReportDataComputer._compute_discount_analysis([])
        assert result["avg_discount_pct"] == 0.0
        assert result["max_discount_pct"] == 0.0
        assert result["top_discounted"] == []


class TestRenewalEnhanced:
    """Issue #136: Evergreen count, expiry distribution."""

    def test_evergreen_count(self) -> None:
        """Evergreen contracts should be counted."""
        findings = [
            _make_finding(title="Evergreen auto-renewal clause"),
            _make_finding(title="Contract is evergreen"),
            _make_finding(title="Standard renewal clause"),
        ]
        result = ReportDataComputer._compute_renewal_analysis(findings)
        assert result["evergreen_count"] == 2

    def test_expiry_distribution_months(self) -> None:
        """Findings mentioning months should populate expiry distribution."""
        findings = [
            _make_finding(title="Contract expires in 3 months", description="renewal needed"),
            _make_finding(title="Expiry in 9 months"),
            _make_finding(title="Term end in 18 months"),
            _make_finding(title="Contract end in 30 months"),
        ]
        result = ReportDataComputer._compute_renewal_analysis(findings)
        dist = result["expiry_distribution"]
        assert dist["0-6mo"] == 1
        assert dist["6-12mo"] == 1
        assert dist["12-24mo"] == 1
        assert dist[">24mo"] == 1

    def test_expiry_distribution_empty(self) -> None:
        """With no month mentions, distribution should be all zeros."""
        findings = [_make_finding(title="Renewal clause present")]
        result = ReportDataComputer._compute_renewal_analysis(findings)
        assert sum(result["expiry_distribution"].values()) == 0


class TestComplianceEnhanced:
    """Issue #121: DPA coverage, top jurisdictions."""

    def test_dpa_coverage_pct(self) -> None:
        """DPA coverage = DPA entities / total entities * 100."""
        findings = [
            _make_finding(
                title="DPA in place",
                subject_safe_name="a",
            ),
            _make_finding(
                title="No compliance issue",
                subject_safe_name="b",
            ),
        ]
        result = ReportDataComputer._compute_compliance_analysis(findings)
        # 1 DPA entity out of 2 total = 50%
        assert result["dpa_coverage_pct"] == pytest.approx(50.0)

    def test_top_jurisdictions_extraction(self) -> None:
        """US state and country names should be extracted from jurisdiction findings."""
        findings = [
            _make_finding(
                title="Governing law: New York",
                description="Jurisdiction is New York, United States",
            ),
            _make_finding(
                title="Governed by California law",
                description="Choice of law California",
            ),
        ]
        result = ReportDataComputer._compute_compliance_analysis(findings)
        jurisdictions = result["top_jurisdictions"]
        names = [j["jurisdiction"] for j in jurisdictions]
        assert "New York" in names
        assert "California" in names

    def test_no_jurisdictions_empty(self) -> None:
        """With no jurisdiction findings, top_jurisdictions should be empty."""
        result = ReportDataComputer._compute_compliance_analysis([])
        assert result["top_jurisdictions"] == []

    def test_dpa_coverage_zero_entities(self) -> None:
        """With no entities, DPA coverage should be 0."""
        result = ReportDataComputer._compute_compliance_analysis([])
        assert result["dpa_coverage_pct"] == 0.0

    def test_compliance_risk_score_computed(self) -> None:
        """Compliance risk score should be severity-weighted."""
        findings = [
            _make_finding(title="GDPR violation", severity="P0"),
            _make_finding(title="CCPA compliance gap", severity="P2"),
        ]
        result = ReportDataComputer._compute_compliance_analysis(findings)
        assert result["compliance_risk_score"] > 0
        assert result["compliance_risk_label"] in ("critical", "high", "medium", "low")

    def test_filing_checklist_from_detected_frameworks(self) -> None:
        """Filing checklist should include items for detected regulatory frameworks."""
        findings = [
            _make_finding(title="GDPR compliance review needed"),
            _make_finding(title="HIPAA BAA missing"),
        ]
        result = ReportDataComputer._compute_compliance_analysis(findings)
        checklist = result["filing_checklist"]
        assert any("GDPR" in item for item in checklist)
        assert any("HIPAA" in item for item in checklist)

    def test_filing_checklist_empty_when_no_frameworks(self) -> None:
        """Filing checklist should be empty with generic findings."""
        findings = [_make_finding(title="General compliance concern")]
        result = ReportDataComputer._compute_compliance_analysis(findings)
        assert result["filing_checklist"] == []


class TestEntityEnhanced:
    """Issue #137: Entity names, migration risk score."""

    def test_entity_names_extracted(self) -> None:
        """Entity names from findings should be collected."""
        findings = [
            _make_finding(title="Legal entity mismatch", subject_safe_name="acme_corp"),
            _make_finding(title="Subsidiary issue", subject_safe_name="beta_inc"),
        ]
        result = ReportDataComputer._compute_entity_distribution(findings)
        assert "acme_corp" in result["entity_names"]
        assert "beta_inc" in result["entity_names"]

    def test_migration_risk_low(self) -> None:
        """0-1 entities = low risk."""
        findings = [_make_finding(title="Legal entity issue", subject_safe_name="one")]
        result = ReportDataComputer._compute_entity_distribution(findings)
        assert result["migration_risk_score"] == "low"

    def test_migration_risk_medium(self) -> None:
        """2-3 entities = medium risk."""
        findings = [
            _make_finding(title="Legal entity mismatch", subject_safe_name="a"),
            _make_finding(title="Subsidiary issue", subject_safe_name="b"),
        ]
        result = ReportDataComputer._compute_entity_distribution(findings)
        assert result["migration_risk_score"] == "medium"

    def test_migration_risk_critical(self) -> None:
        """6+ entities = critical risk."""
        findings = [_make_finding(title="Legal entity mismatch", subject_safe_name=f"ent_{i}") for i in range(7)]
        result = ReportDataComputer._compute_entity_distribution(findings)
        assert result["migration_risk_score"] == "critical"


class TestTimelineEnhanced:
    """Issue #147: Cliff risk, earliest/latest expiry."""

    def test_cliff_risk_true(self) -> None:
        """Cliff risk is True when >3 dates in the same quarter."""
        findings = [
            _make_finding(
                title=f"Expiry on 2026-06-{10 + i:02d}",
                description="Contract expiring",
            )
            for i in range(5)
        ]
        result = ReportDataComputer._compute_contract_timeline(findings)
        assert result["cliff_risk"] is True

    def test_cliff_risk_false(self) -> None:
        """Cliff risk is False when dates are spread out."""
        findings = [
            _make_finding(title="Expiry on 2026-03-01", description="Contract expiring"),
            _make_finding(title="Expiry on 2026-09-01", description="Contract renewal"),
        ]
        result = ReportDataComputer._compute_contract_timeline(findings)
        assert result["cliff_risk"] is False

    def test_earliest_latest_expiry(self) -> None:
        """Earliest and latest dates should be correctly identified."""
        findings = [
            _make_finding(title="Expiry on 2026-03-15", description="Contract expiring"),
            _make_finding(title="Term end 2027-12-01", description="Contract end date"),
            _make_finding(title="Expiry on 2026-06-01", description="Contract renewal"),
        ]
        result = ReportDataComputer._compute_contract_timeline(findings)
        assert result["earliest_expiry"] == "2026-03-15"
        assert result["latest_expiry"] == "2027-12-01"

    def test_no_dates_empty_strings(self) -> None:
        """With no date mentions, earliest/latest should be empty."""
        findings = [_make_finding(title="Expiry clause present")]
        result = ReportDataComputer._compute_contract_timeline(findings)
        assert result["earliest_expiry"] == ""
        assert result["latest_expiry"] == ""


class TestLiabilityAnalysis:
    """Issue #156: Insurance, uncapped liability, liability caps."""

    def test_insurance_count(self) -> None:
        """Insurance findings should be counted."""
        findings = [
            _make_finding(title="Insurance coverage required", subject_safe_name="a"),
            _make_finding(title="Liability cap at $1M", subject_safe_name="b"),
        ]
        result = ReportDataComputer._compute_liability_analysis(findings)
        assert result["insurance_count"] == 1
        assert result["total_liability_findings"] == 2

    def test_uncapped_detection(self) -> None:
        """Findings with 'uncapped' or 'unlimited' should be flagged."""
        findings = [
            _make_finding(title="Uncapped liability exposure", subject_safe_name="a"),
            _make_finding(title="Unlimited liability clause", subject_safe_name="b"),
        ]
        result = ReportDataComputer._compute_liability_analysis(findings)
        assert result["uncapped_count"] == 2

    def test_liability_cap_with_dollar_amount(self) -> None:
        """Liability findings with dollar amounts should count as caps."""
        findings = [
            _make_finding(
                title="Limitation of liability capped at $5M",
                description="Cap on liability set at $5 million",
                subject_safe_name="a",
            ),
        ]
        result = ReportDataComputer._compute_liability_analysis(findings)
        assert result["liability_cap_count"] == 1

    def test_indemnification_count(self) -> None:
        """Indemnification findings should be counted."""
        findings = [
            _make_finding(title="Mutual indemnification clause"),
            _make_finding(title="Indemnity obligations unclear"),
        ]
        result = ReportDataComputer._compute_liability_analysis(findings)
        assert result["indemnification_count"] == 2


class TestIPRiskAnalysis:
    """Issue #158: IP ownership gaps, open source, license risk."""

    def test_ip_findings_counted(self) -> None:
        """IP-related findings should be counted."""
        findings = [
            _make_finding(title="Patent portfolio review needed"),
            _make_finding(title="Copyright assignment missing"),
        ]
        result = ReportDataComputer._compute_ip_risk_analysis(findings)
        assert result["total_ip_findings"] == 2

    def test_ip_ownership_gaps(self) -> None:
        """Findings with 'gap' or 'missing' + IP keyword should count as gaps."""
        findings = [
            _make_finding(title="IP assignment gap identified", description="Intellectual property"),
            _make_finding(title="Missing patent documentation", description="Patent filing"),
        ]
        result = ReportDataComputer._compute_ip_risk_analysis(findings)
        assert result["ip_ownership_gaps"] == 2

    def test_open_source_detection(self) -> None:
        """Open source license findings should be classified."""
        findings = [
            _make_finding(title="GPL licensed component found"),
            _make_finding(title="Open source dependency audit"),
            _make_finding(title="Apache license used"),
        ]
        result = ReportDataComputer._compute_ip_risk_analysis(findings)
        assert result["open_source_count"] == 3

    def test_license_risk_count(self) -> None:
        """Findings mentioning 'license' should be counted as license risks."""
        findings = [
            _make_finding(title="MIT license compliance"),
            _make_finding(title="Proprietary license review"),
        ]
        result = ReportDataComputer._compute_ip_risk_analysis(findings)
        assert result["license_risk_count"] == 2


class TestCrossDomainRisks:
    """Issue #103: Entities with findings across 3+ domains."""

    def test_cross_domain_detection(self) -> None:
        """Entity with findings in 3+ domains should appear in cross_domain_risks."""
        merged: dict[str, Any] = {
            "multi_risk": {
                "subject": "Multi Risk",
                "findings": [
                    _make_finding(agent="legal", severity="P1"),
                    _make_finding(agent="finance", severity="P2"),
                    _make_finding(agent="commercial", severity="P2"),
                ],
                "gaps": [],
            }
        }
        result = ReportDataComputer().compute(merged)
        assert len(result.cross_domain_risks) == 1
        risk = result.cross_domain_risks[0]
        assert risk["entity"] == "multi_risk"
        assert risk["domain_count"] == 3

    def test_no_cross_domain_for_single_domain(self) -> None:
        """Entity with findings in only 1 domain should not appear."""
        merged: dict[str, Any] = {
            "single": {
                "subject": "Single",
                "findings": [
                    _make_finding(agent="legal", severity="P1"),
                    _make_finding(agent="legal", severity="P2"),
                ],
                "gaps": [],
            }
        }
        result = ReportDataComputer().compute(merged)
        assert len(result.cross_domain_risks) == 0

    def test_risk_score_weighted(self) -> None:
        """Risk score should use severity weights (P0=10, P1=5, P2=2, P3=1)."""
        merged: dict[str, Any] = {
            "entity_a": {
                "subject": "Entity A",
                "findings": [
                    _make_finding(agent="legal", severity="P0"),
                    _make_finding(agent="finance", severity="P1"),
                    _make_finding(agent="commercial", severity="P2"),
                ],
                "gaps": [],
            }
        }
        result = ReportDataComputer().compute(merged)
        assert len(result.cross_domain_risks) == 1
        risk = result.cross_domain_risks[0]
        assert risk["risk_score"] == pytest.approx(17.0)  # 10 + 5 + 2
        assert risk["has_p0"] is True

    def test_cross_domain_rag_red_with_p0(self) -> None:
        """Cross-domain RAG should be red if any entity has P0."""
        merged: dict[str, Any] = {
            "risky": {
                "subject": "Risky",
                "findings": [
                    _make_finding(agent="legal", severity="P0"),
                    _make_finding(agent="finance", severity="P2"),
                    _make_finding(agent="commercial", severity="P3"),
                ],
                "gaps": [],
            }
        }
        result = ReportDataComputer().compute(merged)
        assert result.section_rag.get("cross_domain") == "red"


class TestValuationBridge:
    """Issue #116: Valuation exposure and impact calculation."""

    def test_empty_when_no_arr(self) -> None:
        """Should return empty dict when total ARR is 0."""
        result = ReportDataComputer._compute_valuation_bridge(0.0, 0.0, {})
        assert result == {}

    def test_exposure_calculation(self) -> None:
        """Exposure = total_arr - risk_adjusted_arr."""
        result = ReportDataComputer._compute_valuation_bridge(
            1_000_000.0,
            800_000.0,
            {},
        )
        assert result["total_exposure"] == pytest.approx(200_000.0)
        assert result["exposure_pct"] == pytest.approx(20.0)

    def test_valuation_multiples(self) -> None:
        """Valuation impact should be exposure * multiple for each scenario."""
        result = ReportDataComputer._compute_valuation_bridge(
            1_000_000.0,
            900_000.0,
            {},
        )
        exposure = 100_000.0
        assert result["valuation_impact"]["conservative"] == pytest.approx(exposure * 5.0)
        assert result["valuation_impact"]["base"] == pytest.approx(exposure * 8.0)
        assert result["valuation_impact"]["premium"] == pytest.approx(exposure * 12.0)

    def test_risk_categories_from_waterfall(self) -> None:
        """Risk categories should be extracted from waterfall amounts as a sorted list."""
        waterfall = {
            "change_of_control": {"amount": 50_000.0, "contracts": 2},
            "pricing_risk": {"amount": 30_000.0, "contracts": 1},
        }
        result = ReportDataComputer._compute_valuation_bridge(
            1_000_000.0,
            920_000.0,
            waterfall,
        )
        cats = result["risk_categories"]
        assert isinstance(cats, list)
        assert len(cats) == 2
        # Sorted by exposure descending
        assert cats[0]["category"] == "Change Of Control"
        assert cats[0]["exposure"] == 50_000.0
        assert cats[1]["category"] == "Pricing Risk"
        assert cats[1]["exposure"] == 30_000.0


class TestNewFieldsOnModel:
    """Verify new fields exist on ReportComputedData with correct defaults."""

    def test_liability_analysis_default(self) -> None:
        data = ReportComputedData()
        assert data.liability_analysis["total_liability_findings"] == 0
        assert data.liability_analysis["uncapped_count"] == 0

    def test_ip_risk_analysis_default(self) -> None:
        data = ReportComputedData()
        assert data.ip_risk_analysis["total_ip_findings"] == 0
        assert data.ip_risk_analysis["ip_ownership_gaps"] == 0

    def test_cross_domain_risks_default(self) -> None:
        data = ReportComputedData()
        assert data.cross_domain_risks == []

    def test_valuation_bridge_default(self) -> None:
        data = ReportComputedData()
        assert data.valuation_bridge == {}


class TestRagIndicators:
    """Verify new RAG indicators for liability, IP, cross-domain, valuation."""

    def test_liability_rag_red_on_uncapped(self) -> None:
        """Liability RAG should be red if uncapped count > 0."""
        merged: dict[str, Any] = {
            "a": {
                "subject": "A",
                "findings": [
                    _make_finding(title="Uncapped liability clause", agent="legal"),
                ],
                "gaps": [],
            }
        }
        result = ReportDataComputer().compute(merged)
        assert result.section_rag.get("liability") == "red"

    def test_ip_rag_amber_on_findings(self) -> None:
        """IP RAG should be amber when IP findings exist but gaps <= 3."""
        merged: dict[str, Any] = {
            "a": {
                "subject": "A",
                "findings": [
                    _make_finding(title="Patent review needed", agent="legal"),
                ],
                "gaps": [],
            }
        }
        result = ReportDataComputer().compute(merged)
        assert result.section_rag.get("ip_risk") == "amber"


class TestRendererKeyAlignment:
    """Verify computed_metrics output keys match what renderers actually read."""

    def test_liability_keys_match_renderer(self) -> None:
        """Liability analysis keys must match what LiabilityRenderer reads."""
        merged: dict[str, Any] = {
            "a": {
                "subject": "A",
                "findings": [
                    _make_finding(title="Insurance requirement gap", agent="legal"),
                    _make_finding(title="Uncapped liability in MSA", agent="legal"),
                ],
                "gaps": [],
            }
        }
        result = ReportDataComputer().compute(merged)
        la = result.liability_analysis
        # These are the exact keys the renderer reads (html_liability.py)
        assert "total_liability_findings" in la
        assert "insurance_count" in la
        assert "liability_cap_count" in la  # NOT "liability_caps"
        assert "uncapped_count" in la
        assert "indemnification_count" in la
        assert "findings" in la

    def test_ip_risk_keys_match_renderer(self) -> None:
        """IP risk keys must match what IPRiskRenderer reads."""
        merged: dict[str, Any] = {
            "a": {
                "subject": "A",
                "findings": [
                    _make_finding(title="Open source GPL dependency", agent="producttech"),
                ],
                "gaps": [],
            }
        }
        result = ReportDataComputer().compute(merged)
        ip = result.ip_risk_analysis
        assert "total_ip_findings" in ip
        assert "ip_ownership_gaps" in ip
        assert "open_source_count" in ip
        assert "license_risk_count" in ip  # NOT "license_risks"
        assert "findings" in ip

    def test_discount_keys_match_renderer(self) -> None:
        """Discount analysis keys must match what DiscountAnalysisRenderer reads."""
        merged: dict[str, Any] = {
            "a": {
                "subject": "A",
                "findings": [
                    _make_finding(title="15% discount below list price", agent="commercial"),
                ],
                "gaps": [],
            }
        }
        result = ReportDataComputer().compute(merged)
        da = result.discount_analysis
        assert "avg_discount_pct" in da  # NOT "avg_discount"
        assert "max_discount_pct" in da  # NOT "max_discount"
        assert "top_discounted" in da

    def test_timeline_cliff_risk_is_bool(self) -> None:
        """Timeline cliff_risk must be a bool, not a count."""
        merged: dict[str, Any] = {
            "a": {
                "subject": "A",
                "findings": [
                    _make_finding(title="Contract expires 2026-03-15", agent="legal"),
                ],
                "gaps": [],
            }
        }
        result = ReportDataComputer().compute(merged)
        ct = result.contract_timeline
        assert "cliff_risk" in ct
        assert isinstance(ct["cliff_risk"], bool)

    def test_entity_migration_risk_is_string(self) -> None:
        """Entity migration_risk_score must be a string label."""
        merged: dict[str, Any] = {
            "a": {
                "subject": "A",
                "findings": [
                    _make_finding(title="Legal entity migration required", agent="legal"),
                ],
                "gaps": [],
            }
        }
        result = ReportDataComputer().compute(merged)
        ed = result.entity_distribution
        assert "migration_risk_score" in ed
        assert isinstance(ed["migration_risk_score"], str)
        assert ed["migration_risk_score"] in ("critical", "high", "medium", "low")

    def test_valuation_bridge_risk_categories_is_list(self) -> None:
        """Valuation bridge risk_categories must be a list of dicts."""
        waterfall = {"change_of_control": {"amount": 50_000.0, "contracts": 2}}
        result = ReportDataComputer._compute_valuation_bridge(1_000_000.0, 950_000.0, waterfall)
        cats = result["risk_categories"]
        assert isinstance(cats, list)
        if cats:
            assert "category" in cats[0]
            assert "exposure" in cats[0]


class TestFmtCurrency:
    """Verify fmt_currency handles all edge cases."""

    def test_millions(self) -> None:
        from dd_agents.reporting.html_base import fmt_currency

        assert fmt_currency(5_000_000.0) == "$5.0M"

    def test_thousands(self) -> None:
        from dd_agents.reporting.html_base import fmt_currency

        assert fmt_currency(50_000.0) == "$50K"

    def test_small(self) -> None:
        from dd_agents.reporting.html_base import fmt_currency

        assert fmt_currency(500.0) == "$500"

    def test_zero(self) -> None:
        from dd_agents.reporting.html_base import fmt_currency

        assert fmt_currency(0.0) == "$0"

    def test_negative_millions(self) -> None:
        from dd_agents.reporting.html_base import fmt_currency

        assert fmt_currency(-2_000_000.0) == "-$2.0M"

    def test_negative_thousands(self) -> None:
        from dd_agents.reporting.html_base import fmt_currency

        assert fmt_currency(-5_000.0) == "-$5K"

    def test_negative_small(self) -> None:
        from dd_agents.reporting.html_base import fmt_currency

        assert fmt_currency(-99.0) == "-$99"
