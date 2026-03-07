"""Tests for Wave 3 features: 8 issues (#108, #119, #120, #131, #132, #138, #139, #144)."""

from __future__ import annotations

from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_computed_data(**overrides: Any) -> Any:
    """Build a minimal ReportComputedData-like mock."""
    from dd_agents.reporting.computed_metrics import ReportComputedData

    defaults: dict[str, Any] = {
        "total_findings": 0,
        "total_gaps": 0,
        "material_findings": [],
        "severity_counts": {"P0": 0, "P1": 0, "P2": 0, "P3": 0},
        "domain_findings_count": {},
        "domain_severity": {},
        "category_groups": {},
        "findings_by_category": {},
        "wolf_pack": [],
        "wolf_pack_p0": [],
        "all_findings": [],
        "noise_findings": [],
        "noise_count": 0,
        "data_quality_findings": [],
        "data_quality_count": 0,
        "gap_priority_counts": {},
        "gap_type_counts": {},
        "governance_avg": 0.0,
        "risk_label": "Low",
        "risk_score": 0.0,
        "display_names": {},
        "section_rag": {},
        "hhi": 0.0,
        "xref_total": 0,
        "xref_match_pct": 0.0,
        "xref_mismatch_count": 0,
        "saas_metrics": {},
        "revenue_by_customer": {},
        "total_contracted_arr": 0.0,
        "risk_adjusted_arr": 0.0,
        "revenue_data_coverage": 0.0,
        "risk_waterfall": {},
        "concentration_treemap": [],
        "provenance_stats": {},
        "discount_analysis": {},
        "renewal_analysis": {},
        "compliance_analysis": {},
        "entity_distribution": {},
        "contract_timeline": {},
        "liability_analysis": {},
        "ip_risk_analysis": {},
        "cross_domain_risks": [],
        "integration_playbook": {},
        "valuation_bridge": {},
        "clause_analysis": {},
        "key_employee_analysis": {},
        "tech_stack_analysis": {},
        "product_adoption": {},
        "language_distribution": {},
    }
    defaults.update(overrides)
    return ReportComputedData(**defaults)


def _make_finding(
    title: str = "Test Finding",
    severity: str = "P2",
    category: str = "change_of_control",
    agent: str = "legal",
    customer: str = "test_customer",
    description: str = "",
) -> dict[str, Any]:
    return {
        "title": title,
        "severity": severity,
        "category": category,
        "agent": agent,
        "_customer_safe_name": customer,
        "_customer": customer,
        "description": description,
    }


# ===========================================================================
# Issue #108: Board Presentation Mode, Print/Export & Accessibility
# ===========================================================================


class TestBoardPresentationMode:
    """Tests for #108: Board Presentation Mode."""

    def test_presentation_mode_css_exists(self) -> None:
        from dd_agents.reporting.html_base import render_css

        css = render_css()
        assert ".presentation-mode" in css

    def test_print_css_page_break_rules(self) -> None:
        from dd_agents.reporting.html_base import render_css

        css = render_css()
        assert "@media print" in css
        assert "page-break" in css

    def test_nav_bar_has_presentation_button(self) -> None:
        from dd_agents.reporting.html_base import render_nav_bar

        html = render_nav_bar()
        assert "presentation" in html.lower() or "Presentation" in html

    def test_js_has_presentation_toggle(self) -> None:
        from dd_agents.reporting.html_base import render_js

        js = render_js()
        assert "presentation" in js.lower()

    def test_aria_nav_label(self) -> None:
        from dd_agents.reporting.html_base import render_nav_bar

        html = render_nav_bar()
        assert "aria-label" in html
        assert "role='navigation'" in html or 'role="navigation"' in html

    def test_skip_link_present(self) -> None:
        from dd_agents.reporting.html_base import render_nav_bar

        html = render_nav_bar()
        assert "skip-link" in html


# ===========================================================================
# Issue #119: Contract Clause Library & Precedent Database
# ===========================================================================


