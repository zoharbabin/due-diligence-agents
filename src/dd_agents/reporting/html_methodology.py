"""Methodology and limitations renderer (Issue #113 B7)."""

from __future__ import annotations

from dd_agents.reporting.html_base import DOMAIN_AGENTS, DOMAIN_DISPLAY, SectionRenderer


class MethodologyRenderer(SectionRenderer):
    """Render the methodology and limitations section.

    Describes: entities analyzed, agents deployed, findings extracted,
    data quality metrics, and known limitations.
    """

    def render(self) -> str:
        d = self.data

        parts: list[str] = [
            "<section class='report-section' id='sec-methodology'>",
            "<h2>Methodology &amp; Limitations</h2>",
        ]

        # Process summary
        parts.append("<h3>Analysis Process</h3>")
        parts.append(
            "<p>This due diligence report was generated through automated analysis "
            "of the target company's data room documents using specialized AI agents. "
            "The process follows a deterministic 38-step pipeline with 5 blocking "
            "quality gates.</p>"
        )

        # Generation provenance (secret-free): which provider/model produced the
        # analysis, for audit/governance review. Sourced from the persisted run
        # metadata routing receipt (see RunMetadata.llm_*).
        run_meta = (self.config or {}).get("_run_metadata") or {}
        if isinstance(run_meta, dict):
            provider = run_meta.get("llm_provider")
            models = run_meta.get("llm_models") or []
            base_url = run_meta.get("llm_base_url")
            if provider or models:
                items: list[str] = []
                if provider:
                    items.append(f"<li>Provider: <strong>{self.escape(str(provider))}</strong></li>")
                if models:
                    model_str = ", ".join(self.escape(str(m)) for m in models)
                    items.append(f"<li>Model(s): <strong>{model_str}</strong></li>")
                if base_url:
                    items.append(f"<li>Gateway: <strong>{self.escape(str(base_url))}</strong></li>")
                parts.append("<h3>Generation Provenance</h3>")
                parts.append(
                    "<p>The findings in this report were produced by the following model/provider configuration:</p>"
                )
                parts.append("<ul>" + "".join(items) + "</ul>")

        # Key stats
        parts.append(
            "<div class='metrics-strip'>"
            f"<div class='metric-card'><div class='value'>{d.subjects_analyzed}</div>"
            "<div class='label'>Entities Analyzed</div></div>"
            f"<div class='metric-card'><div class='value'>{d.total_findings}</div>"
            "<div class='label'>Findings Extracted</div></div>"
            f"<div class='metric-card'><div class='value'>{d.total_gaps}</div>"
            "<div class='label'>Gaps Identified</div></div>"
            f"<div class='metric-card'><div class='value'>{d.total_cross_refs}</div>"
            "<div class='label'>Data Points Reconciled</div></div>"
            "</div>"
        )

        # Agent coverage
        parts.append("<h3>Agent Coverage</h3>")
        parts.append(
            "<table class='sortable'><caption>Agent coverage by domain</caption><thead><tr>"
            "<th scope='col'>Domain</th><th scope='col'>Findings</th>"
            "<th scope='col'>Risk Level</th></tr></thead><tbody>"
        )
        for domain in DOMAIN_AGENTS:
            display = DOMAIN_DISPLAY.get(domain, domain)
            count = d.findings_by_domain.get(domain, 0)
            risk = d.domain_risk_labels.get(domain, "Clean")
            parts.append(f"<tr><td>{self.escape(display)}</td><td>{count}</td><td>{self.escape(risk)}</td></tr>")
        parts.append("</tbody></table>")

        # Data quality
        parts.append("<h3>Data Quality</h3>")
        quality_items: list[str] = []
        quality_items.append(
            f"Cross-reference match rate: <strong>{d.match_rate:.0%}</strong>"
            f" ({d.cross_ref_matches} matches, {d.cross_ref_mismatches} mismatches"
            f" of {d.total_cross_refs} data points)"
        )
        quality_items.append(f"Average governance resolution: <strong>{d.avg_governance_pct:.0f}%</strong>")
        if d.unresolved_governance_count > 0:
            quality_items.append(
                f"Entities with incomplete governance: <strong>{d.unresolved_governance_count}</strong>"
            )
        parts.append("<ul>")
        for item in quality_items:
            parts.append(f"<li>{item}</li>")
        parts.append("</ul>")

        # Limitations
        parts.append("<h3>Known Limitations</h3>")
        parts.append(
            "<ul>"
            "<li>Analysis is limited to documents provided in the data room. "
            "Documents not included may contain material information.</li>"
            "<li>Financial figures extracted from contract text are best-effort "
            "and may not reflect current values.</li>"
            "<li>Unreadable or corrupted documents are flagged as gaps but "
            "cannot be analyzed.</li>"
            "<li>AI-generated findings should be verified by legal and "
            "financial advisors before making investment decisions.</li>"
            "<li>Cross-reference reconciliation depends on data availability "
            "in both contract documents and reference sources.</li>"
            "</ul>"
        )

        parts.append("</section>")
        return "\n".join(parts)
