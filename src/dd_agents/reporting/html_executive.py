"""Executive summary renderer — hero zone with verdict, takeaways, domain grid.

Layer 1 of the report: answers 'should I worry?' in 5 seconds without
scrolling. Supports optional executive synthesis override and LLM-generated
narrative content for deal-specific context.
"""

from __future__ import annotations

from typing import Any

from dd_agents.reporting.html_base import (
    DOMAIN_COLORS,
    DOMAIN_DISPLAY,
    SectionRenderer,
    get_domain_agents,
)
from dd_agents.reporting.html_charts import render_donut_chart
from dd_agents.utils.constants import ALL_SEVERITIES, SEVERITY_P0

_VERDICT_SIGNAL_COLORS: dict[str, str] = {
    "NO-GO": "#dc3545",
    "CONDITIONAL": "#fd7e14",
    "PROCEED WITH CONDITIONS": "#ffc107",
    "PROCEED": "#28a745",
}

# Maps the raw deterministic verdict signal (verdict.py SIGNAL_*) to the
# reader-facing display vocabulary used on the badge. Ordered worst→best:
# No-Go > Proceed with Caution > Conditional Go > Go. CONDITIONAL is the MORE
# severe tier (P1>=3) so it reads "Proceed with Caution"; PROCEED WITH
# CONDITIONS (P1>=1) is milder and reads "Conditional Go" — matching the
# risk-label fallback in _resolve_verdict (High→Caution, Medium/Low→Conditional).
_VERDICT_DISPLAY_LABEL: dict[str, str] = {
    "NO-GO": "No-Go",
    "CONDITIONAL": "Proceed with Caution",
    "PROCEED WITH CONDITIONS": "Conditional Go",
    "PROCEED": "Go",
}