class TestClauseLibrary:
    """Tests for #119: Clause Library."""

    def test_library_has_entries(self) -> None:
        from dd_agents.reporting.clause_library import CLAUSE_LIBRARY

        assert len(CLAUSE_LIBRARY) == 18

    def test_classify_finding_coc(self) -> None:
        from dd_agents.reporting.clause_library import classify_finding

        f = _make_finding(category="change_of_control")
        assert classify_finding(f) == "change_of_control"

    def test_classify_finding_by_keyword(self) -> None:
        from dd_agents.reporting.clause_library import classify_finding

        f = _make_finding(category="other", title="Termination for Convenience clause found")
        assert classify_finding(f) == "termination_for_convenience"

    def test_classify_finding_unknown_returns_none(self) -> None:
        from dd_agents.reporting.clause_library import classify_finding

        f = _make_finding(category="xyz_unknown", title="Some unrelated finding", description="No keywords here")
        assert classify_finding(f) is None

    def test_get_clause_context_returns_market_norm(self) -> None:
        from dd_agents.reporting.clause_library import CLAUSE_LIBRARY, get_clause_context

        for key in CLAUSE_LIBRARY:
            ctx = get_clause_context(key)
            assert ctx["market_norm"], f"Empty market_norm for {key}"
            assert ctx["risk_implications"], f"Empty risk_implications for {key}"

    def test_get_clause_context_unknown_raises(self) -> None:
        from dd_agents.reporting.clause_library import get_clause_context

        with pytest.raises(KeyError):
            get_clause_context("nonexistent_clause")

    def test_list_clause_types(self) -> None:
        from dd_agents.reporting.clause_library import list_clause_types

        types = list_clause_types()
        assert "change_of_control" in types
        assert "liability_cap" in types
        assert len(types) == 18

    def test_clause_library_renderer_empty(self) -> None:
        from dd_agents.reporting.html_clause_library import ClauseLibraryRenderer

        data = _make_computed_data(clause_analysis={})
        r = ClauseLibraryRenderer(data, {}, {})
        assert r.render() == ""

    def test_clause_library_renderer_renders_section(self) -> None:
        from dd_agents.reporting.html_clause_library import ClauseLibraryRenderer

        clause_analysis = {
            "clause_counts": {"change_of_control": 3, "liability_cap": 1},
            "clause_findings": {
                "change_of_control": [
                    _make_finding(title="CoC clause requires consent"),
                    _make_finding(title="CoC auto-termination"),
                    _make_finding(title="CoC notification only"),
                ],
                "liability_cap": [_make_finding(title="Uncapped liability", category="liability")],
            },
            "total_classified": 4,
        }
        data = _make_computed_data(clause_analysis=clause_analysis)
        r = ClauseLibraryRenderer(data, {}, {})
        html = r.render()
        assert "sec-clause-library" in html
        assert "Market Norm" in html
        assert "Risk Implications" in html

    def test_clause_library_renderer_xss(self) -> None:
        from dd_agents.reporting.html_clause_library import ClauseLibraryRenderer

        clause_analysis = {
            "clause_counts": {"change_of_control": 1},
            "clause_findings": {
                "change_of_control": [_make_finding(title="<script>alert(1)</script>")],
            },
            "total_classified": 1,
        }
        data = _make_computed_data(clause_analysis=clause_analysis)
        r = ClauseLibraryRenderer(data, {}, {})
        html = r.render()
        assert "<script>alert(1)</script>" not in html

    def test_compute_clause_analysis(self) -> None:
        from dd_agents.reporting.html_clause_library import ClauseLibraryRenderer

        findings = [
            _make_finding(category="change_of_control"),
            _make_finding(title="liability cap is low", category="liability"),
            _make_finding(category="xyz_unknown", title="Unknown finding"),
        ]
        result = ClauseLibraryRenderer.compute_clause_analysis(findings)
        assert result["total_classified"] == 2
        assert "change_of_control" in result["clause_counts"]


# ===========================================================================
# Issue #120: Pipeline Progress Dashboard
# ===========================================================================


