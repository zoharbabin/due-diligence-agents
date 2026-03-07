"""Tests for Configurable Report Templates & White-Label Branding (Issue #123)."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003

import pytest

from dd_agents.reporting.templates import (
    BUILTIN_TEMPLATES,
    ReportBranding,
    ReportSections,
    ReportTemplate,
    TemplateLibrary,
    generate_branding_css,
    should_include_section,
)


class TestReportBranding:
    """Test branding configuration."""

    def test_defaults(self) -> None:
        branding = ReportBranding()
        assert branding.primary_color == "#1a365d"
        assert branding.accent_color == "#e53e3e"
        assert branding.confidential_label == "CONFIDENTIAL"

    def test_custom_branding(self) -> None:
        branding = ReportBranding(
            firm_name="Advisory Co",
            primary_color="#003366",
            footer_text="Confidential -- Prepared by Advisory Co",
        )
        assert branding.firm_name == "Advisory Co"
        assert branding.footer_text == "Confidential -- Prepared by Advisory Co"


class TestReportSections:
    """Test section include/exclude configuration."""

    def test_defaults(self) -> None:
        sections = ReportSections()
        assert sections.include == []
        assert sections.exclude == []
        assert sections.detail_level == "standard"

    def test_include_filter(self) -> None:
        sections = ReportSections(include=["executive_summary", "dashboard"])
        assert should_include_section("executive_summary", sections) is True
        assert should_include_section("entity_detail", sections) is False

    def test_exclude_filter(self) -> None:
        sections = ReportSections(exclude=["entity_detail", "data_quality"])
        assert should_include_section("executive_summary", sections) is True
        assert should_include_section("entity_detail", sections) is False

    def test_include_and_exclude(self) -> None:
        sections = ReportSections(
            include=["executive_summary", "dashboard", "entity_detail"],
            exclude=["entity_detail"],
        )
        assert should_include_section("executive_summary", sections) is True
        assert should_include_section("entity_detail", sections) is False
        assert should_include_section("methodology", sections) is False

    def test_empty_filters_include_all(self) -> None:
        sections = ReportSections()
        assert should_include_section("anything", sections) is True


class TestBrandingCSS:
    """Test CSS generation from branding config."""

    def test_generates_css_variables(self) -> None:
        branding = ReportBranding(primary_color="#003366", accent_color="#ff0000")
        css = generate_branding_css(branding)
        assert "--brand-primary: #003366" in css
        assert "--brand-accent: #ff0000" in css

    def test_custom_font(self) -> None:
        branding = ReportBranding(font_family="Inter")
        css = generate_branding_css(branding)
        assert "--brand-font: Inter" in css
        assert "font-family: var(--brand-font)" in css

    def test_default_branding_generates_css(self) -> None:
        branding = ReportBranding()
        css = generate_branding_css(branding)
        assert ":root {" in css
        assert "--brand-primary" in css


class TestBuiltinTemplates:
    """Test pre-built template library."""

    def test_all_builtin_templates_exist(self) -> None:
        expected = {"full_report", "board_summary", "legal_deep_dive", "financial_analysis", "technical_assessment"}
        assert set(BUILTIN_TEMPLATES.keys()) == expected

    def test_full_report_template(self) -> None:
        tpl = BUILTIN_TEMPLATES["full_report"]
        assert tpl.name == "Full DD Report"
        assert tpl.sections.detail_level == "detailed"
        assert tpl.sections.include == []  # All sections

    def test_board_summary_template(self) -> None:
        tpl = BUILTIN_TEMPLATES["board_summary"]
        assert tpl.sections.detail_level == "executive"
        assert "executive_summary" in tpl.sections.include
        assert "recommendations" in tpl.sections.include
        assert len(tpl.sections.include) == 8

    def test_legal_deep_dive_template(self) -> None:
        tpl = BUILTIN_TEMPLATES["legal_deep_dive"]
        assert "coc_analysis" in tpl.sections.include
        assert "ip_risk" in tpl.sections.include

    def test_financial_analysis_template(self) -> None:
        tpl = BUILTIN_TEMPLATES["financial_analysis"]
        assert "financial_impact" in tpl.sections.include
        assert "saas_metrics" in tpl.sections.include

    def test_technical_assessment_template(self) -> None:
        tpl = BUILTIN_TEMPLATES["technical_assessment"]
        assert "tech_stack" in tpl.sections.include


class TestTemplateLibrary:
    """Test template library management."""

    @pytest.fixture()
    def library(self, tmp_path: Path) -> TemplateLibrary:
        return TemplateLibrary(templates_dir=tmp_path / "templates")

    def test_list_builtin_templates(self, library: TemplateLibrary) -> None:
        templates = library.list_templates()
        assert len(templates) >= 5
        ids = {t.id for t in templates}
        assert "full_report" in ids
        assert "board_summary" in ids

    def test_get_builtin_template(self, library: TemplateLibrary) -> None:
        tpl = library.get_template("full_report")
        assert tpl is not None
        assert tpl.name == "Full DD Report"

    def test_get_nonexistent_template(self, library: TemplateLibrary) -> None:
        assert library.get_template("nonexistent") is None

    def test_save_custom_template(self, library: TemplateLibrary) -> None:
        custom = ReportTemplate(
            id="my_template",
            name="My Custom Template",
            description="Custom for our firm",
            branding=ReportBranding(firm_name="Our Firm"),
            sections=ReportSections(include=["executive_summary"]),
        )
        path = library.save_template(custom)
        assert path is not None
        assert path.exists()

        # Verify it's retrievable
        retrieved = library.get_template("my_template")
        assert retrieved is not None
        assert retrieved.name == "My Custom Template"

    def test_delete_custom_template(self, library: TemplateLibrary) -> None:
        custom = ReportTemplate(id="temp", name="Temporary")
        library.save_template(custom)
        assert library.delete_template("temp") is True
        assert library.get_template("temp") is None

    def test_cannot_delete_builtin(self, library: TemplateLibrary) -> None:
        assert library.delete_template("full_report") is False

    def test_custom_overrides_builtin(self, library: TemplateLibrary) -> None:
        custom = ReportTemplate(id="full_report", name="Our Full Report Override")
        library.save_template(custom)
        tpl = library.get_template("full_report")
        assert tpl is not None
        assert tpl.name == "Our Full Report Override"

    def test_load_templates_from_dir(self, tmp_path: Path) -> None:
        tpl_dir = tmp_path / "templates"
        tpl_dir.mkdir()
        tpl = ReportTemplate(id="preloaded", name="Preloaded Template")
        import json

        (tpl_dir / "preloaded.json").write_text(json.dumps(tpl.model_dump()), encoding="utf-8")
        library = TemplateLibrary(templates_dir=tpl_dir)
        loaded = library.get_template("preloaded")
        assert loaded is not None
        assert loaded.name == "Preloaded Template"

    def test_no_templates_dir(self) -> None:
        library = TemplateLibrary(templates_dir=None)
        templates = library.list_templates()
        assert len(templates) == 5  # Builtins only
        assert library.save_template(ReportTemplate(id="x", name="X")) is None
