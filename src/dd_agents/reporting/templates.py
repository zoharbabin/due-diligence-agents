"""Configurable report templates & white-label branding (Issue #123).

Provides:
- ReportBranding: custom firm name, logo, colors, footer
- ReportSections: include/exclude sections, detail levels
- TemplateLibrary: pre-built templates (Board Summary, Full Report, etc.)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path  # noqa: TC003 — used at runtime

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ReportBranding(BaseModel):
    """White-label branding configuration."""

    firm_name: str = Field(default="", description="Advisory firm name for header/footer")
    logo_path: str = Field(default="", description="Path to logo image file")
    primary_color: str = Field(default="#1a365d", description="Primary brand color (CSS hex)")
    accent_color: str = Field(default="#e53e3e", description="Accent color for highlights")
    background_color: str = Field(default="#ffffff", description="Page background")
    font_family: str = Field(default="", description="Custom font family (CSS)")
    footer_text: str = Field(default="", description="Custom footer text")
    confidential_label: str = Field(default="CONFIDENTIAL", description="Confidentiality badge text")


class ReportSections(BaseModel):
    """Section include/exclude configuration."""

    include: list[str] = Field(
        default_factory=list,
        description="Sections to include (empty = all). Section IDs from renderer list.",
    )
    exclude: list[str] = Field(
        default_factory=list,
        description="Sections to exclude. Applied after include filter.",
    )
    detail_level: str = Field(
        default="standard",
        description="Detail level: executive | standard | detailed",
    )


class ReportTemplate(BaseModel):
    """A named report template combining branding and section config."""

    id: str = Field(description="Template identifier")
    name: str = Field(description="Human-readable name")
    description: str = Field(default="")
    branding: ReportBranding = Field(default_factory=ReportBranding)
    sections: ReportSections = Field(default_factory=ReportSections)
    metadata: dict[str, str] = Field(default_factory=dict)


# Pre-built templates
BUILTIN_TEMPLATES: dict[str, ReportTemplate] = {
    "full_report": ReportTemplate(
        id="full_report",
        name="Full DD Report",
        description="Complete due diligence report with all sections and full detail",
        sections=ReportSections(detail_level="detailed"),
    ),
    "board_summary": ReportTemplate(
        id="board_summary",
        name="Board Summary",
        description="Executive summary for board presentation — KPIs, Go/No-Go, top findings only",
        sections=ReportSections(
            include=[
                "red_flag",
                "executive_summary",
                "dashboard",
                "financial_impact",
                "saas_metrics",
                "valuation_bridge",
                "findings_table",
                "recommendations",
            ],
            detail_level="executive",
        ),
    ),
    "legal_deep_dive": ReportTemplate(
        id="legal_deep_dive",
        name="Legal Deep Dive",
        description="Detailed legal analysis — CoC, TfC, privacy, compliance, IP risk",
        sections=ReportSections(
            include=[
                "executive_summary",
                "findings_table",
                "coc_analysis",
                "tfc_analysis",
                "privacy_analysis",
                "compliance",
                "liability",
                "ip_risk",
                "clause_library",
                "recommendations",
                "entity_detail",
            ],
            detail_level="detailed",
        ),
    ),
    "financial_analysis": ReportTemplate(
        id="financial_analysis",
        name="Financial Analysis",
        description="Financial-focused report — revenue, SaaS metrics, valuation, discounts",
        sections=ReportSections(
            include=[
                "executive_summary",
                "dashboard",
                "financial_impact",
                "saas_metrics",
                "valuation_bridge",
                "discount_analysis",
                "cross_ref",
                "recommendations",
            ],
            detail_level="standard",
        ),
    ),
    "technical_assessment": ReportTemplate(
        id="technical_assessment",
        name="Technical Assessment",
        description="Product & technology focused analysis",
        sections=ReportSections(
            include=[
                "executive_summary",
                "findings_table",
                "domain_producttech",
                "tech_stack",
                "product_adoption",
                "ip_risk",
                "recommendations",
            ],
            detail_level="standard",
        ),
    ),
}


class TemplateLibrary:
    """Manage report templates — built-in and custom."""

    def __init__(self, templates_dir: Path | None = None) -> None:
        self.templates_dir = templates_dir
        self._custom: dict[str, ReportTemplate] = {}
        if templates_dir and templates_dir.is_dir():
            self._load_custom_templates()

    def _load_custom_templates(self) -> None:
        if not self.templates_dir:
            return
        for f in self.templates_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                tpl = ReportTemplate.model_validate(data)
                self._custom[tpl.id] = tpl
            except Exception:
                logger.warning("Failed to load template: %s", f)

    def list_templates(self) -> list[ReportTemplate]:
        """List all available templates (built-in + custom)."""
        all_templates = dict(BUILTIN_TEMPLATES)
        all_templates.update(self._custom)
        return list(all_templates.values())

    def get_template(self, template_id: str) -> ReportTemplate | None:
        """Get a template by ID."""
        if template_id in self._custom:
            return self._custom[template_id]
        return BUILTIN_TEMPLATES.get(template_id)

    def save_template(self, template: ReportTemplate) -> Path | None:
        """Save a custom template to disk."""
        if not self.templates_dir:
            return None
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        path = self.templates_dir / f"{template.id}.json"
        path.write_text(
            json.dumps(template.model_dump(), indent=2),
            encoding="utf-8",
        )
        self._custom[template.id] = template
        return path

    def delete_template(self, template_id: str) -> bool:
        """Delete a custom template (cannot delete built-ins)."""
        if template_id in BUILTIN_TEMPLATES:
            return False
        if template_id in self._custom:
            del self._custom[template_id]
            if self.templates_dir:
                path = self.templates_dir / f"{template_id}.json"
                path.unlink(missing_ok=True)
            return True
        return False


def generate_branding_css(branding: ReportBranding) -> str:
    """Generate CSS custom properties from branding config."""
    parts = [":root {"]
    if branding.primary_color:
        parts.append(f"  --brand-primary: {branding.primary_color};")
    if branding.accent_color:
        parts.append(f"  --brand-accent: {branding.accent_color};")
    if branding.background_color:
        parts.append(f"  --brand-bg: {branding.background_color};")
    if branding.font_family:
        parts.append(f"  --brand-font: {branding.font_family};")
    parts.append("}")

    if branding.font_family:
        parts.append("body { font-family: var(--brand-font), -apple-system, sans-serif; }")
    if branding.primary_color:
        parts.append(".nav-sidebar { background-color: var(--brand-primary); }")
        parts.append("h1, h2, h3 { color: var(--brand-primary); }")

    return "\n".join(parts)


def should_include_section(section_id: str, sections_config: ReportSections) -> bool:
    """Determine if a section should be included based on config."""
    if sections_config.include and section_id not in sections_config.include:
        return False
    return not (sections_config.exclude and section_id in sections_config.exclude)
