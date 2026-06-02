"""Actionable Recommendations renderer — consolidated action items dashboard (Issue #200).

Renders matched recommendations as a structured table grouped by timeline phase:
Pre-close → Post-close 30d → Post-close 90d → Long-term.

Includes a legal disclaimer that recommendations are advisory, not legal counsel.
"""

from __future__ import annotations

from typing import Any

from dd_agents.reporting.html_base import SEVERITY_COLORS, SectionRenderer
from dd_agents.reporting.recommendation_templates import (
    MatchedRecommendation,
    generate_recommendations,
)
from dd_agents.utils.constants import SEVERITY_P0, SEVERITY_P1

# Timeline phase ordering and display
_TIMELINE_ORDER = ["Pre-close", "Post-close 30d", "Post-close 90d", "Long-term"]
_TIMELINE_COLORS: dict[str, str] = {
    "Pre-close": "var(--red, #dc3545)",
    "Post-close 30d": "var(--orange, #fd7e14)",
    "Post-close 90d": "var(--yellow, #ffc107)",
    "Long-term": "var(--text-secondary, #6c757d)",
}


class ActionItemsRenderer(SectionRenderer):
    """Render the consolidated action items dashboard.

    Neurosymbolic: deterministic risk templates provide structured reasoning
    scaffolding; when narrative synthesis is available, LLM-generated
    recommendations use those patterns as input to produce context-aware
    actions tied to deal thesis and cross-domain findings.
    """

    def render(self) -> str:
        # Try narrative-generated recommendations first
        narr_recs = self._get_narrative_recommendations()
        if narr_recs:
            return self._render_narrative_recommendations(narr_recs)

        # Fallback: template-matched recommendations
        material = getattr(self.data, "material_findings", [])
        recommendations = generate_recommendations(material, max_items=30) if material else []
        if not recommendations:
            # No action items, but the AI-assisted disclosure (§1.3/§8.2) must
            # ALWAYS appear in the report — render the disclaimer unconditionally.
            return self._render_empty_with_disclaimer()

        parts: list[str] = [
            "<section class='report-section' id='sec-action-items'>",
            "<h2>Action Items</h2>",
            self._render_disclaimer(is_llm=False),
            self._render_summary_strip(recommendations),
        ]

        grouped: dict[str, list[MatchedRecommendation]] = {t: [] for t in _TIMELINE_ORDER}
        for rec in recommendations:
            phase = rec.timeline if rec.timeline in _TIMELINE_ORDER else "Long-term"
            grouped[phase].append(rec)

        for phase in _TIMELINE_ORDER:
            items = grouped[phase]
            if items:
                parts.append(self._render_phase(phase, items))

        parts.append("</section>")
        return "\n".join(p for p in parts if p)

    def _get_narrative_recommendations(self) -> list[dict[str, Any]]:
        """Extract recommendations from narrative data if available."""
        narr = self.data.narrative
        if not narr or not isinstance(narr, dict):
            return []
        recs = narr.get("recommendations", [])
        if not isinstance(recs, list) or not recs:
            return []
        return [r for r in recs if isinstance(r, dict)]

    def _render_narrative_recommendations(self, recs: list[dict[str, Any]]) -> str:
        """Render LLM-generated recommendations with context-aware rationale."""
        parts: list[str] = [
            "<section class='report-section' id='sec-action-items'>",
            "<h2>Action Items</h2>",
            self._render_disclaimer(is_llm=True),
        ]

        # Summary strip
        by_urgency: dict[str, int] = {}
        for r in recs:
            urgency = str(r.get("urgency", "pre-close"))
            by_urgency[urgency] = by_urgency.get(urgency, 0) + 1

        pre_close = by_urgency.get("pre-close", 0)
        day_1 = by_urgency.get("day-1", 0)
        short_term = by_urgency.get("30-day", 0) + by_urgency.get("90-day", 0)
        parts.append(
            "<div class='metrics-strip'>"
            f"<div class='metric-card'><div class='value'>{len(recs)}</div>"
            "<div class='label'>Total Actions</div></div>"
            f"<div class='metric-card'><div class='value' style='color:#dc3545'>{pre_close}</div>"
            "<div class='label'>Pre-close</div></div>"
            f"<div class='metric-card'><div class='value' style='color:#fd7e14'>{day_1}</div>"
            "<div class='label'>Day 1</div></div>"
            f"<div class='metric-card'><div class='value' style='color:#ffc107'>{short_term}</div>"
            "<div class='label'>30-90 Day</div></div>"
            "</div>"
        )

        # Group by urgency
        urgency_order = ["pre-close", "day-1", "30-day", "90-day", "long-term"]
        urgency_labels = {
            "pre-close": "Pre-close",
            "day-1": "Day 1",
            "30-day": "Post-close 30d",
            "90-day": "Post-close 90d",
            "long-term": "Long-term",
        }
        urgency_colors = {
            "pre-close": "var(--red, #dc3545)",
            "day-1": "var(--orange, #fd7e14)",
            "30-day": "var(--yellow, #ffc107)",
            "90-day": "var(--amber, #d97706)",
            "long-term": "var(--text-secondary, #6c757d)",
        }

        grouped: dict[str, list[dict[str, Any]]] = {u: [] for u in urgency_order}
        for r in recs:
            urgency = str(r.get("urgency", "pre-close"))
            if urgency not in grouped:
                urgency = "long-term"
            grouped[urgency].append(r)

        for urgency in urgency_order:
            items = grouped[urgency]
            if not items:
                continue
            label = urgency_labels.get(urgency, urgency)
            color = urgency_colors.get(urgency, "#6c757d")
            parts.append(
                f"<h3 style='margin-top:20px'>"
                f"<span class='rec-timeline' style='background:{color}22;color:{color}'>"
                f"{self.escape(label)}</span> ({len(items)} actions)</h3>"
            )
            parts.append("<table class='subject-table sortable'><thead><tr>")
            parts.append(
                "<th scope='col'>#</th>"
                "<th scope='col'>Action</th>"
                "<th scope='col'>Rationale</th>"
                "<th scope='col'>Owner</th>"
                "<th scope='col'>Effort</th>"
                "</tr></thead><tbody>"
            )

            for i, item in enumerate(items, 1):
                action = self.escape(str(item.get("action", "")))
                rationale = self.escape(str(item.get("rationale", "")))
                owner = self.escape(str(item.get("owner", "")))
                effort = self.escape(str(item.get("estimated_effort", "")))
                raw_refs = item.get("finding_refs", [])
                refs_text = ""
                if raw_refs and isinstance(raw_refs, list):
                    refs_text = (
                        f"<br><span class='text-small text-muted'>Re: "
                        f"{self.escape(', '.join(str(r)[:40] for r in raw_refs[:3]))}</span>"
                    )

                parts.append(
                    f"<tr><td>{i}</td>"
                    f"<td><strong>{action}</strong>{refs_text}</td>"
                    f"<td><span class='text-small'>{rationale}</span></td>"
                    f"<td>{owner}</td>"
                    f"<td>{effort}</td></tr>"
                )

            parts.append("</tbody></table>")

        parts.append("</section>")
        return "\n".join(p for p in parts if p)

    def _render_empty_with_disclaimer(self) -> str:
        """Render the section with the unconditional disclaimer and no items.

        The AI-assisted analysis disclosure (audit §1.3/§8.2) must always appear
        in the report — even when there are zero matched/narrative action items.
        """
        return "\n".join(
            [
                "<section class='report-section' id='sec-action-items'>",
                "<h2>Action Items</h2>",
                self._render_disclaimer(is_llm=False),
                "<p class='text-muted'>No action items were generated from the current findings.</p>",
                "</section>",
            ]
        )

    def _render_disclaimer(self, *, is_llm: bool = False) -> str:
        """Render advisory disclaimer appropriate to the recommendation source.

        AI-assisted analysis disclosure (§1.3/§8.2): the advisory notice — that
        output is AI-assisted analysis to be verified with qualified advisors and
        does not constitute professional counsel — is rendered unconditionally,
        including the empty path via :meth:`_render_empty_with_disclaimer`.
        """
        if is_llm:
            return (
                "<div class='alert alert-info'>"
                "<div class='alert-title'>Advisory Notice</div>"
                "<div class='alert-body'>These recommendations are produced through neurosymbolic "
                "analysis — deterministic risk scoring and cross-domain trigger rules guide LLM "
                "synthesis across all findings, deal context, and buyer thesis. This is "
                "AI-assisted analysis — verify with qualified advisors. They do not "
                "constitute legal, financial, or professional counsel.</div>"
                "</div>"
            )
        return (
            "<div class='alert alert-info'>"
            "<div class='alert-title'>Advisory Notice</div>"
            "<div class='alert-body'>These recommendations are produced through deterministic "
            "analysis of findings against domain-specific risk patterns. This is "
            "AI-assisted analysis — verify with qualified advisors. They do not constitute "
            "legal, financial, or professional counsel.</div>"
            "</div>"
        )

    def _render_summary_strip(self, recommendations: list[MatchedRecommendation]) -> str:
        """Render a metrics strip with recommendation counts by timeline."""
        pre_close = sum(1 for r in recommendations if r.timeline == "Pre-close")
        post_30 = sum(1 for r in recommendations if r.timeline == "Post-close 30d")
        post_90 = sum(1 for r in recommendations if r.timeline == "Post-close 90d")
        total = len(recommendations)

        return (
            "<div class='metrics-strip'>"
            f"<div class='metric-card'><div class='value'>{total}</div>"
            "<div class='label'>Total Actions</div></div>"
            f"<div class='metric-card'><div class='value' style='color:#dc3545'>{pre_close}</div>"
            "<div class='label'>Pre-close</div></div>"
            f"<div class='metric-card'><div class='value' style='color:#fd7e14'>{post_30}</div>"
            "<div class='label'>Post-close 30d</div></div>"
            f"<div class='metric-card'><div class='value' style='color:#ffc107'>{post_90}</div>"
            "<div class='label'>Post-close 90d</div></div>"
            "</div>"
        )

    def _render_phase(self, phase: str, items: list[MatchedRecommendation]) -> str:
        """Render a timeline phase group."""
        color = _TIMELINE_COLORS.get(phase, "#6c757d")
        parts: list[str] = [
            f"<h3 style='margin-top:20px'>"
            f"<span class='rec-timeline' style='background:{color}22;color:{color}'>"
            f"{self.escape(phase)}</span> "
            f"({len(items)} actions)</h3>",
            "<table class='subject-table sortable'><thead><tr>",
            "<th scope='col'>#</th>",
            "<th scope='col'>Action</th>",
            "<th scope='col'>Owner</th>",
            "<th scope='col'>Effort</th>",
            "<th scope='col'>Severity</th>",
            "<th scope='col'>Escalation</th>",
            "</tr></thead><tbody>",
        ]

        for i, rec in enumerate(items, 1):
            sev_color = SEVERITY_COLORS.get(rec.finding_severity, "#6c757d")
            is_critical = rec.finding_severity in (SEVERITY_P0, SEVERITY_P1)

            action = self.escape(rec.action)
            owner = self.escape(rec.owner)
            effort = self.escape(rec.effort)
            escalation = self.escape(rec.escalation)
            finding_title = self.escape(rec.finding_title[:50])

            # P0/P1 get full row; P2/P3 condensed
            if is_critical:
                parts.append(
                    f"<tr>"
                    f"<td>{i}</td>"
                    f"<td><strong>{action}</strong>"
                    f"<br><span class='text-small text-muted'>Re: {finding_title}</span></td>"
                    f"<td>{owner}</td>"
                    f"<td>{effort}</td>"
                    f"<td><span class='severity-badge' style='background:{sev_color}'>"
                    f"{self.escape(rec.finding_severity)}</span></td>"
                    f"<td><span class='text-small'>{escalation}</span></td>"
                    f"</tr>"
                )
            else:
                parts.append(
                    f"<tr>"
                    f"<td>{i}</td>"
                    f"<td>{action}"
                    f" <span class='text-small text-muted'>({finding_title})</span></td>"
                    f"<td>{owner}</td>"
                    f"<td>{effort}</td>"
                    f"<td><span class='severity-badge' style='background:{sev_color}'>"
                    f"{self.escape(rec.finding_severity)}</span></td>"
                    f"<td><span class='text-small'>{escalation}</span></td>"
                    f"</tr>"
                )

        parts.append("</tbody></table>")
        return "\n".join(parts)
