"""Self-contained interactive HTML report generator.

Generates a single HTML file with progressive disclosure in 4 layers:

Layer 1 (Decision): Verdict, takeaways, domain strip, open items — visible on load
Layer 2 (Actions): Recommendations, financial impact, valuation bridge — expand to view
Layer 3 (Domains): Domain cards, cross-domain correlation, deep-dives — expand to view
Layer 4 (Evidence): All findings, specialized analyses, appendix — expand to view

Features: off-canvas sidebar navigation, severity filtering, global search,
sortable tables, collapsible layers, print mode, CSS custom properties,
RAG indicators, neurosymbolic recommendations engine.

Architecture: Thin orchestrator that delegates to per-section renderers.
Each renderer inherits SectionRenderer and consumes pre-computed ReportComputedData.
"""

from __future__ import annotations

import contextlib
import html
import json
import logging
from typing import TYPE_CHECKING, Any

from dd_agents.reporting.computed_metrics import ReportDataComputer
from dd_agents.reporting.html_action_items import ActionItemsRenderer
from dd_agents.reporting.html_analysis import (
    CoCAnalysisRenderer,
    PrivacyAnalysisRenderer,
    SubjectHealthRenderer,
    TfCAnalysisRenderer,
)
from dd_agents.reporting.html_base import render_css, render_js, render_nav_bar
from dd_agents.reporting.html_completeness import CompletenessRenderer
from dd_agents.reporting.html_compliance import ComplianceRenderer
from dd_agents.reporting.html_config_panel import ConfigPanelRenderer
from dd_agents.reporting.html_cross import CrossRefRenderer
from dd_agents.reporting.html_cross_domain import CrossDomainRenderer
from dd_agents.reporting.html_dashboard import DashboardRenderer
from dd_agents.reporting.html_diff import DiffRenderer
from dd_agents.reporting.html_discount import DiscountAnalysisRenderer
from dd_agents.reporting.html_domain_summary import DomainSummaryRenderer
from dd_agents.reporting.html_domains import DomainRenderer
from dd_agents.reporting.html_entity import EntityDistributionRenderer
from dd_agents.reporting.html_executive import ExecutiveSummaryRenderer
from dd_agents.reporting.html_filter_bar import FilterBarRenderer
from dd_agents.reporting.html_financial import FinancialImpactRenderer
from dd_agents.reporting.html_findings_table import FindingsTableRenderer
from dd_agents.reporting.html_gaps import GapRenderer
from dd_agents.reporting.html_governance import GovernanceGraphRenderer
from dd_agents.reporting.html_integration_playbook import IntegrationPlaybookRenderer
from dd_agents.reporting.html_ip_risk import IPRiskRenderer
from dd_agents.reporting.html_liability import LiabilityRenderer
from dd_agents.reporting.html_methodology import MethodologyRenderer
from dd_agents.reporting.html_quality import QualityRenderer
from dd_agents.reporting.html_recommendations import RecommendationsRenderer
from dd_agents.reporting.html_red_flags import RedFlagAssessmentRenderer
from dd_agents.reporting.html_renewal import RenewalAnalysisRenderer
from dd_agents.reporting.html_risk import RiskRenderer
from dd_agents.reporting.html_saas_metrics import SaaSMetricsRenderer
from dd_agents.reporting.html_strategy import StrategyRenderer
from dd_agents.reporting.html_subjects import SubjectRenderer
from dd_agents.reporting.html_timeline import TimelineRenderer
from dd_agents.reporting.html_valuation import ValuationBridgeRenderer
from dd_agents.reporting.verdict import VerdictRubric

if TYPE_CHECKING:
    from pathlib import Path

    from dd_agents.reporting.html_base import SectionRenderer

logger = logging.getLogger(__name__)

# The four overridable verdict-rubric thresholds (config.reporting.verdict).
_VERDICT_RUBRIC_KEYS = frozenset(
    {
        "no_go_p0_min",
        "conditional_p1_min",
        "proceed_with_conditions_p1_min",
        "high_exposure_pct",
    }
)


def _verdict_rubric_from_config(deal_config: dict[str, Any] | None) -> VerdictRubric | None:
    """Build a VerdictRubric from ``config.reporting.verdict``, if present.

    Returns ``None`` (rubric defaults apply) when the section is absent or
    holds no recognized keys. Unknown keys are ignored so a malformed config
    can never raise here.
    """
    if not isinstance(deal_config, dict):
        return None
    reporting = deal_config.get("reporting")
    if not isinstance(reporting, dict):
        return None
    raw = reporting.get("verdict")
    if not isinstance(raw, dict):
        return None
    overrides = {k: v for k, v in raw.items() if k in _VERDICT_RUBRIC_KEYS and v is not None}
    if not overrides:
        return None
    return VerdictRubric(**overrides)


def _clause_lib_renderer(computed: Any, merged_data: dict[str, Any], config: dict[str, Any]) -> SectionRenderer:
    from dd_agents.reporting.html_clause_library import ClauseLibraryRenderer

    return ClauseLibraryRenderer(computed, merged_data, config)


