"""Base class, constants, CSS, JS, and shared helpers for HTML report renderers.

Every section renderer inherits ``SectionRenderer`` and calls shared helpers
for severity badges, bar charts, finding cards, citations, and HTML escaping.
CSS and JS live here as the single source of truth.
"""

from __future__ import annotations

import html as _html
import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dd_agents.reporting.computed_metrics import ReportComputedData

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (shared across all renderers)
# ---------------------------------------------------------------------------

SEVERITY_COLORS: dict[str, str] = {
    "P0": "#dc3545",
    "P1": "#fd7e14",
    "P2": "#ffc107",
    "P3": "#6c757d",
}

SEVERITY_BG: dict[str, str] = {
    "P0": "#fff5f5",
    "P1": "#fff8f0",
    "P2": "#fffdf0",
    "P3": "#f8f9fa",
}

SEVERITY_LABELS: dict[str, str] = {
    "P0": "Critical",
    "P1": "High",
    "P2": "Medium",
    "P3": "Low",
}

DOMAIN_AGENTS: list[str] = ["legal", "finance", "commercial", "producttech"]

DOMAIN_DISPLAY: dict[str, str] = {
    "legal": "Legal",
    "finance": "Finance",
    "commercial": "Commercial",
    "producttech": "Product & Tech",
}

DOMAIN_COLORS: dict[str, str] = {
    "legal": "#4a90d9",
    "finance": "#2d8a4e",
    "commercial": "#7c3aed",
    "producttech": "#d97706",
}


# ---------------------------------------------------------------------------
# SectionRenderer ABC
# ---------------------------------------------------------------------------


