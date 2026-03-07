"""Regulatory & Compliance Risk Assessment renderer (Issue #121).

Renders privacy compliance scorecard, jurisdiction distribution,
industry exposure, and remediation roadmap.
"""

from __future__ import annotations

import html
from typing import Any

from dd_agents.reporting.html_base import SectionRenderer

_SEV_CLASS: dict[str, str] = {"P0": "sev-p0", "P1": "sev-p1", "P2": "sev-p2", "P3": "sev-p3"}


class ComplianceRenderer(SectionRenderer):
    """Render Regulatory & Compliance Risk Assessment section."""

    def render(self) -> str:
        analysis: dict[str, Any] = getattr(self.data, "compliance_analysis", {})
        total = analysis.get("total_compliance_findings", 0)
        if total == 0:
            return ""

        parts: list[str] = [
            "<section id='sec-compliance' class='report-section'>",
            "<h2>Regulatory &amp; Compliance Risk Assessment</h2>",
        ]

        dpa = analysis.get("dpa_findings_count", 0)
        jurisdiction = analysis.get("jurisdiction_findings_count", 0)
        regulatory = analysis.get("regulatory_findings_count", 0)

        # Metrics strip
        parts.append("<div class='metrics-strip'>")
        for label, value in [
            ("Compliance Findings", str(total)),
            ("DPA Issues", str(dpa)),
            ("Jurisdiction", str(jurisdiction)),
            ("Regulatory", str(regulatory)),
        ]:
            parts.append(
                f"<div class='metric-card'>"
                f"<div class='metric-value'>{html.escape(value)}</div>"
                f"<div class='metric-label'>{html.escape(label)}</div>"
                f"</div>"
            )
        parts.append("</div>")

        if dpa > 0:
            parts.append(
                f"<div class='alert-box alert-amber'>"
                f"<strong>{dpa}</strong> DPA-related findings identified. "
                f"Assess GDPR/CCPA compliance posture and remediation costs.</div>"
            )

        # Findings table
        findings = analysis.get("findings", [])
        if findings:
            parts.append("<h3>Compliance Findings</h3>")
            parts.append(
                "<table class='findings-table'><thead><tr>"
                "<th>Severity</th><th>Entity</th><th>Finding</th>"
                "</tr></thead><tbody>"
            )
            for f in findings[:15]:
                sev = str(f.get("severity", "P3"))
                cls = _SEV_CLASS.get(sev, "sev-p3")
                title = html.escape(str(f.get("title", "")))
                customer = html.escape(str(f.get("_customer", f.get("_customer_safe_name", ""))))
                parts.append(
                    f"<tr><td><span class='sev-badge {cls}'>{sev}</span></td><td>{customer}</td><td>{title}</td></tr>"
                )
            parts.append("</tbody></table>")

        parts.append("</section>")
        return "\n".join(parts)
