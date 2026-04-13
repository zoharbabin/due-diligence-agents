"""Self-contained interactive HTML report generator.

Generates a single HTML file (Mermaid.js loaded from CDN for governance graphs).
Top-down executive M&A decision-support report with progressive drill-down:

Level 0: Deal-Level Decision View (go/no-go signals)
  Level 1: Domain Analysis (Legal / Finance / Commercial / ProductTech)
    Level 2: Risk Categories within each domain
      Level 3: Per-Subject / Per-Entity findings
        Level 4: Individual findings with full citations

Features: sidebar navigation with scroll tracking, alert boxes, severity
filtering, global search, sortable tables, collapsible sections, print mode,
CSS custom properties, RAG indicators, recommendations engine.

Architecture: Thin orchestrator that delegates to per-section renderers.
Each renderer inherits SectionRenderer and consumes pre-computed ReportComputedData.
"""

from __future__ import annotations

import html
import logging
from typing import TYPE_CHECKING, Any

from dd_agents.reporting.computed_metrics import ReportDataComputer
from dd_agents.reporting.html_analysis import (
    CoCAnalysisRenderer,
    PrivacyAnalysisRenderer,
    SubjectHealthRenderer,
    TfCAnalysisRenderer,
)
from dd_agents.reporting.html_base import render_css, render_js, render_nav_bar
from dd_agents.reporting.html_compliance import ComplianceRenderer
from dd_agents.reporting.html_cross import CrossRefRenderer
from dd_agents.reporting.html_cross_domain import CrossDomainRenderer
from dd_agents.reporting.html_dashboard import DashboardRenderer
from dd_agents.reporting.html_diff import DiffRenderer
from dd_agents.reporting.html_discount import DiscountAnalysisRenderer
from dd_agents.reporting.html_domains import DomainRenderer
from dd_agents.reporting.html_entity import EntityDistributionRenderer
from dd_agents.reporting.html_executive import ExecutiveSummaryRenderer
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

if TYPE_CHECKING:
    from pathlib import Path

    from dd_agents.reporting.html_base import SectionRenderer

logger = logging.getLogger(__name__)


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

        # Single-pass metrics computation
        computer = ReportDataComputer()
        computed = computer.compute(merged_data, executive_synthesis=executive_synthesis)

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

        # Section renderers (professional DD report flow — rendering overhaul)
        renderers: list[SectionRenderer] = [
            # 0. Red Flag Assessment (quick-scan mode — Issue #125, renders only when data present)
            RedFlagAssessmentRenderer(computed, merged_data, renderer_config),
            # 1. Executive summary (Go/No-Go, risk heatmap, deal breakers, key metrics)
            ExecutiveSummaryRenderer(computed, merged_data, renderer_config),
            # 2. Dashboard (deal header + metrics strip — material counts)
            DashboardRenderer(computed, merged_data, renderer_config),
            # 2b. Financial Impact (revenue-at-risk waterfall, treemap — Issue #102)
            FinancialImpactRenderer(computed, merged_data, renderer_config),
            # 2c. SaaS Health Metrics (KPI cards, tier distribution — Issue #115)
            SaaSMetricsRenderer(computed, merged_data, renderer_config),
            # 2d. Valuation Impact Bridge (Issue #116)
            ValuationBridgeRenderer(computed, merged_data, renderer_config),
            # 3. P0/P1 entity tables
            FindingsTableRenderer(computed, merged_data, renderer_config),
            # 4. Change of Control analysis
            CoCAnalysisRenderer(computed, merged_data, renderer_config),
            # 4b. Termination for Convenience — Revenue Quality
            TfCAnalysisRenderer(computed, merged_data, renderer_config),
            # 5. Data Privacy analysis
            PrivacyAnalysisRenderer(computed, merged_data, renderer_config),
            # 6. Risk Heatmap (domain deep-dive summary)
            RiskRenderer(computed, merged_data, renderer_config),
            # 7. Domain sections (Legal, Finance, Commercial, ProductTech) — capped
            DomainRenderer(computed, merged_data, renderer_config),
            # 8. Discount & Pricing Analysis (Issue #135)
            DiscountAnalysisRenderer(computed, merged_data, renderer_config),
            # 9. Renewal & Contract Expiry (Issue #136)
            RenewalAnalysisRenderer(computed, merged_data, renderer_config),
            # 10. Regulatory & Compliance (Issue #121)
            ComplianceRenderer(computed, merged_data, renderer_config),
            # 11. Legal Entity Distribution (Issue #137)
            EntityDistributionRenderer(computed, merged_data, renderer_config),
            # 12. Contract Date Timeline (Issue #147)
            TimelineRenderer(computed, merged_data, renderer_config),
            # 12a. Insurance & Liability Analysis (Issue #156)
            LiabilityRenderer(computed, merged_data, renderer_config),
            # 12b. IP & Technology License Risk (Issue #158)
            IPRiskRenderer(computed, merged_data, renderer_config),
            # 12c. Cross-Domain Risk Correlation (Issue #103)
            CrossDomainRenderer(computed, merged_data, renderer_config),
            # 12d. Clause Analysis (Issue #119)
            _clause_lib_renderer(computed, merged_data, renderer_config),
            # 12e. Key Employee & Organizational Risk (Issue #131)
            _key_employee_renderer(computed, merged_data, renderer_config),
            # 12f. Technology Stack Assessment (Issue #132)
            _tech_stack_renderer(computed, merged_data, renderer_config),
            # 12g. Product Adoption Matrix (Issue #138)
            _product_adoption_renderer(computed, merged_data, renderer_config),
            # 13. Cross-Reference Reconciliation
            CrossRefRenderer(computed, merged_data, renderer_config),
            # 14. Entity Health Tiers
            SubjectHealthRenderer(computed, merged_data, renderer_config),
            # 15. Recommendations
            RecommendationsRenderer(computed, merged_data, renderer_config),
            # 15b. Post-Close Integration Playbook (Issue #117)
            IntegrationPlaybookRenderer(computed, merged_data, renderer_config),
            # 15c. Governance Graph Visualization (Issue #142)
            GovernanceGraphRenderer(computed, merged_data, renderer_config),
            # --- Appendix ---
            # 16. Missing or Incomplete Data (moved from main body to appendix)
            GapRenderer(computed, merged_data, renderer_config),
            # 17. Entity Detail (collapsed)
            SubjectRenderer(computed, merged_data, renderer_config),
            # 18. Methodology & Limitations (collapsed appendix)
            MethodologyRenderer(computed, merged_data, renderer_config),
            # 19. Data Quality appendix (collapsed) — governance, QA, noise findings
            QualityRenderer(computed, merged_data, renderer_config, run_dir=run_dir),
        ]

        # Conditional diff section (only for incremental runs)
        renderers.append(DiffRenderer(computed, merged_data, renderer_config, run_dir=run_dir))

        # Conditional buyer strategy section
        if computed.buyer_strategy:
            renderers.append(StrategyRenderer(computed, merged_data, renderer_config))

        for renderer in renderers:
            section_html = renderer.render()
            if section_html:
                parts.append(section_html)

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
