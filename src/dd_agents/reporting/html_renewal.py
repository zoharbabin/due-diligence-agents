"""Renewal & Contract Expiry Analysis renderer (Issue #136).

Renders renewal type distribution, price escalation caps, and
contract expiry timeline with pre-close alert boxes.
"""

from __future__ import annotations

import html
from typing import Any

from dd_agents.reporting.html_base import SectionRenderer

_SEV_CLASS: dict[str, str] = {"P0": "sev-p0", "P1": "sev-p1", "P2": "sev-p2", "P3": "sev-p3"}


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
                f"<div class='metric-value'>{html.escape(value)}</div>"
                f"<div class='metric-label'>{html.escape(label)}</div>"
                f"</div>"
            )
        parts.append("</div>")

        if manual > 0:
            parts.append(
                f"<div class='alert-box alert-amber'>"
                f"<strong>{manual}</strong> contracts require manual renewal — "
                f"proactive outreach needed to prevent lapses.</div>"
            )

        # Findings table
        findings = analysis.get("findings", [])
        if findings:
            parts.append("<h3>Renewal Findings</h3>")
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