class TestProgressDashboard:
    """Tests for #120: Pipeline Progress Dashboard."""

    def test_tracker_init(self) -> None:
        from dd_agents.orchestrator.progress import PipelineProgressTracker

        tracker = PipelineProgressTracker()
        assert tracker.current_step == 0
        assert tracker.completed_steps == 0
        assert tracker.total_steps == 35

    def test_start_complete_step(self) -> None:
        from dd_agents.orchestrator.progress import PipelineProgressTracker

        tracker = PipelineProgressTracker()
        tracker.start_step(1, "inventory")
        assert tracker.current_step == 1
        assert tracker.current_step_name == "inventory"
        tracker.complete_step()
        assert tracker.completed_steps == 1

    def test_estimate_eta_no_history(self) -> None:
        from dd_agents.orchestrator.progress import PipelineProgressTracker

        tracker = PipelineProgressTracker()
        assert tracker.estimate_remaining_ms() == 0.0

    def test_estimate_eta_with_history(self) -> None:
        from dd_agents.orchestrator.progress import PipelineProgressTracker

        tracker = PipelineProgressTracker(total_steps=10)
        # Simulate completing 5 steps at ~100ms each
        tracker._step_durations = [100.0, 100.0, 100.0, 100.0, 100.0]
        tracker.completed_steps = 5
        eta = tracker.estimate_remaining_ms()
        assert eta == pytest.approx(500.0)

    def test_agent_progress_update(self) -> None:
        from dd_agents.orchestrator.progress import PipelineProgressTracker

        tracker = PipelineProgressTracker()
        tracker.update_agent_progress("legal", 5, 20, "customer_a")
        snap = tracker.snapshot
        assert snap["agent_progress"]["legal"]["customers_processed"] == 5
        assert snap["agent_progress"]["legal"]["pct"] == pytest.approx(25.0)

    def test_finding_count_update(self) -> None:
        from dd_agents.orchestrator.progress import PipelineProgressTracker

        tracker = PipelineProgressTracker()
        tracker.update_finding_counts({"P0": 2, "P1": 5})
        snap = tracker.snapshot
        assert snap["finding_counts"]["P0"] == 2
        assert snap["finding_counts"]["P1"] == 5

    def test_snapshot_structure(self) -> None:
        from dd_agents.orchestrator.progress import PipelineProgressTracker

        tracker = PipelineProgressTracker()
        tracker.start_step(3, "extraction")
        snap = tracker.snapshot
        assert "current_step" in snap
        assert "total_steps" in snap
        assert "elapsed_ms" in snap
        assert "estimated_remaining_ms" in snap
        assert "finding_counts" in snap
        assert "agent_progress" in snap
        assert snap["current_step"] == 3
        assert snap["current_step_name"] == "extraction"


# ===========================================================================
# Issue #131: Key Employee & Organizational Risk Analysis
# ===========================================================================


class TestKeyEmployee:
    """Tests for #131: Key Employee & Organizational Risk."""

    def test_valid_categories_include_new(self) -> None:
        from dd_agents.tools.validate_finding import VALID_CATEGORIES

        assert "employment_agreement" in VALID_CATEGORIES
        assert "retention_risk" in VALID_CATEGORIES
        assert "non_compete_enforcement" in VALID_CATEGORIES
        assert "organizational_risk" in VALID_CATEGORIES

    def test_focus_areas_include_key_person(self) -> None:
        from dd_agents.agents.specialists import LEGAL_FOCUS_AREAS

        assert "key_person_dependency" in LEGAL_FOCUS_AREAS
        assert "employment_agreements" in LEGAL_FOCUS_AREAS
        assert "retention_risk" in LEGAL_FOCUS_AREAS

    def test_renderer_empty(self) -> None:
        from dd_agents.reporting.html_key_employee import KeyEmployeeRenderer

        data = _make_computed_data(key_employee_analysis={})
        r = KeyEmployeeRenderer(data, {}, {})
        assert r.render() == ""

    def test_renderer_renders_section(self) -> None:
        from dd_agents.reporting.html_key_employee import KeyEmployeeRenderer

        analysis = {
            "total_findings": 3,
            "retention_risk_count": 1,
            "noncompete_gap_count": 1,
            "findings": [
                _make_finding(title="CTO has no deputy", category="organizational_risk", severity="P1"),
                _make_finding(title="Vesting cliff risk", category="retention_risk"),
                _make_finding(title="Missing non-compete", category="non_compete_enforcement"),
            ],
        }
        data = _make_computed_data(key_employee_analysis=analysis)
        r = KeyEmployeeRenderer(data, {}, {})
        html = r.render()
        assert "sec-key-employee" in html
        assert "Key Employee" in html

    def test_renderer_xss(self) -> None:
        from dd_agents.reporting.html_key_employee import KeyEmployeeRenderer

        analysis = {
            "total_findings": 1,
            "retention_risk_count": 0,
            "noncompete_gap_count": 0,
            "findings": [_make_finding(title="<script>alert(1)</script>")],
        }
        data = _make_computed_data(key_employee_analysis=analysis)
        r = KeyEmployeeRenderer(data, {}, {})
        html = r.render()
        assert "<script>alert(1)</script>" not in html

    def test_renderer_alert_on_p0(self) -> None:
        from dd_agents.reporting.html_key_employee import KeyEmployeeRenderer

        analysis = {
            "total_findings": 1,
            "retention_risk_count": 0,
            "noncompete_gap_count": 0,
            "findings": [_make_finding(title="Critical key person risk", severity="P0")],
        }
        data = _make_computed_data(key_employee_analysis=analysis)
        r = KeyEmployeeRenderer(data, {}, {})
        html = r.render()
        assert "alert-critical" in html or "Critical Key-Person" in html


