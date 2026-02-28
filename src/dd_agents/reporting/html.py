"""Self-contained interactive HTML report generator.

Generates a single HTML file with no external dependencies.
Features: collapsible customer sections, severity color coding,
sortable columns (embedded JS), citation popups, summary dashboard.
"""

from __future__ import annotations

import html
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# Severity color palette
_SEVERITY_COLORS: dict[str, str] = {
    "P0": "#ff4444",
    "P1": "#ff8800",
    "P2": "#ffcc00",
    "P3": "#cccccc",
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
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

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
            f"<h1>{html.escape(title)}</h1>",
        ]

        if run_id:
            parts.append(f"<p class='run-id'>Run ID: {html.escape(run_id)}</p>")

        parts.append(self._render_summary_dashboard(merged_data))

        for customer, data in sorted(merged_data.items()):
            parts.append(self._render_customer_section(customer, data))

        parts.extend(
            [
                f"<script>{self._render_js()}</script>",
                "</body>",
                "</html>",
            ]
        )

        output_path.write_text("\n".join(parts), encoding="utf-8")
        logger.info("HTML report written to %s", output_path)

    def _render_css(self) -> str:
        return """
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       margin: 20px; background: #f8f9fa; color: #333; }
h1 { color: #1a1a2e; }
.run-id { color: #666; font-size: 0.9em; }
.dashboard { display: flex; gap: 16px; flex-wrap: wrap; margin: 20px 0; }
.stat-card { background: white; border-radius: 8px; padding: 16px 24px;
             box-shadow: 0 1px 3px rgba(0,0,0,0.1); min-width: 120px; }
.stat-card .value { font-size: 2em; font-weight: bold; }
.stat-card .label { color: #666; font-size: 0.85em; }
.customer-section { background: white; border-radius: 8px; margin: 16px 0;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.1); overflow: hidden; }
.customer-header { padding: 12px 20px; cursor: pointer; display: flex;
                   justify-content: space-between; align-items: center;
                   background: #e9ecef; }
.customer-header:hover { background: #dee2e6; }
.customer-body { padding: 16px 20px; display: none; }
.customer-body.open { display: block; }
.finding { border-left: 4px solid #ccc; padding: 8px 12px; margin: 8px 0;
           background: #fafafa; border-radius: 0 4px 4px 0; }
.finding .title { font-weight: bold; }
.finding .meta { color: #666; font-size: 0.85em; margin-top: 4px; }
.severity-badge { display: inline-block; padding: 2px 8px; border-radius: 4px;
                  color: white; font-weight: bold; font-size: 0.8em; }
.citation { background: #f0f0f0; padding: 8px; margin: 4px 0; border-radius: 4px;
            font-size: 0.9em; }
.citation .quote { font-style: italic; color: #555; }
table.sortable { width: 100%; border-collapse: collapse; margin: 8px 0; }
table.sortable th, table.sortable td { padding: 8px 12px; border: 1px solid #dee2e6;
                                        text-align: left; }
table.sortable th { background: #e9ecef; cursor: pointer; user-select: none; }
table.sortable th:hover { background: #dee2e6; }
"""

    def _render_js(self) -> str:
        return """
document.querySelectorAll('.customer-header').forEach(function(header) {
    header.addEventListener('click', function() {
        var body = this.nextElementSibling;
        body.classList.toggle('open');
        var arrow = this.querySelector('.arrow');
        arrow.textContent = body.classList.contains('open') ? '\\u25BC' : '\\u25B6';
    });
});
document.querySelectorAll('table.sortable th').forEach(function(th) {
    th.addEventListener('click', function() {
        var table = this.closest('table');
        var tbody = table.querySelector('tbody');
        var rows = Array.from(tbody.querySelectorAll('tr'));
        var col = Array.from(this.parentNode.children).indexOf(this);
        var asc = this.dataset.sort !== 'asc';
        rows.sort(function(a, b) {
            var va = a.children[col].textContent.trim();
            var vb = b.children[col].textContent.trim();
            return asc ? va.localeCompare(vb) : vb.localeCompare(va);
        });
        rows.forEach(function(row) { tbody.appendChild(row); });
        this.dataset.sort = asc ? 'asc' : 'desc';
    });
});
"""

    def _render_summary_dashboard(self, merged_data: dict[str, Any]) -> str:
        total_customers = len(merged_data)
        total_findings = 0
        total_gaps = 0
        severity_counts: dict[str, int] = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}

        for data in merged_data.values():
            findings = data.get("findings", [])
            total_findings += len(findings)
            total_gaps += len(data.get("gaps", []))
            for f in findings:
                sev = f.get("severity", "P3") if isinstance(f, dict) else "P3"
                if sev in severity_counts:
                    severity_counts[sev] += 1

        cards: list[str] = [
            f"<div class='stat-card'><div class='value'>{total_customers}</div>"
            "<div class='label'>Customers</div></div>",
            f"<div class='stat-card'><div class='value'>{total_findings}</div><div class='label'>Findings</div></div>",
            f"<div class='stat-card'><div class='value'>{total_gaps}</div><div class='label'>Gaps</div></div>",
        ]
        for sev, count in severity_counts.items():
            color = _SEVERITY_COLORS.get(sev, "#ccc")
            cards.append(
                f"<div class='stat-card'><div class='value' style='color:{color}'>{count}</div>"
                f"<div class='label'>{sev}</div></div>"
            )

        return "<div class='dashboard'>" + "".join(cards) + "</div>"

    def _render_customer_section(self, customer: str, data: Any) -> str:
        customer_name = data.get("customer", customer) if isinstance(data, dict) else customer
        findings = data.get("findings", []) if isinstance(data, dict) else []
        gaps = data.get("gaps", []) if isinstance(data, dict) else []

        finding_count = len(findings)
        parts: list[str] = [
            "<div class='customer-section'>",
            f"<div class='customer-header'>"
            f"<span><strong>{html.escape(customer_name)}</strong> "
            f"({finding_count} finding{'s' if finding_count != 1 else ''}, "
            f"{len(gaps)} gap{'s' if len(gaps) != 1 else ''})</span>"
            f"<span class='arrow'>&#9654;</span></div>",
            "<div class='customer-body'>",
        ]

        if findings:
            parts.append("<h3>Findings</h3>")
            for f in findings:
                parts.append(self._render_finding(f))

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

    def _render_finding(self, finding: Any) -> str:
        if not isinstance(finding, dict):
            return ""

        severity = str(finding.get("severity", "P3"))
        color = _SEVERITY_COLORS.get(severity, "#ccc")
        title = html.escape(str(finding.get("title", "Untitled")))
        description = html.escape(str(finding.get("description", "")))
        agent = html.escape(str(finding.get("agent", "")))
        confidence = html.escape(str(finding.get("confidence", "")))

        parts: list[str] = [
            f"<div class='finding' style='border-left-color:{color}'>",
            f"<div class='title'><span class='severity-badge' "
            f"style='background:{color}'>{html.escape(severity)}</span> {title}</div>",
            f"<div>{description}</div>",
            f"<div class='meta'>Agent: {agent} | Confidence: {confidence}</div>",
        ]

        citations = finding.get("citations", [])
        for cit in citations:
            parts.append(self._render_citation(cit))

        parts.append("</div>")
        return "\n".join(parts)

    def _render_citation(self, citation: Any) -> str:
        if not isinstance(citation, dict):
            return ""

        source = html.escape(str(citation.get("source_path", "")))
        location = html.escape(str(citation.get("location", "")))
        quote = citation.get("exact_quote", "")

        parts: list[str] = [
            "<div class='citation'>",
            f"<strong>{source}</strong>",
        ]
        if location:
            parts.append(f" ({location})")
        if quote:
            parts.append(f"<div class='quote'>{html.escape(str(quote))}</div>")
        parts.append("</div>")
        return "".join(parts)
