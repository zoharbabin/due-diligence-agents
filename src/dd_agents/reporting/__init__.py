"""dd_agents.reporting subpackage -- merge, diff, Excel generation, HTML, contract date reconciliation."""

from __future__ import annotations

from dd_agents.reporting.computed_metrics import ReportComputedData, ReportDataComputer
from dd_agents.reporting.contract_dates import ContractDateReconciler
from dd_agents.reporting.diff import ReportDiffBuilder
from dd_agents.reporting.excel import ExcelReportGenerator
from dd_agents.reporting.html import HTMLReportGenerator
from dd_agents.reporting.html_base import SectionRenderer
from dd_agents.reporting.html_charts import (
    render_donut_chart,
    render_heatmap_grid,
    render_timeline_chart,
    render_waterfall_chart,
)
from dd_agents.reporting.merge import FindingMerger
from dd_agents.reporting.recommendation_templates import (
    MatchedRecommendation,
    RecommendationTemplate,
    generate_recommendations,
    match_recommendation,
)
from dd_agents.reporting.verdict import VerdictResult, compute_verdict

__all__ = [
    "ContractDateReconciler",
    "ExcelReportGenerator",
    "FindingMerger",
    "HTMLReportGenerator",
    "MatchedRecommendation",
    "RecommendationTemplate",
    "ReportComputedData",
    "ReportDataComputer",
    "ReportDiffBuilder",
    "SectionRenderer",
    "VerdictResult",
    "compute_verdict",
    "generate_recommendations",
    "match_recommendation",
    "render_donut_chart",
    "render_heatmap_grid",
    "render_timeline_chart",
    "render_waterfall_chart",
]
