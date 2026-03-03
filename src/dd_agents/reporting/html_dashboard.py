"""Dashboard renderer — executive summary with deal-level KPIs (Issue #100)."""

from __future__ import annotations

import difflib
import html
from collections import defaultdict
from typing import Any

from dd_agents.reporting.html_base import DOMAIN_DISPLAY, SEVERITY_COLORS, SectionRenderer

_SIMILARITY_THRESHOLD = 0.7


def _dedup_similar_findings(findings: list[dict[str, Any]]) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    """Group findings with >0.7 title similarity via SequenceMatcher.

    Returns list of (primary_finding, [similar_findings]).
    """
    if not findings:
        return []
    groups: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    used: set[int] = set()

    for i, f in enumerate(findings):
        if i in used:
            continue
        primary = f
        similar: list[dict[str, Any]] = []
        title_i = str(f.get("title", ""))
        for j in range(i + 1, len(findings)):
            if j in used:
                continue
            title_j = str(findings[j].get("title", ""))
            ratio = difflib.SequenceMatcher(None, title_i, title_j).ratio()
            if ratio > _SIMILARITY_THRESHOLD:
                similar.append(findings[j])
                used.add(j)
        groups.append((primary, similar))
        used.add(i)
    return groups


class DashboardRenderer(SectionRenderer):
    """Render the deal header, key metrics strip, deal breakers (P0), and key risks (P1)."""

    def render(self) -> str:
        parts: list[str] = []
        parts.append(self._render_deal_header())
        parts.append(self._render_key_metrics())
        parts.append(self._render_wolf_pack())
        parts.append(self._render_key_risks())
        return "\n".join(p for p in parts if p)

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

        cards.append(_card(self.data.total_customers, "Entities"))
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
        """Render Deal Breakers: P0 only, with similarity dedup."""
        p0 = self.data.wolf_pack_p0
        has_any = bool(p0) or any(f.get("severity") == "P1" for f in self.data.wolf_pack)

        parts: list[str] = [
            "<section class='wolf-pack report-section' id='sec-wolf-pack'>",
            f"<h2>Deal Breakers ({len(p0)})</h2>",
        ]

        if not has_any:
            parts.append("<p class='text-muted'>No P0 or P1 findings detected. No immediate deal-breaker risks.</p>")
        elif not p0:
            parts.append("<p class='text-muted'>No P0 findings. See Key Risks below for P1 issues.</p>")
        else:
            groups = _dedup_similar_findings(p0)
            for primary, similar in groups:
                parts.append(self._render_wolf_card(primary, len(similar)))

        parts.append("</section>")
        return "\n".join(parts)

    def _render_key_risks(self) -> str:
        """Render Key Risks: P1 findings grouped by domain in a collapsed accordion."""
        p1 = [f for f in self.data.wolf_pack if f.get("severity") == "P1"]
        if not p1:
            return ""

        parts: list[str] = [
            "<section class='report-section' id='sec-key-risks'>",
            f"<h2>Key Risks ({len(p1)})</h2>",
        ]

        by_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for f in p1:
            domain = self.agent_to_domain(str(f.get("agent", "")))
            by_domain[domain].append(f)

        for domain, domain_findings in sorted(by_domain.items()):
            display = DOMAIN_DISPLAY.get(domain, domain)
            parts.append(
                f"<div class='domain-section'>"
                f"<div class='domain-header' tabindex='0' role='button' aria-expanded='false'>"
                f"<h2>{html.escape(display)} "
                f"<span class='severity-badge' style='background:#fd7e14;color:#333'>{len(domain_findings)}</span></h2>"
                f"<span class='arrow'>&#9654;</span></div>"
                f"<div class='domain-body'>"
            )
            groups = _dedup_similar_findings(domain_findings)
            for primary, similar in groups:
                parts.append(self._render_wolf_card(primary, len(similar)))
            parts.append("</div></div>")

        parts.append("</section>")
        return "\n".join(parts)

    def _render_wolf_card(self, f: dict[str, Any], similar_count: int = 0) -> str:
        """Render a single wolf-card for a finding, with optional similar badge."""
        sev = f.get("severity", "P3")
        color = SEVERITY_COLORS.get(sev, "#ccc")
        title = html.escape(str(f.get("title", "Untitled")))
        customer = html.escape(str(f.get("_customer", "")))
        agent = html.escape(str(f.get("agent", "")))
        desc = html.escape(str(f.get("description", "")))

        similar_badge = ""
        if similar_count > 0:
            similar_badge = (
                f" <span class='severity-badge' style='background:#e9ecef;color:#333'>+{similar_count} similar</span>"
            )

        quote = ""
        citations = f.get("citations", [])
        if citations and isinstance(citations, list):
            first_cit = citations[0]
            if isinstance(first_cit, dict):
                q = first_cit.get("exact_quote", "")
                if q:
                    quote = html.escape(str(q))

        parts: list[str] = [
            f"<div class='wolf-card' style='border-left-color:{color}' "
            f"data-severity='{html.escape(sev)}'>"
            f"<div class='wolf-title'>{self.severity_badge(sev)} {title}{similar_badge}</div>"
            f"<div class='wolf-meta'>Entity: {customer} | Agent: {agent}</div>"
        ]
        if desc:
            parts.append(f"<div class='text-small mt-8'>{desc}</div>")
        if quote:
            parts.append(f"<div class='wolf-quote'>&ldquo;{quote}&rdquo;</div>")
        parts.append("</div>")
        return "\n".join(parts)
