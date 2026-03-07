"""Contract Date Timeline & Expiry Calendar renderer (Issue #147).

Renders contract expiry timeline, renewal waterfall, and key date
alerts using inline CSS visualization (no external dependencies).
"""

from __future__ import annotations

import html
from typing import Any

from dd_agents.reporting.html_base import SectionRenderer

_SEV_CLASS: dict[str, str] = {"P0": "sev-p0", "P1": "sev-p1", "P2": "sev-p2", "P3": "sev-p3"}


class TimelineRenderer(SectionRenderer):
    """Render Contract Date Timeline & Expiry Calendar section."""

    def render(self) -> str:
        timeline: dict[str, Any] = getattr(self.data, "contract_timeline", {})
        total = timeline.get("expiry_findings_count", 0)
        if total == 0:
            return ""

        parts: list[str] = [
            "<section id='sec-timeline' class='report-section'>",
            "<h2>Contract Date Timeline &amp; Expiry Calendar</h2>",
        ]

        dates = timeline.get("date_mentions_count", 0)

        parts.append("<div class='metrics-strip'>")
        for label, value in [
            ("Date-Related Findings", str(total)),
            ("Date Mentions", str(dates)),
        ]:
            parts.append(
                f"<div class='metric-card'>"
                f"<div class='metric-value'>{html.escape(value)}</div>"
                f"<div class='metric-label'>{html.escape(label)}</div>"
                f"</div>"
            )
        parts.append("</div>")

        if total > 5:
            parts.append(
                f"<div class='alert-box alert-amber'>"
                f"<strong>{total}</strong> contract date/expiry findings — "
                f"review for cliff risks and pre-close expiry exposure.</div>"
            )

        # Findings table
        findings = timeline.get("findings", [])
        if findings:
            parts.append("<h3>Contract Date Findings</h3>")
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
