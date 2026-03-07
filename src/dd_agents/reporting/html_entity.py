"""Legal Entity Distribution & Migration Risk renderer (Issue #137).

Renders entity distribution visualization, migration risk alerts,
and entity consolidation cost estimates.
"""

from __future__ import annotations

import html
from typing import Any

from dd_agents.reporting.html_base import SectionRenderer

_SEV_CLASS: dict[str, str] = {"P0": "sev-p0", "P1": "sev-p1", "P2": "sev-p2", "P3": "sev-p3"}


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
            ("Entities Mentioned", str(entities)),
        ]:
            parts.append(
                f"<div class='metric-card'>"
                f"<div class='metric-value'>{html.escape(value)}</div>"
                f"<div class='metric-label'>{html.escape(label)}</div>"
                f"</div>"
            )
        parts.append("</div>")

        if entities > 3:
            parts.append(
                f"<div class='alert-box alert-amber'>"
                f"<strong>{entities}</strong> legal entities referenced — "
                f"entity consolidation may be required post-close.</div>"
            )

        # Findings table
        findings = analysis.get("findings", [])
        if findings:
            parts.append("<h3>Entity-Related Findings</h3>")
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