class SectionRenderer(ABC):
    """Abstract base class for all HTML report section renderers."""

    def __init__(
        self, data: ReportComputedData, merged_data: dict[str, Any], config: dict[str, Any] | None = None
    ) -> None:
        self.data = data
        self.merged_data = merged_data
        self.config = config or {}

    @abstractmethod
    def render(self) -> str:
        """Return HTML string for this section."""

    # -- Shared helpers -------------------------------------------------------

    @staticmethod
    def escape(text: str) -> str:
        """HTML-escape a string."""
        return _html.escape(str(text))

    @staticmethod
    def severity_badge(severity: str) -> str:
        """Render a colored severity badge."""
        color = SEVERITY_COLORS.get(severity, "#6c757d")
        extra_cls = " sev-p1" if severity == "P1" else (" sev-p2" if severity == "P2" else "")
        return f"<span class='severity-badge{extra_cls}' style='background:{color}'>{_html.escape(severity)}</span>"

    @staticmethod
    def risk_color(risk: str) -> str:
        """Color for a risk rating label."""
        return {
            "Critical": "#dc3545",
            "High": "#fd7e14",
            "Medium": "#ffc107",
            "Low": "#6c757d",
            "Clean": "#28a745",
        }.get(risk, "#6c757d")

    @staticmethod
    def domain_risk(sev: dict[str, int]) -> str:
        """Compute risk label from severity distribution."""
        if sev.get("P0", 0) > 0:
            return "Critical"
        if sev.get("P1", 0) > 0:
            return "High"
        if sev.get("P2", 0) > 0:
            return "Medium"
        if sev.get("P3", 0) > 0:
            return "Low"
        return "Clean"

    @staticmethod
    def agent_to_domain(agent: str) -> str:
        """Map an agent name to one of the 4 domains."""
        agent = agent.lower().strip()
        if agent in DOMAIN_AGENTS:
            return agent
        if "legal" in agent:
            return "legal"
        if "financ" in agent:
            return "finance"
        if "commerc" in agent:
            return "commercial"
        if "product" in agent or "tech" in agent:
            return "producttech"
        return "legal"

    def render_finding_card(self, finding: Any) -> str:
        """Render a collapsible finding card."""
        if not isinstance(finding, dict):
            return ""
        severity = str(finding.get("severity", "P3"))
        color = SEVERITY_COLORS.get(severity, "#ccc")
        title = self.escape(str(finding.get("title", "Untitled")))
        customer = self.escape(str(finding.get("_customer", finding.get("customer", ""))))
        agent = self.escape(str(finding.get("agent", "")))

        return (
            f"<div class='finding-card' style='border-left-color:{color}' "
            f"data-severity='{self.escape(severity)}' data-domain='{self.escape(self.agent_to_domain(agent))}' "
            f"tabindex='0' role='button' aria-expanded='false'>"
            f"<div class='fc-title'>{self.severity_badge(severity)} {title} "
            f"<span class='arrow'>&#9654;</span></div>"
            f"<div class='fc-meta'>Customer: {customer} | Agent: {agent}</div>"
            f"</div>"
        )

    def render_finding_detail(self, finding: Any) -> str:
        """Render expanded finding detail with description, badges, and citations."""
        if not isinstance(finding, dict):
            return ""
        severity = str(finding.get("severity", "P3"))
        color = SEVERITY_COLORS.get(severity, "#ccc")
        description = self.escape(str(finding.get("description", "")))
        confidence = str(finding.get("confidence", ""))
        verification = str(finding.get("verification_status", finding.get("verified", "")))
        detection = str(finding.get("detection_method", ""))

        parts: list[str] = [f"<div class='finding-detail' style='border-left-color:{color}'>"]

        if description:
            parts.append(f"<div class='fd-description'>{description}</div>")

        badges: list[str] = []
        if confidence:
            badges.append(f"<span class='text-small'>Confidence: <strong>{self.escape(confidence)}</strong></span>")
        if verification:
            vb_class = (
                "vb-verified"
                if verification.lower() in ("verified", "true")
                else ("vb-failed" if verification.lower() in ("failed", "false") else "vb-unchecked")
            )
            badges.append(f"<span class='verification-badge {vb_class}'>{self.escape(verification)}</span>")
        if detection:
            badges.append(f"<span class='text-small text-muted'>Detection: {self.escape(detection)}</span>")
        if badges:
            parts.append(f"<div class='fd-badges'>{''.join(badges)}</div>")

        for cit in finding.get("citations", []):
            parts.append(self.render_citation(cit))

        parts.append("</div>")
        return "\n".join(parts)

    def render_citation(self, citation: Any) -> str:
        """Render a citation block."""
        if not isinstance(citation, dict):
            return ""
        source = self.escape(str(citation.get("source_path", "")))
        section = citation.get("section_ref", citation.get("section", ""))
        page = citation.get("page", "")
        location = citation.get("location", "")
        quote = citation.get("exact_quote", "")

        loc_parts: list[str] = []
        if section:
            loc_parts.append(str(section))
        if page:
            loc_parts.append(f"p.{page}")
        if location and not loc_parts:
            loc_parts.append(str(location))
        loc_str = ", ".join(loc_parts)

        parts: list[str] = ["<div class='citation'>"]
        parts.append(f"<span class='source'>{source}</span>")
        if loc_str:
            parts.append(f" <span class='location'>({self.escape(loc_str)})</span>")
        if quote:
            parts.append(f"<span class='quote'>&ldquo;{self.escape(str(quote))}&rdquo;</span>")
        parts.append("</div>")
        return "".join(parts)

    def render_empty_state(self, message: str) -> str:
        """Render an empty-state placeholder."""
        return f"<p class='text-muted'>{self.escape(message)}</p>"

    def render_bar_chart(self, items: list[tuple[str, float]], max_val: float | None = None) -> str:
        """Render a horizontal bar chart."""
        if not items:
            return ""
        if max_val is None:
            max_val = max(v for _, v in items) if items else 1
        max_val = max(max_val, 1)

        parts: list[str] = []
        for label, value in items:
            pct = (value / max_val) * 100
            parts.append(
                f"<div class='gov-bar-container'>"
                f"<span class='gov-label'>{self.escape(label)}</span>"
                f"<div style='flex:1;background:#e9ecef;border-radius:4px;height:16px'>"
                f"<div style='width:{pct:.0f}%;background:#4a90d9;height:100%;border-radius:4px'></div>"
                f"</div>"
                f"<span class='gov-pct'>{value:.0f}</span>"
                f"</div>"
            )
        return "\n".join(parts)

    def render_severity_bar(self, severity_counts: dict[str, int]) -> str:
        """Render a severity distribution bar with screen-reader text."""
        total = max(sum(severity_counts.values()), 1)
        # Screen-reader-accessible description
        sr_parts = [f"{s}: {severity_counts.get(s, 0)}" for s in ("P0", "P1", "P2", "P3") if severity_counts.get(s, 0)]
        sr_text = self.escape(", ".join(sr_parts) or "No findings")
        parts: list[str] = [f"<div class='sev-bar' role='img' aria-label='Severity distribution: {sr_text}'>"]
        for s in ("P0", "P1", "P2", "P3"):
            pct = (severity_counts.get(s, 0) / total) * 100
            if pct > 0:
                parts.append(f"<span style='width:{pct:.1f}%;background:{SEVERITY_COLORS[s]}'></span>")
        parts.append("</div>")
        return "".join(parts)

    def render_category_group(self, category: str, findings: list[dict[str, Any]]) -> str:
        """Render a collapsible category group with findings grouped by customer."""
        sev_counts: dict[str, int] = defaultdict(int)
        for f in findings:
            sev_counts[f.get("severity", "P3")] += 1
        sev_str = self.escape(", ".join(f"{k}:{v}" for k, v in sorted(sev_counts.items()) if v > 0))

        parts: list[str] = [
            "<div class='category-group'>",
            f"<div class='category-header' tabindex='0' role='button' aria-expanded='false'>"
            f"<span><strong>{self.escape(category)}</strong> ({len(findings)} findings, {sev_str})</span>"
            f"<span class='arrow'>&#9654;</span></div>",
            "<div class='category-body'>",
        ]

        by_customer: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for f in findings:
            by_customer[str(f.get("_customer", "Unknown"))].append(f)

        for cust, cust_findings in sorted(by_customer.items()):
            parts.append(f"<h3>{self.escape(cust)}</h3>")
            for f in cust_findings:
                parts.append(self.render_finding_card(f))
                parts.append(self.render_finding_detail(f))

        parts.extend(["</div>", "</div>"])
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------


