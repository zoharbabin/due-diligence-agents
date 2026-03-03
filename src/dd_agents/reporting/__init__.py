"""dd_agents.reporting subpackage -- merge, diff, Excel generation, HTML, contract date reconciliation."""

from __future__ import annotations

from dd_agents.reporting.contract_dates import ContractDateReconciler
from dd_agents.reporting.diff import ReportDiffBuilder
from dd_agents.reporting.excel import ExcelReportGenerator
from dd_agents.reporting.html import HTMLReportGenerator
from dd_agents.reporting.merge import FindingMerger

__all__ = [
    "ContractDateReconciler",
    "ExcelReportGenerator",
    "FindingMerger",
    "HTMLReportGenerator",
    "ReportDiffBuilder",
]