# ===========================================================================
# Issue #132: Technology Stack Assessment & Technical Debt
# ===========================================================================


class TestTechStack:
    """Tests for #132: Technology Stack Assessment."""

    def test_valid_categories_include_new(self) -> None:
        from dd_agents.tools.validate_finding import VALID_CATEGORIES

        assert "technical_debt" in VALID_CATEGORIES
        assert "security_posture" in VALID_CATEGORIES
        assert "scalability" in VALID_CATEGORIES
        assert "migration_complexity" in VALID_CATEGORIES
        assert "architecture_risk" in VALID_CATEGORIES

    def test_focus_areas_include_tech_debt(self) -> None:
        from dd_agents.agents.specialists import PRODUCTTECH_FOCUS_AREAS

        assert "technical_debt" in PRODUCTTECH_FOCUS_AREAS
        assert "security_posture" in PRODUCTTECH_FOCUS_AREAS
        assert "scalability" in PRODUCTTECH_FOCUS_AREAS

    def test_renderer_empty(self) -> None:
        from dd_agents.reporting.html_tech_stack import TechStackRenderer

        data = _make_computed_data(tech_stack_analysis={})
        r = TechStackRenderer(data, {}, {})
        assert r.render() == ""

    def test_renderer_renders_section(self) -> None:
        from dd_agents.reporting.html_tech_stack import TechStackRenderer

        analysis = {
            "total_findings": 4,
            "security_gap_count": 2,
            "tech_debt_count": 1,
            "migration_risk_count": 1,
            "findings": [
                _make_finding(title="SOC2 certification expired", category="security_posture", severity="P1"),
                _make_finding(title="Legacy API deprecated", category="technical_debt"),
                _make_finding(title="Vendor lock-in risk", category="migration_complexity"),
                _make_finding(title="Missing pen test", category="security_posture"),
            ],
        }
        data = _make_computed_data(tech_stack_analysis=analysis)
        r = TechStackRenderer(data, {}, {})
        html = r.render()
        assert "sec-tech-stack" in html
        assert "Technology Stack" in html

    def test_renderer_xss(self) -> None:
        from dd_agents.reporting.html_tech_stack import TechStackRenderer

        analysis = {
            "total_findings": 1,
            "security_gap_count": 0,
            "tech_debt_count": 0,
            "migration_risk_count": 0,
            "findings": [_make_finding(title="<script>alert(1)</script>")],
        }
        data = _make_computed_data(tech_stack_analysis=analysis)
        r = TechStackRenderer(data, {}, {})
        html = r.render()
        assert "<script>alert(1)</script>" not in html


# ===========================================================================
# Issue #138: Product Adoption Matrix & Platform Dependency
# ===========================================================================


