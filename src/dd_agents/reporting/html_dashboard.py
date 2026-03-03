"""Dashboard renderer — executive summary with deal-level KPIs (Issue #100)."""

from __future__ import annotations

import html

from dd_agents.reporting.html_base import SEVERITY_COLORS, SectionRenderer


class DashboardRenderer(SectionRenderer):
    """Render the deal header, key metrics strip, and wolf pack section."""

    def render(self) -> str:
        parts: list[str] = []
        parts.append(self._render_deal_header())
        parts.append(self._render_key_metrics())
        parts.append(self._render_wolf_pack())
        return "\n".join(parts)

    def _render_deal_header(self) -> str:
        risk = self.data.deal_risk_label
        risk_color = self.risk_color(risk)

        title = self.config.get("_title", "Due Diligence Report")
        run_id = self.config.get("_run_id", "")
        deal_config = self.config.get("_deal_config")

        buyer = ""
        target = ""
        deal_type = ""
        if deal_config and isinstance(deal_config, dict):
            buyer_obj = deal_config.get("buyer") or {}
            buyer = buyer_obj.get("name", "") if isinstance(buyer_obj, dict) else ""
            target_obj = deal_config.get("target") or {}
            target = target_obj.get("name", "") if isinstance(target_obj, dict) else ""
            deal_obj = deal_config.get("deal") or {}
            deal_type = deal_obj.get("type", "") if isinstance(deal_obj, dict) else ""

        parts: list[str] = ["<div class='deal-header' id='sec-header'>"]
        parts.append(f"<h1>{html.escape(title)}</h1>")

        meta_parts: list[str] = []
        if buyer and target:
            meta_parts.append(f"{html.escape(buyer)} acquiring {html.escape(target)}")
        if deal_type:
            meta_parts.append(f"Deal type: {html.escape(deal_type)}")
        if meta_parts:
            parts.append(f"<div class='deal-meta'>{' | '.join(meta_parts)}</div>")

        parts.append(
            f"<div class='risk-badge' style='background:{risk_color};color:white'>"
            f"Overall Risk: {html.escape(risk)}</div>"
        )

        if run_id:
            parts.append(f"<div class='run-id'>Run ID: {html.escape(run_id)}</div>")

        parts.append("</div>")
        return "\n".join(parts)

    def _render_key_metrics(self) -> str:
        sc = self.data.findings_by_severity
        cards: list[str] = []

        def _card(value: str | int, label: str, color: str = "#1a1a2e") -> str:
            return (
                f"<div class='metric-card'>"
                f"<div class='value' style='color:{color}'>{html.escape(str(value))}</div>"
                f"<div class='label'>{html.escape(label)}</div>"
                f"</div>"
            )

        cards.append(_card(self.data.total_customers, "Customers"))
        cards.append(_card(self.data.total_findings, "Findings"))
        cards.append(_card(self.data.total_gaps, "Gaps"))
        for sev in ("P0", "P1", "P2", "P3"):
            cards.append(_card(sc.get(sev, 0), sev, SEVERITY_COLORS.get(sev, "#ccc")))

        gov_scores = self.data.governance_scores
        if gov_scores:
            avg_gov = self.data.avg_governance_pct
            cards.append(_card(f"{avg_gov:.0f}%", "Avg Governance", "#2d8a4e" if avg_gov >= 90 else "#d97706"))

        return "<div class='metrics-strip'>" + "".join(cards) + "</div>"

    def _render_wolf_pack(self) -> str:
        wolf = self.data.wolf_pack
        parts: list[str] = [
            "<section class='wolf-pack report-section' id='sec-wolf-pack'>",
            f"<h2>Deal Breakers ({len(wolf)})</h2>",
        ]

        if not wolf:
            parts.append("<p class='text-muted'>No P0 or P1 findings detected. No immediate deal-breaker risks.</p>")
        else:
            for f in wolf:
                sev = f.get("severity", "P3")
                color = SEVERITY_COLORS.get(sev, "#ccc")
                title = html.escape(str(f.get("title", "Untitled")))
                customer = html.escape(str(f.get("_customer", "")))
                agent = html.escape(str(f.get("agent", "")))
                desc = html.escape(str(f.get("description", "")))

                quote = ""
                citations = f.get("citations", [])
                if citations and isinstance(citations, list):
                    first_cit = citations[0]
                    if isinstance(first_cit, dict):
                        q = first_cit.get("exact_quote", "")
                        if q:
                            quote = html.escape(str(q))

                parts.append(
                    f"<div class='wolf-card' style='border-left-color:{color}' "
                    f"data-severity='{html.escape(sev)}'>"
                    f"<div class='wolf-title'>{self.severity_badge(sev)} {title}</div>"
                    f"<div class='wolf-meta'>Customer: {customer} | Agent: {agent}</div>"
                )
                if desc:
                    parts.append(f"<div class='text-small mt-8'>{desc}</div>")
                if quote:
                    parts.append(f"<div class='wolf-quote'>&ldquo;{quote}&rdquo;</div>")
                parts.append("</div>")

        parts.append("</section>")
        return "\n".join(parts)
