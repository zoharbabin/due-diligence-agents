"""Renewal & Contract Expiry Analysis renderer (Issue #136).

Renders renewal type distribution, price escalation caps, and
contract expiry findings with alert boxes.
"""

from __future__ import annotations

from typing import Any

from dd_agents.reporting.html_base import SectionRenderer


class RenewalAnalysisRenderer(SectionRenderer):
    """Render Renewal & Contract Expiry Analysis section."""

    def render(self) -> str:
        analysis: dict[str, Any] = getattr(self.data, "renewal_analysis", {})
        total = analysis.get("total_renewal_findings", 0)
        if total == 0:
            return ""

        parts: list[str] = [
            "<section id='sec-renewal' class='report-section'>",
            "<h2>Renewal &amp; Contract Expiry Analysis</h2>",
        ]

        auto = analysis.get("auto_renew_count", 0)
        manual = analysis.get("manual_renew_count", 0)
        escalation = analysis.get("escalation_cap_count", 0)

        # Summary metrics
        parts.append("<div class='metrics-strip'>")
        for label, value in [
            ("Renewal Findings", str(total)),
            ("Auto-Renew", str(auto)),
            ("Manual Renew", str(manual)),
            ("Escalation Caps", str(escalation)),
        ]:
            parts.append(
                f"<div class='metric-card'>"
                f"<div class='value'>{self.escape(value)}</div>"
                f"<div class='label'>{self.escape(label)}</div>"
                f"</div>"
            )
        parts.append("</div>")

        if manual > 0:
            parts.append(
                self.render_alert(
                    "high",
                    f"{manual} contracts require manual renewal",
                    f"Proactive outreach needed to prevent lapses. "
                    f"{auto} contracts auto-renew; {manual} require manual action.",
                )
            )

        # Findings table
        findings = analysis.get("findings", [])
        if findings:
            parts.append("<h3>Renewal Findings</h3>")
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
