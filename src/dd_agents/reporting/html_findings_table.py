"""Customer-level P0/P1 findings table renderer (Issue #113 B1).

Replaces individual finding cards in the executive view with scannable
customer-level tables showing: Entity, P0/P1 Count, Total Findings,
and Primary Issue.
"""

from __future__ import annotations

import html
from typing import Any

from dd_agents.reporting.html_base import SectionRenderer


class FindingsTableRenderer(SectionRenderer):
    """Render customer-level P0 and P1 findings tables."""

    def render(self) -> str:
        parts: list[str] = []

        p0_section = self._render_severity_table(
            "P0 Deal Stoppers",
            "sec-p0-table",
            self.data.customer_p0_summary,
            "p0_count",
            "critical",
        )
        if p0_section:
            parts.append(p0_section)

        p1_section = self._render_severity_table(
            "P1 Critical Issues",
            "sec-p1-table",
            self.data.customer_p1_summary,
            "p1_count",
            "high",
        )
        if p1_section:
            parts.append(p1_section)

        return "\n".join(parts)

    def _render_severity_table(
        self,
        title: str,
        section_id: str,
        rows: list[dict[str, Any]],
        count_key: str,
        alert_level: str,
    ) -> str:
        if not rows:
            return ""

        total_entities = len(rows)
        total_count = sum(r.get(count_key, 0) for r in rows)

        parts: list[str] = [
            f"<section class='report-section' id='{html.escape(section_id)}'>",
            f"<h2>{html.escape(title)}</h2>",
        ]

        # Alert box with summary
        parts.append(
            self.render_alert(
                alert_level,
                f"{total_count} {html.escape(title)} across {total_entities} entities",
                f"{total_entities} entities have findings at this severity level. "
                f"Review each entity's primary issue and total finding count below.",
            )
        )

        # Customer-level table
        parts.append(
            "<table class='customer-table sortable'><thead><tr>"
            "<th scope='col'>Entity</th>"
            f"<th scope='col'>{html.escape(count_key.upper().replace('_', ' '))}</th>"
            "<th scope='col'>Total Findings</th>"
            "<th scope='col'>Primary Issue</th>"
            "</tr></thead><tbody>"
        )

        # Show top 10 directly, rest collapsed
        visible = rows[:10]
        collapsed = rows[10:]

        for row in visible:
            parts.append(self._render_row(row, count_key))

        if collapsed:
            parts.append(
                f"<tr class='category-header' tabindex='0' role='button' aria-expanded='false'>"
                f"<td colspan='4' style='text-align:center;cursor:pointer'>"
                f"<strong>+ {len(collapsed)} more entities</strong> "
                f"<span class='arrow'>&#9654;</span></td></tr>"
            )
            for row in collapsed:
                parts.append(f"<tr class='category-body'>{self._render_row_cells(row, count_key)}</tr>")

        parts.append("</tbody></table>")
        parts.append("</section>")
        return "\n".join(parts)

    def _render_row(self, row: dict[str, Any], count_key: str) -> str:
        return f"<tr>{self._render_row_cells(row, count_key)}</tr>"

    @staticmethod
    def _render_row_cells(row: dict[str, Any], count_key: str) -> str:
        customer = html.escape(str(row.get("customer", "")))
        count = row.get(count_key, 0)
        total = row.get("total_findings", 0)
        issue = html.escape(str(row.get("primary_issue", "")))
        return f"<td><strong>{customer}</strong></td><td>{count}</td><td>{total}</td><td>{issue}</td>"
