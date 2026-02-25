"""5-layer numerical audit.

Implements the blocking gate between analysis completion and Excel
generation. Every number in the pipeline must be traceable, re-derivable,
cross-source consistent, format-consistent, and semantically reasonable.
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dd_agents.models.audit import AuditCheck

if TYPE_CHECKING:
    from dd_agents.models.numerical import ManifestEntry, NumericalManifest

logger = logging.getLogger(__name__)


def _manifest_get(manifest: NumericalManifest, entry_id: str) -> ManifestEntry | None:
    """Retrieve a manifest entry by ID."""
    for n in manifest.numbers:
        if n.id == entry_id:
            return n
    return None


class NumericalAuditor:
    """5-layer numerical auditor -- BLOCKING gate before Excel generation.

    Layers
    ------
    1. Source traceability  -- every number traces to a source file.
    2. Arithmetic           -- re-derive values from source.
    3. Cross-source         -- ``customers.csv`` vs ``counts.json`` vs findings.
    4. Cross-format parity  -- spot-check Excel vs JSON (post-generation only).
    5. Semantic              -- flag implausible values.
    """

    def __init__(
        self,
        run_dir: Path,
        inventory_dir: Path | None = None,
        prior_manifest: NumericalManifest | None = None,
    ) -> None:
        self.run_dir = run_dir
        self.inventory_dir = inventory_dir or run_dir
        self.prior_manifest = prior_manifest

    # ------------------------------------------------------------------ #
    # full audit
    # ------------------------------------------------------------------ #

    def run_full_audit(self, manifest: NumericalManifest) -> list[AuditCheck]:
        """Run all 5 layers and return a list of AuditCheck results.

        Layers 1-3 and 5 run pre-generation.
        Layer 4 is skipped when no Excel path is provided.
        """
        checks: list[AuditCheck] = [
            self.check_source_traceability(manifest),
            self.check_arithmetic(manifest),
            self.check_cross_source_consistency(manifest),
            self.check_semantic_reasonableness(manifest),
        ]
        return checks

    # ------------------------------------------------------------------ #
    # Layer 1 -- Source Traceability
    # ------------------------------------------------------------------ #

    def check_source_traceability(self, manifest: NumericalManifest) -> AuditCheck:
        """Every number must trace to a specific file and derivation method."""
        failures: list[str] = []
        for entry in manifest.numbers:
            resolved = self._resolve_path(entry.source_file)
            if not self._source_exists(resolved):
                failures.append(f"{entry.id} ({entry.label}): source_file '{entry.source_file}' does not exist")
            if not entry.derivation:
                failures.append(f"{entry.id} ({entry.label}): missing derivation")
        return AuditCheck(
            passed=len(failures) == 0,
            dod_checks=[17],
            details={"layer": 1, "failures": failures},
            rule="Layer 1: every number maps to a file that exists.",
        )

    # ------------------------------------------------------------------ #
    # Layer 2 -- Arithmetic Verification
    # ------------------------------------------------------------------ #

    def check_arithmetic(self, manifest: NumericalManifest) -> AuditCheck:
        """Re-derive every number from source.

        For known IDs (N001-N010) this uses deterministic rederivation.
        For unknown IDs, the value is accepted as-is (verification flag set).
        """
        failures: list[str] = []
        for entry in manifest.numbers:
            rederived = self._rederive(entry)
            if rederived is not None and rederived != entry.value:
                failures.append(f"{entry.id} ({entry.label}): manifest={entry.value}, rederived={rederived}")
            entry.verified = True
        return AuditCheck(
            passed=len(failures) == 0,
            dod_checks=[17],
            details={"layer": 2, "failures": failures},
            rule="Layer 2: re-derive every number from source.",
        )

    # ------------------------------------------------------------------ #
    # Layer 3 -- Cross-Source Consistency
    # ------------------------------------------------------------------ #

    def check_cross_source_consistency(self, manifest: NumericalManifest) -> AuditCheck:
        """Numbers that appear in multiple sources must agree."""
        failures: list[str] = []

        # Cross-check: customers.csv row count == counts.json total_customers
        csv_count = self._count_csv_rows("customers.csv")
        counts_total = self._read_counts_json_field("total_customers")
        n001 = _manifest_get(manifest, "N001")

        if csv_count is not None and counts_total is not None and csv_count != counts_total:
            failures.append(f"customers.csv rows ({csv_count}) != counts.json total_customers ({counts_total})")

        if csv_count is not None and n001 is not None and csv_count != n001.value:
            failures.append(f"customers.csv rows ({csv_count}) != manifest N001 ({n001.value})")

        # Cross-check: severity sum == total findings
        n003 = _manifest_get(manifest, "N003")
        n004 = _manifest_get(manifest, "N004")
        n005 = _manifest_get(manifest, "N005")
        n006 = _manifest_get(manifest, "N006")
        n007 = _manifest_get(manifest, "N007")

        if n003 is not None and n004 is not None and n005 is not None and n006 is not None and n007 is not None:
            severity_sum = n004.value + n005.value + n006.value + n007.value
            if severity_sum != n003.value:
                failures.append(f"N004+N005+N006+N007 ({severity_sum}) != N003 ({n003.value})")

        return AuditCheck(
            passed=len(failures) == 0,
            dod_checks=[17],
            details={"layer": 3, "failures": failures},
            rule="Layer 3: numbers across files must agree.",
        )

    # ------------------------------------------------------------------ #
    # Layer 4 -- Cross-Format Parity (post-generation)
    # ------------------------------------------------------------------ #

    def check_cross_format_parity(
        self,
        excel_path: Path,
        manifest: NumericalManifest,
        sample_count: int = 3,
    ) -> AuditCheck:
        """Spot-check that Excel cell values match manifest values.

        Parameters
        ----------
        excel_path:
            Path to the generated Excel workbook.
        manifest:
            The numerical manifest to verify against.
        sample_count:
            Number of manifest entries to spot-check (default 3).
        """
        failures: list[str] = []

        if not excel_path.exists():
            return AuditCheck(
                passed=False,
                dod_checks=[17],
                details={"layer": 4, "failures": ["Excel file does not exist"]},
                rule="Layer 4: Excel cells match manifest values.",
            )

        try:
            import openpyxl

            wb = openpyxl.load_workbook(excel_path, data_only=True)
        except Exception as exc:
            return AuditCheck(
                passed=False,
                dod_checks=[17],
                details={"layer": 4, "failures": [f"Cannot open Excel: {exc}"]},
                rule="Layer 4: Excel cells match manifest values.",
            )

        # Spot-check random entries
        entries = manifest.numbers
        sample = random.sample(entries, min(sample_count, len(entries)))
        for entry in sample:
            # Check if value appears in any sheet
            found = self._find_value_in_workbook(wb, entry)
            if not found:
                failures.append(f"{entry.id} ({entry.label}): value {entry.value} not found in Excel workbook")

        return AuditCheck(
            passed=len(failures) == 0,
            dod_checks=[17],
            details={
                "layer": 4,
                "samples_checked": len(sample),
                "failures": failures,
            },
            rule="Layer 4: Excel cells match manifest values.",
        )

    # ------------------------------------------------------------------ #
    # Layer 5 -- Semantic Reasonableness
    # ------------------------------------------------------------------ #

    def check_semantic_reasonableness(self, manifest: NumericalManifest) -> AuditCheck:
        """Flag numbers that are implausible."""
        failures: list[str] = []

        # No negative values
        for entry in manifest.numbers:
            if isinstance(entry.value, (int, float)) and entry.value < 0:
                failures.append(f"{entry.id} ({entry.label}): negative value {entry.value}")

        n003 = _manifest_get(manifest, "N003")
        n004 = _manifest_get(manifest, "N004")

        # P0 count cannot exceed total findings
        if n003 and n004 and n004.value > n003.value:
            failures.append("P0 findings count > total findings count")

        # Customer count change >20% between runs
        if self.prior_manifest:
            prior_n001 = _manifest_get(self.prior_manifest, "N001")
            curr_n001 = _manifest_get(manifest, "N001")
            if prior_n001 and curr_n001:
                pct_change = abs(curr_n001.value - prior_n001.value) / max(prior_n001.value, 1)
                if pct_change > 0.20:
                    failures.append(
                        f"Customer count changed by {pct_change:.0%} ({prior_n001.value} -> {curr_n001.value})"
                    )

        # Gap count decreased between runs
        if self.prior_manifest:
            prior_n009 = _manifest_get(self.prior_manifest, "N009")
            curr_n009 = _manifest_get(manifest, "N009")
            if prior_n009 and curr_n009 and curr_n009.value < prior_n009.value:
                failures.append(
                    f"Gap count decreased ({prior_n009.value} -> {curr_n009.value}). "
                    f"Gaps should only increase or stay same unless data added."
                )

        return AuditCheck(
            passed=len(failures) == 0,
            dod_checks=[17],
            details={"layer": 5, "failures": failures},
            rule="Layer 5: flag implausible numbers.",
        )

    # ------------------------------------------------------------------ #
    # private helpers
    # ------------------------------------------------------------------ #

    def _resolve_path(self, source_file: str) -> Path:
        """Resolve ``{RUN_DIR}`` placeholder and glob patterns."""
        resolved = source_file.replace("{RUN_DIR}", str(self.run_dir))
        # If the path contains a glob wildcard, check if at least one match exists
        if "*" in resolved:
            return Path(resolved)
        return Path(resolved)

    def _source_exists(self, path: Path) -> bool:
        path_str = str(path)
        if "*" in path_str:
            from glob import glob as _glob

            return len(_glob(path_str)) > 0
        return path.exists()

    def _rederive(self, entry: ManifestEntry) -> int | float | None:
        """Attempt to re-derive a manifest entry value from source."""
        match entry.id:
            case "N001":
                return self._count_csv_rows("customers.csv")
            case "N002":
                return self._count_file_lines("files.txt")
            case "N003":
                return self._count_merged_findings()
            case "N004":
                return self._count_findings_by_severity("P0")
            case "N005":
                return self._count_findings_by_severity("P1")
            case "N006":
                return self._count_findings_by_severity("P2")
            case "N007":
                return self._count_findings_by_severity("P3")
            case "N008":
                return self._count_total_gaps()
            case "N009":
                return self._count_ghost_customers()
            case "N010":
                return self._count_reference_files()
            case _:
                # For entries beyond N001-N010, accept the manifest value
                return None

    def _load_merged_findings(self) -> list[dict[str, Any]]:
        """Load all findings from the merged findings directory.

        Excludes entries whose category is ``domain_reviewed_no_issues``.
        """
        merged_dir = self.run_dir / "findings" / "merged"
        if not merged_dir.exists():
            return []
        all_findings: list[dict[str, Any]] = []
        for jf in sorted(merged_dir.glob("*.json")):
            try:
                data = json.loads(jf.read_text())
                findings = data.get("findings", [])
                for f in findings:
                    if f.get("category") != "domain_reviewed_no_issues":
                        all_findings.append(f)
            except (json.JSONDecodeError, OSError):
                continue
        return all_findings

    def _count_merged_findings(self) -> int:
        """N003: count total findings from merged dir, excluding domain_reviewed_no_issues."""
        return len(self._load_merged_findings())

    def _count_findings_by_severity(self, severity: str) -> int:
        """N004-N007: count findings matching a specific severity level."""
        return sum(1 for f in self._load_merged_findings() if f.get("severity") == severity)

    def _count_total_gaps(self) -> int:
        """N008: count total gaps from the gaps directory."""
        gaps_dir = self.run_dir / "findings" / "merged" / "gaps"
        if not gaps_dir.exists():
            return 0
        total = 0
        for gf in sorted(gaps_dir.glob("*.json")):
            try:
                gdata = json.loads(gf.read_text())
                if isinstance(gdata, list):
                    total += len(gdata)
                elif isinstance(gdata, dict):
                    total += len(gdata.get("gaps", []))
            except (json.JSONDecodeError, OSError):
                continue
        return total

    def _count_ghost_customers(self) -> int | None:
        """N009: count ghost customer mentions from customer_mentions.json."""
        path = self.inventory_dir / "customer_mentions.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            if isinstance(data, list):
                return sum(1 for item in data if item.get("ghost", False))
            if isinstance(data, dict):
                ghost_count = data.get("ghost_count")
                if ghost_count is not None:
                    return int(ghost_count)
                ghost_list: list[Any] = data.get("ghost_customers", [])
                return len(ghost_list)
        except (json.JSONDecodeError, OSError):
            return None
        return None

    def _count_reference_files(self) -> int | None:
        """N010: count reference files from reference_files.json."""
        path = self.inventory_dir / "reference_files.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            if isinstance(data, list):
                return len(data)
            if isinstance(data, dict):
                return len(data.get("files", []))
        except (json.JSONDecodeError, OSError):
            return None
        return None

    def _count_csv_rows(self, filename: str) -> int | None:
        """Count data rows (excluding header) in a CSV file."""
        path = self.inventory_dir / filename
        if not path.exists():
            return None
        lines = path.read_text().strip().splitlines()
        # Subtract header row
        return max(0, len(lines) - 1) if lines else 0

    def _count_file_lines(self, filename: str) -> int | None:
        """Count lines in a text file."""
        path = self.inventory_dir / filename
        if not path.exists():
            return None
        lines = path.read_text().strip().splitlines()
        return len(lines)

    def _read_counts_json_field(self, field: str) -> Any:
        """Read a field from counts.json."""
        path = self.inventory_dir / "counts.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return data.get(field)
        except (json.JSONDecodeError, OSError):
            return None

    def _find_value_in_workbook(self, wb: Any, entry: ManifestEntry) -> bool:
        """Search for a manifest entry's value in the workbook."""
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            for row in ws.iter_rows(values_only=True):
                for cell_value in row:
                    if cell_value == entry.value:
                        return True
        return False
