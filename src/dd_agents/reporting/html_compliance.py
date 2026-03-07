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

        dpa_coverage_pct = analysis.get("dpa_coverage_pct", 0.0)

        # Metrics strip
        parts.append("<div class='metrics-strip'>")
        for label, value in [
            ("Compliance Findings", str(total)),
            ("DPA Issues", str(dpa)),
            ("DPA Coverage", f"{dpa_coverage_pct:.0f}%"),
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

        # Compliance risk score
        risk_score = analysis.get("compliance_risk_score", 0)
        risk_label = str(analysis.get("compliance_risk_label", "low"))
        if risk_score > 0:
            _risk_colors: dict[str, str] = {
                "critical": "var(--red)",
                "high": "var(--red)",
                "medium": "var(--amber)",
                "low": "var(--green)",
            }
            risk_color = _risk_colors.get(risk_label, "var(--green)")
            parts.append(
                f"<div class='metric-card'>"
                f"<div class='value' style='color:{risk_color}'>"
                f"{risk_score}</div>"
                f"<div class='label'>Risk Score ({self.escape(risk_label.title())})</div>"
                f"</div>"
            )

        if dpa > 0:
            parts.append(
                self.render_alert(
                    "high" if dpa > 3 else "info",
                    f"{dpa} DPA-related findings identified",
                    "Assess GDPR/CCPA compliance posture and remediation costs. "
                    "Typical DPA remediation: $50K-$500K depending on scope.",
                )
            )

        # Top jurisdictions table
        top_jurisdictions: list[dict[str, Any]] = analysis.get("top_jurisdictions", [])
        if top_jurisdictions:
            parts.append("<h3>Top Jurisdictions</h3>")
            parts.append(
                "<table class='customer-table sortable'><thead><tr>"
                "<th scope='col'>Jurisdiction</th>"
                "<th scope='col'>Count</th>"
                "</tr></thead><tbody>"
            )
            for entry in top_jurisdictions[:15]:
                name = self.escape(str(entry.get("jurisdiction", "")))
                count = entry.get("count", 0)
                parts.append(f"<tr><td>{name}</td><td>{count}</td></tr>")
            parts.append("</tbody></table>")

        # Filing checklist
        checklist: list[str] = analysis.get("filing_checklist", [])
        if checklist:
            parts.append("<h3>Regulatory Filing Checklist</h3>")
            parts.append("<ul>")
            for item in checklist:
                parts.append(f"<li>{self.escape(item)}</li>")
            parts.append("</ul>")

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
                customer = self.escape(self._resolve_display_name(f))
                parts.append(f"<tr><td>{self.severity_badge(sev)}</td><td>{customer}</td><td>{title}</td></tr>")
            parts.append("</tbody></table>")

        parts.append("</section>")
        return "\n".join(parts)
