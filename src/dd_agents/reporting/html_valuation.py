"""Valuation Impact Bridge renderer (Issue #116).

Renders ARR-to-risk-adjusted valuation bridge with multiple-based
impact analysis and risk category breakdown.
"""

from __future__ import annotations

from typing import Any

from dd_agents.reporting.html_base import SectionRenderer


def _fmt_currency(amount: float) -> str:
    """Format a dollar amount for display."""
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    if amount >= 1_000:
        return f"${amount / 1_000:.0f}K"
    return f"${amount:,.0f}"


class ValuationBridgeRenderer(SectionRenderer):
    """Render Valuation Impact Bridge section."""

    def render(self) -> str:
        bridge: dict[str, Any] = getattr(self.data, "valuation_bridge", {})
        total_arr = bridge.get("total_arr", 0.0)
        if not bridge or total_arr <= 0:
            return ""

        risk_adjusted_arr = bridge.get("risk_adjusted_arr", 0.0)
        total_exposure = bridge.get("total_exposure", 0.0)
        exposure_pct = (total_exposure / total_arr * 100) if total_arr > 0 else 0.0

        parts: list[str] = [
            "<section id='sec-valuation' class='report-section'>",
            "<h2>Valuation Impact Bridge</h2>",
        ]

        # Metrics strip
        parts.append("<div class='metrics-strip'>")
        for label, value in [
            ("Total ARR", _fmt_currency(total_arr)),
            ("Risk-Adjusted ARR", _fmt_currency(risk_adjusted_arr)),
            ("Total Exposure", _fmt_currency(total_exposure)),
            ("Exposure %", f"{exposure_pct:.1f}%"),
        ]:
            parts.append(
                f"<div class='metric-card'>"
                f"<div class='value'>{self.escape(value)}</div>"
                f"<div class='label'>{self.escape(label)}</div>"
                f"</div>"
            )
        parts.append("</div>")

        # Exposure alerts
        if exposure_pct > 20:
            parts.append(
                self.render_alert(
                    "critical",
                    f"Revenue exposure at {exposure_pct:.1f}%",
                    f"Total risk exposure of {_fmt_currency(total_exposure)} represents "
                    f"{exposure_pct:.1f}% of ARR. Significant valuation adjustment required.",
                )
            )
        elif exposure_pct > 5:
            parts.append(
                self.render_alert(
                    "high",
                    f"Revenue exposure at {exposure_pct:.1f}%",
                    f"Total risk exposure of {_fmt_currency(total_exposure)} represents "
                    f"{exposure_pct:.1f}% of ARR. Material valuation impact likely.",
                )
            )

        # Valuation impact at multiples
        parts.append("<h3>Valuation Impact at Multiples</h3>")
        parts.append(
            "<table class='customer-table sortable'><thead><tr>"
            "<th scope='col'>Multiple</th>"
            "<th scope='col'>Gross Valuation</th>"
            "<th scope='col'>Risk Adjustment</th>"
            "<th scope='col'>Net Valuation</th>"
            "</tr></thead><tbody>"
        )
        for mult in (5, 8, 12):
            gross = total_arr * mult
            adjustment = total_exposure * mult
            net = risk_adjusted_arr * mult
            parts.append(
                f"<tr><td>{mult}x</td>"
                f"<td>{self.escape(_fmt_currency(gross))}</td>"
                f"<td>{self.escape(_fmt_currency(adjustment))}</td>"
                f"<td>{self.escape(_fmt_currency(net))}</td></tr>"
            )
        parts.append("</tbody></table>")

        # Risk category breakdown
        categories: list[dict[str, Any]] = bridge.get("risk_categories", [])
        if categories:
            parts.append("<h3>Risk Category Breakdown</h3>")
            parts.append(
                "<table class='customer-table sortable'><thead><tr>"
                "<th scope='col'>Category</th>"
                "<th scope='col'>Exposure</th>"
                "<th scope='col'>% of Total</th>"
                "</tr></thead><tbody>"
            )
            for cat in categories[:15]:
                name = self.escape(str(cat.get("category", "")))
                amount = cat.get("exposure", 0.0)
                cat_pct = (amount / total_exposure * 100) if total_exposure > 0 else 0.0
                parts.append(
                    f"<tr><td>{name}</td><td>{self.escape(_fmt_currency(amount))}</td><td>{cat_pct:.1f}%</td></tr>"
                )
            parts.append("</tbody></table>")

        parts.append("</section>")
        return "\n".join(parts)
