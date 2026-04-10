"""Contract Date Timeline & Expiry Calendar renderer (Issue #147).

Renders contract date findings, expiry metrics, and key date
alerts using existing CSS classes.
"""

from __future__ import annotations

from typing import Any

from dd_agents.reporting.html_base import SectionRenderer


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
        earliest_expiry = timeline.get("earliest_expiry", "")
        latest_expiry = timeline.get("latest_expiry", "")
        cliff_risk = bool(timeline.get("cliff_risk", False))

        kpi_items: list[tuple[str, str]] = [
            ("Date-Related Findings", str(total)),
            ("Date Mentions", str(dates)),
        ]
        if earliest_expiry:
            kpi_items.append(("Earliest Expiry", str(earliest_expiry)))
        if latest_expiry:
            kpi_items.append(("Latest Expiry", str(latest_expiry)))

        parts.append("<div class='metrics-strip'>")
        for label, value in kpi_items:
            parts.append(
                f"<div class='metric-card'>"
                f"<div class='value'>{self.escape(value)}</div>"
                f"<div class='label'>{self.escape(label)}</div>"
                f"</div>"
            )
        parts.append("</div>")

        if cliff_risk:
            parts.append(
                self.render_alert(
                    "critical",
                    "Cliff risk detected: clustered contract expirations",
                    "Multiple contracts have clustered expiry dates in the same quarter, "
                    "creating cliff risk. Consider staggering renewals to mitigate concentration.",
                )
            )

        if total > 5:
            parts.append(
                self.render_alert(
                    "high" if total > 10 else "info",
                    f"{total} contract date/expiry findings",
                    f"Review for cliff risks and pre-close expiry exposure. "
                    f"{dates} specific date mentions found across findings.",
                )
            )

        # Findings table
        findings = timeline.get("findings", [])
        if findings:
            parts.append("<h3>Contract Date Findings</h3>")
            parts.append(
                "<table class='subject-table sortable'><thead><tr>"
                "<th scope='col'>Severity</th>"
                "<th scope='col'>Entity</th>"
                "<th scope='col'>Finding</th>"
                "</tr></thead><tbody>"
            )
            for f in findings[:15]:
                sev = str(f.get("severity", "P3"))
                title = self.escape(str(f.get("title", "")))
                entity_name = self.escape(self._resolve_display_name(f))
                parts.append(f"<tr><td>{self.severity_badge(sev)}</td><td>{entity_name}</td><td>{title}</td></tr>")
            parts.append("</tbody></table>")

        parts.append("</section>")
        return "\n".join(parts)
