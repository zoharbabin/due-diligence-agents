"""Unit tests for pre-merge validation and cross-agent anomaly detection (step 23).

Covers:
- File completeness checks (missing agent files detected / all present passes)
- JSON integrity checks (corrupt files detected)
- Schema compliance checks (missing required keys flagged)
- Citation path verification (invalid paths flagged / valid paths pass)
- Asymmetric risk detection (P0+zero flagged / balanced not flagged)
- Severity disagreement detection (2+ level gap flagged / adjacent not flagged)
- Summary matrix correctness
- Report serialization (writes valid JSON)
- Non-customer files excluded (coverage_manifest.json)
- Empty findings array handled
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from dd_agents.validation.pre_merge import PreMergeValidator

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

AGENTS = ["legal", "finance", "commercial", "producttech"]
CUSTOMERS = ["customer_a", "customer_b"]


def _make_finding(
    severity: str = "P2",
    category: str = "general",
    title: str = "Test finding",
    source_path: str = "1. Due Diligence/doc.pdf",
) -> dict[str, Any]:
    return {
        "severity": severity,
        "category": category,
        "title": title,
        "description": "A test finding description.",
        "citations": [
            {
                "source_path": source_path,
                "exact_quote": "some text",
            }
        ],
    }


def _write_agent_file(
    findings_dir: Path,
    agent: str,
    customer: str,
    findings: list[dict[str, Any]] | None = None,
) -> None:
    """Write a customer JSON file into the agent's findings directory."""
    agent_dir = findings_dir / agent
    agent_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "customer": customer,
        "customer_safe_name": customer,
        "agent": agent,
        "findings": findings if findings is not None else [_make_finding()],
    }
    (agent_dir / f"{customer}.json").write_text(json.dumps(data, indent=2))


def _setup_complete(findings_dir: Path, file_inventory: list[str] | None = None) -> PreMergeValidator:
    """Create a validator with all 4 agents × 2 customers populated."""
    for agent in AGENTS:
        for customer in CUSTOMERS:
            _write_agent_file(findings_dir, agent, customer)
    inv = file_inventory or ["1. Due Diligence/doc.pdf"]
    return PreMergeValidator(
        run_dir=findings_dir.parent,
        findings_dir=findings_dir,
        customer_safe_names=CUSTOMERS,
        file_inventory=inv,
    )


# ---------------------------------------------------------------------------
# File completeness
# ---------------------------------------------------------------------------


class TestFileCompleteness:
    def test_missing_agent_file_detected(self, tmp_path: Path) -> None:
        findings_dir = tmp_path / "findings"
        # Write files for all agents except finance for customer_b
        for agent in AGENTS:
            for customer in CUSTOMERS:
                if agent == "finance" and customer == "customer_b":
                    continue
                _write_agent_file(findings_dir, agent, customer)

        validator = PreMergeValidator(
            run_dir=tmp_path,
            findings_dir=findings_dir,
            customer_safe_names=CUSTOMERS,
            file_inventory=["1. Due Diligence/doc.pdf"],
        )
        report = validator.validate()
        assert len(report.file_completeness_issues) > 0
        issue = report.file_completeness_issues[0]
        assert issue["customer"] == "customer_b"
        assert "finance" in issue["missing_agents"]

    def test_all_present_passes(self, tmp_path: Path) -> None:
        findings_dir = tmp_path / "findings"
        validator = _setup_complete(findings_dir)
        report = validator.validate()
        assert report.file_completeness_issues == []


# ---------------------------------------------------------------------------
# JSON integrity
# ---------------------------------------------------------------------------


class TestJsonIntegrity:
    def test_corrupt_file_detected(self, tmp_path: Path) -> None:
        findings_dir = tmp_path / "findings"
        # Set up normal files first
        for agent in AGENTS:
            for customer in CUSTOMERS:
                _write_agent_file(findings_dir, agent, customer)

        # Corrupt one file
        corrupt_path = findings_dir / "legal" / "customer_a.json"
        corrupt_path.write_text("{invalid json content")

        validator = PreMergeValidator(
            run_dir=tmp_path,
            findings_dir=findings_dir,
            customer_safe_names=CUSTOMERS,
            file_inventory=["1. Due Diligence/doc.pdf"],
        )
        report = validator.validate()
        assert len(report.json_integrity_issues) > 0
        assert report.json_integrity_issues[0]["agent"] == "legal"
        assert report.json_integrity_issues[0]["customer"] == "customer_a"
        # Corrupt JSON makes the report not pass
        assert report.passed is False


# ---------------------------------------------------------------------------
# Schema compliance
# ---------------------------------------------------------------------------


