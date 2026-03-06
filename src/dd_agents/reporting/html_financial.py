"""Revenue-at-Risk & Financial Impact renderer (Issue #102).

Renders:
1. Financial Impact Summary — key metrics strip
2. Revenue-at-Risk Waterfall — CSS bar chart showing risk exposure by category
3. Customer Concentration Treemap — CSS grid proportional to revenue
"""

from __future__ import annotations

import html

from dd_agents.reporting.html_base import SectionRenderer


def _fmt_currency(amount: float) -> str:
    """Format a dollar amount for display (e.g., $1.2M, $500K, $36)."""
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    if amount >= 1_000:
        return f"${amount / 1_000:.0f}K"
    return f"${amount:,.0f}"


def _fmt_pct(value: float) -> str:
    """Format a percentage for display."""
    return f"{value:.0f}%"


class FinancialImpactRenderer(SectionRenderer):
    """Render the Revenue-at-Risk & Financial Impact section."""

    def render(self) -> str:
        if not self.data or self.data.total_contracted_arr <= 0:
            return ""

        parts: list[str] = [
            "<section id='sec-financial' class='report-section'>",
            "<h2>Revenue-at-Risk & Financial Impact</h2>",
        ]

        parts.append(self._render_metrics_strip())
        parts.append(self._render_waterfall())

        if self.data.concentration_treemap:
            parts.append(self._render_treemap())

        # Data coverage note
        cov = self.data.revenue_data_coverage
        total = self.data.total_customers
        with_data = int(cov * total)
        parts.append(
            f"<p class='data-note'>Revenue data available for {with_data} of "
            f"{total} entities ({_fmt_pct(cov * 100)}). "
            f"Entities without revenue data are excluded from financial impact calculations.</p>"
        )

        parts.append("</section>")
        return "\n".join(parts)

    def _render_metrics_strip(self) -> str:
        """Render key financial metrics strip."""
        d = self.data
        assert d is not None
        total = d.total_contracted_arr
        adjusted = d.risk_adjusted_arr
        exposure = total - adjusted
        exposure_pct = (exposure / total * 100) if total > 0 else 0

        return (
            "<div class='metrics-strip'>"
            f"<div class='metric'><span class='metric-value'>{_fmt_currency(total)}</span>"
            "<span class='metric-label'>Total Contracted ARR</span></div>"
            f"<div class='metric'><span class='metric-value' style='color: var(--severity-p1, #d63384)'>"
            f"{_fmt_currency(exposure)}</span>"
            f"<span class='metric-label'>Revenue at Risk ({_fmt_pct(exposure_pct)})</span></div>"
            f"<div class='metric'><span class='metric-value' style='color: var(--severity-p3, #198754)'>"
            f"{_fmt_currency(adjusted)}</span>"
            "<span class='metric-label'>Risk-Adjusted ARR</span></div>"
            "</div>"
        )

    def _render_waterfall(self) -> str:
        """Render revenue-at-risk waterfall chart."""
        d = self.data
        assert d is not None
        total = d.total_contracted_arr
        if total <= 0:
            return ""

        parts: list[str] = [
            "<h3>Revenue-at-Risk Waterfall</h3>",
            "<div class='waterfall'>",
            # Total bar
            "<div class='waterfall-row'>",
            "<span class='waterfall-label'>Total Contracted ARR</span>",
            "<div class='waterfall-bar-container'>",
            f"<div class='waterfall-bar waterfall-bar--total' style='width:100%'>"
            f"<span>{_fmt_currency(total)}</span></div>",
            "</div></div>",
        ]

        # Risk category bars
        category_labels: dict[str, str] = {
            "change_of_control": "Change of Control Exposure",
            "termination_for_convenience": "Termination for Convenience",
            "customer_concentration": "Customer Concentration Risk",
            "pricing_risk": "Pricing & Discount Risk",
        }

        cumulative = 0.0
        for cat_key in ("change_of_control", "termination_for_convenience", "customer_concentration", "pricing_risk"):
            cat_data = d.risk_waterfall.get(cat_key)
            if not cat_data or cat_data.get("amount", 0.0) <= 0:
                continue
            amount = cat_data["amount"]
            contracts = cat_data.get("contracts", 0)
            pct = amount / total * 100
            offset_pct = (total - cumulative - amount) / total * 100
            cumulative += amount
            label = category_labels.get(cat_key, cat_key.replace("_", " ").title())

            parts.append(
                "<div class='waterfall-row'>"
                f"<span class='waterfall-label'>{html.escape(label)}</span>"
                "<div class='waterfall-bar-container'>"
                f"<div class='waterfall-bar waterfall-bar--risk' "
                f"style='width:{pct:.1f}%;margin-left:{offset_pct:.1f}%'>"
                f"<span>-{_fmt_currency(amount)} ({contracts} entities)</span>"
                "</div></div></div>"
            )

        # Risk-adjusted bar
        adjusted_pct = d.risk_adjusted_arr / total * 100
        parts.append(
            "<div class='waterfall-row'>"
            "<span class='waterfall-label'><strong>Risk-Adjusted ARR</strong></span>"
            "<div class='waterfall-bar-container'>"
            f"<div class='waterfall-bar waterfall-bar--adjusted' style='width:{adjusted_pct:.1f}%'>"
            f"<span>{_fmt_currency(d.risk_adjusted_arr)}</span></div>"
            "</div></div>"
        )

        parts.append("</div>")  # close waterfall
        return "\n".join(parts)

    def _render_treemap(self) -> str:
        """Render customer concentration treemap using CSS grid."""
        d = self.data
        assert d is not None
        items = d.concentration_treemap
        if not items:
            return ""

        risk_colors: dict[str, str] = {
            "critical": "var(--severity-p0, #dc3545)",
            "high": "var(--severity-p1, #d63384)",
            "medium": "var(--severity-p2, #fd7e14)",
            "low": "var(--severity-p3, #198754)",
        }

        parts: list[str] = [
            "<h3>Customer Revenue Concentration</h3>",
            "<div class='treemap' style='display:flex;flex-wrap:wrap;gap:2px;min-height:120px'>",
        ]

        for item in items[:20]:  # Cap at 20 for readability
            pct = item.get("pct", 0)
            name = html.escape(str(item.get("display_name", "")))
            revenue = _fmt_currency(item.get("revenue", 0))
            risk = item.get("risk_level", "low")
            color = risk_colors.get(risk, risk_colors["low"])
            min_width = max(pct, 5)  # Minimum 5% width for visibility

            parts.append(
                f"<div class='treemap-cell' style='flex-basis:{min_width}%;background:{color};"
                f"padding:8px;color:#fff;border-radius:4px;min-width:60px' "
                f"title='{name}: {revenue} ({_fmt_pct(pct)})'>"
                f"<strong>{name}</strong><br>{revenue} ({_fmt_pct(pct)})"
                "</div>"
            )

        parts.append("</div>")
        return "\n".join(parts)
