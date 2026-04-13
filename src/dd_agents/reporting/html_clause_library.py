"""Clause library report section renderer (Issue #119, Phase 1).

Renders a clause analysis section grouping findings by canonical clause type
with market norm comparisons.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from dd_agents.reporting.clause_library import CLAUSE_LIBRARY, classify_finding
from dd_agents.reporting.html_base import SectionRenderer
from dd_agents.utils.constants import SEVERITY_P3


class ClauseLibraryRenderer(SectionRenderer):
    """Render the Clause Analysis section with market norm comparisons."""

    def render(self) -> str:
        if self.data is None:
            return ""

        clause_analysis = getattr(self.data, "clause_analysis", {})
        if not clause_analysis or not clause_analysis.get("clause_counts"):
            return ""

        clause_counts: dict[str, int] = clause_analysis.get("clause_counts", {})
        clause_findings: dict[str, list[dict[str, Any]]] = clause_analysis.get("clause_findings", {})
        total_classified = clause_analysis.get("total_classified", 0)

        parts: list[str] = [
            "<section class='report-section' id='sec-clause-library'>",
            "<h2>Clause Analysis</h2>",
            "<p>Findings classified against standard M&amp;A clause taxonomy with market norm comparisons.</p>",
        ]

        # Summary metrics
        total_types = len(clause_counts)
        parts.append(
            "<div class='metrics-strip'>"
            f"<div class='metric-card'><div class='value'>{total_classified}</div>"
            "<div class='label'>Classified Findings</div></div>"
            f"<div class='metric-card'><div class='value'>{total_types}</div>"
            "<div class='label'>Clause Types Found</div></div>"
            "</div>"
        )

        # Per clause type breakdown
        for clause_key, count in sorted(clause_counts.items(), key=lambda x: -x[1]):
            clause_def = CLAUSE_LIBRARY.get(clause_key)
            if not clause_def:
                continue

            name = self.escape(clause_def["name"])
            market_norm = self.escape(clause_def["market_norm"])
            risk_impl = self.escape(clause_def["risk_implications"])
            findings = clause_findings.get(clause_key, [])

            parts.append(
                f"<div class='category-group'>"
                f"<div class='category-header' tabindex='0' role='button' aria-expanded='false'>"
                f"<span class='arrow'>&#9654;</span> {name} "
                f"<span class='badge' style='background:#6c757d;color:#fff;'>{count}</span>"
                f"</div>"
                f"<div class='category-body'>"
            )

            # Market norm comparison
            norm_style = "margin:8px 0;padding:8px 12px;background:#f0f4ff;"
            norm_style += "border-left:3px solid #4a90d9;border-radius:4px;"
            risk_style = "margin:8px 0;padding:8px 12px;background:#fff8f0;"
            risk_style += "border-left:3px solid #fd7e14;border-radius:4px;"
            parts.append(
                f"<div style='{norm_style}'>"
                f"<strong>Market Norm:</strong> {market_norm}"
                f"</div>"
                f"<div style='{risk_style}'>"
                f"<strong>Risk Implications:</strong> {risk_impl}"
                f"</div>"
            )

            # Findings table
            if findings:
                parts.append(
                    "<table class='subject-table sortable'><thead><tr>"
                    "<th scope='col'>Entity</th><th scope='col'>Severity</th>"
                    "<th scope='col'>Finding</th>"
                    "</tr></thead><tbody>"
                )
                for f in findings[:20]:  # Cap per clause type
                    entity = self.escape(self._resolve_display_name(f))
                    sev = str(f.get("severity", SEVERITY_P3))
                    title = self.escape(str(f.get("title", "")))
                    parts.append(f"<tr><td>{entity}</td><td>{self.severity_badge(sev)}</td><td>{title}</td></tr>")
                parts.append("</tbody></table>")
                if len(findings) > 20:
                    parts.append(f"<p><em>Showing 20 of {len(findings)} findings</em></p>")

            parts.append("</div></div>")

        parts.append("</section>")
        return "\n".join(parts)

    @staticmethod
    def compute_clause_analysis(material_findings: list[dict[str, Any]]) -> dict[str, Any]:
        """Classify all material findings into clause types.

        Returns a dict with ``clause_counts``, ``clause_findings``, and
        ``total_classified``.
        """
        clause_counts: dict[str, int] = defaultdict(int)
        clause_findings: dict[str, list[dict[str, Any]]] = defaultdict(list)
        total_classified = 0

        for f in material_findings:
            clause_type = classify_finding(f)
            if clause_type:
                clause_counts[clause_type] += 1
                clause_findings[clause_type].append(f)
                total_classified += 1

        return {
            "clause_counts": dict(clause_counts),
            "clause_findings": dict(clause_findings),
            "total_classified": total_classified,
        }