class TestProductAdoption:
    """Tests for #138: Product Adoption Matrix."""

    def test_renderer_empty(self) -> None:
        from dd_agents.reporting.html_product_adoption import ProductAdoptionRenderer

        data = _make_computed_data(product_adoption={})
        r = ProductAdoptionRenderer(data, {}, {})
        assert r.render() == ""

    def test_renderer_no_products(self) -> None:
        from dd_agents.reporting.html_product_adoption import ProductAdoptionRenderer

        data = _make_computed_data(product_adoption={"products": [], "matrix": {}})
        r = ProductAdoptionRenderer(data, {}, {})
        assert r.render() == ""

    def test_renderer_renders_matrix(self) -> None:
        from dd_agents.reporting.html_product_adoption import ProductAdoptionRenderer

        adoption = {
            "products": ["Platform A", "Platform B"],
            "matrix": {
                "customer_1": ["Platform A", "Platform B"],
                "customer_2": ["Platform A"],
            },
        }
        data = _make_computed_data(
            product_adoption=adoption,
            display_names={"customer_1": "Customer One", "customer_2": "Customer Two"},
        )
        r = ProductAdoptionRenderer(data, {}, {})
        html = r.render()
        assert "sec-product-adoption" in html
        assert "Platform A" in html
        assert "&#10003;" in html  # checkmark
        assert "Product Adoption" in html

    def test_renderer_xss(self) -> None:
        from dd_agents.reporting.html_product_adoption import ProductAdoptionRenderer

        adoption = {
            "products": ["<script>alert(1)</script>"],
            "matrix": {"evil_customer": ["<script>alert(1)</script>"]},
        }
        data = _make_computed_data(product_adoption=adoption)
        r = ProductAdoptionRenderer(data, {}, {})
        html = r.render()
        assert "<script>alert(1)</script>" not in html

    def test_single_product_risk_alert(self) -> None:
        from dd_agents.reporting.html_product_adoption import ProductAdoptionRenderer

        adoption = {
            "products": ["Platform A", "Platform B"],
            "matrix": {
                "c1": ["Platform A"],
                "c2": ["Platform A"],
                "c3": ["Platform A"],
                "c4": ["Platform A"],
                "c5": ["Platform A", "Platform B"],
            },
        }
        data = _make_computed_data(product_adoption=adoption)
        r = ProductAdoptionRenderer(data, {}, {})
        html = r.render()
        assert "Single-Product" in html


# ===========================================================================
# Issue #139: Web Research Integration
# ===========================================================================


class TestWebResearch:
    """Tests for #139: Web Research Integration."""

    def test_judge_config_has_web_research(self) -> None:
        from dd_agents.models.config import JudgeConfig

        config = JudgeConfig()
        assert hasattr(config, "web_research_enabled")
        assert config.web_research_enabled is False

    def test_web_research_disabled_by_default(self) -> None:
        from dd_agents.models.config import DealConfig

        dc = DealConfig(
            config_version="1.0.0",
            buyer={"name": "Buyer"},
            target={"name": "Target"},
            deal={"type": "acquisition", "focus_areas": ["legal"]},
        )
        assert dc.judge.web_research_enabled is False

    def test_web_research_tool_schema(self) -> None:
        from dd_agents.tools.web_research import web_research_tool_schema

        schema = web_research_tool_schema()
        assert schema["name"] == "web_research"
        assert "input_schema" in schema
        assert "query" in schema["input_schema"]["properties"]

    def test_format_web_research_result(self) -> None:
        from dd_agents.tools.web_research import format_web_research_result

        result = format_web_research_result("Is Company X SOC2 certified?", url="https://example.com")
        assert result["source_type"] == "web_research"
        assert result["confidence"] == "low"
        assert result["access_date"]  # Non-empty

    def test_format_verified_result(self) -> None:
        from dd_agents.tools.web_research import format_web_research_result

        result = format_web_research_result("test query", verified=True)
        assert result["confidence"] == "medium"
        assert result["verified_against_data_room"] is True


# ===========================================================================
# Issue #144: Multi-Language Document Support
# ===========================================================================


