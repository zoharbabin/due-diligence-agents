"""Regulatory & Compliance Risk Assessment renderer (Issue #121).

Renders compliance scorecard metrics, DPA coverage, jurisdiction
distribution, and regulatory findings with alert boxes.
"""

from __future__ import annotations

from typing import Any

from dd_agents.reporting.html_base import SectionRenderer


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
                f"<div class='value'>{self.escape(value)}</div>"
                f"<div class='label'>{self.escape(label)}</div>"
                f"</div>"
            )
        parts.append("</div>")

        if dpa > 0:
            parts.append(
                self.render_alert(
                    "high" if dpa > 3 else "info",
                    f"{dpa} DPA-related findings identified",
                    "Assess GDPR/CCPA compliance posture and remediation costs. "
                    "Typical DPA remediation: $50K-$500K depending on scope.",
                )
            )

        # Findings table
        findings = analysis.get("findings", [])
        if findings:
            parts.append("<h3>Compliance Findings</h3>")
            parts.append(
                "<table class='customer-table sortable'><thead><tr>"
                "<th scope='col'>Severity</th>"
                "<th scope='col'>Entity</th>"
                "<th scope='col'>Finding</th>"
                "</tr></thead><tbody>"
            )
            for f in findings[:15]:
                sev = str(f.get("severity", "P3"))
                title = self.escape(str(f.get("title", "")))
                customer = self.escape(str(f.get("_customer", f.get("_customer_safe_name", ""))))
                parts.append(f"<tr><td>{self.severity_badge(sev)}</td><td>{customer}</td><td>{title}</td></tr>")
            parts.append("</tbody></table>")

        parts.append("</section>")
        return "\n".join(parts)