class TestSchemaCompliance:
    def test_missing_required_keys_flagged(self, tmp_path: Path) -> None:
        findings_dir = tmp_path / "findings"
        for agent in AGENTS:
            for customer in CUSTOMERS:
                _write_agent_file(findings_dir, agent, customer)

        # Write a finding missing "severity" and "citations"
        bad_data = {
            "customer": "customer_a",
            "customer_safe_name": "customer_a",
            "agent": "legal",
            "findings": [
                {
                    "category": "general",
                    "title": "Incomplete finding",
                    "description": "Missing severity and citations.",
                }
            ],
        }
        (findings_dir / "legal" / "customer_a.json").write_text(json.dumps(bad_data))

        validator = PreMergeValidator(
            run_dir=tmp_path,
            findings_dir=findings_dir,
            customer_safe_names=CUSTOMERS,
            file_inventory=["1. Due Diligence/doc.pdf"],
        )
        report = validator.validate()
        assert len(report.schema_issues) > 0
        # Should flag missing severity and citations
        missing_keys = {k for issue in report.schema_issues for k in issue.get("missing_keys", [])}
        assert "severity" in missing_keys or "citations" in missing_keys


# ---------------------------------------------------------------------------
# Citation path verification
# ---------------------------------------------------------------------------


class TestCitationPaths:
    def test_invalid_paths_flagged(self, tmp_path: Path) -> None:
        findings_dir = tmp_path / "findings"
        for agent in AGENTS:
            for customer in CUSTOMERS:
                _write_agent_file(
                    findings_dir,
                    agent,
                    customer,
                    [_make_finding(source_path="nonexistent/path/to/file.pdf")],
                )

        validator = PreMergeValidator(
            run_dir=tmp_path,
            findings_dir=findings_dir,
            customer_safe_names=CUSTOMERS,
            file_inventory=["1. Due Diligence/doc.pdf"],
        )
        report = validator.validate()
        assert len(report.citation_path_issues) > 0

    def test_valid_paths_pass(self, tmp_path: Path) -> None:
        findings_dir = tmp_path / "findings"
        validator = _setup_complete(findings_dir, file_inventory=["1. Due Diligence/doc.pdf"])
        report = validator.validate()
        assert report.citation_path_issues == []


# ---------------------------------------------------------------------------
# Asymmetric risk detection
# ---------------------------------------------------------------------------


class TestAsymmetricRisk:
    def test_p0_plus_zero_findings_flagged(self, tmp_path: Path) -> None:
        findings_dir = tmp_path / "findings"
        for agent in AGENTS:
            for customer in CUSTOMERS:
                if agent == "legal" and customer == "customer_a":
                    _write_agent_file(findings_dir, agent, customer, [_make_finding(severity="P0")])
                elif agent == "finance" and customer == "customer_a":
                    _write_agent_file(findings_dir, agent, customer, findings=[])
                else:
                    _write_agent_file(findings_dir, agent, customer)

        validator = PreMergeValidator(
            run_dir=tmp_path,
            findings_dir=findings_dir,
            customer_safe_names=CUSTOMERS,
            file_inventory=["1. Due Diligence/doc.pdf"],
        )
        report = validator.validate()
        assert len(report.asymmetric_risk_anomalies) > 0
        anomaly = report.asymmetric_risk_anomalies[0]
        assert anomaly["customer"] == "customer_a"

    def test_balanced_customer_not_flagged(self, tmp_path: Path) -> None:
        findings_dir = tmp_path / "findings"
        # All agents have similar findings for all customers
        validator = _setup_complete(findings_dir)
        report = validator.validate()
        assert report.asymmetric_risk_anomalies == []


# ---------------------------------------------------------------------------
# Severity disagreement detection
# ---------------------------------------------------------------------------


class TestSeverityDisagreement:
    def test_two_level_gap_flagged(self, tmp_path: Path) -> None:
        findings_dir = tmp_path / "findings"
        shared_category = "change_of_control_clauses"

        for agent in AGENTS:
            for customer in CUSTOMERS:
                if agent == "legal":
                    _write_agent_file(
                        findings_dir,
                        agent,
                        customer,
                        [_make_finding(severity="P0", category=shared_category)],
                    )
                elif agent == "commercial":
                    _write_agent_file(
                        findings_dir,
                        agent,
                        customer,
                        [_make_finding(severity="P3", category=shared_category)],
                    )
                else:
                    _write_agent_file(findings_dir, agent, customer)

        validator = PreMergeValidator(
            run_dir=tmp_path,
            findings_dir=findings_dir,
            customer_safe_names=CUSTOMERS,
            file_inventory=["1. Due Diligence/doc.pdf"],
        )
        report = validator.validate()
        assert len(report.severity_disagreements) > 0
        disagreement = report.severity_disagreements[0]
        assert disagreement["category"] == shared_category

    def test_adjacent_levels_not_flagged(self, tmp_path: Path) -> None:
        findings_dir = tmp_path / "findings"
        shared_category = "ip_ownership"

        for agent in AGENTS:
            for customer in CUSTOMERS:
                if agent == "legal":
                    _write_agent_file(
                        findings_dir,
                        agent,
                        customer,
                        [_make_finding(severity="P1", category=shared_category)],
                    )
                elif agent == "commercial":
                    _write_agent_file(
                        findings_dir,
                        agent,
                        customer,
                        [_make_finding(severity="P2", category=shared_category)],
                    )
                else:
                    _write_agent_file(findings_dir, agent, customer)

        validator = PreMergeValidator(
            run_dir=tmp_path,
            findings_dir=findings_dir,
            customer_safe_names=CUSTOMERS,
            file_inventory=["1. Due Diligence/doc.pdf"],
        )
        report = validator.validate()
        assert report.severity_disagreements == []