class TestMultiLanguage:
    """Tests for #144: Multi-Language Document Support."""

    def test_detect_english(self) -> None:
        from dd_agents.extraction.language_detect import detect_language

        text = "The parties agree that this agreement shall be governed by the laws of the State of New York."
        assert detect_language(text) == "en"

    def test_detect_german(self) -> None:
        from dd_agents.extraction.language_detect import detect_language

        text = (
            "Die Parteien vereinbaren, dass dieser Vertrag den Gesetzen "
            "der Bundesrepublik Deutschland unterliegt und ausgelegt wird."
        )
        assert detect_language(text) == "de"

    def test_detect_french(self) -> None:
        from dd_agents.extraction.language_detect import detect_language

        text = (
            "Les parties conviennent que le présent contrat est régi "
            "par les lois de la République française et interprété."
        )
        assert detect_language(text) == "fr"

    def test_detect_spanish(self) -> None:
        from dd_agents.extraction.language_detect import detect_language

        text = (
            "Las partes acuerdan que el presente contrato se regirá "
            "por las leyes del Reino de España y se interpretará."
        )
        assert detect_language(text) == "es"

    def test_detect_short_text_unknown(self) -> None:
        from dd_agents.extraction.language_detect import detect_language

        assert detect_language("Hello") == "unknown"

    def test_detect_japanese(self) -> None:
        from dd_agents.extraction.language_detect import detect_language

        text = (
            "本契約は日本法に準拠し、これに従って解釈されるものとする。"
            "当事者は本契約に関する紛争について東京地方裁判所を合意管轄裁判所とする。"
        )
        assert detect_language(text) == "ja"

    def test_detect_chinese(self) -> None:
        from dd_agents.extraction.language_detect import detect_language

        text = (
            "本合同受中华人民共和国法律管辖并按其解释。"
            "各方同意就本合同引起的争议提交北京仲裁委员会仲裁。"
            "本合同的签署和执行均应适用中华人民共和国的法律法规。"
        )
        assert detect_language(text) == "zh"

    def test_language_names(self) -> None:
        from dd_agents.extraction.language_detect import LANGUAGE_NAMES

        assert LANGUAGE_NAMES["en"] == "English"
        assert LANGUAGE_NAMES["de"] == "German"
        assert len(LANGUAGE_NAMES) == 10

    def test_citation_has_source_language(self) -> None:
        from dd_agents.models.finding import Citation

        cit = Citation(source_type="file", source_path="/test.pdf", source_language="de")
        assert cit.source_language == "de"

    def test_citation_source_language_default(self) -> None:
        from dd_agents.models.finding import Citation

        cit = Citation(source_type="file", source_path="/test.pdf")
        assert cit.source_language is None

    def test_extraction_quality_has_language(self) -> None:
        from dd_agents.models.inventory import ExtractionQualityEntry

        entry = ExtractionQualityEntry(file_path="/test.pdf", method="pymupdf", source_language="fr")
        assert entry.source_language == "fr"

    def test_extraction_quality_language_default(self) -> None:
        from dd_agents.models.inventory import ExtractionQualityEntry

        entry = ExtractionQualityEntry(file_path="/test.pdf", method="pymupdf")
        assert entry.source_language == "en"


# ===========================================================================
# Issue #131/#132: Prompt Builder Focus Extensions
# ===========================================================================


class TestPromptBuilderExtensions:
    """Tests for agent prompt extensions in #131 and #132."""

    def test_legal_prompt_includes_key_employee(self) -> None:
        from dd_agents.agents.prompt_builder import SPECIALIST_FOCUS, AgentType

        legal_focus = SPECIALIST_FOCUS[AgentType.LEGAL]
        assert (
            "KEY EMPLOYEE" in legal_focus or "key person" in legal_focus.lower() or "retention" in legal_focus.lower()
        )

    def test_producttech_prompt_includes_tech_stack(self) -> None:
        from dd_agents.agents.prompt_builder import SPECIALIST_FOCUS, AgentType

        pt_focus = SPECIALIST_FOCUS[AgentType.PRODUCTTECH]
        assert "TECHNOLOGY STACK" in pt_focus or "technical debt" in pt_focus.lower()


# ===========================================================================
# Computed metrics new fields
# ===========================================================================


class TestComputedMetricsNewFields:
    """Tests for new ReportComputedData fields."""

    def test_clause_analysis_field_exists(self) -> None:
        data = _make_computed_data()
        assert hasattr(data, "clause_analysis")

    def test_key_employee_analysis_field_exists(self) -> None:
        data = _make_computed_data()
        assert hasattr(data, "key_employee_analysis")

    def test_tech_stack_analysis_field_exists(self) -> None:
        data = _make_computed_data()
        assert hasattr(data, "tech_stack_analysis")

    def test_product_adoption_field_exists(self) -> None:
        data = _make_computed_data()
        assert hasattr(data, "product_adoption")

    def test_language_distribution_field_exists(self) -> None:
        data = _make_computed_data()
        assert hasattr(data, "language_distribution")


# ===========================================================================
# HTML report integration
# ===========================================================================


class TestHTMLReportIntegration:
    """Tests for renderers being wired into the HTML report."""

    def test_clause_library_renderer_in_report(self) -> None:
        from dd_agents.reporting import html as report_module

        assert hasattr(report_module, "_clause_lib_renderer")

    def test_key_employee_renderer_in_report(self) -> None:
        from dd_agents.reporting import html as report_module

        assert hasattr(report_module, "_key_employee_renderer")

    def test_tech_stack_renderer_in_report(self) -> None:
        from dd_agents.reporting import html as report_module

        assert hasattr(report_module, "_tech_stack_renderer")

    def test_product_adoption_renderer_in_report(self) -> None:
        from dd_agents.reporting import html as report_module

        assert hasattr(report_module, "_product_adoption_renderer")

    def test_nav_has_new_sections(self) -> None:
        from dd_agents.reporting.html_base import render_nav_bar

        html = render_nav_bar()
        assert "sec-clause-library" in html
        assert "sec-key-employee" in html
        assert "sec-tech-stack" in html
        assert "sec-product-adoption" in html


