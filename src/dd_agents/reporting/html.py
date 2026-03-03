"""Self-contained interactive HTML report generator.

Generates a single HTML file with no external dependencies.
Top-down executive M&A decision-support report with progressive drill-down:

Level 0: Deal-Level Decision View (go/no-go signals)
  Level 1: Domain Analysis (Legal / Finance / Commercial / ProductTech)
    Level 2: Risk Categories within each domain
      Level 3: Per-Customer / Per-Entity findings
        Level 4: Individual findings with full citations

Features: wolf-pack deal-breaker alerts, domain heatmap, severity filtering,
global search, sortable tables, collapsible sections, print mode.
"""

from __future__ import annotations

import contextlib
import html
import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# Severity color palette (matches plan spec)
_SEVERITY_COLORS: dict[str, str] = {
    "P0": "#dc3545",
    "P1": "#fd7e14",
    "P2": "#ffc107",
    "P3": "#6c757d",
}

_SEVERITY_BG: dict[str, str] = {
    "P0": "#fff5f5",
    "P1": "#fff8f0",
    "P2": "#fffdf0",
    "P3": "#f8f9fa",
}

_SEVERITY_LABELS: dict[str, str] = {
    "P0": "Critical",
    "P1": "High",
    "P2": "Medium",
    "P3": "Low",
}

_DOMAIN_AGENTS: list[str] = ["legal", "finance", "commercial", "producttech"]

_DOMAIN_DISPLAY: dict[str, str] = {
    "legal": "Legal",
    "finance": "Finance",
    "commercial": "Commercial",
    "producttech": "Product & Tech",
}

_DOMAIN_COLORS: dict[str, str] = {
    "legal": "#4a90d9",
    "finance": "#2d8a4e",
    "commercial": "#7c3aed",
    "producttech": "#d97706",
}


