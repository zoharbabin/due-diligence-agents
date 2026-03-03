"""Cross-reference reconciliation renderer (Issue #103)."""

from __future__ import annotations

import html

from dd_agents.reporting.html_base import SectionRenderer


class CrossRefRenderer(SectionRenderer):
    """Render the data reconciliation cross-reference section."""

    def render(self) -> str:
        has_xrefs = False
        for data in self.merged_data.values():
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

        for csn, data in sorted(self.merged_data.items()):
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