# ===========================================================================
# Audit round: _compute_* methods direct tests
# ===========================================================================


class TestComputeKeyEmployeeAnalysis:
    """Direct tests for _compute_key_employee_analysis."""

    def test_empty_findings_returns_empty(self) -> None:
        from dd_agents.reporting.computed_metrics import ReportDataComputer

        result = ReportDataComputer._compute_key_employee_analysis([])
        assert result == {}

    def test_matches_key_person(self) -> None:
        from dd_agents.reporting.computed_metrics import ReportDataComputer

        findings = [
            _make_finding(title="Key person dependency on CTO"),
            _make_finding(title="Revenue growth steady"),
        ]
        result = ReportDataComputer._compute_key_employee_analysis(findings)
        assert result["total_findings"] == 1
        assert result["retention_risk_count"] == 0
        assert result["noncompete_gap_count"] == 0

    def test_retention_and_noncompete_overlap(self) -> None:
        from dd_agents.reporting.computed_metrics import ReportDataComputer

        findings = [
            _make_finding(title="Key employee retention risk with non-compete gap"),
        ]
        result = ReportDataComputer._compute_key_employee_analysis(findings)
        assert result["total_findings"] == 1
        assert result["retention_risk_count"] == 1
        assert result["noncompete_gap_count"] == 1

    def test_no_matches_returns_empty(self) -> None:
        from dd_agents.reporting.computed_metrics import ReportDataComputer

        findings = [_make_finding(title="Standard revenue clause")]
        result = ReportDataComputer._compute_key_employee_analysis(findings)
        assert result == {}


class TestComputeTechStackAnalysis:
    """Direct tests for _compute_tech_stack_analysis."""

    def test_empty_findings_returns_empty(self) -> None:
        from dd_agents.reporting.computed_metrics import ReportDataComputer

        result = ReportDataComputer._compute_tech_stack_analysis([])
        assert result == {}

    def test_security_subcategory(self) -> None:
        from dd_agents.reporting.computed_metrics import ReportDataComputer

        findings = [_make_finding(title="SOC2 compliance gap in security posture")]
        result = ReportDataComputer._compute_tech_stack_analysis(findings)
        assert result["total_findings"] == 1
        assert result["security_gap_count"] == 1
        assert result["findings"][0]["_tech_subcategory"] == "Security Posture"

    def test_debt_subcategory(self) -> None:
        from dd_agents.reporting.computed_metrics import ReportDataComputer

        findings = [_make_finding(title="Legacy system with technical debt")]
        result = ReportDataComputer._compute_tech_stack_analysis(findings)
        assert result["total_findings"] == 1
        assert result["tech_debt_count"] == 1
        assert result["findings"][0]["_tech_subcategory"] == "Technical Debt"

    def test_migration_subcategory(self) -> None:
        from dd_agents.reporting.computed_metrics import ReportDataComputer

        findings = [_make_finding(title="Vendor lock-in with migration complexity")]
        result = ReportDataComputer._compute_tech_stack_analysis(findings)
        assert result["total_findings"] == 1
        assert result["migration_risk_count"] == 1
        assert result["findings"][0]["_tech_subcategory"] == "Migration Complexity"

    def test_default_subcategory(self) -> None:
        from dd_agents.reporting.computed_metrics import ReportDataComputer

        findings = [_make_finding(title="Technology stack uses deprecated framework")]
        result = ReportDataComputer._compute_tech_stack_analysis(findings)
        assert result["total_findings"] == 1
        # deprecated matches debt_kw, so it's Technical Debt
        assert result["findings"][0]["_tech_subcategory"] == "Technical Debt"

    def test_no_tech_findings_returns_empty(self) -> None:
        from dd_agents.reporting.computed_metrics import ReportDataComputer

        findings = [_make_finding(title="Revenue recognition issue")]
        result = ReportDataComputer._compute_tech_stack_analysis(findings)
        assert result == {}