class HTMLReportGenerator:
    """Generate a self-contained HTML due-diligence report."""

    def generate(
        self,
        merged_data: dict[str, Any],
        output_path: Path,
        *,
        run_id: str = "",
        title: str = "Due Diligence Report",
        run_metadata: dict[str, Any] | None = None,
        deal_config: dict[str, Any] | None = None,
    ) -> None:
        """Write the HTML report to *output_path*.

        Parameters
        ----------
        merged_data:
            ``{customer_safe_name: merged_customer_dict}``
        output_path:
            Destination file path.
        run_id:
            Pipeline run identifier for the header.
        title:
            Report title shown in the header.
        run_metadata:
            Pipeline run metadata (finding_counts, quality_scores, etc.).
        deal_config:
            Raw deal configuration dict (buyer, target, deal type, etc.).
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        agg = self._precompute_aggregates(merged_data)

        parts: list[str] = [
            "<!DOCTYPE html>",
            "<html lang='en'>",
            "<head>",
            f"<title>{html.escape(title)}</title>",
            "<meta charset='utf-8'>",
            "<meta name='viewport' content='width=device-width, initial-scale=1'>",
            f"<style>{self._render_css()}</style>",
            "</head>",
            "<body>",
            self._render_nav_bar(),
        ]

        parts.append(
            self._render_deal_header(
                title=title,
                run_id=run_id,
                deal_config=deal_config,
                agg=agg,
            )
        )
        parts.append(self._render_key_metrics(agg, run_metadata))
        parts.append(self._render_wolf_pack(agg))
        parts.append(self._render_deal_risk_heatmap(agg))

        for domain in _DOMAIN_AGENTS:
            parts.append(self._render_domain_section(domain, agg, merged_data))

        parts.append(self._render_gap_analysis(agg, merged_data))
        parts.append(self._render_cross_reference_section(merged_data))
        parts.append(self._render_governance_metrics(merged_data))
        parts.append(self._render_quality_scores(run_metadata))

        parts.append("<section id='sec-customers' class='report-section'>")
        parts.append("<h2>Customer Detail</h2>")
        for customer, data in sorted(merged_data.items()):
            parts.append(self._render_customer_section(customer, data))
        parts.append("</section>")

        parts.extend(
            [
                f"<script>{self._render_js()}</script>",
                "</body>",
                "</html>",
            ]
        )

        output_path.write_text("\n".join(parts), encoding="utf-8")
        logger.info("HTML report written to %s", output_path)

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def _precompute_aggregates(self, merged_data: dict[str, Any]) -> dict[str, Any]:
        """Single-pass data aggregation for all report sections."""
        total_customers = len(merged_data)
        total_findings = 0
        total_gaps = 0
        severity_counts: dict[str, int] = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        domain_findings: dict[str, list[dict[str, Any]]] = defaultdict(list)
        domain_severity: dict[str, dict[str, int]] = {d: {"P0": 0, "P1": 0, "P2": 0, "P3": 0} for d in _DOMAIN_AGENTS}
        category_groups: dict[str, dict[str, list[dict[str, Any]]]] = {d: defaultdict(list) for d in _DOMAIN_AGENTS}
        wolf_pack: list[dict[str, Any]] = []
        all_findings: list[dict[str, Any]] = []
        gap_priority_counts: dict[str, int] = defaultdict(int)
        gap_type_counts: dict[str, int] = defaultdict(int)
        governance_scores: dict[str, float] = {}

        for csn, data in merged_data.items():
            if not isinstance(data, dict):
                continue
            findings = data.get("findings", [])
            gaps = data.get("gaps", [])
            total_findings += len(findings)
            total_gaps += len(gaps)

            gov = data.get("governance_resolution_pct")
            if gov is not None:
                with contextlib.suppress(ValueError, TypeError):
                    governance_scores[csn] = float(gov)

            for f in findings:
                if not isinstance(f, dict):
                    continue
                sev = f.get("severity", "P3")
                if sev in severity_counts:
                    severity_counts[sev] += 1

                agent = str(f.get("agent", "")).lower()
                domain = self._agent_to_domain(agent)
                enriched = {**f, "_customer_safe_name": csn, "_customer": data.get("customer", csn)}
                domain_findings[domain].append(enriched)
                if domain in domain_severity and sev in domain_severity[domain]:
                    domain_severity[domain][sev] += 1

                cat = str(f.get("category", "uncategorized")).lower()
                if domain in category_groups:
                    category_groups[domain][cat].append(enriched)

                if sev in ("P0", "P1"):
                    wolf_pack.append(enriched)

                all_findings.append(enriched)

            for g in gaps:
                if not isinstance(g, dict):
                    continue
                gap_priority_counts[str(g.get("priority", "unknown"))] += 1
                gap_type_counts[str(g.get("gap_type", "unknown"))] += 1

        wolf_pack.sort(key=lambda f: (0 if f.get("severity") == "P0" else 1, str(f.get("title", ""))))

        return {
            "total_customers": total_customers,
            "total_findings": total_findings,
            "total_gaps": total_gaps,
            "severity_counts": severity_counts,
            "domain_findings": dict(domain_findings),
            "domain_severity": domain_severity,
            "category_groups": {d: dict(cats) for d, cats in category_groups.items()},
            "wolf_pack": wolf_pack,
            "all_findings": all_findings,
            "gap_priority_counts": dict(gap_priority_counts),
            "gap_type_counts": dict(gap_type_counts),
            "governance_scores": governance_scores,
        }

    @staticmethod
    def _agent_to_domain(agent: str) -> str:
        """Map an agent name to one of the 4 domains."""
        agent = agent.lower().strip()
        if agent in _DOMAIN_AGENTS:
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

    @staticmethod
    def _compute_deal_risk(severity_counts: dict[str, int]) -> str:
        """Compute overall deal risk from severity distribution."""
        if severity_counts.get("P0", 0) > 0:
            return "Critical"
        if severity_counts.get("P1", 0) >= 3:
            return "High"
        if severity_counts.get("P1", 0) > 0 or severity_counts.get("P2", 0) >= 5:
            return "Medium"
        if severity_counts.get("P2", 0) > 0:
            return "Low"
        return "Clean"

    @staticmethod
    def _risk_color(risk: str) -> str:
        """Color for a risk rating string."""
        return {
            "Critical": "#dc3545",
            "High": "#fd7e14",
            "Medium": "#ffc107",
            "Low": "#6c757d",
            "Clean": "#28a745",
        }.get(risk, "#6c757d")

    @staticmethod
    def _domain_risk(sev: dict[str, int]) -> str:
        """Domain-level risk from severity counts."""
        if sev.get("P0", 0) > 0:
            return "Critical"
        if sev.get("P1", 0) > 0:
            return "High"
        if sev.get("P2", 0) > 0:
            return "Medium"
        if sev.get("P3", 0) > 0:
            return "Low"
        return "Clean"

    # ------------------------------------------------------------------
    # CSS
    # ------------------------------------------------------------------

    def _render_css(self) -> str:
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
@media print {
    .nav-bar, .filter-bar { display: none !important; }
    .domain-body, .customer-body, .category-body, .finding-detail { display: block !important; }
    .domain-body.open, .customer-body.open, .category-body.open, .finding-detail.open { display: block !important; }
    body { background: white; }
    .deal-header { background: #1a1a2e !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .content { max-width: 100%; padding: 0; }
    .heatmap-cell, .metric-card, .finding-card, .wolf-card, .customer-section,
    .domain-section, .category-group { break-inside: avoid; }
}

/* Utility */
.hidden { display: none !important; }
.text-muted { color: #666; }
.text-small { font-size: 0.85em; }
.mt-8 { margin-top: 8px; }
.mb-8 { margin-bottom: 8px; }
.flex-between { display: flex; justify-content: space-between; align-items: center; }
"""

    # ------------------------------------------------------------------
    # JS
    # ------------------------------------------------------------------

    def _render_js(self) -> str:
        return """
(function() {
    'use strict';

    // --- Toggle collapsible sections ---
    function setupToggles(headerSel, bodySel) {
        document.querySelectorAll(headerSel).forEach(function(header) {
            header.addEventListener('click', function(e) {
                if (e.target.tagName === 'A') return;
                var body = this.nextElementSibling;
                if (!body) return;
                body.classList.toggle('open');
                var arrow = this.querySelector('.arrow');
                if (arrow) arrow.classList.toggle('open');
            });
        });
    }
    setupToggles('.customer-header', '.customer-body');
    setupToggles('.domain-header', '.domain-body');
    setupToggles('.category-header', '.category-body');

    // --- Finding card expand ---
    document.querySelectorAll('.finding-card').forEach(function(card) {
        card.addEventListener('click', function() {
            var detail = this.nextElementSibling;
            if (detail && detail.classList.contains('finding-detail')) {
                detail.classList.toggle('open');
                var arrow = this.querySelector('.arrow');
                if (arrow) arrow.classList.toggle('open');
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
        });
    }
    if (collapseBtn) {
        collapseBtn.addEventListener('click', function() {
            document.querySelectorAll(allSel).forEach(function(el) {
                el.classList.remove('open');
            });
            document.querySelectorAll('.arrow').forEach(function(a) { a.classList.remove('open'); });
        });
    }

    // --- Sticky nav active highlight ---
    var sections = document.querySelectorAll('.report-section, .deal-header, .wolf-pack');
    var navLinks = document.querySelectorAll('.nav-bar a[href^=\"#\"]');
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

    # ------------------------------------------------------------------
    # Navigation bar
    # ------------------------------------------------------------------

    def _render_nav_bar(self) -> str:
        return (
            "<nav class='nav-bar'>"
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
            "<div class='filter-bar'>"
            "<input type='text' id='global-search' placeholder='Search all content...' aria-label='Search'>"
            "<div class='filter-group'>"
            "<span class='filter-group-label'>Severity:</span>"
            "<label><input type='checkbox' class='sev-filter' value='P0' checked> P0</label>"
            "<label><input type='checkbox' class='sev-filter' value='P1' checked> P1</label>"
            "<label><input type='checkbox' class='sev-filter' value='P2' checked> P2</label>"
            "<label><input type='checkbox' class='sev-filter' value='P3' checked> P3</label>"
            "</div>"
            "<div class='filter-group'>"
            "<span class='filter-group-label'>Domain:</span>"
            "<label><input type='checkbox' class='agent-filter' value='legal' checked> Legal</label>"
            "<label><input type='checkbox' class='agent-filter' value='finance' checked> Finance</label>"
            "<label><input type='checkbox' class='agent-filter' value='commercial' checked> Commercial</label>"
            "<label><input type='checkbox' class='agent-filter' value='producttech' checked> Product&amp;Tech</label>"
            "</div>"
            "<button class='btn-sm' id='btn-expand-all'>Expand All</button>"
            "<button class='btn-sm' id='btn-collapse-all'>Collapse All</button>"
            "</div>"
            "<div class='content'>"
        )

    # ------------------------------------------------------------------
    # Level 0: Deal header
    # ------------------------------------------------------------------

    def _render_deal_header(
        self,
        *,
        title: str,
        run_id: str,
        deal_config: dict[str, Any] | None,
        agg: dict[str, Any],
    ) -> str:
        risk = self._compute_deal_risk(agg["severity_counts"])
        risk_color = self._risk_color(risk)

        buyer = ""
        target = ""
        deal_type = ""
        if deal_config and isinstance(deal_config, dict):
            buyer_obj = deal_config.get("buyer", {})
            buyer = buyer_obj.get("name", "") if isinstance(buyer_obj, dict) else str(buyer_obj)
            target_obj = deal_config.get("target", {})
            target = target_obj.get("name", "") if isinstance(target_obj, dict) else str(target_obj)
            deal_obj = deal_config.get("deal", {})
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

    # ------------------------------------------------------------------
    # Key metrics strip
    # ------------------------------------------------------------------

    def _render_key_metrics(self, agg: dict[str, Any], run_metadata: dict[str, Any] | None) -> str:
        sc = agg["severity_counts"]
        cards: list[str] = []

        def _card(value: str | int, label: str, color: str = "#1a1a2e") -> str:
            return (
                f"<div class='metric-card'>"
                f"<div class='value' style='color:{color}'>{html.escape(str(value))}</div>"
                f"<div class='label'>{html.escape(label)}</div>"
                f"</div>"
            )

        cards.append(_card(agg["total_customers"], "Customers"))
        cards.append(_card(agg["total_findings"], "Findings"))
        cards.append(_card(agg["total_gaps"], "Gaps"))
        for sev in ("P0", "P1", "P2", "P3"):
            cards.append(_card(sc.get(sev, 0), sev, _SEVERITY_COLORS.get(sev, "#ccc")))

        gov_scores = agg.get("governance_scores", {})
        if gov_scores:
            avg_gov = sum(gov_scores.values()) / len(gov_scores)
            cards.append(_card(f"{avg_gov:.0f}%", "Avg Governance", "#2d8a4e" if avg_gov >= 90 else "#d97706"))

        return "<div class='metrics-strip'>" + "".join(cards) + "</div>"

    # ------------------------------------------------------------------
    # Wolf pack (deal breakers)
    # ------------------------------------------------------------------

    def _render_wolf_pack(self, agg: dict[str, Any]) -> str:
        wolf = agg.get("wolf_pack", [])
        parts: list[str] = [
            "<section class='wolf-pack report-section' id='sec-wolf-pack'>",
            f"<h2>Deal Breakers ({len(wolf)})</h2>",
        ]

        if not wolf:
            parts.append("<p class='text-muted'>No P0 or P1 findings detected. No immediate deal-breaker risks.</p>")
        else:
            for f in wolf:
                sev = f.get("severity", "P3")
                color = _SEVERITY_COLORS.get(sev, "#ccc")
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
                    f"<div class='wolf-title'>{self._render_severity_badge(sev)} {title}</div>"
                    f"<div class='wolf-meta'>Customer: {customer} | Agent: {agent}</div>"
                )
                if desc:
                    parts.append(f"<div class='text-small mt-8'>{desc}</div>")
                if quote:
                    parts.append(f"<div class='wolf-quote'>&ldquo;{quote}&rdquo;</div>")
                parts.append("</div>")

        parts.append("</section>")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Deal risk heatmap
    # ------------------------------------------------------------------

    def _render_deal_risk_heatmap(self, agg: dict[str, Any]) -> str:
        parts: list[str] = [
            "<section class='report-section' id='sec-heatmap'>",
            "<h2>Domain Risk Heatmap</h2>",
            "<div class='heatmap'>",
        ]

        for domain in _DOMAIN_AGENTS:
            sev = agg["domain_severity"].get(domain, {})
            risk = self._domain_risk(sev)
            risk_color = self._risk_color(risk)
            domain_color = _DOMAIN_COLORS.get(domain, "#666")
            total = sum(sev.values())
            display = _DOMAIN_DISPLAY.get(domain, domain)

            sev_str = " | ".join(f"{k}:{v}" for k, v in sev.items() if v > 0) or "None"

            parts.append(
                f"<a href='#sec-domain-{html.escape(domain)}' style='text-decoration:none;color:inherit'>"
                f"<div class='heatmap-cell' style='border-top-color:{domain_color}'>"
                f"<div class='domain-name'>{html.escape(display)}</div>"
                f"<div class='domain-risk' style='color:{risk_color}'>{html.escape(risk)}</div>"
                f"<div class='domain-counts'>{total} findings ({sev_str})</div>"
                f"</div></a>"
            )

        parts.extend(["</div>", "</section>"])
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Level 1: Domain deep dives
    # ------------------------------------------------------------------

    def _render_domain_section(self, domain: str, agg: dict[str, Any], merged_data: dict[str, Any]) -> str:
        display = _DOMAIN_DISPLAY.get(domain, domain)
        domain_color = _DOMAIN_COLORS.get(domain, "#666")
        sev = agg["domain_severity"].get(domain, {})
        risk = self._domain_risk(sev)
        risk_color = self._risk_color(risk)
        total = sum(sev.values())
        categories = agg["category_groups"].get(domain, {})

        parts: list[str] = [
            f"<section class='report-section' id='sec-domain-{html.escape(domain)}'>",
            f"<div class='domain-section' data-domain='{html.escape(domain)}'>",
            f"<div class='domain-header' style='border-left-color:{domain_color}'>",
            f"<h2>{html.escape(display)} ({total} findings)</h2>",
            f"<span><span class='severity-badge' style='background:{risk_color}'>{html.escape(risk)}</span> "
            f"<span class='arrow'>&#9654;</span></span>",
            "</div>",
            "<div class='domain-body'>",
        ]

        # Severity distribution bar
        total_sev = max(sum(sev.values()), 1)
        parts.append("<div class='sev-bar'>")
        for s in ("P0", "P1", "P2", "P3"):
            pct = (sev.get(s, 0) / total_sev) * 100
            if pct > 0:
                parts.append(f"<span style='width:{pct:.1f}%;background:{_SEVERITY_COLORS[s]}'></span>")
        parts.append("</div>")

        # Category breakdown
        if categories:
            parts.append(
                "<table class='sortable'><thead><tr>"
                "<th>Category</th><th>Findings</th><th>Severity Mix</th>"
                "<th>Top Customer</th></tr></thead><tbody>"
            )
            for cat, cat_findings in sorted(categories.items(), key=lambda x: -len(x[1])):
                cat_sev: dict[str, int] = defaultdict(int)
                customer_counts: dict[str, int] = defaultdict(int)
                for cf in cat_findings:
                    cat_sev[cf.get("severity", "P3")] += 1
                    customer_counts[str(cf.get("_customer", ""))] += 1
                top_customer = max(customer_counts, key=customer_counts.get) if customer_counts else ""  # type: ignore[arg-type]
                sev_mix = ", ".join(f"{k}:{v}" for k, v in sorted(cat_sev.items()) if v > 0)

                parts.append(
                    f"<tr><td>{html.escape(cat)}</td><td>{len(cat_findings)}</td>"
                    f"<td>{html.escape(sev_mix)}</td><td>{html.escape(top_customer)}</td></tr>"
                )
            parts.append("</tbody></table>")

            # Category drill-down (Level 2)
            for cat, cat_findings in sorted(categories.items(), key=lambda x: -len(x[1])):
                parts.append(self._render_category_group(cat, cat_findings))
        else:
            parts.append("<p class='text-muted'>No findings in this domain.</p>")

        parts.extend(["</div>", "</div>", "</section>"])
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Level 2: Category groups
    # ------------------------------------------------------------------

    def _render_category_group(self, category: str, findings: list[dict[str, Any]]) -> str:
        sev_counts: dict[str, int] = defaultdict(int)
        for f in findings:
            sev_counts[f.get("severity", "P3")] += 1
        sev_str = ", ".join(f"{k}:{v}" for k, v in sorted(sev_counts.items()) if v > 0)

        parts: list[str] = [
            "<div class='category-group'>",
            f"<div class='category-header'>"
            f"<span><strong>{html.escape(category)}</strong> ({len(findings)} findings, {sev_str})</span>"
            f"<span class='arrow'>&#9654;</span></div>",
            "<div class='category-body'>",
        ]

        # Group by customer
        by_customer: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for f in findings:
            by_customer[str(f.get("_customer", "Unknown"))].append(f)

        for cust, cust_findings in sorted(by_customer.items()):
            parts.append(f"<h4>{html.escape(cust)}</h4>")
            for f in cust_findings:
                parts.append(self._render_finding_card(f))
                parts.append(self._render_finding_detail(f))

        parts.extend(["</div>", "</div>"])
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Level 3: Customer sections (enhanced)
    # ------------------------------------------------------------------

    def _render_customer_section(self, customer: str, data: Any) -> str:
        customer_name = data.get("customer", customer) if isinstance(data, dict) else customer
        findings = data.get("findings", []) if isinstance(data, dict) else []
        gaps = data.get("gaps", []) if isinstance(data, dict) else []
        xrefs = data.get("cross_references", []) if isinstance(data, dict) else []
        gov_pct = data.get("governance_resolution_pct") if isinstance(data, dict) else None

        finding_count = len(findings)
        # Compute per-customer severity summary
        sev_summary: dict[str, int] = defaultdict(int)
        for f in findings:
            if isinstance(f, dict):
                sev_summary[f.get("severity", "P3")] += 1
        sev_str = " ".join(
            f"<span class='severity-badge' style='background:{_SEVERITY_COLORS.get(s, '#ccc')}'>{s}:{c}</span>"
            for s, c in sorted(sev_summary.items())
            if c > 0
        )

        parts: list[str] = [
            "<div class='customer-section'>",
            f"<div class='customer-header'>"
            f"<span><strong>{html.escape(customer_name)}</strong> "
            f"({finding_count} finding{'s' if finding_count != 1 else ''}, "
            f"{len(gaps)} gap{'s' if len(gaps) != 1 else ''}) {sev_str}</span>"
            f"<span class='arrow'>&#9654;</span></div>",
            "<div class='customer-body'>",
        ]

        # Governance score
        if gov_pct is not None:
            try:
                pct = float(gov_pct)
                color = "#28a745" if pct >= 90 else ("#ffc107" if pct >= 70 else "#dc3545")
                parts.append(
                    f"<div class='mb-8'>Governance Resolution: <strong style='color:{color}'>{pct:.0f}%</strong></div>"
                )
            except (ValueError, TypeError):
                pass

        # Cross-references
        if xrefs and isinstance(xrefs, list):
            parts.append("<h3>Cross-Reference Reconciliation</h3>")
            parts.append(
                "<table class='sortable'><thead><tr>"
                "<th>Field</th><th>Source A</th><th>Source B</th><th>Match</th>"
                "</tr></thead><tbody>"
            )
            for xr in xrefs:
                if not isinstance(xr, dict):
                    continue
                field = html.escape(str(xr.get("field", "")))
                src_a = html.escape(str(xr.get("source_a", xr.get("value_a", ""))))
                src_b = html.escape(str(xr.get("source_b", xr.get("value_b", ""))))
                match = xr.get("match", xr.get("matches", True))
                match_str = "Yes" if match else "No"
                row_class = "xref-mismatch" if not match else "xref-match"
                parts.append(
                    f"<tr class='{row_class}'><td>{field}</td><td>{src_a}</td><td>{src_b}</td><td>{match_str}</td></tr>"
                )
            parts.append("</tbody></table>")

        # Findings grouped by domain
        if findings:
            parts.append("<h3>Findings</h3>")
            by_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for f in findings:
                if isinstance(f, dict):
                    domain = self._agent_to_domain(str(f.get("agent", "")))
                    by_domain[domain].append(f)
                else:
                    by_domain["legal"].append({"_raw": f})

            for domain in _DOMAIN_AGENTS:
                domain_f = by_domain.get(domain, [])
                if not domain_f:
                    continue
                display = _DOMAIN_DISPLAY.get(domain, domain)
                parts.append(f"<h4 style='color:{_DOMAIN_COLORS.get(domain, '#666')}'>{html.escape(display)}</h4>")
                for f in domain_f:
                    parts.append(self._render_finding_card(f))
                    parts.append(self._render_finding_detail(f))

        # Gaps
        if gaps:
            parts.append("<h3>Gaps</h3>")
            parts.append(
                "<table class='sortable'><thead><tr>"
                "<th>Priority</th><th>Type</th><th>Missing Item</th>"
                "<th>Risk</th></tr></thead><tbody>"
            )
            for g in gaps:
                if isinstance(g, dict):
                    prio = html.escape(str(g.get("priority", "")))
                    gtype = html.escape(str(g.get("gap_type", "")))
                    item = html.escape(str(g.get("missing_item", "")))
                    risk = html.escape(str(g.get("risk_if_missing", "")))
                    parts.append(f"<tr><td>{prio}</td><td>{gtype}</td><td>{item}</td><td>{risk}</td></tr>")
            parts.append("</tbody></table>")

        parts.extend(["</div>", "</div>"])
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Level 4: Finding card + detail
    # ------------------------------------------------------------------

    def _render_finding_card(self, finding: Any) -> str:
        if not isinstance(finding, dict):
            return ""
        severity = str(finding.get("severity", "P3"))
        color = _SEVERITY_COLORS.get(severity, "#ccc")
        title = html.escape(str(finding.get("title", "Untitled")))
        customer = html.escape(str(finding.get("_customer", finding.get("customer", ""))))
        agent = html.escape(str(finding.get("agent", "")))

        return (
            f"<div class='finding-card' style='border-left-color:{color}' "
            f"data-severity='{html.escape(severity)}' data-domain='{html.escape(self._agent_to_domain(agent))}'>"
            f"<div class='fc-title'>{self._render_severity_badge(severity)} {title} "
            f"<span class='arrow'>&#9654;</span></div>"
            f"<div class='fc-meta'>Customer: {customer} | Agent: {agent}</div>"
            f"</div>"
        )

    def _render_finding_detail(self, finding: Any) -> str:
        if not isinstance(finding, dict):
            return ""
        severity = str(finding.get("severity", "P3"))
        color = _SEVERITY_COLORS.get(severity, "#ccc")
        description = html.escape(str(finding.get("description", "")))
        confidence = str(finding.get("confidence", ""))
        verification = str(finding.get("verification_status", finding.get("verified", "")))
        detection = str(finding.get("detection_method", ""))

        parts: list[str] = [
            f"<div class='finding-detail' style='border-left-color:{color}'>",
        ]

        if description:
            parts.append(f"<div class='fd-description'>{description}</div>")

        # Badges row
        badges: list[str] = []
        if confidence:
            badges.append(f"<span class='text-small'>Confidence: <strong>{html.escape(confidence)}</strong></span>")
        if verification:
            vb_class = (
                "vb-verified"
                if verification.lower() in ("verified", "true")
                else ("vb-failed" if verification.lower() in ("failed", "false") else "vb-unchecked")
            )
            badges.append(f"<span class='verification-badge {vb_class}'>{html.escape(verification)}</span>")
        if detection:
            badges.append(f"<span class='text-small text-muted'>Detection: {html.escape(detection)}</span>")
        if badges:
            parts.append(f"<div class='fd-badges'>{''.join(badges)}</div>")

        # Citations
        citations = finding.get("citations", [])
        if citations:
            for cit in citations:
                parts.append(self._render_citation(cit))

        parts.append("</div>")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Citation
    # ------------------------------------------------------------------

    def _render_citation(self, citation: Any) -> str:
        if not isinstance(citation, dict):
            return ""
        source = html.escape(str(citation.get("source_path", "")))
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
            parts.append(f" <span class='location'>({html.escape(loc_str)})</span>")
        if quote:
            parts.append(f"<span class='quote'>&ldquo;{html.escape(str(quote))}&rdquo;</span>")
        parts.append("</div>")
        return "".join(parts)

    # ------------------------------------------------------------------
    # Gap analysis section
    # ------------------------------------------------------------------

    def _render_gap_analysis(self, agg: dict[str, Any], merged_data: dict[str, Any]) -> str:
        total_gaps = agg["total_gaps"]
        prio_counts = agg.get("gap_priority_counts", {})
        type_counts = agg.get("gap_type_counts", {})

        parts: list[str] = [
            "<section class='report-section' id='sec-gaps'>",
            f"<h2>Gap Analysis ({total_gaps} gaps)</h2>",
        ]

        if total_gaps == 0:
            parts.append("<p class='text-muted'>No documentation gaps identified.</p>")
            parts.append("</section>")
            return "\n".join(parts)

        # Summary grid
        parts.append("<div class='gap-summary-grid'>")
        # Priority distribution
        parts.append("<div class='metric-card'><div class='label'>By Priority</div>")
        for p, c in sorted(prio_counts.items()):
            parts.append(f"<div>{self._render_severity_badge(p)} {c}</div>")
        parts.append("</div>")
        # Type distribution
        parts.append("<div class='metric-card'><div class='label'>By Type</div>")
        for t, c in sorted(type_counts.items()):
            parts.append(f"<div><strong>{html.escape(t)}</strong>: {c}</div>")
        parts.append("</div>")
        parts.append("</div>")

        # Full sortable table
        parts.append(
            "<table class='sortable'><thead><tr>"
            "<th>Customer</th><th>Priority</th><th>Type</th>"
            "<th>Missing Item</th><th>Risk</th></tr></thead><tbody>"
        )
        for csn, data in sorted(merged_data.items()):
            if not isinstance(data, dict):
                continue
            customer = html.escape(str(data.get("customer", csn)))
            for g in data.get("gaps", []):
                if not isinstance(g, dict):
                    continue
                prio = html.escape(str(g.get("priority", "")))
                gtype = html.escape(str(g.get("gap_type", "")))
                item = html.escape(str(g.get("missing_item", "")))
                risk = html.escape(str(g.get("risk_if_missing", "")))
                parts.append(
                    f"<tr><td>{customer}</td><td>{prio}</td><td>{gtype}</td><td>{item}</td><td>{risk}</td></tr>"
                )
        parts.append("</tbody></table>")

        parts.append("</section>")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Cross-reference reconciliation
    # ------------------------------------------------------------------

    def _render_cross_reference_section(self, merged_data: dict[str, Any]) -> str:
        has_xrefs = False
        for data in merged_data.values():
            if isinstance(data, dict) and data.get("cross_references"):
                has_xrefs = True
                break

        if not has_xrefs:
            return ""

        parts: list[str] = [
            "<section class='report-section' id='sec-xref'>",
            "<h2>Data Reconciliation</h2>",
            "<table class='sortable'><thead><tr>"
            "<th>Customer</th><th>Field</th><th>Source A</th>"
            "<th>Source B</th><th>Match</th></tr></thead><tbody>",
        ]

        for csn, data in sorted(merged_data.items()):
            if not isinstance(data, dict):
                continue
            customer = html.escape(str(data.get("customer", csn)))
            xrefs = data.get("cross_references", [])
            if not isinstance(xrefs, list):
                continue
            for xr in xrefs:
                if not isinstance(xr, dict):
                    continue
                field = html.escape(str(xr.get("field", "")))
                src_a = html.escape(str(xr.get("source_a", xr.get("value_a", ""))))
                src_b = html.escape(str(xr.get("source_b", xr.get("value_b", ""))))
                match = xr.get("match", xr.get("matches", True))
                match_str = "Yes" if match else "No"
                row_class = "xref-mismatch" if not match else "xref-match"
                parts.append(
                    f"<tr class='{row_class}'><td>{customer}</td><td>{field}</td>"
                    f"<td>{src_a}</td><td>{src_b}</td><td>{match_str}</td></tr>"
                )

        parts.extend(["</tbody></table>", "</section>"])
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Governance metrics
    # ------------------------------------------------------------------

    def _render_governance_metrics(self, merged_data: dict[str, Any]) -> str:
        scores: list[tuple[str, float]] = []
        for csn, data in sorted(merged_data.items()):
            if not isinstance(data, dict):
                continue
            gov = data.get("governance_resolution_pct")
            if gov is not None:
                with contextlib.suppress(ValueError, TypeError):
                    scores.append((str(data.get("customer", csn)), float(gov)))

        if not scores:
            return ""

        parts: list[str] = [
            "<section class='report-section' id='sec-governance'>",
            "<h2>Governance Resolution</h2>",
        ]

        for name, pct in sorted(scores, key=lambda x: x[1]):
            color = "#28a745" if pct >= 90 else ("#ffc107" if pct >= 70 else "#dc3545")
            width = max(min(pct, 100), 0)
            parts.append(
                f"<div class='gov-bar-container'>"
                f"<span class='gov-label'>{html.escape(name)}</span>"
                f"<div style='flex:1;background:#e9ecef;border-radius:4px;height:20px'>"
                f"<div class='gov-bar' style='width:{width:.0f}%;background:{color}'></div>"
                f"</div>"
                f"<span class='gov-pct' style='color:{color}'>{pct:.0f}%</span>"
                f"</div>"
            )

        parts.append("</section>")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Quality scores (judge data)
    # ------------------------------------------------------------------

    def _render_quality_scores(self, run_metadata: dict[str, Any] | None) -> str:
        if not run_metadata or not isinstance(run_metadata, dict):
            return ""
        qs = run_metadata.get("quality_scores")
        if not qs:
            return ""

        parts: list[str] = [
            "<section class='report-section' id='sec-quality'>",
            "<h2>Quality Audit</h2>",
        ]

        if isinstance(qs, dict):
            agent_scores = qs.get("agent_scores", qs)
            if isinstance(agent_scores, dict):
                parts.append(
                    "<table class='sortable'><thead><tr>"
                    "<th>Agent</th><th>Score</th><th>Details</th>"
                    "</tr></thead><tbody>"
                )
                for agent_name, score_data in sorted(agent_scores.items()):
                    if isinstance(score_data, dict):
                        score_val = score_data.get("score", score_data.get("overall", ""))
                        details = score_data.get("details", score_data.get("notes", ""))
                    else:
                        score_val = score_data
                        details = ""
                    parts.append(
                        f"<tr><td>{html.escape(str(agent_name))}</td>"
                        f"<td>{html.escape(str(score_val))}</td>"
                        f"<td>{html.escape(str(details))}</td></tr>"
                    )
                parts.append("</tbody></table>")

        parts.append("</section>")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Reusable rendering helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _render_severity_badge(severity: str) -> str:
        color = _SEVERITY_COLORS.get(severity, "#6c757d")
        return f"<span class='severity-badge' style='background:{color}'>{html.escape(severity)}</span>"

    def _render_bar_chart(self, items: list[tuple[str, float]], max_val: float | None = None) -> str:
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
                f"<span class='gov-label'>{html.escape(label)}</span>"
                f"<div style='flex:1;background:#e9ecef;border-radius:4px;height:16px'>"
                f"<div style='width:{pct:.0f}%;background:#4a90d9;height:100%;border-radius:4px'></div>"
                f"</div>"
                f"<span class='gov-pct'>{value:.0f}</span>"
                f"</div>"
            )
        return "\n".join(parts)