def render_css() -> str:
    """Return the full CSS for the report."""
    return """
/* Reset & base */
*, *::before, *::after { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       margin: 0; padding: 0; background: #f4f5f7; color: #1a1a2e; line-height: 1.5; }

/* Navigation */
.nav-bar { position: sticky; top: 0; z-index: 1000; background: #1a1a2e; color: white;
           display: flex; align-items: center; gap: 0; padding: 0 16px;
           box-shadow: 0 2px 8px rgba(0,0,0,0.15); flex-wrap: wrap; }
.nav-bar a { color: #a8b2d1; text-decoration: none; padding: 12px 14px; font-size: 0.85em;
             transition: color 0.2s, background 0.2s; white-space: nowrap; }
.nav-bar a:hover, .nav-bar a.active { color: white; background: rgba(255,255,255,0.1); }
.nav-brand { font-weight: 700; font-size: 0.95em; color: white !important; margin-right: 8px; }

/* Filter bar */
.filter-bar { background: white; border-bottom: 1px solid #e0e0e0; padding: 10px 24px;
              display: flex; gap: 16px; align-items: center; flex-wrap: wrap; }
.filter-bar label { font-size: 0.85em; color: #555; cursor: pointer; display: flex; align-items: center; gap: 4px; }
.filter-bar input[type="text"] { padding: 6px 12px; border: 1px solid #ccc; border-radius: 4px;
                                  font-size: 0.85em; width: 220px; }
.filter-group { display: flex; gap: 8px; align-items: center; }
.filter-group-label { font-size: 0.8em; font-weight: 600; color: #333;
                      text-transform: uppercase; letter-spacing: 0.5px; }
.btn-sm { padding: 5px 12px; font-size: 0.8em; border: 1px solid #ccc; background: white;
          border-radius: 4px; cursor: pointer; }
.btn-sm:hover { background: #f0f0f0; }

/* Content wrapper */
.content { max-width: 1400px; margin: 0 auto; padding: 24px; }

/* Report sections */
.report-section { margin-bottom: 32px; }
.report-section > h2 { color: #1a1a2e; font-size: 1.3em; border-bottom: 2px solid #1a1a2e;
                        padding-bottom: 8px; margin-bottom: 16px; }

/* Deal header */
.deal-header { background: linear-gradient(135deg, #1a1a2e, #16213e); color: white;
               padding: 32px; border-radius: 12px; margin-bottom: 24px; }
.deal-header h1 { margin: 0 0 8px; font-size: 1.8em; }
.deal-header .deal-meta { color: #a8b2d1; font-size: 0.95em; }
.deal-header .risk-badge { display: inline-block; padding: 6px 20px; border-radius: 20px;
                           font-weight: 700; font-size: 1.1em; margin-top: 12px; }
.deal-header .run-id { color: #6c7a96; font-size: 0.8em; margin-top: 8px; }

/* Key metrics strip */
.metrics-strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
                 gap: 12px; margin-bottom: 24px; }
.metric-card { background: white; border-radius: 8px; padding: 16px; text-align: center;
               box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.metric-card .value { font-size: 1.8em; font-weight: 700; }
.metric-card .label { color: #666; font-size: 0.8em; text-transform: uppercase; letter-spacing: 0.5px; }

/* Wolf pack */
.wolf-pack { margin-bottom: 24px; }
.wolf-pack h2 { color: #dc3545; }
.wolf-card { background: white; border-left: 5px solid; border-radius: 4px 8px 8px 4px;
             padding: 16px 20px; margin-bottom: 12px;
             box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
.wolf-card .wolf-title { font-weight: 700; font-size: 1.05em; margin-bottom: 4px; }
.wolf-card .wolf-meta { color: #666; font-size: 0.85em; }
.wolf-card .wolf-quote { background: #f8f9fa; padding: 8px 12px; margin-top: 8px;
                          border-radius: 4px; font-style: italic; color: #555; font-size: 0.9em; }

/* Heatmap */
.heatmap { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }
.heatmap-cell { background: white; border-radius: 8px; padding: 20px; text-align: center;
                box-shadow: 0 1px 3px rgba(0,0,0,0.08); cursor: pointer; transition: transform 0.15s, box-shadow 0.15s;
                border-top: 4px solid; }
.heatmap-cell:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.12); }
.heatmap-cell .domain-name { font-weight: 700; font-size: 1.1em; }
.heatmap-cell .domain-risk { font-size: 0.9em; margin: 6px 0; font-weight: 600; }
.heatmap-cell .domain-counts { font-size: 0.8em; color: #666; }

/* Domain sections */
.domain-section { background: white; border-radius: 8px; margin-bottom: 20px;
                  box-shadow: 0 1px 3px rgba(0,0,0,0.08); overflow: hidden; }
.domain-header { padding: 16px 24px; cursor: pointer; display: flex;
                 justify-content: space-between; align-items: center;
                 border-left: 5px solid; transition: background 0.15s; }
.domain-header:hover { background: #f8f9fa; }
.domain-header h2 { margin: 0; font-size: 1.15em; }
.domain-body { padding: 0 24px 20px; display: none; }
.domain-body.open { display: block; }

/* Severity distribution bar */
.sev-bar { display: flex; height: 8px; border-radius: 4px; overflow: hidden; margin: 8px 0; }
.sev-bar span { display: block; }

/* Category groups */
.category-group { border: 1px solid #e9ecef; border-radius: 6px; margin: 10px 0; overflow: hidden; }
.category-header { padding: 10px 16px; cursor: pointer; display: flex;
                   justify-content: space-between; align-items: center; background: #f8f9fa; }
.category-header:hover { background: #f0f1f3; }
.category-body { padding: 12px 16px; display: none; }
.category-body.open { display: block; }

/* Customer sections */
.customer-section { background: white; border-radius: 8px; margin: 12px 0;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.08); overflow: hidden; }
.customer-header { padding: 12px 20px; cursor: pointer; display: flex;
                   justify-content: space-between; align-items: center;
                   background: #e9ecef; transition: background 0.15s; }
.customer-header:hover { background: #dee2e6; }
.customer-body { padding: 16px 20px; display: none; }
.customer-body.open { display: block; }

/* Finding cards */
.finding-card { border-left: 4px solid #ccc; padding: 10px 14px; margin: 8px 0;
                background: #fafafa; border-radius: 0 6px 6px 0; cursor: pointer;
                transition: background 0.15s; }
.finding-card:hover { background: #f0f0f0; }
.finding-card .fc-title { font-weight: 600; }
.finding-card .fc-meta { color: #666; font-size: 0.85em; margin-top: 2px; }
.finding-detail { display: none; padding: 12px 14px; background: #f8f9fa;
                  border-left: 4px solid #ccc; margin: 0 0 8px; border-radius: 0 0 6px 0; }
.finding-detail.open { display: block; }
.finding-detail .fd-description { margin-bottom: 8px; }
.finding-detail .fd-badges { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }

/* Severity badge */
.severity-badge { display: inline-block; padding: 2px 10px; border-radius: 12px;
                  color: white; font-weight: 600; font-size: 0.8em; }
.severity-badge.sev-p1 { color: #333; }  /* Dark text on orange — WCAG AA contrast (4.9:1) */
.severity-badge.sev-p2 { color: #333; }  /* Dark text on yellow — WCAG AA contrast (12.6:1) */

/* Verification badge */
.verification-badge { display: inline-block; padding: 2px 10px; border-radius: 12px;
                      font-size: 0.75em; font-weight: 600; }
.vb-verified { background: #d4edda; color: #155724; }
.vb-failed { background: #f8d7da; color: #721c24; }
.vb-unchecked { background: #e9ecef; color: #495057; }

/* Citations */
.citation { background: #f0f0f0; padding: 10px 14px; margin: 6px 0; border-radius: 6px;
            font-size: 0.9em; border-left: 3px solid #a8b2d1; }
.citation .source { font-weight: 600; color: #1a1a2e; }
.citation .location { color: #666; font-size: 0.85em; }
.citation .quote { font-style: italic; color: #555; margin-top: 4px; padding: 6px 10px;
                   background: #e8e8e8; border-radius: 4px; display: block; }

/* Cross-reference */
.xref-mismatch { background: #fff5f5; border-left: 3px solid #dc3545; }
.xref-match { background: #f0fff0; }

/* Gap analysis */
.gap-summary-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }

/* Governance bars */
.gov-bar-container { display: flex; align-items: center; gap: 10px; margin: 4px 0; }
.gov-bar { height: 20px; border-radius: 4px; transition: width 0.3s; }
.gov-label { min-width: 150px; font-size: 0.9em; }
.gov-pct { font-size: 0.85em; font-weight: 600; min-width: 50px; }

/* Tables */
table.sortable { width: 100%; border-collapse: collapse; margin: 8px 0; font-size: 0.9em; }
table.sortable th, table.sortable td { padding: 8px 12px; border: 1px solid #dee2e6;
                                        text-align: left; }
table.sortable th { background: #e9ecef; cursor: pointer; user-select: none; white-space: nowrap; }
table.sortable th:hover { background: #dee2e6; }
table.sortable th::after { content: ' \\2195'; color: #aaa; font-size: 0.8em; }

/* Arrow toggle */
.arrow { font-size: 0.8em; transition: transform 0.2s; display: inline-block; }
.arrow.open { transform: rotate(90deg); }

/* Responsive */
@media (max-width: 900px) {
    .heatmap { grid-template-columns: repeat(2, 1fr); }
    .metrics-strip { grid-template-columns: repeat(2, 1fr); }
    .gap-summary-grid { grid-template-columns: 1fr; }
}
@media (max-width: 600px) {
    .heatmap { grid-template-columns: 1fr; }
    .content { padding: 12px; }
    .nav-bar { flex-wrap: nowrap; overflow-x: auto; }
}

/* Print mode */
@page { margin: 2cm 1.5cm; }
@media print {
    .nav-bar, .filter-bar, .skip-link { display: none !important; }
    .domain-body, .customer-body, .category-body, .finding-detail { display: block !important; }
    body { background: white; font-size: 11pt; orphans: 3; widows: 3; }
    .deal-header { background: #1a1a2e !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .severity-badge { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .sev-bar span { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .content { max-width: 100%; padding: 0; }
    .heatmap-cell, .metric-card, .finding-card, .wolf-card, .customer-section,
    .domain-section, .category-group, .citation, table.sortable { break-inside: avoid; }
    .report-section > h2 { break-after: avoid; }
    h3, h4 { break-after: avoid; }
    a[href^="http"]::after { content: " (" attr(href) ")"; font-size: 0.8em; color: #666;
                             word-break: break-all; }
    .nav-bar a::after { content: none !important; }
    .arrow { display: none !important; }
}

/* Accessibility: skip link */
.skip-link { position: absolute; top: -40px; left: 0; background: #1a1a2e; color: white;
             padding: 8px 16px; z-index: 10000; font-size: 0.9em; text-decoration: none;
             transition: top 0.15s; }
.skip-link:focus { top: 0; }

/* Accessibility: focus styles */
*:focus { outline: 2px solid #4a90d9; outline-offset: 2px; }
*:focus:not(:focus-visible) { outline: none; }
*:focus-visible { outline: 2px solid #4a90d9; outline-offset: 2px; }
.finding-card:focus-visible, .category-header:focus-visible,
.domain-header:focus-visible, .customer-header:focus-visible {
    outline: 2px solid #4a90d9; outline-offset: -2px; box-shadow: 0 0 0 3px rgba(74,144,217,0.3); }

/* Utility */
.hidden { display: none !important; }
.text-muted { color: #666; }
.text-small { font-size: 0.85em; }
.mt-8 { margin-top: 8px; }
.mb-8 { margin-bottom: 8px; }
.flex-between { display: flex; justify-content: space-between; align-items: center; }
"""


