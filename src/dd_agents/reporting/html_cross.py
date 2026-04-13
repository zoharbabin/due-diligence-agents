"""Cross-reference reconciliation renderer (Issue #103)."""

from __future__ import annotations

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

        # Summary stats
        total = self.data.total_cross_refs
        matches = self.data.cross_ref_matches
        mismatches = self.data.cross_ref_mismatches
        rate = self.data.match_rate

        parts: list[str] = [
            "<section class='report-section' id='sec-xref'>",
            "<h2>Data Reconciliation</h2>",
        ]

        # Summary cards
        parts.append(
            "<div class='metrics-strip'>"
            f"<div class='metric-card'><div class='value'>{total}</div>"
            "<div class='label'>Data Points</div></div>"
            f"<div class='metric-card'><div class='value' style='color:#28a745'>{matches}</div>"
            "<div class='label'>Matches</div></div>"
            f"<div class='metric-card'><div class='value' style='color:#dc3545'>{mismatches}</div>"
            "<div class='label'>Mismatches</div></div>"
            f"<div class='metric-card'><div class='value'>{rate:.0%}</div>"
            "<div class='label'>Match Rate</div></div>"
            "</div>"
        )

        parts.append(
            "<table class='sortable'><thead><tr>"
            "<th scope='col'>Entity</th><th scope='col'>Field</th>"
            "<th scope='col'>Contract Value</th><th scope='col'>Reference Value</th>"
            "<th scope='col'>Match</th></tr></thead><tbody>"
        )

        for csn, data in sorted(self.merged_data.items()):
            if not isinstance(data, dict):
                continue
            raw_name = str(data.get("subject", csn))
            entity_name = self.escape(self.data.display_names.get(csn, raw_name) if self.data else raw_name)
            xrefs = data.get("cross_references", [])
            if not isinstance(xrefs, list):
                continue
            for xr in xrefs:
                if not isinstance(xr, dict):
                    continue
                field = self.escape(str(xr.get("data_point", xr.get("field", ""))))
                src_a = self.escape(str(xr.get("contract_value", xr.get("source_a", xr.get("value_a", "")))))
                src_b = self.escape(str(xr.get("reference_value", xr.get("source_b", xr.get("value_b", "")))))
                raw_status = str(xr.get("match_status", xr.get("match", ""))).lower()
                is_match = raw_status in ("match", "true", "yes")
                is_mismatch = raw_status in ("mismatch", "false", "no")
                match_str = "Yes" if is_match else ("No" if is_mismatch else "Unverified")
                row_class = "xref-mismatch" if is_mismatch else ("xref-match" if is_match else "xref-unverified")
                parts.append(
                    f"<tr class='{row_class}'><td>{entity_name}</td><td>{field}</td>"
                    f"<td>{src_a}</td><td>{src_b}</td><td>{match_str}</td></tr>"
                )

        parts.extend(["</tbody></table>", "</section>"])
        return "\n".join(parts)
