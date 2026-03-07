"""Unit tests for dd_agents.tools module."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from dd_agents.tools.get_customer_files import get_customer_files
from dd_agents.tools.report_progress import report_progress
from dd_agents.tools.resolve_entity import resolve_entity
from dd_agents.tools.server import (
    create_tool_definitions,
    get_tools_for_agent,
)
from dd_agents.tools.validate_finding import validate_finding
from dd_agents.tools.validate_gap import validate_gap
from dd_agents.tools.validate_manifest import validate_manifest
from dd_agents.tools.verify_citation import verify_citation

if TYPE_CHECKING:
    from pathlib import Path

# ===================================================================
# validate_finding
# ===================================================================


class TestValidateFinding:
    """Tests for validate_finding tool."""

    def test_valid_finding(self) -> None:
        finding = {
            "severity": "P2",
            "category": "termination",
            "title": "Termination clause allows exit without cure",
            "description": "Section 12 grants early termination right.",
            "citations": [
                {
                    "source_type": "file",
                    "source_path": "./Acme/MSA.pdf",
                    "exact_quote": "Customer may terminate immediately.",
                }
            ],
            "confidence": "high",
        }
        result = validate_finding(finding)
        assert result["valid"] is True

    def test_invalid_finding_missing_required(self) -> None:
        finding = {
            "severity": "P2",
            # missing category, title, description, citations, confidence
        }
        result = validate_finding(finding)
        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_invalid_severity(self) -> None:
        finding = {
            "severity": "CRITICAL",  # not a valid Severity
            "category": "termination",
            "title": "Test finding",
            "description": "A test.",
            "citations": [
                {
                    "source_type": "file",
                    "source_path": "./test.pdf",
                    "exact_quote": "quote",
                }
            ],
            "confidence": "high",
        }
        result = validate_finding(finding)
        assert result["valid"] is False

    def test_invalid_category(self) -> None:
        finding = {
            "severity": "P2",
            "category": "made_up_category",
            "title": "Test",
            "description": "Desc",
            "citations": [
                {
                    "source_type": "file",
                    "source_path": "./test.pdf",
                    "exact_quote": "quote",
                }
            ],
            "confidence": "high",
        }
        result = validate_finding(finding)
        assert result["valid"] is False
        assert any("category" in e for e in result["errors"])

    def test_p0_without_exact_quote(self) -> None:
        finding = {
            "severity": "P0",
            "category": "change_of_control",
            "title": "Deal-stopper finding",
            "description": "Critical issue found.",
            "citations": [
                {
                    "source_type": "file",
                    "source_path": "./Acme/MSA.pdf",
                    # exact_quote deliberately omitted (None)
                }
            ],
            "confidence": "high",
        }
        result = validate_finding(finding)
        assert result["valid"] is False
        assert any("exact_quote" in e for e in result["errors"])

    def test_p3_without_exact_quote_allowed(self) -> None:
        finding = {
            "severity": "P3",
            "category": "domain_reviewed_no_issues",
            "title": "No issues found",
            "description": "Domain reviewed, clean.",
            "citations": [
                {
                    "source_type": "file",
                    "source_path": "./Acme/MSA.pdf",
                    # No exact_quote needed for P3
                }
            ],
            "confidence": "high",
        }
        result = validate_finding(finding)
        assert result["valid"] is True


# ===================================================================
# validate_gap
# ===================================================================


class TestValidateGap:
    """Tests for validate_gap tool."""

    def test_valid_gap(self) -> None:
        gap = {
            "customer": "Acme Corp",
            "priority": "P1",
            "gap_type": "Missing_Doc",
            "missing_item": "Master Services Agreement",
            "why_needed": "Governs all commercial terms",
            "risk_if_missing": "Cannot assess liability exposure",
            "request_to_company": "Please provide the MSA",
            "evidence": "Referenced in SOW section 1.1",
            "detection_method": "cross_reference",
        }
        result = validate_gap(gap)
        assert result["valid"] is True

    def test_invalid_gap_missing_fields(self) -> None:
        gap = {
            "customer": "Acme Corp",
            "priority": "P1",
            # missing many required fields
        }
        result = validate_gap(gap)
        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_invalid_gap_type(self) -> None:
        gap = {
            "customer": "Acme Corp",
            "priority": "P1",
            "gap_type": "Invalid_Type",  # not a valid GapType
            "missing_item": "Some doc",
            "why_needed": "Needed",
            "risk_if_missing": "Risk",
            "request_to_company": "Request",
            "evidence": "Evidence",
            "detection_method": "cross_reference",
        }
        result = validate_gap(gap)
        assert result["valid"] is False

    def test_invalid_detection_method(self) -> None:
        gap = {
            "customer": "Acme Corp",
            "priority": "P1",
            "gap_type": "Missing_Doc",
            "missing_item": "Some doc",
            "why_needed": "Needed",
            "risk_if_missing": "Risk",
            "request_to_company": "Request",
            "evidence": "Evidence",
            "detection_method": "guessing",  # not valid
        }
        result = validate_gap(gap)
        assert result["valid"] is False


# ===================================================================
# validate_manifest
# ===================================================================


class TestValidateManifest:
    """Tests for validate_manifest tool."""

    def test_valid_manifest(self) -> None:
        manifest = {
            "agent": "legal",
            "run_id": "run_001",
            "coverage_pct": 0.95,
            "analysis_units_assigned": 5,
            "analysis_units_completed": 5,
            "files_assigned": ["a.pdf", "b.pdf"],
            "files_read": [
                {"path": "a.pdf", "extraction_quality": "primary"},
                {"path": "b.pdf", "extraction_quality": "primary"},
            ],
            "customers": [
                {"name": "Acme", "status": "complete"},
                {"name": "Globex", "status": "complete"},
            ],
        }
        result = validate_manifest(manifest)
        assert result["valid"] is True

    def test_low_coverage_pct(self) -> None:
        manifest = {
            "agent": "legal",
            "run_id": "run_001",
            "coverage_pct": 0.50,  # below 0.90 threshold
            "files_assigned": [],
        }
        result = validate_manifest(manifest)
        assert result["valid"] is False
        assert any("coverage_pct" in e for e in result["errors"])

    def test_fallback_not_attempted(self) -> None:
        manifest = {
            "agent": "legal",
            "run_id": "run_001",
            "coverage_pct": 0.95,
            "files_assigned": [],
            "files_failed": [
                {
                    "path": "bad.pdf",
                    "reason": "extraction failure",
                    "fallback_attempted": False,
                }
            ],
        }
        result = validate_manifest(manifest)
        assert result["valid"] is False
        assert any("fallback_attempted" in e for e in result["errors"])


# ===================================================================
# verify_citation
# ===================================================================


class TestVerifyCitation:
    """Tests for verify_citation tool."""

    def test_citation_found_exact(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()

        # Create extracted text file
        source_path = "Acme/MSA.pdf"
        safe_name = source_path.replace("/", "__")
        text_file = text_dir / f"{safe_name}.md"
        text_file.write_text("This agreement grants Customer the right to terminate immediately upon written notice.")

        citation = {
            "source_path": "Acme/MSA.pdf",
            "exact_quote": "right to terminate immediately upon written notice",
        }
        result = verify_citation(
            citation,
            files_list=["Acme/MSA.pdf", "Acme/SOW.pdf"],
            text_dir=str(text_dir),
        )
        assert result["found"] is True
        assert result["method"] == "exact"

    def test_citation_not_found_missing_source(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()

        citation = {
            "source_path": "NonExistent/file.pdf",
            "exact_quote": "some quote",
        }
        result = verify_citation(
            citation,
            files_list=["Acme/MSA.pdf"],
            text_dir=str(text_dir),
        )
        assert result["found"] is False
        assert "not found in file inventory" in result["reason"]

    def test_citation_source_only_no_quote(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()

        citation = {
            "source_path": "Acme/MSA.pdf",
            "exact_quote": "",
        }
        result = verify_citation(
            citation,
            files_list=["Acme/MSA.pdf"],
            text_dir=str(text_dir),
        )
        assert result["found"] is True
        assert result["method"] == "source_only"

    def test_citation_not_found_in_text(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()

        source_path = "Acme/MSA.pdf"
        safe_name = source_path.replace("/", "__")
        text_file = text_dir / f"{safe_name}.md"
        text_file.write_text("Completely unrelated content here.")

        citation = {
            "source_path": "Acme/MSA.pdf",
            "exact_quote": "This specific clause does not exist in the document at all",
        }
        result = verify_citation(
            citation,
            files_list=["Acme/MSA.pdf"],
            text_dir=str(text_dir),
        )
        assert result["found"] is False

    def test_empty_source_path(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()

        citation = {"source_path": "", "exact_quote": "test"}
        result = verify_citation(citation, files_list=[], text_dir=str(text_dir))
        assert result["found"] is False
        assert "Empty source_path" in result["reason"]

    def test_no_extracted_text_file(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()

        citation = {
            "source_path": "Acme/MSA.pdf",
            "exact_quote": "some quote",
        }
        result = verify_citation(
            citation,
            files_list=["Acme/MSA.pdf"],
            text_dir=str(text_dir),
        )
        assert result["found"] is False
        assert "Extracted text not found" in result["reason"]

    def test_citation_with_leading_dot_slash(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()

        source_path = "./Acme/MSA.pdf"
        safe_name = source_path.lstrip("./").replace("/", "__")
        text_file = text_dir / f"{safe_name}.md"
        text_file.write_text("The payment terms are net 30 days.")

        citation = {
            "source_path": "./Acme/MSA.pdf",
            "exact_quote": "payment terms are net 30 days",
        }
        result = verify_citation(
            citation,
            files_list=["./Acme/MSA.pdf"],
            text_dir=str(text_dir),
        )
        assert result["found"] is True


# ===================================================================
# get_customer_files
# ===================================================================


class TestGetCustomerFiles:
    """Tests for get_customer_files tool."""

    def test_returns_correct_file_list(self) -> None:
        customers_csv = [
            {
                "customer_safe_name": "acme_corp",
                "file_list": ["MSA.pdf", "SOW.pdf", "NDA.pdf"],
            },
            {
                "customer_safe_name": "globex",
                "file_list": ["Agreement.pdf"],
            },
        ]
        result = get_customer_files("acme_corp", customers_csv)
        assert result["customer"] == "acme_corp"
        assert result["file_count"] == 3
        assert result["files"] == ["MSA.pdf", "SOW.pdf", "NDA.pdf"]

    def test_unknown_customer(self) -> None:
        customers_csv = [{"customer_safe_name": "acme_corp", "file_list": ["a.pdf"]}]
        result = get_customer_files("nonexistent", customers_csv)
        assert result["error"] == "unknown_customer"
        assert result["name"] == "nonexistent"

    def test_empty_file_list(self) -> None:
        customers_csv = [{"customer_safe_name": "empty_corp", "file_list": []}]
        result = get_customer_files("empty_corp", customers_csv)
        assert result["file_count"] == 0
        assert result["files"] == []

    def test_comma_separated_file_list(self) -> None:
        customers_csv = [
            {
                "customer_safe_name": "csv_corp",
                "file_list": "MSA.pdf, SOW.pdf",  # string instead of list
            }
        ]
        result = get_customer_files("csv_corp", customers_csv)
        assert result["file_count"] == 2
        assert "MSA.pdf" in result["files"]
        assert "SOW.pdf" in result["files"]


# ===================================================================
# resolve_entity
# ===================================================================


class TestResolveEntity:
    """Tests for resolve_entity tool."""

    def test_cache_hit(self, tmp_path: Path) -> None:
        cache_data = {
            "entries": {
                "Acme Inc.": {
                    "canonical": "Acme Corporation",
                    "match_pass": 2,
                    "match_type": "exact",
                    "confidence": 1.0,
                }
            }
        }
        cache_path = tmp_path / "entity_resolution_cache.json"
        cache_path.write_text(json.dumps(cache_data))

        result = resolve_entity("Acme Inc.", str(cache_path))
        assert result["canonical"] == "Acme Corporation"
        assert result["match_type"] == "exact"
        assert result["confidence"] == 1.0

    def test_cache_miss(self, tmp_path: Path) -> None:
        cache_data = {"entries": {}}
        cache_path = tmp_path / "entity_resolution_cache.json"
        cache_path.write_text(json.dumps(cache_data))

        result = resolve_entity("Unknown Entity", str(cache_path))
        assert result["status"] == "unresolved"
        assert result["name"] == "Unknown Entity"

    def test_cache_file_not_exists(self, tmp_path: Path) -> None:
        cache_path = tmp_path / "nonexistent_cache.json"
        result = resolve_entity("Acme Inc.", str(cache_path))
        assert result["status"] == "unresolved"

    def test_corrupt_cache_file(self, tmp_path: Path) -> None:
        cache_path = tmp_path / "entity_resolution_cache.json"
        cache_path.write_text("NOT VALID JSON")

        result = resolve_entity("Acme Inc.", str(cache_path))
        assert result["status"] == "unresolved"


# ===================================================================
# report_progress
# ===================================================================


class TestReportProgress:
    """Tests for report_progress tool."""

    def test_in_progress(self) -> None:
        result = report_progress(
            agent_name="legal",
            customers_processed=5,
            total_customers=10,
            current_customer="acme_corp",
        )
        assert result["agent"] == "legal"
        assert result["customers_processed"] == 5
        assert result["total_customers"] == 10
        assert result["current_customer"] == "acme_corp"
        assert result["progress_pct"] == 50.0
        assert result["status"] == "in_progress"

    def test_complete(self) -> None:
        result = report_progress(
            agent_name="finance",
            customers_processed=10,
            total_customers=10,
            current_customer="last_one",
        )
        assert result["progress_pct"] == 100.0
        assert result["status"] == "complete"

    def test_starting(self) -> None:
        result = report_progress(
            agent_name="commercial",
            customers_processed=0,
            total_customers=10,
            current_customer="",
        )
        assert result["progress_pct"] == 0.0
        assert result["status"] == "starting"

    def test_zero_total(self) -> None:
        result = report_progress(
            agent_name="producttech",
            customers_processed=0,
            total_customers=0,
            current_customer="",
        )
        assert result["progress_pct"] == 0.0


# ===================================================================
# create_tool_definitions (server.py)
# ===================================================================


class TestCreateToolDefinitions:
    """Tests for create_tool_definitions and server module."""

    def test_all_tools_registered(self) -> None:
        defs = create_tool_definitions()
        names = {d["name"] for d in defs}
        expected = {
            "validate_finding",
            "validate_gap",
            "validate_manifest",
            "verify_citation",
            "get_customer_files",
            "resolve_entity",
            "search_similar",
            "report_progress",
        }
        assert names == expected

    def test_definitions_have_required_fields(self) -> None:
        defs = create_tool_definitions()
        for d in defs:
            assert "name" in d
            assert "description" in d
            assert "input_schema" in d
            assert "handler" in d
            assert isinstance(d["description"], str)
            assert isinstance(d["input_schema"], dict)

    def test_specialist_tools(self) -> None:
        tools = get_tools_for_agent("specialist")
        assert "validate_finding" in tools
        assert "validate_gap" in tools
        assert "verify_citation" in tools
        assert "report_progress" in tools

    def test_judge_tools(self) -> None:
        tools = get_tools_for_agent("judge")
        assert "verify_citation" in tools
        assert "validate_finding" not in tools

    def test_unknown_agent_type(self) -> None:
        tools = get_tools_for_agent("unknown")
        assert tools == []

    def test_input_schemas_are_valid_json_schema(self) -> None:
        defs = create_tool_definitions()
        for d in defs:
            schema = d["input_schema"]
            assert schema.get("type") == "object"
            assert "properties" in schema
            assert "required" in schema