class TestComputeProductAdoption:
    """Direct tests for _compute_product_adoption."""

    def test_empty_findings_returns_empty(self) -> None:
        from dd_agents.reporting.computed_metrics import ReportDataComputer

        result = ReportDataComputer._compute_product_adoption([], {})
        assert result == {}

    def test_extracts_products_from_findings(self) -> None:
        from dd_agents.reporting.computed_metrics import ReportDataComputer

        findings = [
            _make_finding(
                title="Platform license — Enterprise Suite",
                category="product_scope",
                customer="acme",
            ),
            _make_finding(
                title="Module: Analytics Dashboard",
                category="product_scope",
                customer="acme",
            ),
            _make_finding(
                title="Platform — Core API",
                category="product",
                customer="beta_corp",
            ),
        ]
        result = ReportDataComputer._compute_product_adoption(findings, {})
        assert "products" in result
        assert "matrix" in result
        assert len(result["products"]) == 3
        assert "acme" in result["matrix"]
        assert len(result["matrix"]["acme"]) == 2

    def test_no_product_findings_returns_empty(self) -> None:
        from dd_agents.reporting.computed_metrics import ReportDataComputer

        findings = [_make_finding(title="Revenue clause", category="revenue")]
        result = ReportDataComputer._compute_product_adoption(findings, {})
        assert result == {}

    def test_missing_csn_skipped(self) -> None:
        from dd_agents.reporting.computed_metrics import ReportDataComputer

        findings = [
            _make_finding(title="Platform scope", category="product_scope", customer=""),
        ]
        result = ReportDataComputer._compute_product_adoption(findings, {})
        assert result == {}


class TestComputeLanguageDistribution:
    """Direct tests for _compute_language_distribution."""

    def test_empty_returns_empty(self) -> None:
        from dd_agents.reporting.computed_metrics import ReportDataComputer

        result = ReportDataComputer._compute_language_distribution([])
        assert result == {}

    def test_aggregates_from_citations(self) -> None:
        from dd_agents.reporting.computed_metrics import ReportDataComputer

        findings = [
            {
                "title": "Finding 1",
                "citations": [
                    {"source_language": "en", "source_path": "/a.pdf"},
                    {"source_language": "de", "source_path": "/b.pdf"},
                ],
            },
            {
                "title": "Finding 2",
                "citations": [{"source_language": "en", "source_path": "/c.pdf"}],
            },
        ]
        result = ReportDataComputer._compute_language_distribution(findings)
        assert result == {"en": 2, "de": 1}

    def test_skips_missing_language(self) -> None:
        from dd_agents.reporting.computed_metrics import ReportDataComputer

        findings = [
            {"title": "Finding", "citations": [{"source_path": "/a.pdf"}]},
        ]
        result = ReportDataComputer._compute_language_distribution(findings)
        assert result == {}

    def test_skips_non_list_citations(self) -> None:
        from dd_agents.reporting.computed_metrics import ReportDataComputer

        findings = [{"title": "Finding", "citations": "not a list"}]
        result = ReportDataComputer._compute_language_distribution(findings)
        assert result == {}


class TestClauseLibraryEdgeCases:
    """Edge case tests for clause library classification."""

    def test_classify_with_missing_fields(self) -> None:
        from dd_agents.reporting.clause_library import classify_finding

        result = classify_finding({})
        assert result is None

    def test_classify_category_normalization(self) -> None:
        from dd_agents.reporting.clause_library import classify_finding

        f = _make_finding(category="change of control")
        # Spaces replaced with underscores → direct match
        assert classify_finding(f) == "change_of_control"

    def test_classify_returns_first_keyword_match(self) -> None:
        from dd_agents.reporting.clause_library import classify_finding

        # "liability cap" keyword matches liability_cap
        f = _make_finding(
            category="custom",
            title="liability cap with indemnification clause",
        )
        result = classify_finding(f)
        assert result == "liability_cap"


class TestWebResearchEdgeCases:
    """Additional web research tests."""

    def test_unverified_result_low_confidence(self) -> None:
        from dd_agents.tools.web_research import format_web_research_result

        result = format_web_research_result("query", verified=False)
        assert result["confidence"] == "low"
        assert result["verified_against_data_room"] is False

    def test_result_has_access_date_format(self) -> None:
        from dd_agents.tools.web_research import format_web_research_result

        result = format_web_research_result("query")
        # ISO date format YYYY-MM-DD
        assert len(result["access_date"]) == 10
        assert result["access_date"][4] == "-"


class TestBadgeCSSClass:
    """Verify .badge CSS class is defined."""

    def test_badge_class_in_css(self) -> None:
        from dd_agents.reporting.html_base import render_css

        css = render_css()
        assert ".badge" in css
