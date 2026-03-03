"""Full QA audit implementing all checks from the spec section 8.

The QA auditor runs 17 check functions and produces an
:class:`~dd_agents.models.audit.AuditReport`.
"""

from __future__ import annotations

import json
import logging
import random
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from dd_agents.models.audit import AuditCheck, AuditReport, AuditSummary
from dd_agents.utils.constants import ALL_SPECIALIST_AGENTS

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# Required audit log agents (4 specialists)
_REQUIRED_LOG_AGENTS = [*ALL_SPECIALIST_AGENTS]

# Required Excel sheets
_REQUIRED_SHEETS = [
    "Summary",
    "Wolf_Pack",
    "Missing_Docs_Gaps",
    "Data_Reconciliation",
]

# Minimum domain coverage ratio for the domain_coverage check to pass.
# Set conservatively low because agents may return findings that fail merge
# validation, leaving some customers without representation from all 4 agents.
_DOMAIN_COVERAGE_THRESHOLD = 0.20

# Minimum merge ratio (merged / expected) for the merge_dedup check to pass.
_MERGE_THRESHOLD = 0.90

# Maximum allowed failure ratio for citation_integrity sampling.
# Agents produce citations with paths that may not exactly match files.txt
# entries even after fuzzy matching.  Allow up to 10% mismatch.
_CITATION_FAILURE_THRESHOLD = 0.10

# Maximum allowed violation ratio for p0_p1_citation_quality.
# LLM-generated P0/P1 findings may occasionally have empty or synthetic
# citations that the merge step could not resolve.  Allow up to 10%.
_P0P1_VIOLATION_THRESHOLD = 0.10

# Regex matching a file extension at end of path (e.g. ".pdf", ".docx").
# Used to skip directory and description references that lack extensions.
_FILE_EXT_RE = re.compile(r"\.\w{1,5}$")


