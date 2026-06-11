"""Contract-date reconciliation renderer (Issue #244).

Surfaces the active-vs-expired ARR reconciliation in the HTML report (and thus
the PDF, which renders the same HTML). The data is computed in pipeline step 11
(``ContractDateReconciler``), persisted to ``contract_date_reconciliation.json``,
and was previously surfaced ONLY in the Excel ``Contract_Date_Reconciliation``
sheet — a primary-deliverable parity gap.

Each entry compares the subject database's `end_date` against the date found in
the contracts, with a status and the ARR a reviewer should **discount** (expired)
or **re-credit** (stale DB). Sourced from the persisted run metadata (mirrors how
``excel._data_contract_dates`` reads it). Parity-safe: renders nothing when no
reconciliation entries exist.
"""

from __future__ import annotations

from typing import Any

from dd_agents.reporting.html_base import SectionRenderer, fmt_currency


class ContractDatesRenderer(SectionRenderer):
    """Render the contract-date reconciliation section (active-vs-expired ARR)."""

    def render(self) -> str:
        run_meta = (self.config or {}).get("_run_metadata") or {}
        if not isinstance(run_meta, dict):
            return ""
        recon = run_meta.get("contract_date_reconciliation")
        if not isinstance(recon, dict):
            return ""
        entries = recon.get("entries")
        if not isinstance(entries, list) or not entries:
            return ""

        parts: list[str] = [
            "<section class='report-section' id='sec-contract-dates'>",
            "<h2>Contract Date Reconciliation</h2>",
        ]

        # KPI line for the two dollar aggregates a reviewer acts on.
        total_expired = _as_float(recon.get("total_expired_arr"))
        total_reclassified = _as_float(recon.get("total_reclassified_arr"))
        if total_expired or total_reclassified:
            parts.append(
                self.render_alert(
                    "high" if total_expired else "info",
                    "Revenue impact",
                    f"Expired ARR (discount candidate): {fmt_currency(total_expired)} · "
                    f"Reclassified ARR (stale database): {fmt_currency(total_reclassified)}.",
                )
            )

        parts.append(
            "<table class='subject-table sortable'><caption>Contract date reconciliation</caption>"
            "<thead><tr><th scope='col'>Entity</th><th scope='col'>Status</th>"
            "<th scope='col'>Database End</th><th scope='col'>Actual End</th>"
            "<th scope='col'>ARR</th><th scope='col'>Evidence</th></tr></thead><tbody>"
        )
        for e in entries:
            if not isinstance(e, dict):
                continue
            subject = self.escape(str(e.get("subject", "")))
            status = self.escape(str(e.get("status", "")))
            db_end = self.escape(str(e.get("database_end_date", "")))
            actual_end = self.escape(str(e.get("actual_end_date", "")))
            arr = fmt_currency(_as_float(e.get("arr")))
            evidence = self.escape(str(e.get("evidence", "")))
            ev_file = str(e.get("evidence_file", ""))
            if ev_file:
                evidence = f"{evidence} <span class='text-muted'>({self.escape(ev_file)})</span>"
            parts.append(
                f"<tr><td>{subject}</td><td>{status}</td><td>{db_end}</td>"
                f"<td>{actual_end}</td><td>{arr}</td><td>{evidence}</td></tr>"
            )
        parts.append("</tbody></table>")
        parts.append("</section>")
        return "\n".join(parts)


def _as_float(value: Any) -> float:
    """Coerce a possibly-missing/str numeric to float; 0.0 on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
