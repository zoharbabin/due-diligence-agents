"""Executive summary renderer — Go/No-Go signal, risk heatmap, top deal breakers.

Supports optional executive synthesis override: when an ExecutiveSynthesisAgent
has produced calibrated output, its signal/narrative/rankings replace the
mechanical defaults.
"""

from __future__ import annotations

from typing import Any

from dd_agents.reporting.html_base import (
    DOMAIN_COLORS,
    DOMAIN_DISPLAY,
    SEVERITY_COLORS,
    SectionRenderer,
    get_domain_agents,
)
from dd_agents.utils.constants import ALL_SEVERITIES, SEVERITY_P0

# Mapping from synthesis Go/No-Go signals to display colors.
_SYNTHESIS_SIGNAL_COLORS: dict[str, str] = {
    "No-Go": "#dc3545",
    "Proceed with Caution": "#fd7e14",
    "Conditional Go": "#ffc107",
    "Go": "#28a745",
}


class ExecutiveSummaryRenderer(SectionRenderer):
    """Render the executive summary section.

    Assembles already-computed data from ``ReportComputedData`` into a concise
    executive overview: Go/No-Go signal, risk heatmap, top deal breakers,
    key metrics strip, and concentration risk.

    When ``executive_synthesis`` is present on the computed data, its calibrated
    outputs replace the mechanical defaults for Go/No-Go, deal breakers, and
    narrative.
    """

    def render(self) -> str:
        parts: list[str] = [
            "<section class='report-section' id='sec-executive'>",
            "<h2>Executive Summary</h2>",
        ]

        parts.append(self._render_go_no_go())
        parts.append(self._render_executive_narrative())
        parts.append(self._render_risk_heatmap())
        parts.append(self._render_top_deal_breakers())
        parts.append(self._render_key_metrics())
        parts.append(self._render_concentration())

        parts.append("</section>")
        return "\n".join(p for p in parts if p)

    # --- Helpers for synthesis data ---

    def _get_synthesis(self) -> dict[str, Any] | None:
        """Return the executive synthesis dict if available and non-empty."""
        es = self.data.executive_synthesis
        if es and isinstance(es, dict):
            return es
        return None

    def _render_go_no_go(self) -> str:
        """Render the Go/No-Go recommendation.

        When executive synthesis is available, use its calibrated signal and
        rationale instead of the mechanical risk-label mapping.
        """
        es = self._get_synthesis()

        if es and es.get("go_no_go_signal"):
            # Use synthesis signal
            signal = str(es["go_no_go_signal"])
            signal_color = _SYNTHESIS_SIGNAL_COLORS.get(signal, "#ffc107")
            signal_desc = str(es.get("go_no_go_rationale", ""))
            # Use synthesis risk score if provided, otherwise mechanical
            score_override = es.get("risk_score_override", -1)
            score = (
                float(score_override)
                if isinstance(score_override, int | float) and score_override >= 0
                else self.data.deal_risk_score
            )
            label = self.data.deal_risk_label
        else:
            # Mechanical fallback
            score = self.data.deal_risk_score
            label = self.data.deal_risk_label

            if label == "Critical":
                signal = "No-Go"
                signal_color = "#dc3545"
                signal_desc = (
                    "Critical risks identified. Significant deal breakers require resolution before proceeding."
                )
            elif label == "High":
                signal = "Proceed with Caution"
                signal_color = "#fd7e14"
                signal_desc = "High risks identified. Material issues require negotiation and risk mitigation."
            elif label == "Medium":
                signal = "Conditional Go"
                signal_color = "#ffc107"
                signal_desc = "Moderate risks identified. Standard due diligence conditions apply."
            elif label == "Low":
                signal = "Conditional Go"
                signal_color = "#ffc107"
                signal_desc = "Low risks identified. Standard due diligence conditions apply."
            else:  # "Clean" or any unexpected value
                signal = "Go"
                signal_color = "#28a745"
                signal_desc = "No material risks identified. Deal fundamentals are sound."

        return (
            f"<div class='metric-card' style='border-left:5px solid {signal_color};text-align:left;padding:20px'>"
            f"<div style='font-size:1.4em;font-weight:700;color:{signal_color}'>{self.escape(signal)}</div>"
            f"<div style='color:#666;margin:4px 0'>"
            f"Risk Score: {score:.0f}/100 &mdash; {self.escape(label)}</div>"
            f"<div class='text-small text-muted'>{self.escape(signal_desc)}</div>"
            f"</div>"
        )

    def _render_executive_narrative(self) -> str:
        """Render the executive narrative prose section when synthesis provides it."""
        es = self._get_synthesis()
        if not es:
            return ""
        narrative = str(es.get("executive_narrative", "")).strip()
        if not narrative:
            return ""

        return (
            "<div class='metric-card' style='text-align:left;padding:16px;margin-bottom:12px'>"
            "<h3 style='margin-top:0'>Executive Assessment</h3>"
            f"<div style='line-height:1.6'>{self.escape(narrative)}</div>"
            "</div>"
        )

    def _render_risk_heatmap(self) -> str:
        """Render a compact domain x severity matrix."""
        parts: list[str] = ["<h3>Risk by Domain</h3>", "<table class='sortable'><thead><tr>"]
        parts.append("<th scope='col'>Domain</th>")
        for sev in ALL_SEVERITIES:
            parts.append(f"<th scope='col' style='color:{SEVERITY_COLORS[sev]}'>{sev}</th>")
        parts.append("<th scope='col'>Risk</th></tr></thead><tbody>")

        for domain in get_domain_agents():
            display = DOMAIN_DISPLAY.get(domain, domain)
            sev_counts = self.data.domain_severity.get(domain, {})
            risk_label = self.data.domain_risk_labels.get(domain, "Clean")
            risk_color = self.risk_color(risk_label)
            parts.append(
                f"<tr><td style='color:{DOMAIN_COLORS.get(domain, '#333')};font-weight:600'>{self.escape(display)}</td>"
            )
            for sev in ALL_SEVERITIES:
                count = sev_counts.get(sev, 0)
                bg = f"background:{SEVERITY_COLORS[sev]}22" if count > 0 else ""
                parts.append(f"<td style='{bg}'>{count}</td>")
            parts.append(
                f"<td><span style='color:{risk_color};font-weight:600'>{self.escape(risk_label)}</span></td></tr>"
            )

        parts.append("</tbody></table>")
        return "\n".join(parts)

    def _render_top_deal_breakers(self) -> str:
        """Render top deal breakers.

        When synthesis provides ``deal_breakers_ranked``, render those with
        rank, impact description, and remediation.  Otherwise fall back to
        mechanical ``material_wolf_pack_p0``.
        """
        es = self._get_synthesis()
        ranked = (es.get("deal_breakers_ranked") or []) if es else []

        if ranked:
            return self._render_synthesis_deal_breakers(ranked)

        # Mechanical fallback
        return self._render_mechanical_deal_breakers()

    def _render_synthesis_deal_breakers(self, ranked: list[dict[str, Any]]) -> str:
        """Render ranked deal breakers from executive synthesis."""
        if not ranked:
            return ""

        parts: list[str] = ["<h3>Top Deal Breakers</h3>", "<ol>"]
        for entry in ranked[:10]:
            title = self.escape(str(entry.get("title", "Untitled")))
            raw_entity = str(entry.get("entity", ""))
            entity = self.escape(self.data.display_names.get(raw_entity, raw_entity) if self.data else raw_entity)
            impact = self.escape(str(entry.get("impact_description", "")))
            remediation = self.escape(str(entry.get("remediation", "")))

            parts.append(f"<li><strong>{title}</strong>")
            if entity:
                parts.append(f" <span class='text-small text-muted'>({entity})</span>")
            if impact:
                parts.append(f"<br><span class='text-small'>{impact}</span>")
            if remediation:
                parts.append(f"<br><span class='text-small' style='color:#28a745'>Remediation: {remediation}</span>")
            parts.append("</li>")
        parts.append("</ol>")
        return "\n".join(parts)

    def _render_mechanical_deal_breakers(self) -> str:
        """Render top 5 deal breakers from material_wolf_pack_p0 (mechanical fallback)."""
        top = self.data.material_wolf_pack_p0[:5]
        if not top:
            return ""

        parts: list[str] = ["<h3>Top Deal Breakers</h3>", "<ol>"]
        for f in top:
            title = self.escape(str(f.get("title", "Untitled")))
            desc = self.escape(str(f.get("description", "")))
            display_name = self._resolve_display_name(f)
            entity_name = self.escape(display_name)
            parts.append(f"<li><strong>{title}</strong> <span class='text-small text-muted'>({entity_name})</span>")
            if desc:
                parts.append(f"<br><span class='text-small'>{desc}</span>")
            parts.append("</li>")
        parts.append("</ol>")
        return "\n".join(parts)

    def _render_key_metrics(self) -> str:
        """Render a compact key metrics strip using material counts."""
        d = self.data
        metrics = (
            "<div class='metrics-strip'>"
            f"<div class='metric-card'><div class='value'>{d.material_count}</div>"
            "<div class='label'>Material Findings</div></div>"
            f"<div class='metric-card'><div class='value' style='color:#dc3545'>"
            f"{d.material_by_severity.get(SEVERITY_P0, 0)}</div>"
            "<div class='label'>P0 Critical</div></div>"
            f"<div class='metric-card'><div class='value'>{d.match_rate:.0%}</div>"
            "<div class='label'>Match Rate</div></div>"
            f"<div class='metric-card'><div class='value'>{d.avg_governance_pct:.0f}%</div>"
            "<div class='label'>Avg Governance</div></div>"
            "</div>"
        )
        if d.noise_count > 0:
            metrics += (
                f"<div class='text-small text-muted' style='margin-bottom:12px'>"
                f"This analysis covers {d.material_count} material findings across "
                f"{d.total_subjects} data room sections. "
                f"{d.noise_count} data quality observations are documented in the "
                f"<a href='#sec-governance' style='color:inherit'>appendix</a>.</div>"
            )
        return metrics

    def _render_concentration(self) -> str:
        """Render concentration risk indicator."""
        hhi = self.data.concentration_hhi
        if hhi == 0:
            return ""

        if hhi > 2500:
            level = "High"
            color = "#dc3545"
        elif hhi > 1500:
            level = "Moderate"
            color = "#ffc107"
        else:
            level = "Low"
            color = "#28a745"

        return (
            f"<div class='metric-card' style='text-align:left'>"
            f"<div class='text-small text-muted'>Concentration Risk (HHI)</div>"
            f"<div style='font-size:1.2em;font-weight:600;color:{color}'>"
            f"{hhi:.0f} &mdash; {self.escape(level)}</div>"
            f"</div>"
        )