class ExecutiveSummaryRenderer(SectionRenderer):
    """Render the executive summary hero zone.

    Three-part structure:
    1. Deal context header + verdict card + key takeaways
    2. Domain risk grid (9 clickable cards)
    3. Open items + financial exposure + config guidance
    """

    def render(self) -> str:
        parts: list[str] = [
            "<section class='report-section hero-zone' id='sec-executive'>",
            "<h2>Executive Summary</h2>",
        ]

        parts.append(self._render_deal_header())
        parts.append(self._render_hero_verdict())
        parts.append(self._render_kpi_strip())
        parts.append(self._render_executive_takeaways())
        parts.append(self._render_domain_grid())
        parts.append(self._render_top_deal_breakers())
        parts.append(self._render_open_items())
        parts.append(self._render_config_guidance())

        parts.append("</section>")
        return "\n".join(p for p in parts if p)

    # ------------------------------------------------------------------
    # Deal Header
    # ------------------------------------------------------------------

    def _render_deal_header(self) -> str:
        """Render deal context: buyer → target, deal type, date."""
        config = self.config.get("_deal_config")
        if not config or not isinstance(config, dict):
            return ""

        buyer_name = ""
        target_name = ""
        deal_type = ""

        buyer = config.get("buyer")
        if buyer and isinstance(buyer, dict):
            buyer_name = str(buyer.get("name", ""))
        target = config.get("target")
        if target and isinstance(target, dict):
            target_name = str(target.get("name", ""))
        deal_info = config.get("deal_info")
        if deal_info and isinstance(deal_info, dict):
            deal_type = str(deal_info.get("type", ""))

        if not buyer_name and not target_name:
            return ""

        parts: list[str] = ["<div class='deal-header'>"]
        if buyer_name and target_name:
            parts.append(
                f"<span class='deal-parties'>{self.escape(buyer_name)} "
                f"<span class='deal-arrow'>&rarr;</span> "
                f"{self.escape(target_name)}</span>"
            )
        elif target_name:
            parts.append(f"<span class='deal-parties'>{self.escape(target_name)}</span>")

        if deal_type:
            parts.append(f"<span class='deal-type'>{self.escape(deal_type.replace('_', ' ').title())}</span>")

        # Deal context from narrative (if available)
        narrative = self._get_narrative()
        if narrative:
            deal_ctx = narrative.get("deal_context", {})
            summary = str(deal_ctx.get("summary", "")).strip() if isinstance(deal_ctx, dict) else ""
            if summary:
                parts.append(f"<p class='deal-context-summary'>{self.escape(summary)}</p>")

        parts.append("</div>")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Hero Verdict
    # ------------------------------------------------------------------

    def _render_hero_verdict(self) -> str:
        """Render verdict card with integrated executive assessment.

        Merges the LLM executive narrative directly into the verdict block
        so readers get both the signal AND the reasoning in one place.
        """
        signal, signal_color, signal_desc, score, label = self._resolve_verdict()

        # Get the executive narrative (from synthesis)
        narrative_text = ""
        es = self._get_synthesis()
        if es:
            narrative_text = str(es.get("executive_narrative", "")).strip()

        # Build the verdict body: rationale + narrative (if both exist)
        body_parts: list[str] = []
        if signal_desc:
            body_parts.append(f"<div class='hero-verdict-rationale'>{self.escape(signal_desc)}</div>")
        if narrative_text and narrative_text != signal_desc:
            body_parts.append(f"<div class='hero-verdict-narrative'>{self.escape(narrative_text)}</div>")

        # Contributing factors (only show if no narrative provides richer context)
        if not narrative_text:
            raw_factors = self.data.verdict.get("contributing_factors", []) if self.data.verdict else []
            factors = raw_factors if isinstance(raw_factors, list) else []
            if factors:
                items = "".join(f"<li>{self.escape(str(f))}</li>" for f in factors[:5])
                body_parts.append(f"<ul class='verdict-factors'>{items}</ul>")

        body_html = "\n".join(body_parts)

        return (
            f"<div class='hero-verdict' style='--verdict-color:{signal_color}'>"
            f"<div class='hero-verdict-signal'>{self.escape(signal)}</div>"
            f"<div class='hero-verdict-score'>"
            f"Risk Score: {score:.0f}/100 &mdash; {self.escape(label)}</div>"
            f"{body_html}"
            f"</div>"
        )

    # ------------------------------------------------------------------
    # KPI Strip (Issue #197)
    # ------------------------------------------------------------------

    _KPI_INTENT_COLORS: dict[str, str] = {
        "critical": "#dc3545",
        "good": "#28a745",
        "neutral": "#1a1a2e",
    }

    def _render_kpi_strip(self) -> str:
        """Render the Layer-1 headline KPI strip (3-5 compact metrics)."""
        kpis = self.data.dashboard_kpis
        if not kpis:
            return ""
        cards: list[str] = []
        for kpi in kpis:
            intent = str(kpi.get("intent", "neutral"))
            color = self._KPI_INTENT_COLORS.get(intent, "#1a1a2e")
            label = self.escape(str(kpi.get("label", "")))
            value = self.escape(str(kpi.get("value", "")))
            cards.append(
                f"<div class='metric-card'><div class='value' style='color:{color}'>"
                f"{value}</div><div class='label'>{label}</div></div>"
            )
        return f"<div class='metrics-strip' id='sec-kpi-strip'>{''.join(cards)}</div>"

    # ------------------------------------------------------------------
    # Key Takeaways
    # ------------------------------------------------------------------

    def _render_executive_takeaways(self) -> str:
        """Render key takeaways as full sentences.

        Priority: narrative-generated takeaways > deterministic takeaways.
        """
        # Try narrative-enhanced takeaways first
        narrative = self._get_narrative()
        if narrative:
            deal_ctx = narrative.get("deal_context", {})
            if isinstance(deal_ctx, dict) and deal_ctx.get("buyer_thesis_alignment"):
                thesis_note = str(deal_ctx["buyer_thesis_alignment"]).strip()
                if thesis_note:
                    pass  # Will include below

        takeaways = self.data.executive_takeaways
        if not takeaways:
            return ""

        severity_icons: dict[str, str] = {
            "critical": "&#9650;",
            "high": "&#9679;",
            "medium": "&#9670;",
            "good": "&#9675;",
        }
        severity_colors: dict[str, str] = {
            "critical": "var(--red, #dc3545)",
            "high": "var(--orange, #fd7e14)",
            "medium": "var(--yellow, #ffc107)",
            "good": "var(--green, #28a745)",
        }

        parts: list[str] = [
            "<div class='hero-takeaways'>",
            "<h3>Key Takeaways</h3>",
            "<ol class='takeaway-list'>",
        ]

        for ta in takeaways:
            text = self.escape(str(ta.get("text", "")))
            sev = str(ta.get("severity", "medium"))
            icon = severity_icons.get(sev, "&#9670;")
            color = severity_colors.get(sev, "#ffc107")
            domains = self.escape(str(ta.get("domains", "")))
            parts.append(
                f"<li>"
                f"<span class='takeaway-icon' style='color:{color}'>{icon}</span> "
                f"<span class='takeaway-text'>{text}</span>"
                f" <span class='takeaway-domains'>({domains})</span>"
                f"</li>"
            )

        parts.extend(["</ol>", "</div>"])
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Domain Risk Grid
    # ------------------------------------------------------------------

    def _render_domain_grid(self) -> str:
        """Render domain risk as a compact strip — one row per domain with severity bar."""
        # Only show domains that have findings or are in the active set
        active_domains = [
            d
            for d in get_domain_agents()
            if sum(self.data.domain_severity.get(d, {}).get(s, 0) for s in ALL_SEVERITIES) > 0
        ]
        clean_domains = [d for d in get_domain_agents() if d not in [ad for ad in active_domains]]

        max_findings = max(
            (sum(self.data.domain_severity.get(d, {}).get(s, 0) for s in ALL_SEVERITIES) for d in get_domain_agents()),
            default=1,
        )
        max_findings = max(max_findings, 1)

        parts: list[str] = []

        # At-a-glance severity donut (Issue #199) — complements the per-domain strip.
        donut = render_donut_chart(self.data.material_by_severity, title="Severity Distribution")
        if donut:
            parts.append(f"<div class='hero-donut'>{donut}</div>")

        parts.append("<div class='domain-strip'>")

        for domain in active_domains:
            display = DOMAIN_DISPLAY.get(domain, domain.capitalize())
            sev_counts = self.data.domain_severity.get(domain, {})
            risk_label = self.data.domain_risk_labels.get(domain, "Clean")
            total = sum(sev_counts.get(s, 0) for s in ALL_SEVERITIES)
            domain_color = DOMAIN_COLORS.get(domain, "#333")

            risk_color = "#28a745"
            if risk_label in ("High", "Critical"):
                risk_color = "#dc3545"
            elif risk_label in ("Medium", "Moderate"):
                risk_color = "#fd7e14"
            elif risk_label == "Low":
                risk_color = "#ffc107"

            # Build mini severity segments
            bar_segments = ""
            bar_label_parts: list[str] = []
            for sev in ALL_SEVERITIES:
                count = sev_counts.get(sev, 0)
                if count > 0:
                    from dd_agents.reporting.html_base import SEVERITY_COLORS

                    seg_pct = (count / max_findings) * 100
                    seg_color = SEVERITY_COLORS.get(sev, "#6c757d")
                    bar_segments += f"<span style='width:{seg_pct:.0f}%;background:{seg_color}'></span>"
                    bar_label_parts.append(f"{sev}: {count}")
            # Non-color equivalent for the color-only severity bar (a11y, Issue #199).
            bar_aria = f"Severity distribution: {', '.join(bar_label_parts)}" if bar_label_parts else "No findings"

            parts.append(
                f"<a class='domain-row' href='#sec-domain-{self.escape(domain)}' "
                f"style='--domain-color:{domain_color}'>"
                f"<span class='domain-row-name'>{self.escape(display)}</span>"
                f"<span class='domain-row-bar' role='img' "
                f"aria-label='{self.escape(bar_aria)}'>{bar_segments}</span>"
                f"<span class='domain-row-badge' style='color:{risk_color}'>"
                f"{self.escape(risk_label)}</span>"
                f"<span class='domain-row-count'>{total}</span>"
                f"</a>"
            )

        # Show clean domains as a compact summary
        if clean_domains:
            clean_names = ", ".join(DOMAIN_DISPLAY.get(d, d.capitalize()) for d in clean_domains)
            parts.append(
                f"<div class='domain-row domain-row--clean'>"
                f"<span class='domain-row-name'>{self.escape(clean_names)}</span>"
                f"<span class='domain-row-bar'></span>"
                f"<span class='domain-row-badge' style='color:#28a745'>Clean</span>"
                f"<span class='domain-row-count'>0</span>"
                f"</div>"
            )

        parts.append("</div>")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Open Items Panel
    # ------------------------------------------------------------------

    def _render_open_items(self) -> str:
        """Render open items from narrative: data gaps, needs counsel, cost TBD."""
        narrative = self._get_narrative()
        if not narrative:
            return ""

        open_questions = narrative.get("open_questions", [])
        if not open_questions or not isinstance(open_questions, list):
            return ""

        by_category: dict[str, list[dict[str, Any]]] = {}
        for q in open_questions:
            if not isinstance(q, dict):
                continue
            cat = str(q.get("category", "data_gap"))
            by_category.setdefault(cat, []).append(q)

        category_labels: dict[str, str] = {
            "data_gap": "Needs More Data",
            "needs_counsel": "Needs Counsel",
            "needs_auditor": "Needs Auditor",
            "cost_estimate": "Cost TBD",
            "decision_required": "Decision Required",
        }
        category_icons: dict[str, str] = {
            "data_gap": "&#128269;",
            "needs_counsel": "&#9878;",
            "needs_auditor": "&#128200;",
            "cost_estimate": "&#128176;",
            "decision_required": "&#9888;",
        }

        parts: list[str] = [
            "<div class='open-items-panel'>",
            "<h3>Open Items</h3>",
            "<div class='open-items-grid'>",
        ]

        for cat, items in by_category.items():
            label = category_labels.get(cat, cat.replace("_", " ").title())
            icon = category_icons.get(cat, "&#8226;")
            high_priority = sum(1 for i in items if isinstance(i, dict) and i.get("priority") == "high")

            parts.append(
                f"<div class='open-item-card'>"
                f"<div class='open-item-icon'>{icon}</div>"
                f"<div class='open-item-count'>{len(items)}</div>"
                f"<div class='open-item-label'>{self.escape(label)}</div>"
            )
            if high_priority:
                parts.append(f"<div class='open-item-urgent'>{high_priority} urgent</div>")
            parts.append("</div>")

        parts.extend(["</div>", "</div>"])
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Executive Narrative
    # ------------------------------------------------------------------

    def _render_executive_narrative(self) -> str:
        """Render the executive narrative prose section."""
        es = self._get_synthesis()
        if not es:
            return ""
        narrative_text = str(es.get("executive_narrative", "")).strip()
        if not narrative_text:
            return ""

        return (
            "<div class='executive-narrative'>"
            "<h3>Executive Assessment</h3>"
            f"<div class='narrative-body'>{self.escape(narrative_text)}</div>"
            "</div>"
        )

    # ------------------------------------------------------------------
    # Financial Exposure
    # ------------------------------------------------------------------

    def _render_financial_exposure(self) -> str:
        """Render de-duplicated financial exposure summary table."""
        exposure = self.data.financial_exposure_summary
        if not exposure or self.data.total_contracted_arr <= 0:
            return ""

        from dd_agents.reporting.html_base import fmt_currency

        parts: list[str] = [
            "<h3>Financial Exposure Summary</h3>",
            "<table class='subject-table sortable'><caption>Financial exposure summary</caption><thead><tr>",
            "<th scope='col'>Risk Category</th>",
            "<th scope='col'>Estimated Impact</th>",
            "<th scope='col'>Confidence</th>",
            "<th scope='col'>Contracts</th>",
            "<th scope='col'>Source Domains</th>",
            "</tr></thead><tbody>",
        ]

        for item in exposure:
            category = self.escape(str(item.get("category", "")))
            impact = item.get("estimated_impact", 0.0)
            confidence = self.escape(str(item.get("confidence", "Low")))
            contracts = item.get("contract_count", 0)
            domains = self.escape(", ".join(item.get("source_domains", [])))
            parts.append(
                f"<tr><td>{category}</td>"
                f"<td>{fmt_currency(impact)}</td>"
                f"<td>{confidence}</td>"
                f"<td>{contracts}</td>"
                f"<td>{domains}</td></tr>"
            )

        parts.append("</tbody></table>")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Deal Breakers
    # ------------------------------------------------------------------

    def _render_top_deal_breakers(self) -> str:
        """Render top deal breakers with narrative enhancement."""
        es = self._get_synthesis()
        ranked = (es.get("deal_breakers_ranked") or []) if es else []

        if ranked:
            return self._render_synthesis_deal_breakers(ranked)
        return self._render_mechanical_deal_breakers()

    def _render_synthesis_deal_breakers(self, ranked: list[dict[str, Any]]) -> str:
        if not ranked:
            return ""

        parts: list[str] = ["<h3>Top Deal Breakers</h3>", "<ol class='deal-breaker-list'>"]
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
        top = self.data.material_wolf_pack_p0[:5]
        if not top:
            return ""

        parts: list[str] = ["<h3>Top Deal Breakers</h3>", "<ol class='deal-breaker-list'>"]
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

    # ------------------------------------------------------------------
    # Key Metrics
    # ------------------------------------------------------------------

    def _render_key_metrics(self) -> str:
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

    # ------------------------------------------------------------------
    # Config Guidance
    # ------------------------------------------------------------------

    def _render_config_guidance(self) -> str:
        """Show guidance when deal config is minimal (no buyer_strategy)."""
        config = self.config.get("_deal_config")
        has_buyer_strategy = bool(config and isinstance(config, dict) and config.get("buyer_strategy"))
        if has_buyer_strategy:
            return ""

        # Use narrative-generated guidance if available
        narrative = self._get_narrative()
        guidance = ""
        if narrative and isinstance(narrative, dict):
            guidance = str(narrative.get("config_guidance", "")).strip()

        if not guidance:
            guidance = (
                "For deal-specific insights (thesis alignment, integration risk scoring, "
                "negotiation guidance), add a buyer_strategy section to your deal config. "
                "This enriches the report with buyer-contextualized recommendations and "
                "risk assessments tailored to your acquisition thesis."
            )

        return (
            "<div class='config-guidance'>"
            "<div class='config-guidance-icon'>&#128161;</div>"
            "<div class='config-guidance-body'>"
            f"<strong>Enhance this report</strong> &mdash; {self.escape(guidance)} "
            "See <code>docs/user-guide/deal-configuration.md</code> for details."
            "</div></div>"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_synthesis(self) -> dict[str, Any] | None:
        es = self.data.executive_synthesis
        if es and isinstance(es, dict):
            return es
        return None

    def _get_narrative(self) -> dict[str, Any] | None:
        narr = self.data.narrative
        if narr and isinstance(narr, dict):
            return narr
        return None

    def _resolve_verdict(self) -> tuple[str, str, str, float, str]:
        """Return (signal, color, description, score, label).

        The badge is DETERMINISTIC: the displayed signal, color, and score are
        driven by `data.verdict` (verdict.py:compute_verdict) — never by the LLM.
        The LLM rationale/narrative is surfaced only as supporting text beneath
        the badge (see _render_hero_verdict). This guarantees the headline
        Go/No-Go a reader sees is reproducible and auditable, not a model opinion.

        Falls back to a risk-label heuristic only when no deterministic verdict
        is present (e.g. legacy data).
        """
        if self.data.verdict and self.data.verdict.get("signal"):
            raw_signal = str(self.data.verdict["signal"])
            signal = _VERDICT_DISPLAY_LABEL.get(raw_signal, raw_signal)
            signal_color = _VERDICT_SIGNAL_COLORS.get(raw_signal, "#ffc107")
            signal_desc = str(self.data.verdict.get("rationale", ""))
            score = self.data.deal_risk_score
            label = self.data.deal_risk_label
        else:
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
            elif label in ("Medium", "Low"):
                signal = "Conditional Go"
                signal_color = "#ffc107"
                signal_desc = "Moderate risks identified. Standard due diligence conditions apply."
            else:
                signal = "Go"
                signal_color = "#28a745"
                signal_desc = "No material risks identified. Deal fundamentals are sound."

        return signal, signal_color, signal_desc, score, label
