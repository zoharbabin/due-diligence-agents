"""Unit tests for the dd_agents.validation module.

Tests cover:
- CoverageValidator: correct count passes, missing customer fails, empty dir
- NumericalAuditor: source traceability, cross-source consistency, semantic reasonableness
- QAAuditor: basic audit with sample data
- DefinitionOfDoneChecker: check count, conditional check grouping
- SchemaValidator: validate matching Excel passes, mismatched fails
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from dd_agents.models.audit import AuditCheck, AuditReport
from dd_agents.models.numerical import ManifestEntry, NumericalManifest
from dd_agents.validation.coverage import CoverageValidator
from dd_agents.validation.dod import DefinitionOfDoneChecker
from dd_agents.validation.numerical_audit import NumericalAuditor
from dd_agents.validation.qa_audit import QAAuditor
from dd_agents.validation.schema_validator import SchemaValidator

if TYPE_CHECKING:
    from pathlib import Path

# ===================================================================== #
# Helpers for building sample data
# ===================================================================== #

CUSTOMERS = ["acme_corp", "globex", "initech"]
AGENTS = ["legal", "finance", "commercial", "producttech"]


def _make_customer_json(customer: str, agent: str) -> dict:
    """Minimal valid per-customer agent output."""
    return {
        "customer": customer,
        "customer_safe_name": customer,
        "agent": agent,
        "run_id": "run_001",
        "timestamp": "2025-02-18T00:00:00Z",
        "files_analyzed": 1,
        "findings": [
            {
                "id": f"forensic-dd_{agent}_{customer}_0001",
                "severity": "P2",
                "category": "test_category",
                "title": "Test finding",
                "description": "Test description",
                "citations": [
                    {
                        "source_type": "file",
                        "source_path": f"{customer}/contract.pdf",
                        "exact_quote": "test quote",
                    }
                ],
                "confidence": "high",
                "agent": agent,
            }
        ],
        "gaps": [],
    }


def _make_merged_json(customer: str) -> dict:
    """Minimal merged per-customer output."""
    return {
        "customer": customer,
        "customer_safe_name": customer,
        "findings": [
            {
                "id": f"forensic-dd_legal_{customer}_0001",
                "severity": "P2",
                "category": "test_category",
                "title": "Test finding",
                "description": "Test description",
                "citations": [
                    {
                        "source_type": "file",
                        "source_path": f"{customer}/contract.pdf",
                        "exact_quote": "test quote",
                    }
                ],
                "confidence": "high",
                "agent": "legal",
            }
        ],
        "governance_graph": {"edges": []},
    }


def _make_coverage_manifest(agent: str, customers: list[str]) -> dict:
    """Minimal coverage manifest."""
    return {
        "agent": agent,
        "skill": "forensic-dd",
        "run_id": "run_001",
        "files_assigned": [f"{c}/contract.pdf" for c in customers],
        "files_read": [{"path": f"{c}/contract.pdf"} for c in customers],
        "files_skipped": [],
        "files_failed": [],
        "coverage_pct": 1.0,
        "analysis_units_assigned": len(customers),
        "analysis_units_completed": len(customers),
        "customers": [
            {
                "name": c,
                "files_assigned": [f"{c}/contract.pdf"],
                "files_processed": [f"{c}/contract.pdf"],
                "status": "complete",
            }
            for c in customers
        ],
    }


def _make_manifest(
    n001: int = 3,
    n003: int = 10,
    n004: int = 1,
    n005: int = 2,
    n006: int = 3,
    n007: int = 4,
    n008: int = 0,
    n009: int = 5,
) -> NumericalManifest:
    """Build a NumericalManifest with the given values."""
    return NumericalManifest(
        generated_at="2025-02-18T00:00:00Z",
        numbers=[
            ManifestEntry(
                id="N001", label="total_customers", value=n001, source_file="customers.csv", derivation="COUNT(rows)"
            ),
            ManifestEntry(id="N002", label="total_files", value=20, source_file="files.txt", derivation="wc -l"),
            ManifestEntry(
                id="N003", label="total_findings", value=n003, source_file="findings/*.json", derivation="SUM(findings)"
            ),
            ManifestEntry(
                id="N004", label="findings_p0", value=n004, source_file="findings/*.json", derivation="COUNT(P0)"
            ),
            ManifestEntry(
                id="N005", label="findings_p1", value=n005, source_file="findings/*.json", derivation="COUNT(P1)"
            ),
            ManifestEntry(
                id="N006", label="findings_p2", value=n006, source_file="findings/*.json", derivation="COUNT(P2)"
            ),
            ManifestEntry(
                id="N007", label="findings_p3", value=n007, source_file="findings/*.json", derivation="COUNT(P3)"
            ),
            ManifestEntry(
                id="N008",
                label="clean_result_count",
                value=n008,
                source_file="findings/*.json",
                derivation="COUNT(clean)",
            ),
            ManifestEntry(
                id="N009", label="total_gaps", value=n009, source_file="gaps/*.json", derivation="COUNT(gaps)"
            ),
            ManifestEntry(
                id="N010",
                label="total_reference_files",
                value=5,
                source_file="reference_files.json",
                derivation="len(files)",
            ),
        ],
    )


def _populate_run_dir(
    run_dir: Path,
    inventory_dir: Path,
    customers: list[str] | None = None,
) -> None:
    """Populate a run directory with minimal valid data for QA checks."""
    customers = customers or CUSTOMERS

    # Inventory files
    inventory_dir.mkdir(parents=True, exist_ok=True)
    files_list = [f"{c}/contract.pdf" for c in customers]
    (inventory_dir / "files.txt").write_text("\n".join(files_list) + "\n")
    (inventory_dir / "customers.csv").write_text(
        "group,name,safe_name,path,file_count\n" + "\n".join(f"group1,{c},{c},/data/{c},1" for c in customers) + "\n"
    )
    (inventory_dir / "counts.json").write_text(
        json.dumps({"total_customers": len(customers), "total_files": len(files_list)})
    )
    (inventory_dir / "extraction_quality.json").write_text("[]")

    # Per-agent output directories
    for agent in AGENTS:
        agent_dir = run_dir / "findings" / agent
        agent_dir.mkdir(parents=True, exist_ok=True)
        for customer in customers:
            (agent_dir / f"{customer}.json").write_text(json.dumps(_make_customer_json(customer, agent)))
        (agent_dir / "coverage_manifest.json").write_text(json.dumps(_make_coverage_manifest(agent, customers)))

    # Merged output
    merged_dir = run_dir / "findings" / "merged"
    merged_dir.mkdir(parents=True, exist_ok=True)
    for customer in customers:
        (merged_dir / f"{customer}.json").write_text(json.dumps(_make_merged_json(customer)))

    # Audit logs
    for agent in [*AGENTS, "reporting_lead"]:
        log_dir = run_dir / "audit" / agent
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "audit_log.jsonl").write_text(
            json.dumps(
                {
                    "ts": "2025-02-18T00:00:00Z",
                    "agent": agent,
                    "skill": "forensic-dd",
                    "action": "phase_complete",
                    "target": "analysis",
                    "result": "complete",
                }
            )
            + "\n"
        )

    # Report directory with dummy Excel
    report_dir = run_dir / "report"
    report_dir.mkdir(parents=True, exist_ok=True)


# ===================================================================== #
# CoverageValidator Tests
# ===================================================================== #


class TestCoverageValidator:
    """Tests for CoverageValidator."""

    def test_correct_count_passes(self, tmp_path: Path) -> None:
        """When every customer has output from every agent, all checks pass."""
        agent_dirs: dict[str, Path] = {}
        for agent in AGENTS:
            d = tmp_path / agent
            d.mkdir()
            for customer in CUSTOMERS:
                (d / f"{customer}.json").write_text(json.dumps(_make_customer_json(customer, agent)))
            agent_dirs[agent] = d

        validator = CoverageValidator()
        results = validator.validate(agent_dirs, CUSTOMERS)

        # 4 per-agent checks + 1 aggregate = 5
        assert len(results) == 5
        for check in results:
            assert isinstance(check, AuditCheck)
            assert check.passed is True

    def test_missing_customer_fails(self, tmp_path: Path) -> None:
        """Missing a customer JSON for one agent causes failure."""
        agent_dirs: dict[str, Path] = {}
        for agent in AGENTS:
            d = tmp_path / agent
            d.mkdir()
            for customer in CUSTOMERS:
                if agent == "legal" and customer == "initech":
                    continue  # skip one
                (d / f"{customer}.json").write_text(json.dumps(_make_customer_json(customer, agent)))
            agent_dirs[agent] = d

        validator = CoverageValidator()
        results = validator.validate(agent_dirs, CUSTOMERS)

        # The legal agent check should fail
        legal_check = next(r for r in results if r.details.get("agent") == "legal")
        assert legal_check.passed is False
        assert "initech" in legal_check.details["missing_customers"]

        # Aggregate should also fail
        aggregate = next(r for r in results if r.details.get("aggregate"))
        assert aggregate.passed is False

    def test_empty_dir_fails(self, tmp_path: Path) -> None:
        """An empty agent output directory means all customers are missing."""
        agent_dirs: dict[str, Path] = {}
        for agent in AGENTS:
            d = tmp_path / agent
            d.mkdir()
            # Do not create any JSON files
            agent_dirs[agent] = d

        validator = CoverageValidator()
        results = validator.validate(agent_dirs, CUSTOMERS)

        for check in results:
            if check.details.get("aggregate"):
                assert check.passed is False
            elif "agent" in check.details:
                assert check.passed is False
                assert len(check.details["missing_customers"]) == len(CUSTOMERS)

    def test_missing_agent_dir(self, tmp_path: Path) -> None:
        """When an agent directory does not exist, check fails."""
        agent_dirs: dict[str, Path] = {}
        for agent in AGENTS:
            if agent == "finance":
                agent_dirs[agent] = tmp_path / "nonexistent"
            else:
                d = tmp_path / agent
                d.mkdir()
                for customer in CUSTOMERS:
                    (d / f"{customer}.json").write_text(json.dumps(_make_customer_json(customer, agent)))
                agent_dirs[agent] = d

        validator = CoverageValidator()
        results = validator.validate(agent_dirs, CUSTOMERS)

        finance_check = next(r for r in results if r.details.get("agent") == "finance")
        assert finance_check.passed is False
        assert finance_check.details["error"] == "output directory missing"

    def test_empty_json_file_detected(self, tmp_path: Path) -> None:
        """A JSON file with no findings/gaps is flagged as empty."""
        d = tmp_path / "legal"
        d.mkdir()
        for customer in CUSTOMERS:
            data = {"customer": customer, "findings": [], "gaps": []}
            (d / f"{customer}.json").write_text(json.dumps(data))

        agent_dirs = {"legal": d}
        # Only check legal to isolate the test
        validator = CoverageValidator()
        results = validator.validate(agent_dirs, CUSTOMERS)

        legal_check = next(r for r in results if r.details.get("agent") == "legal")
        assert len(legal_check.details["empty_files"]) == len(CUSTOMERS)


# ===================================================================== #
# NumericalAuditor Tests
# ===================================================================== #


class TestNumericalAuditor:
    """Tests for NumericalAuditor."""

    def test_source_traceability_passes_with_existing_files(self, tmp_path: Path) -> None:
        """Layer 1 passes when all source files exist."""
        # Create source files that the manifest entries reference
        (tmp_path / "customers.csv").write_text("header\nrow1\nrow2\nrow3\n")
        (tmp_path / "files.txt").write_text("file1\nfile2\n")
        (tmp_path / "reference_files.json").write_text("[]")
        # Create directories with JSON files for glob patterns
        findings_dir = tmp_path / "findings"
        findings_dir.mkdir()
        (findings_dir / "sample.json").write_text("{}")
        gaps_dir = tmp_path / "gaps"
        gaps_dir.mkdir()
        (gaps_dir / "sample.json").write_text("{}")

        manifest = _make_manifest(n001=3)
        # Override source_file to use tmp_path
        for entry in manifest.numbers:
            entry.source_file = str(tmp_path / entry.source_file)

        auditor = NumericalAuditor(run_dir=tmp_path, inventory_dir=tmp_path)
        check = auditor.check_source_traceability(manifest)
        assert check.passed is True
        assert check.details["layer"] == 1

    def test_source_traceability_fails_for_missing_file(self, tmp_path: Path) -> None:
        """Layer 1 fails when a source file is missing."""
        manifest = _make_manifest()
        # Point to nonexistent files
        for entry in manifest.numbers:
            entry.source_file = str(tmp_path / "nonexistent" / entry.source_file)

        auditor = NumericalAuditor(run_dir=tmp_path, inventory_dir=tmp_path)
        check = auditor.check_source_traceability(manifest)
        assert check.passed is False
        assert len(check.details["failures"]) > 0

    def test_source_traceability_fails_for_missing_derivation(self, tmp_path: Path) -> None:
        """Layer 1 fails when derivation is empty."""
        manifest = _make_manifest()
        manifest.numbers[0].derivation = ""
        manifest.numbers[0].source_file = str(tmp_path)  # exists
        for entry in manifest.numbers[1:]:
            entry.source_file = str(tmp_path)

        auditor = NumericalAuditor(run_dir=tmp_path, inventory_dir=tmp_path)
        check = auditor.check_source_traceability(manifest)
        assert check.passed is False
        assert any("missing derivation" in f for f in check.details["failures"])

    def test_cross_source_consistency_passes(self, tmp_path: Path) -> None:
        """Layer 3 passes when severity sum equals total findings."""
        manifest = _make_manifest(n003=10, n004=1, n005=2, n006=3, n007=4)
        (tmp_path / "customers.csv").write_text("header\n" + "\n".join(f"row{i}" for i in range(3)) + "\n")
        (tmp_path / "counts.json").write_text(json.dumps({"total_customers": 3}))

        auditor = NumericalAuditor(run_dir=tmp_path, inventory_dir=tmp_path)
        check = auditor.check_cross_source_consistency(manifest)
        assert check.passed is True

    def test_cross_source_consistency_fails_on_mismatch(self, tmp_path: Path) -> None:
        """Layer 3 fails when severity sum does not equal total findings."""
        # N003=10 but N004+N005+N006+N007 = 1+2+3+5 = 11
        manifest = _make_manifest(n003=10, n004=1, n005=2, n006=3, n007=5)
        (tmp_path / "customers.csv").write_text("header\n" + "\n".join(f"row{i}" for i in range(3)) + "\n")
        (tmp_path / "counts.json").write_text(json.dumps({"total_customers": 3}))

        auditor = NumericalAuditor(run_dir=tmp_path, inventory_dir=tmp_path)
        check = auditor.check_cross_source_consistency(manifest)
        assert check.passed is False
        assert any("N004+N005+N006+N007" in f for f in check.details["failures"])

    def test_cross_source_csv_vs_counts_mismatch(self, tmp_path: Path) -> None:
        """Layer 3 catches customers.csv vs counts.json mismatch."""
        manifest = _make_manifest(n001=5)
        (tmp_path / "customers.csv").write_text(
            "header\nrow1\nrow2\nrow3\n"  # 3 data rows
        )
        (tmp_path / "counts.json").write_text(
            json.dumps({"total_customers": 5})  # different from CSV
        )

        auditor = NumericalAuditor(run_dir=tmp_path, inventory_dir=tmp_path)
        check = auditor.check_cross_source_consistency(manifest)
        assert check.passed is False

    def test_semantic_reasonableness_passes(self, tmp_path: Path) -> None:
        """Layer 5 passes for reasonable values."""
        manifest = _make_manifest(n003=10, n004=1)
        auditor = NumericalAuditor(run_dir=tmp_path, inventory_dir=tmp_path)
        check = auditor.check_semantic_reasonableness(manifest)
        assert check.passed is True

    def test_semantic_reasonableness_negative_values(self, tmp_path: Path) -> None:
        """Layer 5 fails on negative values."""
        manifest = _make_manifest()
        manifest.numbers[0].value = -5

        auditor = NumericalAuditor(run_dir=tmp_path, inventory_dir=tmp_path)
        check = auditor.check_semantic_reasonableness(manifest)
        assert check.passed is False
        assert any("negative" in f for f in check.details["failures"])

    def test_semantic_reasonableness_p0_exceeds_total(self, tmp_path: Path) -> None:
        """Layer 5 flags P0 count exceeding total findings."""
        manifest = _make_manifest(n003=5, n004=10)  # P0=10 > total=5
        auditor = NumericalAuditor(run_dir=tmp_path, inventory_dir=tmp_path)
        check = auditor.check_semantic_reasonableness(manifest)
        assert check.passed is False
        assert any("P0 findings count > total findings" in f for f in check.details["failures"])

    def test_semantic_reasonableness_customer_count_spike(self, tmp_path: Path) -> None:
        """Layer 5 flags >20% customer count change between runs."""
        prior = _make_manifest(n001=100)
        current = _make_manifest(n001=150)  # 50% change

        auditor = NumericalAuditor(
            run_dir=tmp_path,
            inventory_dir=tmp_path,
            prior_manifest=prior,
        )
        check = auditor.check_semantic_reasonableness(current)
        assert check.passed is False
        assert any("Customer count changed" in f for f in check.details["failures"])

    def test_run_full_audit(self, tmp_path: Path) -> None:
        """Full audit returns 4 checks (layers 1, 2, 3, 5)."""
        manifest = _make_manifest(n003=10, n004=1, n005=2, n006=3, n007=4)
        (tmp_path / "customers.csv").write_text("header\n" + "\n".join(f"row{i}" for i in range(3)) + "\n")
        (tmp_path / "counts.json").write_text(json.dumps({"total_customers": 3}))

        auditor = NumericalAuditor(run_dir=tmp_path, inventory_dir=tmp_path)
        checks = auditor.run_full_audit(manifest)
        assert len(checks) == 4
        layers = [c.details["layer"] for c in checks]
        assert sorted(layers) == [1, 2, 3, 5]


# ===================================================================== #
# QAAuditor Tests
# ===================================================================== #


class TestQAAuditor:
    """Tests for QAAuditor."""

    def test_basic_audit_with_sample_data(self, tmp_path: Path) -> None:
        """QAAuditor runs all 17 checks and produces an AuditReport."""
        run_dir = tmp_path / "run"
        inventory_dir = tmp_path / "inventory"
        _populate_run_dir(run_dir, inventory_dir)

        # Add report_schema.json for consistency check
        (run_dir / "report_schema.json").write_text("{}")

        # Add numerical_manifest.json
        manifest = _make_manifest()
        (run_dir / "numerical_manifest.json").write_text(manifest.model_dump_json())

        auditor = QAAuditor(
            run_dir=run_dir,
            inventory_dir=inventory_dir,
            customer_safe_names=CUSTOMERS,
        )
        report = auditor.run_full_audit(run_id="test_run")

        assert isinstance(report, AuditReport)
        assert report.run_id == "test_run"
        # Should have 17 check entries
        assert len(report.checks) == 17

    def test_customer_coverage_fails_when_missing(self, tmp_path: Path) -> None:
        """Customer coverage check fails when a customer file is missing."""
        run_dir = tmp_path / "run"
        inventory_dir = tmp_path / "inventory"
        _populate_run_dir(run_dir, inventory_dir)

        # Remove one customer file from one agent
        (run_dir / "findings" / "legal" / "initech.json").unlink()

        auditor = QAAuditor(
            run_dir=run_dir,
            inventory_dir=inventory_dir,
            customer_safe_names=CUSTOMERS,
        )
        report = auditor.run_full_audit()

        cov = report.checks.get("customer_coverage")
        assert cov is not None
        assert cov.passed is False

    def test_write_audit_json(self, tmp_path: Path) -> None:
        """write_audit_json creates a valid JSON file."""
        run_dir = tmp_path / "run"
        inventory_dir = tmp_path / "inventory"
        _populate_run_dir(run_dir, inventory_dir)
        (run_dir / "report_schema.json").write_text("{}")
        manifest = _make_manifest()
        (run_dir / "numerical_manifest.json").write_text(manifest.model_dump_json())

        auditor = QAAuditor(
            run_dir=run_dir,
            inventory_dir=inventory_dir,
            customer_safe_names=CUSTOMERS,
        )
        report = auditor.run_full_audit(run_id="test_run")

        output_path = tmp_path / "audit.json"
        auditor.write_audit_json(report, output_path)
        assert output_path.exists()

        data = json.loads(output_path.read_text())
        assert "audit_passed" in data
        assert "checks" in data
        assert "summary" in data

    def test_audit_summary_counts(self, tmp_path: Path) -> None:
        """AuditReport summary reflects merged findings."""
        run_dir = tmp_path / "run"
        inventory_dir = tmp_path / "inventory"
        _populate_run_dir(run_dir, inventory_dir)
        (run_dir / "report_schema.json").write_text("{}")
        manifest = _make_manifest()
        (run_dir / "numerical_manifest.json").write_text(manifest.model_dump_json())

        auditor = QAAuditor(
            run_dir=run_dir,
            inventory_dir=inventory_dir,
            customer_safe_names=CUSTOMERS,
        )
        report = auditor.run_full_audit()

        assert report.summary.total_customers == len(CUSTOMERS)
        assert report.summary.total_findings >= 0


# ===================================================================== #
# DefinitionOfDoneChecker Tests
# ===================================================================== #


class TestDefinitionOfDoneChecker:
    """Tests for DefinitionOfDoneChecker."""

    def test_check_count_without_conditionals(self, tmp_path: Path) -> None:
        """Without conditional features, expect 30 - 8 conditional = 22 checks."""
        run_dir = tmp_path / "run"
        inventory_dir = tmp_path / "inventory"
        _populate_run_dir(run_dir, inventory_dir)

        checker = DefinitionOfDoneChecker(
            run_dir=run_dir,
            inventory_dir=inventory_dir,
            customer_safe_names=CUSTOMERS,
            deal_config={},
        )
        results = checker.check_all()

        # Core (12) + Reporting (5) + Contract Dates (1) + Extraction (1)
        # + Report Consistency (3) = 22 (no Judge, no Incremental)
        assert len(results) == 22

    def test_check_count_with_judge(self, tmp_path: Path) -> None:
        """With judge.enabled, 4 additional checks appear."""
        run_dir = tmp_path / "run"
        inventory_dir = tmp_path / "inventory"
        _populate_run_dir(run_dir, inventory_dir)

        checker = DefinitionOfDoneChecker(
            run_dir=run_dir,
            inventory_dir=inventory_dir,
            customer_safe_names=CUSTOMERS,
            deal_config={"judge": {"enabled": True, "threshold": 70}},
        )
        results = checker.check_all()
        assert len(results) == 26  # 22 + 4 judge

    def test_check_count_with_incremental(self, tmp_path: Path) -> None:
        """With incremental mode, 4 additional checks appear."""
        run_dir = tmp_path / "run"
        inventory_dir = tmp_path / "inventory"
        _populate_run_dir(run_dir, inventory_dir)

        checker = DefinitionOfDoneChecker(
            run_dir=run_dir,
            inventory_dir=inventory_dir,
            customer_safe_names=CUSTOMERS,
            deal_config={"execution": {"mode": "incremental"}},
        )
        results = checker.check_all()
        assert len(results) == 26  # 22 + 4 incremental

    def test_check_count_with_all_conditionals(self, tmp_path: Path) -> None:
        """With all conditionals, expect full 30 checks."""
        run_dir = tmp_path / "run"
        inventory_dir = tmp_path / "inventory"
        _populate_run_dir(run_dir, inventory_dir)

        checker = DefinitionOfDoneChecker(
            run_dir=run_dir,
            inventory_dir=inventory_dir,
            customer_safe_names=CUSTOMERS,
            deal_config={
                "judge": {"enabled": True, "threshold": 70},
                "execution": {"mode": "incremental"},
            },
        )
        results = checker.check_all()
        assert len(results) == 30

    def test_all_checks_return_audit_check(self, tmp_path: Path) -> None:
        """Every check returns an AuditCheck instance."""
        run_dir = tmp_path / "run"
        inventory_dir = tmp_path / "inventory"
        _populate_run_dir(run_dir, inventory_dir)

        checker = DefinitionOfDoneChecker(
            run_dir=run_dir,
            inventory_dir=inventory_dir,
            customer_safe_names=CUSTOMERS,
        )
        results = checker.check_all()
        for check in results:
            assert isinstance(check, AuditCheck)
            assert isinstance(check.dod_checks, list)
            assert len(check.dod_checks) >= 1

    def test_customer_outputs_pass_with_full_data(self, tmp_path: Path) -> None:
        """DoD check 1 passes when all customer outputs exist."""
        run_dir = tmp_path / "run"
        inventory_dir = tmp_path / "inventory"
        _populate_run_dir(run_dir, inventory_dir)

        checker = DefinitionOfDoneChecker(
            run_dir=run_dir,
            inventory_dir=inventory_dir,
            customer_safe_names=CUSTOMERS,
        )
        check = checker.check_1_customer_outputs_complete()
        assert check.passed is True
        assert 1 in check.dod_checks

    def test_customer_outputs_fail_missing_file(self, tmp_path: Path) -> None:
        """DoD check 1 fails when a customer file is missing."""
        run_dir = tmp_path / "run"
        inventory_dir = tmp_path / "inventory"
        _populate_run_dir(run_dir, inventory_dir)
        (run_dir / "findings" / "legal" / "acme_corp.json").unlink()

        checker = DefinitionOfDoneChecker(
            run_dir=run_dir,
            inventory_dir=inventory_dir,
            customer_safe_names=CUSTOMERS,
        )
        check = checker.check_1_customer_outputs_complete()
        assert check.passed is False

    def test_dod_groups_cover_all_30(self) -> None:
        """Verify that check group ranges cover exactly 1..30."""
        all_nums = set()
        all_nums.update(DefinitionOfDoneChecker.CORE_ANALYSIS)
        all_nums.update(DefinitionOfDoneChecker.REPORTING)
        all_nums.update(DefinitionOfDoneChecker.CONTRACT_DATES)
        all_nums.update(DefinitionOfDoneChecker.EXTRACTION)
        all_nums.update(DefinitionOfDoneChecker.JUDGE)
        all_nums.update(DefinitionOfDoneChecker.INCREMENTAL)
        all_nums.update(DefinitionOfDoneChecker.REPORT_CONSISTENCY)
        assert all_nums == set(range(1, 31))


# ===================================================================== #
# SchemaValidator Tests
# ===================================================================== #


class TestSchemaValidator:
    """Tests for SchemaValidator."""

    @pytest.fixture()
    def _excel_with_matching_schema(self, tmp_path: Path):
        """Create a matching Excel + ReportSchema pair."""
        from dd_agents.models.reporting import (
            ColumnDef,
            ReportSchema,
            SheetDef,
            SortOrder,
        )

        schema = ReportSchema(
            schema_version="1.0",
            sheets=[
                SheetDef(
                    name="Summary",
                    required=True,
                    columns=[
                        ColumnDef(name="Customer", key="customer", type="string"),
                        ColumnDef(name="Findings", key="findings", type="integer"),
                    ],
                    sort_order=[SortOrder(column="Customer", direction="asc")],
                ),
                SheetDef(
                    name="Wolf_Pack",
                    required=True,
                    columns=[
                        ColumnDef(name="ID", key="id", type="string"),
                        ColumnDef(name="Severity", key="severity", type="string"),
                    ],
                ),
            ],
        )

        # Create matching Excel
        import openpyxl

        wb = openpyxl.Workbook()

        ws_summary = wb.active
        ws_summary.title = "Summary"
        ws_summary.append(["Customer", "Findings"])
        ws_summary.append(["Acme Corp", 10])
        ws_summary.append(["Globex", 5])
        ws_summary.append(["Initech", 8])

        ws_wolf = wb.create_sheet("Wolf_Pack")
        ws_wolf.append(["ID", "Severity"])
        ws_wolf.append(["F001", "P0"])

        excel_path = tmp_path / "report.xlsx"
        wb.save(excel_path)

        return schema, excel_path

    def test_matching_excel_passes(self, _excel_with_matching_schema: tuple, tmp_path: Path) -> None:
        """A workbook matching the schema passes all checks."""
        schema, excel_path = _excel_with_matching_schema

        validator = SchemaValidator(schema)
        checks = validator.validate_report(excel_path)

        assert len(checks) >= 3  # sheets, columns, sort, formatting
        for check in checks:
            assert isinstance(check, AuditCheck)
            assert check.passed is True, f"Check failed: {check.details}"

    def test_missing_sheet_fails(self, tmp_path: Path) -> None:
        """When a required sheet is missing, the sheets_exist check fails."""
        from dd_agents.models.reporting import (
            ColumnDef,
            ReportSchema,
            SheetDef,
        )

        schema = ReportSchema(
            schema_version="1.0",
            sheets=[
                SheetDef(
                    name="Summary",
                    required=True,
                    columns=[
                        ColumnDef(name="Customer", key="customer", type="string"),
                    ],
                ),
                SheetDef(
                    name="Details",
                    required=True,
                    columns=[
                        ColumnDef(name="ID", key="id", type="string"),
                    ],
                ),
            ],
        )

        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Summary"
        ws.append(["Customer"])
        # "Details" sheet is missing
        excel_path = tmp_path / "report.xlsx"
        wb.save(excel_path)

        validator = SchemaValidator(schema)
        checks = validator.validate_report(excel_path)

        sheets_check = next(c for c in checks if c.details.get("check") == "sheets_exist")
        assert sheets_check.passed is False
        assert "Details" in sheets_check.details["missing_sheets"]

    def test_column_mismatch_fails(self, tmp_path: Path) -> None:
        """When column names do not match, the columns_match check fails."""
        from dd_agents.models.reporting import (
            ColumnDef,
            ReportSchema,
            SheetDef,
        )

        schema = ReportSchema(
            schema_version="1.0",
            sheets=[
                SheetDef(
                    name="Summary",
                    required=True,
                    columns=[
                        ColumnDef(name="Customer", key="customer", type="string"),
                        ColumnDef(name="Findings Count", key="findings", type="integer"),
                    ],
                ),
            ],
        )

        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Summary"
        ws.append(["Customer", "Total Issues"])  # wrong column name
        excel_path = tmp_path / "report.xlsx"
        wb.save(excel_path)

        validator = SchemaValidator(schema)
        checks = validator.validate_report(excel_path)

        col_check = next(c for c in checks if c.details.get("check") == "columns_match")
        assert col_check.passed is False

    def test_nonexistent_excel_fails(self, tmp_path: Path) -> None:
        """When the Excel file does not exist, validation fails immediately."""
        from dd_agents.models.reporting import ReportSchema

        schema = ReportSchema(schema_version="1.0", sheets=[])
        validator = SchemaValidator(schema)
        checks = validator.validate_report(tmp_path / "nonexistent.xlsx")

        assert len(checks) == 1
        assert checks[0].passed is False

    def test_sort_order_validated(self, tmp_path: Path) -> None:
        """Sort order check detects incorrectly sorted data."""
        from dd_agents.models.reporting import (
            ColumnDef,
            ReportSchema,
            SheetDef,
            SortOrder,
        )

        schema = ReportSchema(
            schema_version="1.0",
            sheets=[
                SheetDef(
                    name="Summary",
                    required=True,
                    columns=[
                        ColumnDef(name="Customer", key="customer", type="string"),
                    ],
                    sort_order=[SortOrder(column="Customer", direction="asc")],
                ),
            ],
        )

        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Summary"
        ws.append(["Customer"])
        ws.append(["Zebra"])  # wrong order
        ws.append(["Acme"])
        ws.append(["Middle"])
        excel_path = tmp_path / "report.xlsx"
        wb.save(excel_path)

        validator = SchemaValidator(schema)
        checks = validator.validate_report(excel_path)

        sort_check = next(c for c in checks if c.details.get("check") == "sort_orders")
        assert sort_check.passed is False
