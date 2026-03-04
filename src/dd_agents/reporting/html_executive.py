"""Executive summary renderer — Go/No-Go signal, risk heatmap, top deal breakers."""

from __future__ import annotations

import html

from dd_agents.reporting.html_base import (
    DOMAIN_AGENTS,
    DOMAIN_COLORS,
    DOMAIN_DISPLAY,
    SEVERITY_COLORS,
    SectionRenderer,
)


class ExecutiveSummaryRenderer(SectionRenderer):
    """Render the executive summary section.

    Assembles already-computed data from ``ReportComputedData`` into a concise
    executive overview: Go/No-Go signal, risk heatmap, top deal breakers,
    key metrics strip, and concentration risk.
    """

    def render(self) -> str:
        parts: list[str] = [
            "<section class='report-section' id='sec-executive'>",
            "<h2>Executive Summary</h2>",
        ]

        parts.append(self._render_go_no_go())
        parts.append(self._render_risk_heatmap())
        parts.append(self._render_top_deal_breakers())
        parts.append(self._render_key_metrics())
        parts.append(self._render_concentration())

        parts.append("</section>")
        return "\n".join(p for p in parts if p)

    def _render_go_no_go(self) -> str:
        """Render the Go/No-Go recommendation based on deal_risk_score."""
        score = self.data.deal_risk_score
        label = self.data.deal_risk_label

        if label == "Critical":
            signal = "No-Go"
            signal_color = "#dc3545"
            signal_desc = "Critical risks identified. Significant deal breakers require resolution before proceeding."
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
            f"<div style='font-size:1.4em;font-weight:700;color:{signal_color}'>{html.escape(signal)}</div>"
            f"<div style='color:#666;margin:4px 0'>"
            f"Risk Score: {score:.0f}/100 &mdash; {html.escape(label)}</div>"
            f"<div class='text-small text-muted'>{html.escape(signal_desc)}</div>"
            f"</div>"
        )

    def _render_risk_heatmap(self) -> str:
        """Render a compact domain x severity matrix."""
        parts: list[str] = ["<h3>Risk by Domain</h3>", "<table class='sortable'><thead><tr>"]
        parts.append("<th scope='col'>Domain</th>")
        for sev in ("P0", "P1", "P2", "P3"):
            parts.append(f"<th scope='col' style='color:{SEVERITY_COLORS[sev]}'>{sev}</th>")
        parts.append("<th scope='col'>Risk</th></tr></thead><tbody>")

        for domain in DOMAIN_AGENTS:
            display = DOMAIN_DISPLAY.get(domain, domain)
            sev_counts = self.data.domain_severity.get(domain, {})
            risk_label = self.data.domain_risk_labels.get(domain, "Clean")
            risk_color = self.risk_color(risk_label)
            parts.append(
                f"<tr><td style='color:{DOMAIN_COLORS.get(domain, '#333')};font-weight:600'>{html.escape(display)}</td>"
            )
            for sev in ("P0", "P1", "P2", "P3"):
                count = sev_counts.get(sev, 0)
                bg = f"background:{SEVERITY_COLORS[sev]}22" if count > 0 else ""
                parts.append(f"<td style='{bg}'>{count}</td>")
            parts.append(
                f"<td><span style='color:{risk_color};font-weight:600'>{html.escape(risk_label)}</span></td></tr>"
            )

        parts.append("</tbody></table>")
        return "\n".join(parts)

    def _render_top_deal_breakers(self) -> str:
        """Render top 5 deal breakers from wolf_pack_p0."""
        top = self.data.wolf_pack_p0[:5]
        if not top:
            return ""

        parts: list[str] = ["<h3>Top Deal Breakers</h3>", "<ol>"]
        for f in top:
            title = html.escape(str(f.get("title", "Untitled")))
            desc = html.escape(str(f.get("description", "")))
            customer = html.escape(str(f.get("_customer", "")))
            parts.append(f"<li><strong>{title}</strong> <span class='text-small text-muted'>({customer})</span>")
            if desc:
                parts.append(f"<br><span class='text-small'>{desc}</span>")
            parts.append("</li>")
        parts.append("</ol>")
        return "\n".join(parts)

    def _render_key_metrics(self) -> str:
        """Render a compact key metrics strip."""
        d = self.data
        return (
            "<div class='metrics-strip'>"
            f"<div class='metric-card'><div class='value'>{d.total_findings}</div>"
            "<div class='label'>Total Findings</div></div>"
            f"<div class='metric-card'><div class='value' style='color:#dc3545'>"
            f"{d.findings_by_severity.get('P0', 0)}</div>"
            "<div class='label'>P0 Critical</div></div>"
            f"<div class='metric-card'><div class='value'>{d.match_rate:.0%}</div>"
            "<div class='label'>Match Rate</div></div>"
            f"<div class='metric-card'><div class='value'>{d.avg_governance_pct:.0f}%</div>"
            "<div class='label'>Avg Governance</div></div>"
            "</div>"
        )

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
            f"{hhi:.0f} &mdash; {html.escape(level)}</div>"
            f"</div>"
        )