# ---------------------------------------------------------------------------
# JS
# ---------------------------------------------------------------------------


def render_js() -> str:
    """Return the full JavaScript for the report."""
    return """
(function() {
    'use strict';

    // --- Toggle collapsible sections (click + keyboard) ---
    function toggleSection(header) {
        var body = header.nextElementSibling;
        if (!body) return;
        var isOpen = body.classList.toggle('open');
        var arrow = header.querySelector('.arrow');
        if (arrow) arrow.classList.toggle('open');
        header.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    }
    function setupToggles(headerSel, bodySel) {
        document.querySelectorAll(headerSel).forEach(function(header) {
            header.addEventListener('click', function(e) {
                if (e.target.tagName === 'A') return;
                toggleSection(this);
            });
            header.addEventListener('keydown', function(e) {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    toggleSection(this);
                }
            });
        });
    }
    setupToggles('.customer-header', '.customer-body');
    setupToggles('.domain-header', '.domain-body');
    setupToggles('.category-header', '.category-body');

    // --- Finding card expand (click + keyboard) ---
    function toggleFinding(card) {
        var detail = card.nextElementSibling;
        if (detail && detail.classList.contains('finding-detail')) {
            var isOpen = detail.classList.toggle('open');
            var arrow = card.querySelector('.arrow');
            if (arrow) arrow.classList.toggle('open');
            card.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
        }
    }
    document.querySelectorAll('.finding-card').forEach(function(card) {
        card.addEventListener('click', function() { toggleFinding(this); });
        card.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                toggleFinding(this);
            }
        });
    });

    // --- Sortable tables ---
    document.querySelectorAll('table.sortable th').forEach(function(th) {
        th.addEventListener('click', function() {
            var table = this.closest('table');
            var tbody = table.querySelector('tbody');
            if (!tbody) return;
            var rows = Array.from(tbody.querySelectorAll('tr'));
            var col = Array.from(this.parentNode.children).indexOf(this);
            var asc = this.dataset.sort !== 'asc';
            rows.sort(function(a, b) {
                var va = (a.children[col] || {}).textContent || '';
                var vb = (b.children[col] || {}).textContent || '';
                va = va.trim(); vb = vb.trim();
                var na = parseFloat(va), nb = parseFloat(vb);
                if (!isNaN(na) && !isNaN(nb)) return asc ? na - nb : nb - na;
                return asc ? va.localeCompare(vb) : vb.localeCompare(va);
            });
            rows.forEach(function(row) { tbody.appendChild(row); });
            this.dataset.sort = asc ? 'asc' : 'desc';
        });
    });

    // --- Global search ---
    var searchInput = document.getElementById('global-search');
    if (searchInput) {
        searchInput.addEventListener('input', function() {
            var query = this.value.toLowerCase().trim();
            var sel = '.customer-section, .wolf-card, .finding-card, .finding-detail';
            document.querySelectorAll(sel).forEach(function(el) {
                if (!query) { el.classList.remove('hidden'); return; }
                var text = el.textContent.toLowerCase();
                if (text.indexOf(query) === -1) el.classList.add('hidden');
                else el.classList.remove('hidden');
            });
        });
    }

    // --- Severity filter ---
    document.querySelectorAll('.sev-filter').forEach(function(cb) {
        cb.addEventListener('change', function() {
            var active = {};
            document.querySelectorAll('.sev-filter').forEach(function(c) { active[c.value] = c.checked; });
            document.querySelectorAll('[data-severity]').forEach(function(el) {
                var sev = el.getAttribute('data-severity');
                if (active[sev] === false) el.classList.add('hidden');
                else el.classList.remove('hidden');
            });
        });
    });

    // --- Agent/domain filter ---
    document.querySelectorAll('.agent-filter').forEach(function(cb) {
        cb.addEventListener('change', function() {
            var active = {};
            document.querySelectorAll('.agent-filter').forEach(function(c) { active[c.value] = c.checked; });
            document.querySelectorAll('[data-domain]').forEach(function(el) {
                var dom = el.getAttribute('data-domain');
                if (active[dom] === false) el.classList.add('hidden');
                else el.classList.remove('hidden');
            });
        });
    });

    // --- Expand/collapse all ---
    var expandBtn = document.getElementById('btn-expand-all');
    var collapseBtn = document.getElementById('btn-collapse-all');
    var allSel = '.domain-body, .customer-body, .category-body, .finding-detail';
    if (expandBtn) {
        expandBtn.addEventListener('click', function() {
            document.querySelectorAll(allSel).forEach(function(el) {
                el.classList.add('open');
            });
            document.querySelectorAll('.arrow').forEach(function(a) { a.classList.add('open'); });
            document.querySelectorAll('[aria-expanded]').forEach(function(h) {
                h.setAttribute('aria-expanded', 'true');
            });
        });
    }
    if (collapseBtn) {
        collapseBtn.addEventListener('click', function() {
            document.querySelectorAll(allSel).forEach(function(el) {
                el.classList.remove('open');
            });
            document.querySelectorAll('.arrow').forEach(function(a) { a.classList.remove('open'); });
            document.querySelectorAll('[aria-expanded]').forEach(function(h) {
                h.setAttribute('aria-expanded', 'false');
            });
        });
    }

    // --- Sticky nav active highlight ---
    var sections = document.querySelectorAll('.report-section, .deal-header, .wolf-pack');
    var navLinks = document.querySelectorAll('.nav-bar a[href^="#"]');
    if (sections.length && navLinks.length) {
        window.addEventListener('scroll', function() {
            var scrollY = window.scrollY + 80;
            sections.forEach(function(sec) {
                if (!sec.id) return;
                if (sec.offsetTop <= scrollY && sec.offsetTop + sec.offsetHeight > scrollY) {
                    navLinks.forEach(function(l) {
                        l.classList.toggle('active', l.getAttribute('href') === '#' + sec.id);
                    });
                }
            });
        });
    }
})();
"""