# ---------------------------------------------------------------------------
# Summary matrix
# ---------------------------------------------------------------------------


class TestSummaryMatrix:
    def test_correct_counts(self, tmp_path: Path) -> None:
        findings_dir = tmp_path / "findings"
        # customer_a: legal has 2 findings, others have 1
        for agent in AGENTS:
            for customer in CUSTOMERS:
                if agent == "legal" and customer == "customer_a":
                    _write_agent_file(
                        findings_dir,
                        agent,
                        customer,
                        [_make_finding(), _make_finding(title="Second finding")],
                    )
                else:
                    _write_agent_file(findings_dir, agent, customer)

        validator = PreMergeValidator(
            run_dir=tmp_path,
            findings_dir=findings_dir,
            customer_safe_names=CUSTOMERS,
            file_inventory=["1. Due Diligence/doc.pdf"],
        )
        report = validator.validate()
        assert report.summary_matrix["customer_a"]["legal"] == 2
        assert report.summary_matrix["customer_a"]["finance"] == 1
        assert report.summary_matrix["customer_b"]["legal"] == 1


# ---------------------------------------------------------------------------
# Report serialization
# ---------------------------------------------------------------------------


class TestReportSerialization:
    def test_writes_valid_json(self, tmp_path: Path) -> None:
        findings_dir = tmp_path / "findings"
        validator = _setup_complete(findings_dir)
        report = validator.validate()

        output_path = tmp_path / "pre_merge_validation.json"
        output_path.write_text(report.model_dump_json(indent=2))

        loaded = json.loads(output_path.read_text())
        assert loaded["passed"] is True
        assert loaded["total_customers"] == 2
        assert isinstance(loaded["summary_matrix"], dict)


# ---------------------------------------------------------------------------
# Non-customer files excluded
# ---------------------------------------------------------------------------


class TestNonCustomerExclusion:
    def test_coverage_manifest_excluded(self, tmp_path: Path) -> None:
        findings_dir = tmp_path / "findings"
        for agent in AGENTS:
            for customer in CUSTOMERS:
                _write_agent_file(findings_dir, agent, customer)
            # Write coverage_manifest.json alongside customer files
            manifest = {"agent": agent, "coverage_pct": 1.0}
            (findings_dir / agent / "coverage_manifest.json").write_text(json.dumps(manifest))

        validator = PreMergeValidator(
            run_dir=tmp_path,
            findings_dir=findings_dir,
            customer_safe_names=CUSTOMERS,
            file_inventory=["1. Due Diligence/doc.pdf"],
        )
        report = validator.validate()
        # coverage_manifest should not appear in any issues as a customer
        all_customers_in_issues = set()
        for issue_list in [
            report.file_completeness_issues,
            report.json_integrity_issues,
            report.schema_issues,
        ]:
            for issue in issue_list:
                if "customer" in issue:
                    all_customers_in_issues.add(issue["customer"])
        assert "coverage_manifest" not in all_customers_in_issues
        # Should not appear in summary matrix
        assert "coverage_manifest" not in report.summary_matrix


# ---------------------------------------------------------------------------
# Empty findings array
# ---------------------------------------------------------------------------


class TestEmptyFindings:
    def test_empty_findings_handled(self, tmp_path: Path) -> None:
        findings_dir = tmp_path / "findings"
        for agent in AGENTS:
            for customer in CUSTOMERS:
                _write_agent_file(findings_dir, agent, customer, findings=[])

        validator = PreMergeValidator(
            run_dir=tmp_path,
            findings_dir=findings_dir,
            customer_safe_names=CUSTOMERS,
            file_inventory=["1. Due Diligence/doc.pdf"],
        )
        report = validator.validate()
        assert report.passed is True
        assert report.total_findings == 0
        assert report.summary_matrix["customer_a"]["legal"] == 0
