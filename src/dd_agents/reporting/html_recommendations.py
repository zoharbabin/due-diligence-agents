"""Recommendations renderer — prioritized action items (Issue #113 B6)."""

from __future__ import annotations

import html

from dd_agents.reporting.html_base import TIMELINE_COLORS, SectionRenderer


class RecommendationsRenderer(SectionRenderer):
    """Render the prioritized recommendations section.

    Recommendations are generated deterministically by
    ``ReportDataComputer._generate_recommendations()`` and stored in
    ``ReportComputedData.recommendations``.  Each recommendation has:
    timeline (Immediate/Pre-Close/Post-Close/Positive), priority, title,
    and description.
    """

    def render(self) -> str:
        recs = self.data.recommendations
        if not recs:
            return ""

        parts: list[str] = [
            "<section class='report-section' id='sec-recommendations'>",
            "<h2>Recommendations</h2>",
        ]

        # Group by timeline for visual ordering
        timeline_order = ["Immediate", "Pre-Close", "Valuation", "Post-Close", "Positive"]
        for timeline in timeline_order:
            group = [r for r in recs if r.get("timeline") == timeline]
            if not group:
                continue
            for rec in group:
                parts.append(self._render_rec_card(rec))

        parts.append("</section>")
        return "\n".join(parts)

    @staticmethod
    def _render_rec_card(rec: dict[str, str]) -> str:
        timeline = rec.get("timeline", "")
        title = html.escape(rec.get("title", ""))
        description = html.escape(rec.get("description", ""))
        color = TIMELINE_COLORS.get(timeline, "#6c757d")

        # Timeline badge background: lighter version of the color
        badge_bg = {
            "Immediate": "#fff5f5",
            "Pre-Close": "#fff8f0",
            "Valuation": "#f5f3ff",
            "Post-Close": "#e8f4fd",
            "Positive": "#f0fff4",
        }.get(timeline, "#f8f9fa")

        return (
            f"<div class='rec-card' style='border-left-color:{color}'>"
            f"<span class='rec-timeline' style='background:{badge_bg};color:{color}'>"
            f"{html.escape(timeline)}</span>"
            f"<div class='rec-title'>{title}</div>"
            f"<div class='rec-desc'>{description}</div>"
            f"</div>"
        )
