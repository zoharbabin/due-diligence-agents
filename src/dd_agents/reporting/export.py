"""Structured data export — CSV, JSON & machine-readable findings (#157)."""

from __future__ import annotations

import csv
import io
import json
from typing import TYPE_CHECKING, Any

from dd_agents.utils.constants import SEVERITY_P3

if TYPE_CHECKING:
    from dd_agents.reporting.computed_metrics import ReportComputedData


def export_findings_json(computed: ReportComputedData, merged_data: dict[str, Any]) -> str:
    """Export all material findings as JSON."""
    findings_out: list[dict[str, Any]] = []
    for f in computed.material_findings:
        findings_out.append(
            {
                "title": f.get("title", ""),
                "severity": f.get("severity", SEVERITY_P3),
                "confidence": f.get("confidence", "medium"),
                "category": f.get("category", ""),
                "domain": f.get("_domain", ""),
                "entity": f.get("_subject_safe_name", ""),
                "description": f.get("description", ""),
                "agent": f.get("agent", ""),
                "citations": f.get("citations", []),
                "metadata": f.get("metadata", {}),
            }
        )

    output: dict[str, Any] = {
        "summary": {
            "total_findings": computed.material_count,
            "by_severity": computed.material_by_severity,
            "total_entities": computed.total_subjects,
            "deal_risk_score": computed.deal_risk_score,
            "deal_risk_label": computed.deal_risk_label,
        },
        "findings": findings_out,
    }
    return json.dumps(output, indent=2, default=str)


_CSV_INJECTION_PREFIXES = ("=", "+", "-", "@", "|", "%")


def _sanitize_csv_field(value: str) -> str:
    """Prefix dangerous CSV fields with a tab to prevent formula injection."""
    if value and value[0] in _CSV_INJECTION_PREFIXES:
        return "\t" + value
    return value


def export_findings_csv(computed: ReportComputedData) -> str:
    """Export material findings as CSV."""
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=[
            "severity",
            "title",
            "category",
            "domain",
            "entity",
            "confidence",
            "agent",
            "description",
        ],
    )
    writer.writeheader()
    for f in computed.material_findings:
        writer.writerow(
            {
                "severity": _sanitize_csv_field(str(f.get("severity", SEVERITY_P3))),
                "title": _sanitize_csv_field(str(f.get("title", ""))),
                "category": _sanitize_csv_field(str(f.get("category", ""))),
                "domain": _sanitize_csv_field(str(f.get("_domain", ""))),
                "entity": _sanitize_csv_field(str(f.get("_subject_safe_name", ""))),
                "confidence": _sanitize_csv_field(str(f.get("confidence", "medium"))),
                "agent": _sanitize_csv_field(str(f.get("agent", ""))),
                "description": _sanitize_csv_field(str(f.get("description", ""))[:500]),
            }
        )
    return buf.getvalue()


def export_risk_summary_json(computed: ReportComputedData) -> str:
    """Export deal risk summary as JSON."""
    output: dict[str, Any] = {
        "deal_risk": {
            "score": computed.deal_risk_score,
            "label": computed.deal_risk_label,
        },
        "severity_distribution": computed.material_by_severity,
        "domain_risk_scores": computed.domain_risk_scores,
        "domain_risk_labels": computed.domain_risk_labels,
        "financial": {
            "total_arr": computed.total_contracted_arr,
            "risk_adjusted_arr": computed.risk_adjusted_arr,
            "revenue_at_risk": computed.total_contracted_arr - computed.risk_adjusted_arr,
        },
        "saas_metrics": computed.saas_metrics,
        "entity_count": computed.total_subjects,
        "material_finding_count": computed.material_count,
        "data_quality_finding_count": computed.data_quality_count,
    }
    return json.dumps(output, indent=2, default=str)
