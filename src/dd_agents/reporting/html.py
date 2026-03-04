"""Self-contained interactive HTML report generator.

Generates a single HTML file with no external dependencies.
Top-down executive M&A decision-support report with progressive drill-down:

Level 0: Deal-Level Decision View (go/no-go signals)
  Level 1: Domain Analysis (Legal / Finance / Commercial / ProductTech)
    Level 2: Risk Categories within each domain
      Level 3: Per-Customer / Per-Entity findings
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
from dd_agents.reporting.html_analysis import CoCAnalysisRenderer, CustomerHealthRenderer, PrivacyAnalysisRenderer
from dd_agents.reporting.html_base import render_css, render_js, render_nav_bar
from dd_agents.reporting.html_cross import CrossRefRenderer
from dd_agents.reporting.html_customers import CustomerRenderer
from dd_agents.reporting.html_dashboard import DashboardRenderer
from dd_agents.reporting.html_diff import DiffRenderer
from dd_agents.reporting.html_domains import DomainRenderer
from dd_agents.reporting.html_executive import ExecutiveSummaryRenderer
from dd_agents.reporting.html_findings_table import FindingsTableRenderer
from dd_agents.reporting.html_gaps import GapRenderer
from dd_agents.reporting.html_methodology import MethodologyRenderer
from dd_agents.reporting.html_quality import QualityRenderer
from dd_agents.reporting.html_recommendations import RecommendationsRenderer
from dd_agents.reporting.html_risk import RiskRenderer
from dd_agents.reporting.html_strategy import StrategyRenderer

if TYPE_CHECKING:
    from pathlib import Path

    from dd_agents.reporting.html_base import SectionRenderer

logger = logging.getLogger(__name__)


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
        run_dir: Path | None = None,
    ) -> None:
        """Write the HTML report to *output_path*.

        Parameters
        ----------
        merged_data:
            ``{customer_safe_name: merged_customer_dict}``
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
        run_dir:
            Pipeline run directory (for loading audit.json, report_diff.json, etc.).
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Single-pass metrics computation
        computer = ReportDataComputer()
        computed = computer.compute(merged_data)

        # Inject buyer_strategy from deal_config if present
        if deal_config and isinstance(deal_config, dict):
            bs = deal_config.get("buyer_strategy")
            if bs and isinstance(bs, dict):
                computed.buyer_strategy = bs

        # Inject acquirer intelligence if provided (Issue #110)
        if acquirer_intelligence and isinstance(acquirer_intelligence, dict):
            computed.acquirer_intelligence = acquirer_intelligence

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

        # Section renderers (order follows executive decision flow — Issue #113 A2)
        renderers: list[SectionRenderer] = [
            # 1. Deal header + key metrics
            DashboardRenderer(computed, merged_data, renderer_config),
            # 2. Executive summary (Go/No-Go, heatmap, top deal breakers)
            ExecutiveSummaryRenderer(computed, merged_data, renderer_config),
            # 3. P0/P1 customer-level tables
            FindingsTableRenderer(computed, merged_data, renderer_config),
            # 4. Domain risk heatmap
            RiskRenderer(computed, merged_data, renderer_config),
            # 5. Change of Control analysis
            CoCAnalysisRenderer(computed, merged_data, renderer_config),
            # 6. Data Privacy analysis
            PrivacyAnalysisRenderer(computed, merged_data, renderer_config),
            # 7. Entity health tiers
            CustomerHealthRenderer(computed, merged_data, renderer_config),
            # 8. Domain deep-dives (collapsed)
            DomainRenderer(computed, merged_data, renderer_config),
            # 9. Gap analysis
            GapRenderer(computed, merged_data, renderer_config),
            # 10. Data reconciliation
            CrossRefRenderer(computed, merged_data, renderer_config),
            # 11. Governance & quality
            QualityRenderer(computed, merged_data, renderer_config, run_dir=run_dir),
            # 12. Entity detail (collapsed)
            CustomerRenderer(computed, merged_data, renderer_config),
            # 13. Recommendations
            RecommendationsRenderer(computed, merged_data, renderer_config),
            # 14. Methodology
            MethodologyRenderer(computed, merged_data, renderer_config),
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
