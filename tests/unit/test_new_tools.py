"""Unit tests for new MCP tools: search_in_file, get_page_content, batch_verify_citations.

Also tests for enhanced verify_citation (page numbers, context) and
enhanced stop hooks (turn-aware guidance).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from dd_agents.hooks.stop import (
    _turn_budget_guidance,
    check_coverage,
)
from dd_agents.reporting.merge import FindingMerger
from dd_agents.tools.batch_verify_citations import batch_verify_citations
from dd_agents.tools.get_page_content import get_page_content
from dd_agents.tools.get_subject_files import _file_metadata
from dd_agents.tools.search_in_file import search_in_file
from dd_agents.tools.verify_citation import (
    _extract_context,
    _find_page_number,
    verify_citation,
)

# ===================================================================
# Helper: write a text file with page markers
# ===================================================================

_PAGED_TEXT = (
    "Preamble text before any page marker.\n"
    "\n--- Page 1 ---\n"
    "Page one content with change of control clause.\n"
    "\n--- Page 2 ---\n"
    "Page two discusses payment terms and net 30 days.\n"
    "\n--- Page 3 ---\n"
    "Page three has termination for convenience provisions.\n"
)


def _write_text(text_dir: Path, source_path: str, content: str) -> Path:
    """Write extracted text file using the safe name convention."""
    safe_name = source_path.replace("/", "__").replace(".", "__", source_path.count(".") - 1)
    # Use the same convention as the extraction pipeline
    from dd_agents.extraction.pipeline import ExtractionPipeline

    safe_name = ExtractionPipeline._safe_text_name(source_path)
    text_file = text_dir / safe_name
    text_file.write_text(content, encoding="utf-8")
    return text_file


# ===================================================================
# search_in_file
# ===================================================================


class TestSearchInFile:
    """Tests for search_in_file tool."""

    def test_basic_search(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()
        _write_text(text_dir, "Acme/MSA.pdf", _PAGED_TEXT)

        result = search_in_file("Acme/MSA.pdf", "change of control", text_dir=str(text_dir))
        assert result["total_matches"] == 1
        assert len(result["matches"]) == 1
        match = result["matches"][0]
        assert match["page_number"] == 1
        assert match["matched_text"] == "change of control"
        assert isinstance(match["char_offset"], int)
        assert match["char_offset"] > 0

    def test_multiple_matches(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()
        content = "The term appears here. The term also appears here."
        _write_text(text_dir, "Acme/MSA.pdf", content)

        result = search_in_file("Acme/MSA.pdf", "term", text_dir=str(text_dir))
        assert result["total_matches"] == 2
        assert len(result["matches"]) == 2

    def test_case_insensitive_by_default(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()
        _write_text(text_dir, "Acme/MSA.pdf", "Change Of Control is important.")

        result = search_in_file("Acme/MSA.pdf", "change of control", text_dir=str(text_dir))
        assert result["total_matches"] == 1

    def test_case_sensitive_flag(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()
        _write_text(text_dir, "Acme/MSA.pdf", "Change Of Control is important.")

        result = search_in_file(
            "Acme/MSA.pdf",
            "change of control",
            text_dir=str(text_dir),
            case_sensitive=True,
        )
        assert result["total_matches"] == 0

    def test_max_results_truncation(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()
        content = " ".join(["term"] * 50)
        _write_text(text_dir, "Acme/MSA.pdf", content)

        result = search_in_file(
            "Acme/MSA.pdf",
            "term",
            text_dir=str(text_dir),
            max_results=5,
        )
        assert result["total_matches"] == 50
        assert len(result["matches"]) == 5
        assert result["truncated"] is True

    def test_empty_query_error(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()

        result = search_in_file("Acme/MSA.pdf", "", text_dir=str(text_dir))
        assert result["error"] == "invalid_input"

    def test_empty_source_path_error(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()

        result = search_in_file("", "query", text_dir=str(text_dir))
        assert result["error"] == "invalid_input"

    def test_missing_file_error(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()

        result = search_in_file("NonExistent/file.pdf", "query", text_dir=str(text_dir))
        assert result["error"] == "not_found"

    def test_path_traversal_blocked(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()
        allowed = tmp_path / "allowed"
        allowed.mkdir()

        result = search_in_file(
            "../../etc/passwd",
            "root",
            text_dir=str(text_dir),
            allowed_dir=str(allowed),
        )
        assert result["error"] == "blocked"

    def test_context_included(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()
        _write_text(text_dir, "Acme/MSA.pdf", _PAGED_TEXT)

        result = search_in_file("Acme/MSA.pdf", "payment terms", text_dir=str(text_dir))
        assert result["total_matches"] == 1
        match = result["matches"][0]
        assert "context_before" in match
        assert "context_after" in match
        assert match["page_number"] == 2

    def test_no_matches_found(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()
        _write_text(text_dir, "Acme/MSA.pdf", "Short content.")

        result = search_in_file("Acme/MSA.pdf", "nonexistent phrase", text_dir=str(text_dir))
        assert result["total_matches"] == 0
        assert result["matches"] == []
        assert result["truncated"] is False


# ===================================================================
# get_page_content
# ===================================================================


class TestGetPageContent:
    """Tests for get_page_content tool."""

    def test_single_page(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()
        _write_text(text_dir, "Acme/MSA.pdf", _PAGED_TEXT)

        result = get_page_content("Acme/MSA.pdf", text_dir=str(text_dir), start_page=2)
        assert "2" in result["pages"]
        assert "payment terms" in result["pages"]["2"]
        assert result["has_page_markers"] is True

    def test_page_range(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()
        _write_text(text_dir, "Acme/MSA.pdf", _PAGED_TEXT)

        result = get_page_content(
            "Acme/MSA.pdf",
            text_dir=str(text_dir),
            start_page=1,
            end_page=3,
        )
        assert len(result["pages"]) == 3
        assert "1" in result["pages"]
        assert "3" in result["pages"]

    def test_total_pages_reported(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()
        _write_text(text_dir, "Acme/MSA.pdf", _PAGED_TEXT)

        result = get_page_content("Acme/MSA.pdf", text_dir=str(text_dir))
        assert result["total_pages"] == 3

    def test_no_page_markers(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()
        _write_text(text_dir, "Acme/plain.txt", "Just plain text without page markers.")

        result = get_page_content("Acme/plain.txt", text_dir=str(text_dir))
        assert result["has_page_markers"] is False
        assert result["total_pages"] == 1
        assert "1" in result["pages"]

    def test_missing_file(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()

        result = get_page_content("NonExistent.pdf", text_dir=str(text_dir))
        assert result["error"] == "not_found"

    def test_empty_source_path(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()

        result = get_page_content("", text_dir=str(text_dir))
        assert result["error"] == "invalid_input"

    def test_path_traversal_blocked(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()
        allowed = tmp_path / "allowed"
        allowed.mkdir()

        result = get_page_content(
            "../../etc/passwd",
            text_dir=str(text_dir),
            allowed_dir=str(allowed),
        )
        assert result["error"] == "blocked"

    def test_out_of_range_page_returns_empty(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()
        _write_text(text_dir, "Acme/MSA.pdf", _PAGED_TEXT)

        result = get_page_content(
            "Acme/MSA.pdf",
            text_dir=str(text_dir),
            start_page=99,
            end_page=100,
        )
        assert result["pages"] == {}


# ===================================================================
# batch_verify_citations
# ===================================================================


class TestBatchVerifyCitations:
    """Tests for batch_verify_citations tool."""

    def test_batch_all_found(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()
        _write_text(text_dir, "Acme/MSA.pdf", "The payment terms are net 30 days.")
        _write_text(text_dir, "Acme/SOW.pdf", "The scope includes consulting services.")

        citations = [
            {"source_path": "Acme/MSA.pdf", "exact_quote": "payment terms are net 30"},
            {"source_path": "Acme/SOW.pdf", "exact_quote": "scope includes consulting"},
        ]
        result = batch_verify_citations(
            citations,
            files_list=["Acme/MSA.pdf", "Acme/SOW.pdf"],
            text_dir=str(text_dir),
        )
        assert result["summary"]["verified"] == 2
        assert result["summary"]["failed"] == 0
        assert result["summary"]["total"] == 2
        assert len(result["results"]) == 2
        assert all(r["found"] for r in result["results"])

    def test_batch_mixed_results(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()
        _write_text(text_dir, "Acme/MSA.pdf", "The payment terms are net 30 days.")

        citations = [
            {"source_path": "Acme/MSA.pdf", "exact_quote": "payment terms are net 30"},
            {"source_path": "Acme/MSA.pdf", "exact_quote": "this quote does not exist anywhere in text"},
        ]
        result = batch_verify_citations(
            citations,
            files_list=["Acme/MSA.pdf"],
            text_dir=str(text_dir),
        )
        assert result["summary"]["verified"] == 1
        assert result["summary"]["failed"] == 1
        assert result["summary"]["total"] == 2

    def test_batch_empty_list(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()

        result = batch_verify_citations(
            [],
            files_list=[],
            text_dir=str(text_dir),
        )
        assert result["summary"]["total"] == 0
        assert result["results"] == []

    def test_batch_returns_page_numbers(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()
        _write_text(text_dir, "Acme/MSA.pdf", _PAGED_TEXT)

        citations = [
            {"source_path": "Acme/MSA.pdf", "exact_quote": "change of control"},
        ]
        result = batch_verify_citations(
            citations,
            files_list=["Acme/MSA.pdf"],
            text_dir=str(text_dir),
        )
        assert result["results"][0]["found"] is True
        assert result["results"][0]["page_number"] == 1


# ===================================================================
# verify_citation — page number detection
# ===================================================================


class TestVerifyCitationPageDetection:
    """Tests for page number and context in verify_citation."""

    def test_page_number_detected(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()
        _write_text(text_dir, "Acme/MSA.pdf", _PAGED_TEXT)

        citation = {
            "source_path": "Acme/MSA.pdf",
            "exact_quote": "termination for convenience",
        }
        result = verify_citation(
            citation,
            files_list=["Acme/MSA.pdf"],
            text_dir=str(text_dir),
        )
        assert result["found"] is True
        assert result["page_number"] == 3

    def test_no_page_markers_returns_none(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()
        _write_text(text_dir, "Acme/notes.txt", "Simple text without page markers.")

        citation = {
            "source_path": "Acme/notes.txt",
            "exact_quote": "without page markers",
        }
        result = verify_citation(
            citation,
            files_list=["Acme/notes.txt"],
            text_dir=str(text_dir),
        )
        assert result["found"] is True
        assert result["page_number"] is None

    def test_context_fields_present(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()
        _write_text(
            text_dir,
            "Acme/MSA.pdf",
            "Before the quote. The exact clause is here. After the quote.",
        )

        citation = {
            "source_path": "Acme/MSA.pdf",
            "exact_quote": "the exact clause is here",
        }
        result = verify_citation(
            citation,
            files_list=["Acme/MSA.pdf"],
            text_dir=str(text_dir),
        )
        assert result["found"] is True
        assert "context_before" in result
        assert "context_after" in result
        assert "matched_text" in result

    def test_source_only_includes_page_number_none(self, tmp_path: Path) -> None:
        text_dir = tmp_path / "text"
        text_dir.mkdir()

        citation = {"source_path": "Acme/MSA.pdf", "exact_quote": ""}
        result = verify_citation(
            citation,
            files_list=["Acme/MSA.pdf"],
            text_dir=str(text_dir),
        )
        assert result["found"] is True
        assert result["page_number"] is None


# ===================================================================
# verify_citation — internal helpers
# ===================================================================


class TestVerifyCitationHelpers:
    """Tests for verify_citation internal helper functions."""

    def test_find_page_number_first_page(self) -> None:
        assert _find_page_number(_PAGED_TEXT, 50) == 1

    def test_find_page_number_later_page(self) -> None:
        # Find offset of text on page 3
        idx = _PAGED_TEXT.index("termination")
        assert _find_page_number(_PAGED_TEXT, idx) == 3

    def test_find_page_number_no_markers(self) -> None:
        assert _find_page_number("Plain text with no markers", 5) is None

    def test_find_page_number_preamble(self) -> None:
        # Text before first marker has no page number
        assert _find_page_number(_PAGED_TEXT, 0) is None

    def test_extract_context(self) -> None:
        text = "AAAA the target text BBBB"
        ctx = _extract_context(text, 5, 15)
        assert ctx["matched_text"] == "the target text"
        assert "AAAA" in ctx["context_before"]
        assert "BBBB" in ctx["context_after"]


# ===================================================================
# stop hook — turn-aware guidance
# ===================================================================


class TestStopHookTurnGuidance:
    """Tests for turn-aware stop hook guidance."""

    def test_no_guidance_when_no_turn_info(self) -> None:
        guidance = _turn_budget_guidance(None, None, 10, 5)
        assert guidance == ""

    def test_no_guidance_when_budget_ample(self) -> None:
        # 10% used — plenty of budget
        guidance = _turn_budget_guidance(20, 200, 10, 5)
        assert guidance == ""

    def test_warning_at_75_percent(self) -> None:
        # 75% used
        guidance = _turn_budget_guidance(150, 200, 10, 5)
        assert "WARNING" in guidance
        assert "turns left" in guidance

    def test_urgent_at_90_percent(self) -> None:
        # 92% used
        guidance = _turn_budget_guidance(184, 200, 10, 5)
        assert "URGENT" in guidance
        assert "PRIORITIZE" in guidance

    def test_check_coverage_includes_turn_guidance(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        # Write 3 of 10 expected files
        for i in range(3):
            (output_dir / f"subject_{i}.json").write_text("{}")

        result = check_coverage(
            str(output_dir),
            10,
            current_turn=180,
            max_turns=200,
        )
        assert result["decision"] == "block"
        assert "URGENT" in result["reason"]

    def test_check_coverage_no_turn_info_still_works(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "subject_a.json").write_text("{}")

        result = check_coverage(str(output_dir), 5)
        assert result["decision"] == "block"
        assert "1/5" in result["reason"]

    def test_check_coverage_complete(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        for i in range(5):
            (output_dir / f"subject_{i}.json").write_text("{}")

        result = check_coverage(str(output_dir), 5)
        assert result["decision"] == "allow"

    def test_turn_budget_zero_max_turns(self) -> None:
        guidance = _turn_budget_guidance(10, 0, 10, 5)
        assert guidance == ""


# ===================================================================
# merge — coverage gap differentiation
# ===================================================================


class TestMergeCoverageGapDifferentiation:
    """Tests for check_agent_coverage with findings_dir."""

    def _make_merged(
        self,
        agents_with_findings: list[str],
    ) -> Any:
        """Build a minimal MergedSubjectOutput for testing."""
        from dd_agents.models.enums import AgentName, Confidence, Severity, SourceType
        from dd_agents.models.finding import Citation, Finding, MergedSubjectOutput

        findings = []
        for i, agent in enumerate(agents_with_findings):
            findings.append(
                Finding(
                    id=f"forensic-dd_{agent}_test_subject_{i:04d}",
                    agent=AgentName(agent),
                    severity=Severity.P3,
                    category="domain_reviewed_no_issues",
                    title="Clean review",
                    description="No issues found",
                    citations=[
                        Citation(
                            source_type=SourceType.FILE,
                            source_path="./test.pdf",
                        )
                    ],
                    confidence=Confidence.HIGH,
                    run_id="run_001",
                    timestamp="2026-01-01T00:00:00Z",
                    analysis_unit="test_subject",
                )
            )

        return MergedSubjectOutput(
            subject="Test Subject",
            subject_safe_name="test_subject",
            findings=findings,
            gaps=[],
        )

    def test_missing_output_detected(self, tmp_path: Path) -> None:
        findings_dir = tmp_path / "findings"
        # Create dirs for some agents but not all
        for agent in ["legal", "finance", "commercial"]:
            agent_dir = findings_dir / agent
            agent_dir.mkdir(parents=True)
            (agent_dir / "test_subject.json").write_text("{}")

        # producttech dir doesn't exist at all
        merged = {"test_subject": self._make_merged(["legal", "finance", "commercial"])}
        gaps = FindingMerger.check_agent_coverage(merged, findings_dir=findings_dir)

        assert len(gaps) == 1
        assert gaps[0]["missing_output"] == ["producttech"]
        assert gaps[0]["no_findings"] == []

    def test_no_findings_detected(self, tmp_path: Path) -> None:
        findings_dir = tmp_path / "findings"
        # All agent dirs exist, all have the subject file
        for agent in ["legal", "finance", "commercial", "producttech"]:
            agent_dir = findings_dir / agent
            agent_dir.mkdir(parents=True)
            (agent_dir / "test_subject.json").write_text('{"findings": [], "gaps": []}')

        # But only legal and finance produced actual findings in merged output
        merged = {"test_subject": self._make_merged(["legal", "finance"])}
        gaps = FindingMerger.check_agent_coverage(merged, findings_dir=findings_dir)

        assert len(gaps) == 1
        assert sorted(gaps[0]["no_findings"]) == ["commercial", "producttech"]
        assert gaps[0]["missing_output"] == []

    def test_mixed_missing_and_no_findings(self, tmp_path: Path) -> None:
        findings_dir = tmp_path / "findings"
        # legal and finance have dirs and files
        for agent in ["legal", "finance"]:
            agent_dir = findings_dir / agent
            agent_dir.mkdir(parents=True)
            (agent_dir / "test_subject.json").write_text("{}")
        # commercial has dir and file but no findings in merged
        comm_dir = findings_dir / "commercial"
        comm_dir.mkdir(parents=True)
        (comm_dir / "test_subject.json").write_text("{}")
        # producttech has no dir at all

        merged = {"test_subject": self._make_merged(["legal", "finance"])}
        gaps = FindingMerger.check_agent_coverage(merged, findings_dir=findings_dir)

        assert len(gaps) == 1
        assert gaps[0]["missing_output"] == ["producttech"]
        assert gaps[0]["no_findings"] == ["commercial"]

    def test_without_findings_dir_all_undifferentiated(self) -> None:
        merged = {"test_subject": self._make_merged(["legal", "finance"])}
        gaps = FindingMerger.check_agent_coverage(merged)

        assert len(gaps) == 1
        # Without findings_dir, all missing go to missing_output
        assert sorted(gaps[0]["missing_output"]) == ["commercial", "producttech"]
        assert gaps[0]["no_findings"] == []

    def test_full_coverage_no_gaps(self) -> None:
        merged = {
            "test_subject": self._make_merged(
                ["legal", "finance", "commercial", "producttech"],
            )
        }
        gaps = FindingMerger.check_agent_coverage(merged)
        assert gaps == []


# ===================================================================
# get_subject_files — file metadata helper
# ===================================================================


class TestFileMetadata:
    """Tests for _file_metadata helper."""

    def test_extension_type_mapping(self) -> None:
        meta = _file_metadata("contract.pdf")
        assert meta["file_type"] == "pdf"
        assert meta["extension"] == ".pdf"

    def test_excel_type(self) -> None:
        meta = _file_metadata("data.xlsx")
        assert meta["file_type"] == "excel"

    def test_unknown_extension(self) -> None:
        meta = _file_metadata("archive.tar.gz")
        assert meta["file_type"] == "gz"

    def test_no_extension(self) -> None:
        meta = _file_metadata("Makefile")
        assert meta["file_type"] == "unknown"

    def test_size_bytes_when_file_exists(self, tmp_path: Path) -> None:
        data_room = tmp_path / "data_room"
        data_room.mkdir()
        (data_room / "contract.pdf").write_text("fake pdf content")

        meta = _file_metadata("contract.pdf", data_room_path=str(data_room))
        assert "size_bytes" in meta
        assert meta["size_bytes"] > 0

    def test_size_bytes_missing_when_no_data_room(self) -> None:
        meta = _file_metadata("contract.pdf")
        assert "size_bytes" not in meta

    def test_precedence_score_included(self) -> None:
        precedence = {"contract.pdf": 0.85}
        meta = _file_metadata("contract.pdf", file_precedence=precedence)
        assert meta["precedence_score"] == 0.85

    def test_precedence_score_with_leading_dot_slash(self) -> None:
        precedence = {"contract.pdf": 0.85}
        meta = _file_metadata("./contract.pdf", file_precedence=precedence)
        assert meta["precedence_score"] == 0.85


# ===================================================================
# Specialist tools list consistency
# ===================================================================


class TestSpecialistToolsConsistency:
    """Ensure SPECIALIST_TOOLS matches SPECIALIST_CUSTOM_TOOLS + builtins."""

    def test_specialist_tools_includes_new_tools(self) -> None:
        from dd_agents.agents.specialists import SPECIALIST_TOOLS

        assert "search_in_file" in SPECIALIST_TOOLS
        assert "get_page_content" in SPECIALIST_TOOLS
        assert "batch_verify_citations" in SPECIALIST_TOOLS

    def test_specialist_custom_tools_includes_new_tools(self) -> None:
        from dd_agents.tools.server import SPECIALIST_CUSTOM_TOOLS

        assert "search_in_file" in SPECIALIST_CUSTOM_TOOLS
        assert "get_page_content" in SPECIALIST_CUSTOM_TOOLS
        assert "batch_verify_citations" in SPECIALIST_CUSTOM_TOOLS

    def test_judge_custom_tools_includes_batch_verify(self) -> None:
        from dd_agents.tools.server import JUDGE_CUSTOM_TOOLS

        assert "batch_verify_citations" in JUDGE_CUSTOM_TOOLS
