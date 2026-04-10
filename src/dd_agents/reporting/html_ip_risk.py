"""IP & Technology License Risk renderer (Issue #158).

Renders IP ownership gaps, open source usage, license risks,
and IP-related findings table.
"""

from __future__ import annotations

from typing import Any

from dd_agents.reporting.html_base import SectionRenderer


class IPRiskRenderer(SectionRenderer):
    """Render IP & Technology License Risk section."""

    def render(self) -> str:
        analysis: dict[str, Any] = getattr(self.data, "ip_risk_analysis", {})
        total = analysis.get("total_ip_findings", 0)
        if total == 0:
            return ""

        ownership_gaps = analysis.get("ip_ownership_gaps", 0)
        open_source = analysis.get("open_source_count", 0)
        license_risks = analysis.get("license_risk_count", 0)

        parts: list[str] = [
            "<section id='sec-ip-risk' class='report-section'>",
            "<h2>IP &amp; Technology License Risk</h2>",
        ]

        # Metrics strip
        parts.append("<div class='metrics-strip'>")
        for label, value in [
            ("Total IP Findings", str(total)),
            ("Ownership Gaps", str(ownership_gaps)),
            ("Open Source", str(open_source)),
            ("License Risks", str(license_risks)),
        ]:
            parts.append(
                f"<div class='metric-card'>"
                f"<div class='value'>{self.escape(value)}</div>"
                f"<div class='label'>{self.escape(label)}</div>"
                f"</div>"
            )
        parts.append("</div>")

        # IP ownership gaps alert
        if ownership_gaps > 0:
            parts.append(
                self.render_alert(
                    "critical" if ownership_gaps > 3 else "high",
                    f"{ownership_gaps} IP ownership gaps identified",
                    f"{ownership_gaps} contracts have unclear IP ownership. "
                    f"Resolve ownership before close to protect core technology assets.",
                )
            )

        # Open source alert
        if open_source > 0:
            parts.append(
                self.render_alert(
                    "info",
                    f"Open source usage detected in {open_source} contexts",
                    f"{open_source} references to open source dependencies found. "
                    f"Review license compatibility and copyleft obligations.",
                )
            )

        # Findings table
        findings = analysis.get("findings", [])
        if findings:
            parts.append("<h3>IP &amp; License Findings</h3>")
            parts.append(
                "<table class='subject-table sortable'><thead><tr>"
                "<th scope='col'>Entity</th>"
                "<th scope='col'>Finding</th>"
                "<th scope='col'>Severity</th>"
                "</tr></thead><tbody>"
            )
            for f in findings[:15]:
                sev = str(f.get("severity", "P3"))
                title = self.escape(str(f.get("title", "")))
                entity_name = self.escape(self._resolve_display_name(f))
                parts.append(f"<tr><td>{entity_name}</td><td>{title}</td><td>{self.severity_badge(sev)}</td></tr>")
            parts.append("</tbody></table>")

        parts.append("</section>")
        return "\n".join(parts)
