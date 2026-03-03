"""Gap analysis renderer — priority/type breakdown and sortable table (Issue #106)."""

from __future__ import annotations

import html

from dd_agents.reporting.html_base import SectionRenderer


class GapRenderer(SectionRenderer):
    """Render the gap analysis section."""

    def render(self) -> str:
        total_gaps = self.data.total_gaps
        prio_counts = self.data.gaps_by_priority
        type_counts = self.data.gaps_by_type

        parts: list[str] = [
            "<section class='report-section' id='sec-gaps'>",
            f"<h2>Gap Analysis ({total_gaps} gaps)</h2>",
        ]

        if total_gaps == 0:
            parts.append("<p class='text-muted'>No documentation gaps identified.</p>")
            parts.append("</section>")
            return "\n".join(parts)

        # Summary grid
        parts.append("<div class='gap-summary-grid'>")
        parts.append("<div class='metric-card'><div class='label'>By Priority</div>")
        for p, c in sorted(prio_counts.items()):
            parts.append(f"<div>{self.severity_badge(p)} {c}</div>")
        parts.append("</div>")
        parts.append("<div class='metric-card'><div class='label'>By Type</div>")
        for t, c in sorted(type_counts.items()):
            parts.append(f"<div><strong>{html.escape(t)}</strong>: {c}</div>")
        parts.append("</div>")
        parts.append("</div>")

        # Full sortable table
        parts.append(
            "<table class='sortable'><thead><tr>"
            "<th scope='col'>Customer</th><th scope='col'>Priority</th><th scope='col'>Type</th>"
            "<th scope='col'>Missing Item</th><th scope='col'>Risk</th></tr></thead><tbody>"
        )
        for csn, data in sorted(self.merged_data.items()):
            if not isinstance(data, dict):
                continue
            customer = html.escape(str(data.get("customer", csn)))
            for g in data.get("gaps", []):
                if not isinstance(g, dict):
                    continue
                prio = html.escape(str(g.get("priority", "")))
                gtype = html.escape(str(g.get("gap_type", "")))
                item = html.escape(str(g.get("missing_item", "")))
                risk = html.escape(str(g.get("risk_if_missing", "")))
                parts.append(
                    f"<tr><td>{customer}</td><td>{prio}</td><td>{gtype}</td><td>{item}</td><td>{risk}</td></tr>"
                )
        parts.append("</tbody></table>")
        parts.append("</section>")
        return "\n".join(parts)