# ---------------------------------------------------------------------------
# Navigation bar
# ---------------------------------------------------------------------------


def render_nav_bar() -> str:
    """Render the sticky navigation bar and filter bar with accessibility."""
    return (
        "<a href='#main-content' class='skip-link'>Skip to main content</a>"
        "<nav class='nav-bar' role='navigation' aria-label='Report sections'>"
        "<a href='#' class='nav-brand'>DD Report</a>"
        "<a href='#sec-wolf-pack'>Deal Breakers</a>"
        "<a href='#sec-heatmap'>Heatmap</a>"
        "<a href='#sec-domain-legal'>Legal</a>"
        "<a href='#sec-domain-finance'>Finance</a>"
        "<a href='#sec-domain-commercial'>Commercial</a>"
        "<a href='#sec-domain-producttech'>Product&amp;Tech</a>"
        "<a href='#sec-gaps'>Gaps</a>"
        "<a href='#sec-governance'>Governance</a>"
        "<a href='#sec-customers'>Customers</a>"
        "</nav>"
        "<div class='filter-bar' role='search' aria-label='Filter findings'>"
        "<input type='text' id='global-search' placeholder='Search all content...' aria-label='Search findings'>"
        "<div class='filter-group'>"
        "<span class='filter-group-label' id='sev-group-label'>Severity:</span>"
        "<div role='group' aria-labelledby='sev-group-label'>"
        "<label><input type='checkbox' class='sev-filter' value='P0' checked> P0</label>"
        "<label><input type='checkbox' class='sev-filter' value='P1' checked> P1</label>"
        "<label><input type='checkbox' class='sev-filter' value='P2' checked> P2</label>"
        "<label><input type='checkbox' class='sev-filter' value='P3' checked> P3</label>"
        "</div></div>"
        "<div class='filter-group'>"
        "<span class='filter-group-label' id='domain-group-label'>Domain:</span>"
        "<div role='group' aria-labelledby='domain-group-label'>"
        "<label><input type='checkbox' class='agent-filter' value='legal' checked> Legal</label>"
        "<label><input type='checkbox' class='agent-filter' value='finance' checked> Finance</label>"
        "<label><input type='checkbox' class='agent-filter' value='commercial' checked> Commercial</label>"
        "<label><input type='checkbox' class='agent-filter' value='producttech' checked> Product&amp;Tech</label>"
        "</div></div>"
        "<button class='btn-sm' id='btn-expand-all' aria-label='Expand all sections'>Expand All</button>"
        "<button class='btn-sm' id='btn-collapse-all' aria-label='Collapse all sections'>Collapse All</button>"
        "</div>"
        "<div class='content' role='main' id='main-content'>"
    )
