"""Missing or Incomplete Data renderer — data quality, gaps, and extraction issues.

Restructured from the original Gap Analysis section to serve as an end-of-report
appendix with three collapsible sub-sections:

1. Data Availability Limitations — findings about missing/unavailable data
2. Documentation Gaps — material gaps with priority/type breakdown
3. Extraction & Quality Issues — noise findings + noise gaps (collapsed by default)
"""

from __future__ import annotations

import html

from dd_agents.reporting.html_base import SectionRenderer


class GapRenderer(SectionRenderer):
    """Render the 'Missing or Incomplete Data' section with 3 sub-sections."""

    def render(self) -> str:
        material_gaps = self.data.material_gaps
        noise_gaps = self.data.noise_gaps
        dq_findings = self.data.data_quality_findings
        material_count = len(material_gaps)
        total_gaps = self.data.total_gaps
        prio_counts = self.data.gaps_by_priority
        type_counts = self.data.gaps_by_type

        total_items = len(dq_findings) + material_count + len(noise_gaps) + len(self.data.noise_findings)

        parts: list[str] = [
            "<section class='report-section' id='sec-gaps'>",
            f"<h2>Missing or Incomplete Data ({total_items} items)</h2>",
        ]

        if total_items == 0 and total_gaps == 0:
            parts.append("<p class='text-muted'>No documentation gaps or data limitations identified.</p>")
            parts.append("</section>")
            return "\n".join(parts)

        # --- Sub-section 1: Data Availability Limitations ---
        if dq_findings:
            parts.append(
                "<div class='domain-section'>"
                "<div class='domain-header' tabindex='0' role='button' aria-expanded='true'"
                " style='border-left-color: var(--orange)'>"
                f"<h2>Data Availability Limitations ({len(dq_findings)})</h2>"
                "<span class='arrow open'>&#9654;</span></div>"
                "<div class='domain-body open'>"
            )
            for f in dq_findings:
                parts.append(self.render_finding_card(f))
                parts.append(self.render_finding_detail(f))
            parts.append("</div></div>")

        # --- Sub-section 2: Documentation Gaps ---
        if material_gaps or prio_counts:
            expanded = "true" if not dq_findings else "false"
            body_cls = " open" if not dq_findings else ""
            arrow_cls = " open" if not dq_findings else ""
            parts.append(
                "<div class='domain-section'>"
                f"<div class='domain-header' tabindex='0' role='button' aria-expanded='{expanded}'"
                " style='border-left-color: var(--blue)'>"
                f"<h2>Documentation Gaps ({material_count})</h2>"
                f"<span class='arrow{arrow_cls}'>&#9654;</span></div>"
                f"<div class='domain-body{body_cls}'>"
            )

            # Summary grid
            if prio_counts or type_counts:
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

            if material_gaps:
                parts.append(
                    "<table class='sortable'><thead><tr>"
                    "<th scope='col'>Entity</th><th scope='col'>Priority</th><th scope='col'>Type</th>"
                    "<th scope='col'>Missing Item</th><th scope='col'>Risk</th>"
                    "<th scope='col'>Why Needed</th><th scope='col'>Request to Company</th>"
                    "<th scope='col'>Agent</th></tr></thead><tbody>"
                )
                for g in material_gaps:
                    display_name = self._resolve_display_name(g)
                    entity_name = html.escape(display_name)
                    prio = html.escape(str(g.get("priority", "")))
                    gtype = html.escape(str(g.get("gap_type", "")))
                    item = html.escape(str(g.get("missing_item", "")))
                    risk = html.escape(str(g.get("risk_if_missing", "")))
                    why = html.escape(str(g.get("why_needed", "")))
                    request = html.escape(str(g.get("request_to_company", "")))
                    agent = html.escape(str(g.get("agent", "")))
                    parts.append(
                        f"<tr><td>{entity_name}</td><td>{prio}</td><td>{gtype}</td>"
                        f"<td>{item}</td><td>{risk}</td><td>{why}</td><td>{request}</td><td>{agent}</td></tr>"
                    )
                parts.append("</tbody></table>")
            else:
                parts.append("<p class='text-muted'>No material documentation gaps identified.</p>")

            parts.append("</div></div>")

        # --- Sub-section 3: Extraction & Quality Issues (collapsed by default) ---
        noise_total = len(noise_gaps) + len(self.data.noise_findings)
        if noise_total > 0:
            parts.append(
                "<div class='domain-section'>"
                "<div class='domain-header' tabindex='0' role='button' aria-expanded='false'"
                " style='border-left-color: var(--gray)'>"
                f"<h2>Extraction &amp; Quality Issues ({noise_total})</h2>"
                "<span class='arrow'>&#9654;</span></div>"
                "<div class='domain-body'>"
            )
            if self.data.noise_findings:
                parts.append(f"<h3>Noise Findings ({len(self.data.noise_findings)})</h3>")
                for f in self.data.noise_findings:
                    parts.append(self.render_finding_card(f))
                    parts.append(self.render_finding_detail(f))

            if noise_gaps:
                parts.append(
                    f"<h3>Noise Gaps ({len(noise_gaps)})</h3>"
                    "<table class='sortable'><thead><tr>"
                    "<th scope='col'>Entity</th><th scope='col'>Missing Item</th>"
                    "<th scope='col'>Risk</th></tr></thead><tbody>"
                )
                for g in noise_gaps:
                    display_name = self._resolve_display_name(g)
                    entity_name = html.escape(display_name)
                    item = html.escape(str(g.get("missing_item", "")))
                    risk = html.escape(str(g.get("risk_if_missing", "")))
                    parts.append(f"<tr><td>{entity_name}</td><td>{item}</td><td>{risk}</td></tr>")
                parts.append("</tbody></table>")

            parts.append("</div></div>")

        parts.append("</section>")
        return "\n".join(parts)