def _key_employee_renderer(computed: Any, merged_data: dict[str, Any], config: dict[str, Any]) -> SectionRenderer:
    from dd_agents.reporting.html_key_employee import KeyEmployeeRenderer

    return KeyEmployeeRenderer(computed, merged_data, config)


def _tech_stack_renderer(computed: Any, merged_data: dict[str, Any], config: dict[str, Any]) -> SectionRenderer:
    from dd_agents.reporting.html_tech_stack import TechStackRenderer

    return TechStackRenderer(computed, merged_data, config)


def _product_adoption_renderer(computed: Any, merged_data: dict[str, Any], config: dict[str, Any]) -> SectionRenderer:
    from dd_agents.reporting.html_product_adoption import ProductAdoptionRenderer

    return ProductAdoptionRenderer(computed, merged_data, config)


class HTMLReportGenerator:
    """Generate a self-contained HTML due-diligence report.

    Thin orchestrator: computes metrics once, then delegates rendering
    to per-section SectionRenderer subclasses.
    """

    def generate(
        self,
        merged_data: dict[str, Any],
        output_path: Path,
        *,
        run_id: str = "",
        title: str = "Due Diligence Report",
        run_metadata: dict[str, Any] | None = None,
        deal_config: dict[str, Any] | None = None,
        acquirer_intelligence: dict[str, Any] | None = None,
        executive_synthesis: dict[str, Any] | None = None,
        red_flag_scan: dict[str, Any] | None = None,
        narrative: dict[str, Any] | None = None,
        run_dir: Path | None = None,
    ) -> None:
        """Write the HTML report to *output_path*.

        Parameters
        ----------
        merged_data:
            ``{subject_safe_name: merged_subject_dict}``
        output_path:
            Destination file path.
        run_id:
            Pipeline run identifier for the header.
        title:
            Report title shown in the header.
        run_metadata:
            Pipeline run metadata (finding_counts, quality_scores, etc.).
        deal_config:
            Raw deal configuration dict (buyer, target, deal type, etc.).
        acquirer_intelligence:
            Optional output from the AcquirerIntelligenceAgent (Issue #110).
        executive_synthesis:
            Optional output from the ExecutiveSynthesisAgent — calibrated
            Go/No-Go signal, severity overrides, and executive narrative.
        red_flag_scan:
            Optional output from the RedFlagScannerAgent (Issue #125) —
            stoplight signal, flags, and recommendation.
        run_dir:
            Pipeline run directory (for loading audit.json, report_diff.json, etc.).
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Single-pass metrics computation. An optional deal-config override
        # (config.reporting.verdict) tunes the deterministic verdict rubric.
        rubric = _verdict_rubric_from_config(deal_config)
        computer = ReportDataComputer()
        computed = computer.compute(merged_data, executive_synthesis=executive_synthesis, rubric=rubric)

        # Inject buyer_strategy from deal_config if present
        if deal_config and isinstance(deal_config, dict):
            bs = deal_config.get("buyer_strategy")
            if bs and isinstance(bs, dict):
                computed.buyer_strategy = bs

        # Inject acquirer intelligence if provided (Issue #110)
        if acquirer_intelligence and isinstance(acquirer_intelligence, dict):
            computed.acquirer_intelligence = acquirer_intelligence

        # Inject red flag scan results if provided (Issue #125)
        if red_flag_scan and isinstance(red_flag_scan, dict):
            computed.red_flag_scan = red_flag_scan

        # Inject cross-domain triggers from audit trail (Issue #189)
        if run_dir is not None:
            triggers_path = run_dir / "audit" / "cross_domain_triggers.json"
            if triggers_path.exists():
                with contextlib.suppress(json.JSONDecodeError, OSError):
                    computed.cross_domain_triggers = json.loads(triggers_path.read_text(encoding="utf-8"))

        # Inject narrative data if provided
        if narrative and isinstance(narrative, dict):
            computed.narrative = narrative

        # Config dict passed to renderers for metadata they need
        renderer_config: dict[str, Any] = {
            "_title": title,
            "_run_id": run_id,
            "_run_metadata": run_metadata,
            "_deal_config": deal_config,
        }

        # Assemble HTML
        parts: list[str] = [
            "<!DOCTYPE html>",
            "<html lang='en'>",
            "<head>",
            f"<title>{html.escape(title)}</title>",
            "<meta charset='utf-8'>",
            "<meta name='viewport' content='width=device-width, initial-scale=1'>",
            f"<style>{render_css()}</style>",
            "</head>",
            "<body>",
            render_nav_bar(section_rag=computed.section_rag),
        ]

        # --- Layer 1: The Decision (one viewport) ---
        layer1_renderers: list[SectionRenderer] = [
            ExecutiveSummaryRenderer(computed, merged_data, renderer_config),
        ]

        # --- Layer 2: What To Do (actions + financial impact) ---
        layer2_renderers: list[SectionRenderer] = [
            ActionItemsRenderer(computed, merged_data, renderer_config),
            FinancialImpactRenderer(computed, merged_data, renderer_config),
            ValuationBridgeRenderer(computed, merged_data, renderer_config),
        ]

        # --- Layer 3: Domain Details (collapsed sections) ---
        layer3_renderers: list[SectionRenderer] = [
            FilterBarRenderer(computed, merged_data, renderer_config),
            DomainSummaryRenderer(computed, merged_data, renderer_config),
            CrossDomainRenderer(computed, merged_data, renderer_config),
            DomainRenderer(computed, merged_data, renderer_config),
        ]

        # --- Layer 4: Full Evidence (collapsed) ---
        layer4_renderers: list[SectionRenderer] = [
            RedFlagAssessmentRenderer(computed, merged_data, renderer_config),
            DashboardRenderer(computed, merged_data, renderer_config),
            SaaSMetricsRenderer(computed, merged_data, renderer_config),
            FindingsTableRenderer(computed, merged_data, renderer_config),
            CoCAnalysisRenderer(computed, merged_data, renderer_config),
            TfCAnalysisRenderer(computed, merged_data, renderer_config),
            PrivacyAnalysisRenderer(computed, merged_data, renderer_config),
            RiskRenderer(computed, merged_data, renderer_config),
            DiscountAnalysisRenderer(computed, merged_data, renderer_config),
            RenewalAnalysisRenderer(computed, merged_data, renderer_config),
            ComplianceRenderer(computed, merged_data, renderer_config),
            EntityDistributionRenderer(computed, merged_data, renderer_config),
            TimelineRenderer(computed, merged_data, renderer_config),
            LiabilityRenderer(computed, merged_data, renderer_config),
            IPRiskRenderer(computed, merged_data, renderer_config),
            _clause_lib_renderer(computed, merged_data, renderer_config),
            _key_employee_renderer(computed, merged_data, renderer_config),
            _tech_stack_renderer(computed, merged_data, renderer_config),
            _product_adoption_renderer(computed, merged_data, renderer_config),
            CrossRefRenderer(computed, merged_data, renderer_config),
            SubjectHealthRenderer(computed, merged_data, renderer_config),
            RecommendationsRenderer(computed, merged_data, renderer_config),
            IntegrationPlaybookRenderer(computed, merged_data, renderer_config),
            GovernanceGraphRenderer(computed, merged_data, renderer_config),
            GapRenderer(computed, merged_data, renderer_config),
            CompletenessRenderer(computed, merged_data, renderer_config),
            SubjectRenderer(computed, merged_data, renderer_config),
            ConfigPanelRenderer(computed, merged_data, renderer_config),
            MethodologyRenderer(computed, merged_data, renderer_config),
            QualityRenderer(computed, merged_data, renderer_config, run_dir=run_dir),
            DiffRenderer(computed, merged_data, renderer_config, run_dir=run_dir),
        ]

        # Conditional buyer strategy section
        if computed.buyer_strategy:
            layer2_renderers.append(StrategyRenderer(computed, merged_data, renderer_config))

        # Render Layer 1 — the decision (always visible, first viewport)
        for renderer in layer1_renderers:
            section_html = renderer.render()
            if section_html:
                parts.append(section_html)

        # Render Layer 2 — what to do (visible, below fold)
        layer2_html: list[str] = []
        for renderer in layer2_renderers:
            section_html = renderer.render()
            if section_html:
                layer2_html.append(section_html)
        if layer2_html:
            parts.append(
                "<div class='layer-divider'>"
                "<button class='layer-toggle' id='toggle-actions' type='button' "
                "aria-expanded='false'>What To Do About It</button>"
                "</div>"
                "<div class='deep-dive-layer' id='actions-content' style='display:none'>"
            )
            parts.extend(layer2_html)
            parts.append("</div>")

        # Render Layer 3 — domain details (collapsed)
        layer3_html: list[str] = []
        for renderer in layer3_renderers:
            section_html = renderer.render()
            if section_html:
                layer3_html.append(section_html)
        if layer3_html:
            parts.append(
                "<div class='layer-divider'>"
                "<button class='layer-toggle' id='toggle-deep-dive' type='button' "
                "aria-expanded='false'>Domain Details</button>"
                "</div>"
                "<div class='deep-dive-layer' id='deep-dive-content' style='display:none'>"
            )
            parts.extend(layer3_html)
            parts.append("</div>")

        # Render Layer 4 — full evidence (collapsed)
        layer4_html: list[str] = []
        for renderer in layer4_renderers:
            section_html = renderer.render()
            if section_html:
                layer4_html.append(section_html)
        if layer4_html:
            parts.append(
                "<div class='layer-divider'>"
                "<button class='layer-toggle layer-toggle--muted' id='toggle-appendix' type='button' "
                "aria-expanded='false'>Full Evidence &amp; Appendix</button>"
                "</div>"
                "<div class='deep-dive-layer' id='appendix-content' style='display:none'>"
            )
            parts.extend(layer4_html)
            parts.append("</div>")

        parts.extend(
            [
                "</div>",  # close <div class='content'> opened in render_nav_bar()
                "</div>",  # close <div class='main-wrapper'> opened in render_nav_bar()
                f"<script>{render_js()}</script>",
                "</body>",
                "</html>",
            ]
        )

        output_path.write_text("\n".join(parts), encoding="utf-8")
        logger.info("HTML report written to %s", output_path)