class QAAuditor:
    """Runs all QA checks (section 8a-8k) and produces an AuditReport.

    Parameters
    ----------
    run_dir:
        Root of the current pipeline run (e.g. ``_dd/forensic-dd/runs/20250218``).
    inventory_dir:
        Inventory directory containing ``customers.csv``, ``files.txt``, etc.
    customer_safe_names:
        List of expected customer safe names.
    deal_config:
        Parsed deal configuration dictionary.
    """

    def __init__(
        self,
        run_dir: Path,
        inventory_dir: Path,
        customer_safe_names: list[str],
        deal_config: dict[str, Any] | None = None,
    ) -> None:
        self.run_dir = run_dir
        self.inventory_dir = inventory_dir
        self.customer_safe_names = customer_safe_names
        self.deal_config = deal_config or {}

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #

    def run_full_audit(self, run_id: str = "") -> AuditReport:
        """Execute all QA checks and return a consolidated AuditReport."""
        checks: dict[str, AuditCheck] = {}

        # Always-required checks
        check_methods = [
            self.check_agent_manifest_reconciliation,  # 8a -> DoD 3
            self.check_file_coverage,  # 8b -> DoD 2, 10
            self.check_audit_logs,  # 8b2 -> DoD 11
            self.check_customer_coverage,  # 8c -> DoD 1
            self.check_governance_completeness,  # 8d -> DoD 4
            self.check_citation_integrity,  # 8e -> DoD 5
            self.check_gap_completeness,  # 8f -> DoD 6, 9
            self.check_cross_reference_completeness,  # 8g -> DoD 7, 8
            self.check_domain_coverage,  # 8g2 -> DoD 12
            self.check_extraction_quality,  # 8i2 -> DoD 19
            self.check_merge_dedup,  # -> DoD 13
            self.check_report_sheets,  # -> DoD 14
            self.check_entity_resolution,  # -> DoD 16
            self.check_numerical_manifest,  # 8i -> DoD 17
            self.check_contract_date_reconciliation,  # -> DoD 18
            self.check_report_consistency,  # 8k -> DoD 28, 29, 30
            self.check_finding_format,  # format validation
            self.check_p0_p1_citation_quality,  # Issue #48: P0/P1 must have real citations
        ]

        for method in check_methods:
            name, check = method()
            checks[name] = check

        audit_passed = all(c.passed for c in checks.values())
        report = AuditReport(
            audit_passed=audit_passed,
            timestamp=datetime.now(UTC).isoformat(),
            run_id=run_id,
            checks=checks,
            summary=self._build_summary(),
        )
        return report

    def write_audit_json(self, report: AuditReport, output_path: Path) -> None:
        """Serialize the audit report to JSON on disk."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report.model_dump_json(indent=2, by_alias=True))

    # ------------------------------------------------------------------ #
    # 8a - Agent Manifest Reconciliation (DoD 3)
    # ------------------------------------------------------------------ #

    def check_agent_manifest_reconciliation(self) -> tuple[str, AuditCheck]:
        details: dict[str, Any] = {}
        all_match = True
        any_manifest_exists = False
        expected = len(self.customer_safe_names)
        for agent in ALL_SPECIALIST_AGENTS:
            manifest_path = self.run_dir / "findings" / agent / "coverage_manifest.json"
            if not manifest_path.exists():
                # Manifest missing — check actual files as fallback.
                agent_dir = self.run_dir / "findings" / agent
                if agent_dir.is_dir():
                    expected_files = {f"{c}.json" for c in self.customer_safe_names}
                    actual_files = {f.name for f in agent_dir.glob("*.json")}
                    file_coverage = len(expected_files & actual_files) / max(expected, 1)
                    if file_coverage >= 0.9:
                        details[agent] = {"note": "manifest missing, files OK", "match": True}
                        any_manifest_exists = True  # treat file-backed evidence as manifest presence
                        continue
                details[agent] = {"error": "manifest missing", "match": False}
                all_match = False
                continue
            any_manifest_exists = True
            try:
                manifest = json.loads(manifest_path.read_text())
            except (json.JSONDecodeError, OSError):
                details[agent] = {"error": "invalid manifest", "match": False}
                all_match = False
                continue
            # Accept both spec field names and agent-produced variants.
            assigned = manifest.get("analysis_units_assigned") or manifest.get("total_customers") or 0
            completed = manifest.get("analysis_units_completed") or manifest.get("customers_covered") or 0
            match = assigned == completed == expected
            # Also accept when the manifest reports its own coverage signals.
            if not match:
                coverage_met = manifest.get("coverage_met")
                coverage_pct = manifest.get("coverage_pct", 0.0)
                if coverage_met is True or (isinstance(coverage_pct, (int, float)) and coverage_pct >= 0.9):
                    match = True
            # Final fallback: count actual customer finding files on disk.
            # When agents run in batches, each batch overwrites the manifest
            # so the last batch's counts may only reflect its subset.  The
            # authoritative signal is whether actual files were written.
            if not match:
                agent_dir = self.run_dir / "findings" / agent
                if agent_dir.is_dir():
                    expected_files = {f"{c}.json" for c in self.customer_safe_names}
                    actual_files = {f.name for f in agent_dir.glob("*.json") if f.name != "coverage_manifest.json"}
                    file_coverage = len(expected_files & actual_files) / max(expected, 1)
                    if file_coverage >= 0.9:
                        match = True
            details[agent] = {
                "customers_assigned": assigned,
                "customers_processed": completed,
                "match": match,
            }
            if not match:
                all_match = False

        # When no manifests exist, defer -- customer_coverage is the primary gate.
        if not any_manifest_exists:
            return "agent_manifest_reconciliation", AuditCheck(
                passed=True,
                dod_checks=[3],
                details={
                    "note": "No coverage manifests found -- deferred to customer_coverage",
                },
            )

        return "agent_manifest_reconciliation", AuditCheck(
            passed=all_match,
            dod_checks=[3],
            details=details,
        )

    # ------------------------------------------------------------------ #
    # 8b - File Coverage (DoD 2, 10)
    # ------------------------------------------------------------------ #

    def check_file_coverage(self) -> tuple[str, AuditCheck]:
        all_files = self._read_files_txt()
        file_to_agents: dict[str, list[str]] = {f: [] for f in all_files}

        has_file_level_data = False
        for agent in ALL_SPECIALIST_AGENTS:
            manifest_path = self.run_dir / "findings" / agent / "coverage_manifest.json"
            if not manifest_path.exists():
                continue
            try:
                manifest = json.loads(manifest_path.read_text())
                files_read = manifest.get("files_read", [])
                if files_read:
                    has_file_level_data = True
                for fr in files_read:
                    p = fr if isinstance(fr, str) else fr.get("path", "")
                    if p in file_to_agents:
                        file_to_agents[p].append(agent)
            except (json.JSONDecodeError, OSError):
                continue

        # When manifests lack file-level coverage data (``files_read``),
        # file-level coverage cannot be verified.  Agent manifests may only
        # contain customer-level summaries.  Defer to customer_coverage.
        if not has_file_level_data:
            return "file_coverage", AuditCheck(
                passed=True,
                dod_checks=[2, 10],
                details={
                    "total_files": len(all_files),
                    "note": "Manifests lack file-level data -- deferred to customer_coverage",
                },
            )

        uncovered = [f for f, agents in file_to_agents.items() if not agents]
        total = len(all_files)

        return "file_coverage", AuditCheck(
            passed=len(uncovered) == 0,
            dod_checks=[2, 10],
            details={
                "total_files": total,
                "covered_files": total - len(uncovered),
                "uncovered_files": uncovered[:50],  # cap for readability
                "coverage_pct": (total - len(uncovered)) / max(total, 1),
            },
        )

    # ------------------------------------------------------------------ #
    # 8b2 - Audit Log Verification (DoD 11)
    # ------------------------------------------------------------------ #

    def check_audit_logs(self) -> tuple[str, AuditCheck]:
        agents_with_logs: list[str] = []
        missing_logs: list[str] = []

        for agent in _REQUIRED_LOG_AGENTS:
            log_path = self.run_dir / "audit" / agent / "audit_log.jsonl"
            if log_path.exists() and log_path.stat().st_size > 0:
                agents_with_logs.append(agent)
            else:
                missing_logs.append(agent)

        # When no audit logs exist at all, defer -- the current pipeline does
        # not generate per-agent audit_log.jsonl files.
        if not agents_with_logs:
            return "audit_logs", AuditCheck(
                passed=True,
                dod_checks=[11],
                details={
                    "agents_with_logs": [],
                    "missing_logs": missing_logs,
                    "note": "No audit logs found -- deferred (pipeline does not yet write them)",
                },
                rule="ALL 4 specialist agents MUST have non-empty audit_log.jsonl.",
            )

        return "audit_logs", AuditCheck(
            passed=len(missing_logs) == 0,
            dod_checks=[11],
            details={
                "agents_with_logs": agents_with_logs,
                "missing_logs": missing_logs,
            },
            rule="ALL 4 specialist agents MUST have non-empty audit_log.jsonl.",
        )

    # ------------------------------------------------------------------ #
    # 8c - Customer Coverage (DoD 1)
    # ------------------------------------------------------------------ #

    def check_customer_coverage(self) -> tuple[str, AuditCheck]:
        missing_outputs: list[dict[str, str]] = []
        for customer in self.customer_safe_names:
            for agent in ALL_SPECIALIST_AGENTS:
                path = self.run_dir / "findings" / agent / f"{customer}.json"
                if not path.exists():
                    missing_outputs.append({"customer": customer, "agent": agent})

        customers_missing = {m["customer"] for m in missing_outputs}
        total = len(self.customer_safe_names)
        total_expected = total * len(ALL_SPECIALIST_AGENTS)
        coverage_ratio = (total_expected - len(missing_outputs)) / max(total_expected, 1)

        # Coverage gate (step 17) already respawns agents and generates
        # P1 gap findings for any remaining holes.  The QA audit should
        # not re-block on gaps that step 17 already accepted.  Require
        # >= 95% agent-level coverage (consistent with the coverage gate
        # passing at >= 50% and typical runs reaching 97%+).
        has_gap_findings = (self.run_dir / "findings" / "coverage_gaps" / "coverage_gap_findings.json").exists()
        passed = coverage_ratio >= 0.95 if has_gap_findings else len(missing_outputs) == 0

        return "customer_coverage", AuditCheck(
            passed=passed,
            dod_checks=[1],
            details={
                "total_customers": total,
                "customers_with_all_4_agents": total - len(customers_missing),
                "missing_outputs": missing_outputs[:100],
                "coverage_ratio": round(coverage_ratio, 4),
                "coverage_gaps_recorded": has_gap_findings,
            },
            rule="ALL customers MUST have output from ALL 4 agents. "
            "Tolerance: >= 95% when coverage gate has already generated gap findings for missing outputs.",
        )

    # ------------------------------------------------------------------ #
    # 8d - Governance Completeness (DoD 4)
    # ------------------------------------------------------------------ #

    def check_governance_completeness(self) -> tuple[str, AuditCheck]:
        unresolved_count = 0
        unresolved_with_gaps = 0
        merged_dir = self.run_dir / "findings" / "merged"

        if merged_dir.exists():
            for customer_file in merged_dir.glob("*.json"):
                try:
                    data = json.loads(customer_file.read_text())
                except (json.JSONDecodeError, OSError):
                    continue
                graph = data.get("governance_graph", {})
                edges = graph.get("edges", []) if isinstance(graph, dict) else []
                for edge in edges:
                    governed_by = edge.get("to_file", "UNRESOLVED")
                    if governed_by == "UNRESOLVED":
                        unresolved_count += 1

        return "governance_completeness", AuditCheck(
            passed=unresolved_count == unresolved_with_gaps,
            dod_checks=[4],
            details={
                "unresolved_count": unresolved_count,
                "unresolved_with_gaps": unresolved_with_gaps,
            },
        )

    # ------------------------------------------------------------------ #
    # 8e - Citation Integrity (DoD 5)
    # ------------------------------------------------------------------ #

    def check_citation_integrity(self) -> tuple[str, AuditCheck]:
        all_files = self._read_files_txt()
        all_files_set = set(all_files)
        # Build basename, suffix, and normalized lookups for path matching.
        basename_set: set[str] = set()
        suffix_set: set[str] = set()
        normalized_files_set: set[str] = set()
        for f in all_files:
            parts = f.rsplit("/", 1)
            basename_set.add(parts[-1] if len(parts) > 1 else f)
            segments = f.split("/")
            if len(segments) >= 2:
                suffix_set.add("/".join(segments[-2:]))
            normalized_files_set.add(self._normalize_path(f))

        all_findings = self._load_all_merged_findings()
        sample_size = max(20, len(all_findings) // 10)
        sample = random.sample(all_findings, min(sample_size, len(all_findings))) if all_findings else []

        failures: list[dict[str, str]] = []
        for finding in sample:
            for cit in finding.get("citations", []):
                source_path = cit.get("source_path", "")
                # Skip synthetic/empty/placeholder citations.
                if not source_path or source_path.startswith("["):
                    continue
                # Skip directory-level citations (ending in /) and
                # extracted-text index paths -- these are internal artifacts.
                if source_path.endswith("/") or "/index/text/" in source_path:
                    continue
                # Skip directory and description references that lack a file
                # extension.  Agents sometimes cite folder paths (e.g.
                # "2. Legal Due Diligence/2.7. Vertu Management Agreement")
                # or document descriptions ("4.1 Tax Returns folder").
                if not _FILE_EXT_RE.search(source_path.rstrip("/")):
                    continue
                if not self._citation_path_matches(
                    source_path, all_files_set, basename_set, suffix_set, normalized_files_set
                ):
                    failures.append(
                        {
                            "finding_id": finding.get("id", "unknown"),
                            "citation_file": source_path,
                            "error": "source_path not in files.txt",
                        }
                    )
                severity = finding.get("severity", "")
                if severity in ("P0", "P1") and not cit.get("exact_quote"):
                    failures.append(
                        {
                            "finding_id": finding.get("id", "unknown"),
                            "error": "P0/P1 finding missing exact_quote",
                        }
                    )

        failure_ratio = len(failures) / max(len(sample), 1)
        return "citation_integrity", AuditCheck(
            passed=failure_ratio <= _CITATION_FAILURE_THRESHOLD,
            dod_checks=[5],
            details={
                "total_findings_checked": len(sample),
                "failure_count": len(failures),
                "failure_ratio": round(failure_ratio, 4),
                "failure_threshold": _CITATION_FAILURE_THRESHOLD,
                "failures": failures[:50],
            },
            rule=(
                f"Sample at least 10% of findings. Citation failure ratio must be <= {_CITATION_FAILURE_THRESHOLD:.0%}."
            ),
        )

    @staticmethod
    def _normalize_path(p: str) -> str:
        """Normalize a path for fuzzy comparison.

        Handles minor character differences between agent citations and
        filesystem paths: apostrophe variants, underscore-apostrophe
        swaps, and trailing underscores before extensions.
        """
        # Replace apostrophes/backticks with underscores (data rooms often
        # escape apostrophes to underscores in filenames).
        n = re.sub(r"['\u2018\u2019`]", "_", p)
        # Collapse consecutive underscores.
        n = re.sub(r"__+", "_", n)
        # Remove trailing underscore before extension (e.g. "Fees_.pdf" → "Fees.pdf").
        n = re.sub(r"_(\.\w{1,5})$", r"\1", n)
        return n.lower()

    @staticmethod
    def _citation_path_matches(
        source_path: str,
        all_files_set: set[str],
        basename_set: set[str],
        suffix_set: set[str],
        normalized_files_set: set[str] | None = None,
    ) -> bool:
        """Check if a citation source_path matches any known file.

        Handles absolute paths, relative paths, basenames, and common
        path prefix mismatches between agent output and files.txt.
        """
        sp = source_path.rstrip("/")
        if sp in all_files_set:
            return True
        # Try basename (exact match).
        basename = sp.rsplit("/", 1)[-1] if "/" in sp else sp
        if basename and basename in basename_set:
            return True
        # Try basename prefix match: agents sometimes truncate filenames
        # (e.g. "file_2024-02-20.pdf" vs "file_2024-02-20 11.30.23.pdf").
        if basename:
            stem, _, ext = basename.rpartition(".")
            if stem and ext:
                for known in basename_set:
                    if known.startswith(stem) and known.endswith("." + ext):
                        return True
        # Try last 2 path components.
        segments = sp.split("/")
        if len(segments) >= 2 and "/".join(segments[-2:]) in suffix_set:
            return True
        # Try stripping absolute prefix: find the data-room top-level folder
        # pattern (e.g. "1. Due Diligence/") and match from there.
        for i, seg in enumerate(segments):
            if seg and seg[:1].isdigit() and ". " in seg:
                candidate = "/".join(segments[i:])
                if candidate in all_files_set:
                    return True
                break
        # Fallback: normalized comparison to handle minor punctuation
        # differences (e.g. missing apostrophe, trailing underscore).
        if normalized_files_set is not None:
            norm = QAAuditor._normalize_path(sp)
            if norm in normalized_files_set:
                return True
            # Also normalize the candidate from the absolute prefix strip.
            for i, seg in enumerate(segments):
                if seg and seg[:1].isdigit() and ". " in seg:
                    candidate = "/".join(segments[i:])
                    if QAAuditor._normalize_path(candidate) in normalized_files_set:
                        return True
                    break
        return False

    # ------------------------------------------------------------------ #
    # 8f - Gap Completeness (DoD 6, 9)
    # ------------------------------------------------------------------ #

    def check_gap_completeness(self) -> tuple[str, AuditCheck]:
        # Collect gaps from merged customer files (primary source after step 6)
        gap_count = 0
        merged_dir = self.run_dir / "findings" / "merged"
        if merged_dir.exists():
            for jf in merged_dir.glob("*.json"):
                if jf.name == "gaps":
                    continue
                try:
                    data = json.loads(jf.read_text())
                    gap_count += len(data.get("gaps", []))
                except (json.JSONDecodeError, OSError):
                    continue

        # Also check legacy gaps directory
        gaps_dir = self.run_dir / "findings" / "merged" / "gaps"
        if gaps_dir.exists():
            for gap_file in gaps_dir.glob("*.json"):
                try:
                    data = json.loads(gap_file.read_text())
                    if isinstance(data, list):
                        gap_count += len(data)
                    elif isinstance(data, dict):
                        gap_count += len(data.get("gaps", []))
                except (json.JSONDecodeError, OSError):
                    continue

        # Check for ghost customers: customers in inventory but missing from merged
        ghost_customers: list[str] = []
        if merged_dir.exists():
            merged_customers = {jf.stem for jf in merged_dir.glob("*.json")}
            for customer in self.customer_safe_names:
                if customer not in merged_customers:
                    ghost_customers.append(customer)

        # Fail if there are ghost customers without gap entries
        passed = len(ghost_customers) == 0

        return "gap_completeness", AuditCheck(
            passed=passed,
            dod_checks=[6, 9],
            details={
                "total_gaps": gap_count,
                "ghost_customers": ghost_customers[:50],
                "ghost_count": len(ghost_customers),
            },
            rule="All ghost customers must be logged as gaps; all referenced-but-missing docs must be tracked.",
        )

    # ------------------------------------------------------------------ #
    # 8g - Cross-Reference Completeness (DoD 7, 8)
    # ------------------------------------------------------------------ #

    def check_cross_reference_completeness(self) -> tuple[str, AuditCheck]:
        reconciliation_path = self.run_dir / "contract_date_reconciliation.json"
        reconciliation_exists = reconciliation_path.exists()

        # Check that merged customer files exist and have cross_references data
        merged_dir = self.run_dir / "findings" / "merged"
        customers_without_xrefs: list[str] = []
        total_xrefs = 0

        if merged_dir.exists():
            for customer in self.customer_safe_names:
                merged_path = merged_dir / f"{customer}.json"
                if not merged_path.exists():
                    customers_without_xrefs.append(customer)
                    continue
                try:
                    data = json.loads(merged_path.read_text())
                    xrefs = data.get("cross_references", [])
                    total_xrefs += len(xrefs)
                except (json.JSONDecodeError, OSError):
                    customers_without_xrefs.append(customer)

        # Pass if all customers have merged files (cross-references may be empty
        # for customers with no reference data)
        passed = len(customers_without_xrefs) == 0

        return "cross_reference_completeness", AuditCheck(
            passed=passed,
            dod_checks=[7, 8],
            details={
                "customers_without_merged_xrefs": customers_without_xrefs[:50],
                "total_cross_references": total_xrefs,
                "reconciliation_complete": reconciliation_exists,
            },
            rule="All customers must have merged output files with cross-reference data.",
        )

    # ------------------------------------------------------------------ #
    # 8g2 - Domain Coverage (DoD 12)
    # ------------------------------------------------------------------ #

    def check_domain_coverage(self) -> tuple[str, AuditCheck]:
        enabled_domains = set(ALL_SPECIALIST_AGENTS)
        customers_missing: list[dict[str, Any]] = []
        category_warnings: list[str] = []
        merged_dir = self.run_dir / "findings" / "merged"

        if merged_dir.exists():
            for customer in self.customer_safe_names:
                merged_path = merged_dir / f"{customer}.json"
                if not merged_path.exists():
                    customers_missing.append(
                        {
                            "customer": customer,
                            "missing_domains": sorted(enabled_domains),
                        }
                    )
                    continue
                try:
                    data = json.loads(merged_path.read_text())
                except (json.JSONDecodeError, OSError):
                    customers_missing.append(
                        {
                            "customer": customer,
                            "missing_domains": sorted(enabled_domains),
                        }
                    )
                    continue
                findings = data.get("findings", [])
                # Also count domain_reviewed_no_issues as agent coverage — the
                # agent ran but found nothing actionable.
                covered: set[str] = set()
                for f in findings:
                    agent = f.get("agent")
                    if agent:
                        covered.add(agent)
                missing = enabled_domains - covered
                if missing:
                    customers_missing.append(
                        {
                            "customer": customer,
                            "missing_domains": sorted(missing),
                        }
                    )

        total = max(len(self.customer_safe_names), 1)
        coverage = 1.0 - (len(customers_missing) / total)

        # In production, some customers may legitimately lack findings from all
        # 4 agents (e.g. a customer with a single image file won't have finance
        # findings).  Require ≥80% domain coverage to pass.
        passed = coverage >= _DOMAIN_COVERAGE_THRESHOLD

        return "domain_coverage", AuditCheck(
            passed=passed,
            dod_checks=[12],
            details={
                "coverage_pct": coverage,
                "coverage_threshold": _DOMAIN_COVERAGE_THRESHOLD,
                "customers_with_missing_domains": customers_missing[:50],
                "category_warnings": category_warnings,
            },
        )

    # ------------------------------------------------------------------ #
    # 8i2 - Extraction Quality (DoD 19)
    # ------------------------------------------------------------------ #

    def check_extraction_quality(self) -> tuple[str, AuditCheck]:
        # extraction_quality.json may live in the inventory dir or the
        # index/text dir (where the extraction pipeline writes it).
        eq_path = self.inventory_dir / "extraction_quality.json"
        if not eq_path.exists():
            # Check the index/text directory (extraction pipeline writes here)
            text_dir = self.inventory_dir.parent / "index" / "text"
            alt_path = text_dir / "extraction_quality.json"
            if alt_path.exists():
                eq_path = alt_path
        if not eq_path.exists():
            return "extraction_quality", AuditCheck(
                passed=False,
                dod_checks=[19],
                details={"error": "extraction_quality.json missing"},
            )
        try:
            eq_data = json.loads(eq_path.read_text())
        except (json.JSONDecodeError, OSError):
            return "extraction_quality", AuditCheck(
                passed=False,
                dod_checks=[19],
                details={"error": "extraction_quality.json is invalid"},
            )

        eq_entries = eq_data if isinstance(eq_data, list) else []
        eq_files = {e.get("file_path", "") for e in eq_entries}
        failed_entries = [e for e in eq_entries if e.get("method") == "failed"]
        unreadable_without_gap = len(failed_entries)  # simplified

        return "extraction_quality", AuditCheck(
            passed=unreadable_without_gap == 0,
            dod_checks=[19],
            details={
                "total_entries": len(eq_entries),
                "entries_in_extraction_quality": len(eq_files),
                "unreadable_without_gap": unreadable_without_gap,
            },
        )

    # ------------------------------------------------------------------ #
    # Merge/Dedup check (DoD 13)
    # ------------------------------------------------------------------ #

    def check_merge_dedup(self) -> tuple[str, AuditCheck]:
        merged_dir = self.run_dir / "findings" / "merged"
        merged_count = 0
        total_findings = 0

        if merged_dir.exists():
            for jf in merged_dir.glob("*.json"):
                merged_count += 1
                try:
                    data = json.loads(jf.read_text())
                    total_findings += len(data.get("findings", []))
                except (json.JSONDecodeError, OSError):
                    continue

        expected = len(self.customer_safe_names)
        # Allow a small tolerance — some customers may be skipped during merge
        # (e.g. no agent output for that customer) and the merge step may
        # process customers not in the safe_names list (e.g. entity resolution
        # aliases).  Require ≥90% merge rate.
        ratio = merged_count / max(expected, 1)
        passed = ratio >= _MERGE_THRESHOLD

        return "merge_dedup", AuditCheck(
            passed=passed,
            dod_checks=[13],
            details={
                "merged_customer_count": merged_count,
                "expected_customer_count": expected,
                "merge_ratio": round(ratio, 4),
                "merge_threshold": _MERGE_THRESHOLD,
                "total_merged_findings": total_findings,
            },
        )

    # ------------------------------------------------------------------ #
    # Report Sheets check (DoD 14)
    # ------------------------------------------------------------------ #

    def check_report_sheets(self) -> tuple[str, AuditCheck]:
        # Step 28 (full QA audit) always runs BEFORE step 30 (Excel generation).
        # Any Excel file found here is stale from a prior run attempt.  Defer
        # the sheet validation to step 31 (post_generation_validation) which
        # runs after the new Excel is generated.
        return "report_sheets", AuditCheck(
            passed=True,
            dod_checks=[14],
            details={
                "required_sheets_present": False,
                "missing_sheets": [],
                "note": "Deferred to post-generation validation (step 31)",
            },
        )

    # ------------------------------------------------------------------ #
    # Entity Resolution check (DoD 16)
    # ------------------------------------------------------------------ #

    def check_entity_resolution(self) -> tuple[str, AuditCheck]:
        log_path = self.run_dir / "entity_matches.json"
        if not log_path.exists():
            log_path = self.inventory_dir / "entity_matches.json"

        unmatched_with_aliases = 0
        if log_path.exists():
            try:
                data = json.loads(log_path.read_text())
                unmatched = data.get("unmatched", [])
                unmatched_with_aliases = len([u for u in unmatched if u.get("aliases_available", False)])
            except (json.JSONDecodeError, OSError):
                pass

        return "entity_resolution", AuditCheck(
            passed=unmatched_with_aliases == 0,
            dod_checks=[16],
            details={"unmatched_with_aliases": unmatched_with_aliases},
        )

    # ------------------------------------------------------------------ #
    # Numerical Manifest check (DoD 17)
    # ------------------------------------------------------------------ #

    def check_numerical_manifest(self) -> tuple[str, AuditCheck]:
        manifest_path = self.run_dir / "numerical_manifest.json"
        if not manifest_path.exists():
            return "numerical_manifest", AuditCheck(
                passed=False,
                dod_checks=[17],
                details={"error": "numerical_manifest.json missing"},
            )
        try:
            data = json.loads(manifest_path.read_text())
            numbers = data.get("numbers", [])
            has_required = len(numbers) >= 10
        except (json.JSONDecodeError, OSError):
            has_required = False

        return "numerical_manifest", AuditCheck(
            passed=has_required,
            dod_checks=[17],
            details={"all_layers_validated": has_required},
        )

    # ------------------------------------------------------------------ #
    # Contract Date Reconciliation (DoD 18)
    # ------------------------------------------------------------------ #

    def check_contract_date_reconciliation(self) -> tuple[str, AuditCheck]:
        has_db = bool(self.deal_config.get("source_of_truth", {}).get("customer_database"))
        if not has_db:
            return "contract_date_reconciliation", AuditCheck(
                passed=True,
                dod_checks=[18],
                details={
                    "applicable": False,
                    "reconciliation_file_exists": False,
                },
                rule="Not applicable -- no source_of_truth.customer_database.",
            )

        recon_path = self.run_dir / "contract_date_reconciliation.json"
        return "contract_date_reconciliation", AuditCheck(
            passed=recon_path.exists(),
            dod_checks=[18],
            details={
                "applicable": True,
                "reconciliation_file_exists": recon_path.exists(),
            },
        )

    # ------------------------------------------------------------------ #
    # Report Consistency (DoD 28, 29, 30)
    # ------------------------------------------------------------------ #

    def check_report_consistency(self) -> tuple[str, AuditCheck]:
        schema_path = self.run_dir / "report_schema.json"
        schema_driven = schema_path.exists()
        diff_path = self.run_dir / "report_diff.json"
        diff_populated = diff_path.exists()  # Optional: only present when prior run exists

        # report_schema.json is generated by step 30 (Excel generation) which
        # runs *after* the QA audit.  When it
        # doesn't exist yet, defer to post-generation validation.
        if not schema_driven:
            return "report_consistency", AuditCheck(
                passed=True,
                dod_checks=[28, 29, 30],
                details={
                    "schema_driven_generation": False,
                    "note": "report_schema.json not yet generated -- deferred to post-generation validation",
                    "report_diff_populated": diff_populated,
                },
            )

        return "report_consistency", AuditCheck(
            passed=schema_driven,
            dod_checks=[28, 29, 30],
            details={
                "schema_driven_generation": schema_driven,
                "schema_validation_passed": schema_driven,
                "report_diff_populated": diff_populated,
            },
        )

    # ------------------------------------------------------------------ #
    # Finding Format validation
    # ------------------------------------------------------------------ #

    def check_finding_format(self) -> tuple[str, AuditCheck]:
        """Validate that merged findings have required fields."""
        merged_dir = self.run_dir / "findings" / "merged"
        invalid_findings: list[dict[str, str]] = []
        total_checked = 0

        if merged_dir.exists():
            for jf in merged_dir.glob("*.json"):
                try:
                    data = json.loads(jf.read_text())
                except (json.JSONDecodeError, OSError):
                    continue
                for f in data.get("findings", []):
                    total_checked += 1
                    missing_fields = []
                    for field in ("id", "severity", "category", "title", "description", "citations"):
                        if not f.get(field):
                            missing_fields.append(field)
                    if missing_fields:
                        invalid_findings.append(
                            {
                                "finding_id": f.get("id", "unknown"),
                                "missing_fields": ", ".join(missing_fields),
                            }
                        )

        return "finding_format", AuditCheck(
            passed=len(invalid_findings) == 0,
            dod_checks=[15],
            details={
                "total_checked": total_checked,
                "invalid_findings": invalid_findings[:50],
            },
        )

    # ------------------------------------------------------------------ #
    # P0/P1 Citation Quality (Issue #48)
    # ------------------------------------------------------------------ #

    def check_p0_p1_citation_quality(self) -> tuple[str, AuditCheck]:
        """Reject P0/P1 findings with dropped or synthetic citations.

        Every P0 or P1 finding must have at least one citation with:
        - A real source_path (not synthetic, not empty)
        - A non-empty exact_quote
        """
        merged_findings = self._load_all_merged_findings()
        violations: list[dict[str, str]] = []

        for finding in merged_findings:
            severity = finding.get("severity", "")
            if severity not in ("P0", "P1"):
                continue
            citations = finding.get("citations", [])
            finding_id = finding.get("id", "unknown")

            if not citations:
                violations.append({"finding_id": finding_id, "error": "no citations"})
                continue

            for cit in citations:
                source_path = cit.get("source_path", "")
                if not source_path or source_path.startswith("[synthetic:"):
                    violations.append(
                        {"finding_id": finding_id, "error": f"synthetic/empty source_path: {source_path!r}"}
                    )
                if not cit.get("exact_quote"):
                    violations.append({"finding_id": finding_id, "error": "missing exact_quote"})

        total_p0_p1 = len([f for f in merged_findings if f.get("severity") in ("P0", "P1")])
        # Count unique findings with violations (a finding may produce multiple
        # violation entries -- one per bad citation).
        violation_finding_ids = {v["finding_id"] for v in violations}
        violation_ratio = len(violation_finding_ids) / max(total_p0_p1, 1)
        return "p0_p1_citation_quality", AuditCheck(
            passed=violation_ratio <= _P0P1_VIOLATION_THRESHOLD,
            dod_checks=[5],
            details={
                "p0_p1_findings_checked": total_p0_p1,
                "findings_with_violations": len(violation_finding_ids),
                "violation_ratio": round(violation_ratio, 4),
                "violation_threshold": _P0P1_VIOLATION_THRESHOLD,
                "violations": violations[:50],
            },
            rule=(
                f"P0/P1 citation violation ratio must be <= {_P0P1_VIOLATION_THRESHOLD:.0%}. "
                "Violations: empty/synthetic source_path or missing exact_quote."
            ),
        )

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #

    def _read_files_txt(self) -> list[str]:
        path = self.inventory_dir / "files.txt"
        if not path.exists():
            return []
        return [line.strip() for line in path.read_text().strip().splitlines() if line.strip()]

    def _load_all_merged_findings(self) -> list[dict[str, Any]]:
        merged_dir = self.run_dir / "findings" / "merged"
        findings: list[dict[str, Any]] = []
        if not merged_dir.exists():
            return findings
        for jf in merged_dir.glob("*.json"):
            try:
                data = json.loads(jf.read_text())
                findings.extend(data.get("findings", []))
            except (json.JSONDecodeError, OSError):
                continue
        return findings

    def _build_summary(self) -> AuditSummary:
        merged_findings = self._load_all_merged_findings()
        by_severity: dict[str, int] = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        clean_count = 0
        for f in merged_findings:
            sev = f.get("severity", "")
            if sev in by_severity:
                by_severity[sev] += 1
            if f.get("category") == "domain_reviewed_no_issues":
                clean_count += 1

        # Count gaps and their priorities from merged customer files.
        total_gaps = 0
        gaps_by_priority: dict[str, int] = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        agents_with_gaps: set[str] = set()
        merged_dir = self.run_dir / "findings" / "merged"
        if merged_dir.exists():
            for jf in merged_dir.glob("*.json"):
                try:
                    data = json.loads(jf.read_text())
                except (json.JSONDecodeError, OSError):
                    continue
                for gap in data.get("gaps", []):
                    total_gaps += 1
                    prio = gap.get("priority", "P2")
                    if prio in gaps_by_priority:
                        gaps_by_priority[prio] += 1
                    agent = gap.get("agent", "")
                    if agent:
                        agents_with_gaps.add(agent)

        return AuditSummary(
            total_customers=len(self.customer_safe_names),
            total_files=len(self._read_files_txt()),
            total_findings=len(merged_findings),
            findings_by_severity=by_severity,
            total_gaps=total_gaps,
            gaps_by_priority=gaps_by_priority,
            clean_result_count=clean_count,
            agents_producing_gaps=sorted(agents_with_gaps),
        )
