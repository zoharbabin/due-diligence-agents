"""Legal Entity Distribution & Migration Risk renderer (Issue #137).

Renders entity distribution metrics, migration risk alerts,
and entity-related findings table.
"""

from __future__ import annotations

from typing import Any

from dd_agents.reporting.html_base import SectionRenderer


class EntityDistributionRenderer(SectionRenderer):
    """Render Legal Entity Distribution section."""

    def render(self) -> str:
        analysis: dict[str, Any] = getattr(self.data, "entity_distribution", {})
        total = analysis.get("entity_findings_count", 0)
        if total == 0:
            return ""

        parts: list[str] = [
            "<section id='sec-entity' class='report-section'>",
            "<h2>Legal Entity Distribution &amp; Migration Risk</h2>",
        ]

        entities = analysis.get("total_entities_mentioned", 0)

        parts.append("<div class='metrics-strip'>")
        for label, value in [
            ("Entity Findings", str(total)),
            ("Entities Referenced", str(entities)),
        ]:
            parts.append(
                f"<div class='metric-card'>"
                f"<div class='value'>{self.escape(value)}</div>"
                f"<div class='label'>{self.escape(label)}</div>"
                f"</div>"
            )
        parts.append("</div>")

        if entities > 3:
            parts.append(
                self.render_alert(
                    "high" if entities > 5 else "info",
                    f"{entities} legal entities referenced",
                    "Entity consolidation may be required post-close. Typical cost: $50-200K in legal fees per entity.",
                )
            )

        # Findings table
        findings = analysis.get("findings", [])
        if findings:
            parts.append("<h3>Entity-Related Findings</h3>")
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
