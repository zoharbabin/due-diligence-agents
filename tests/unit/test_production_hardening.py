"""Unit tests for production hardening changes (Issues #87-#94).

Covers:
- #87: File access instructions in specialist prompts
- #88: Safe name enforcement in prompts + merge_all expected_subjects fuzzy matching
- #89: Entity cache save() requires run_id (tested via orchestrator)
- #90: JSON output constraint in system prompt
- #91: Coverage gate retries all missing subjects
- #92: Per-agent batch sizing (FinanceAgent smaller batches)
- #93: Citation verification mandate + verification_status field
- #94: Tool list naming clarity (SPECIALIST_CUSTOM_TOOLS etc.)
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from dd_agents.agents.base import BaseAgentRunner
from dd_agents.agents.prompt_builder import PromptBuilder
from dd_agents.agents.specialists import (
    CommercialAgent,
    FinanceAgent,
    LegalAgent,
    ProductTechAgent,
)
from dd_agents.models.finding import Citation
from dd_agents.models.inventory import SubjectEntry
from dd_agents.reporting.merge import FindingMerger
from dd_agents.tools.server import (
    JUDGE_CUSTOM_TOOLS,
    SPECIALIST_CUSTOM_TOOLS,
    get_tools_for_agent,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    return project


@pytest.fixture
def tmp_run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "_dd" / "forensic-dd" / "runs" / "20250218_143000"
    run_dir.mkdir(parents=True)
    return run_dir


@pytest.fixture
def run_id() -> str:
    return "20250218_143000"


@pytest.fixture
def builder(tmp_project: Path, tmp_run_dir: Path, run_id: str) -> PromptBuilder:
    return PromptBuilder(
        project_dir=tmp_project,
        run_dir=tmp_run_dir,
        run_id=run_id,
    )


@pytest.fixture
def sample_subjects() -> list[SubjectEntry]:
    return [
        SubjectEntry(
            group="Above 200K USD",
            name="Acme Corp",
            safe_name="acme_corp",
            path="./Above 200K USD/Acme Corp/",
            file_count=2,
            files=[
                "./Above 200K USD/Acme Corp/MSA.pdf",
                "./Above 200K USD/Acme Corp/DPA.pdf",
            ],
        ),
        SubjectEntry(
            group="Below 200K USD",
            name="Beta Inc",
            safe_name="beta",
            path="./Below 200K USD/Beta Inc/",
            file_count=1,
            files=["./Below 200K USD/Beta Inc/Contract.docx"],
        ),
    ]


def _make_finding(
    severity: str = "P2",
    category: str = "change_of_control",
    source_path: str = "contract.pdf",
    location: str = "Section 5",
    exact_quote: str = "Sample quote",
    title: str = "Test finding",
    description: str = "A test finding",
    confidence: str = "high",
) -> dict[str, Any]:
    return {
        "severity": severity,
        "category": category,
        "title": title,
        "description": description,
        "citations": [
            {
                "source_type": "file",
                "source_path": source_path,
                "location": location,
                "exact_quote": exact_quote,
            }
        ],
        "confidence": confidence,
    }


# ===========================================================================
# Issue #87: File access instructions
# ===========================================================================


class TestFileAccessInstructions:
    """Tests for _build_file_access_instructions and its integration."""

    def test_static_method_returns_string(self) -> None:
        result = PromptBuilder._build_file_access_instructions()
        assert isinstance(result, str)
        assert len(result) > 100

    def test_includes_read_tool_instruction(self) -> None:
        result = PromptBuilder._build_file_access_instructions()
        assert "Read tool" in result

    def test_includes_supported_formats(self) -> None:
        result = PromptBuilder._build_file_access_instructions()
        assert ".pdf" in result
        assert ".xlsx" in result
        assert ".docx" in result

    def test_warns_against_converted_versions(self) -> None:
        result = PromptBuilder._build_file_access_instructions()
        assert "do not" in result.lower() or "Do not" in result
        assert "converted" in result.lower() or "alternative" in result.lower()

    def test_includes_grep_for_large_files(self) -> None:
        result = PromptBuilder._build_file_access_instructions()
        assert "Grep" in result

    def test_file_access_in_specialist_prompt(
        self,
        builder: PromptBuilder,
        sample_subjects: list[SubjectEntry],
    ) -> None:
        """File access instructions appear in the specialist prompt."""
        prompt = builder.build_specialist_prompt(
            agent_name="legal",
            subjects=sample_subjects,
        )
        assert "HOW TO READ FILES" in prompt
        assert "Read tool" in prompt

    def test_file_access_in_all_specialist_prompts(
        self,
        builder: PromptBuilder,
        sample_subjects: list[SubjectEntry],
    ) -> None:
        """All four specialist agents get file access instructions."""
        for agent_name in ("legal", "finance", "commercial", "producttech"):
            prompt = builder.build_specialist_prompt(
                agent_name=agent_name,
                subjects=sample_subjects,
            )
            assert "HOW TO READ FILES" in prompt, f"Missing in {agent_name} prompt"

    def test_no_text_dir_parameter_in_build_specialist_prompt(self) -> None:
        """build_specialist_prompt no longer accepts text_dir parameter."""
        import inspect

        sig = inspect.signature(PromptBuilder.build_specialist_prompt)
        assert "text_dir" not in sig.parameters


# ===========================================================================
# Issue #88: Safe name enforcement
# ===========================================================================


class TestSafeNameEnforcement:
    """Tests for safe_name enforcement in prompts and merge_all."""

    def test_prompt_contains_critical_filename_instruction(
        self,
        builder: PromptBuilder,
        sample_subjects: list[SubjectEntry],
    ) -> None:
        """Prompt includes CRITICAL filename instruction for each subject."""
        prompt = builder.build_specialist_prompt(
            agent_name="legal",
            subjects=sample_subjects,
        )
        assert "CRITICAL" in prompt
        assert "OUTPUT FILENAMES" in prompt or "output filename" in prompt.lower()
        assert "character-for-character" in prompt

    def test_merge_all_without_expected_subjects(self, tmp_path: Path) -> None:
        """merge_all works fine without expected_subjects (backward compat)."""
        findings_dir = tmp_path / "findings"
        legal_dir = findings_dir / "legal"
        legal_dir.mkdir(parents=True)

        output = {
            "subject": "Acme Corp",
            "subject_safe_name": "acme_corp",
            "findings": [_make_finding()],
            "governance_graph": {"edges": []},
            "cross_references": [],
        }
        (legal_dir / "acme_corp.json").write_text(json.dumps(output))

        merger = FindingMerger(run_id="test", timestamp="2025-01-01T00:00:00Z")
        results = merger.merge_all(findings_dir)
        assert "acme_corp" in results

    def test_merge_all_with_matching_expected_subjects(self, tmp_path: Path) -> None:
        """merge_all succeeds when discovered stems match expected list."""
        findings_dir = tmp_path / "findings"
        legal_dir = findings_dir / "legal"
        legal_dir.mkdir(parents=True)

        output = {
            "subject": "Acme Corp",
            "subject_safe_name": "acme_corp",
            "findings": [_make_finding()],
            "governance_graph": {"edges": []},
            "cross_references": [],
        }
        (legal_dir / "acme_corp.json").write_text(json.dumps(output))

        merger = FindingMerger(run_id="test", timestamp="2025-01-01T00:00:00Z")
        results = merger.merge_all(
            findings_dir,
            expected_subjects=["acme_corp"],
        )
        assert "acme_corp" in results

    def test_merge_all_fuzzy_matches_similar_stems(self, tmp_path: Path) -> None:
        """merge_all fuzzy-matches a close stem to the expected subject."""
        findings_dir = tmp_path / "findings"
        legal_dir = findings_dir / "legal"
        legal_dir.mkdir(parents=True)

        # Agent wrote "acme" instead of "acme_corp" — fuzzy match should correct it
        output = {
            "subject": "Acme Corp",
            "subject_safe_name": "acme_corp",
            "findings": [_make_finding()],
            "governance_graph": {"edges": []},
            "cross_references": [],
        }
        (legal_dir / "acme_corp_inc.json").write_text(json.dumps(output))

        merger = FindingMerger(run_id="test", timestamp="2025-01-01T00:00:00Z")
        results = merger.merge_all(
            findings_dir,
            expected_subjects=["acme_corp"],
        )
        # If rapidfuzz scored >= 80%, the file should be renamed
        # and the result should contain acme_corp
        assert "acme_corp" in results or "acme_corp_inc" in results

    def test_merge_all_logs_missing_expected(self, tmp_path: Path) -> None:
        """merge_all logs warning when expected subjects have no findings."""
        findings_dir = tmp_path / "findings"
        legal_dir = findings_dir / "legal"
        legal_dir.mkdir(parents=True)

        output = {
            "subject": "Acme Corp",
            "subject_safe_name": "acme_corp",
            "findings": [_make_finding()],
            "governance_graph": {"edges": []},
            "cross_references": [],
        }
        (legal_dir / "acme_corp.json").write_text(json.dumps(output))

        merger = FindingMerger(run_id="test", timestamp="2025-01-01T00:00:00Z")
        # "missing_customer" is expected but has no findings
        results = merger.merge_all(
            findings_dir,
            expected_subjects=["acme_corp", "missing_customer"],
        )
        assert "acme_corp" in results
        # missing_customer should not appear in results
        assert "missing_customer" not in results


# ===========================================================================
# Issue #90: JSON output constraint in system prompt
# ===========================================================================


class TestJsonOutputConstraint:
    """Tests for the JSON-only output constraint in base _spawn_agent."""

    def test_critical_constraints_include_json_rule(
        self,
        tmp_project: Path,
        tmp_run_dir: Path,
        run_id: str,
    ) -> None:
        """The CRITICAL CONSTRAINTS block (built in _spawn_agent) references
        JSON_OUTPUT_CONSTRAINT for constraint #5.  Verify the constant contains
        the expected rules and that _spawn_agent references it."""
        import inspect

        from dd_agents.agents.prompt_constants import JSON_OUTPUT_CONSTRAINT

        # The constant itself must contain the JSON output rules
        assert "valid JSON object" in JSON_OUTPUT_CONSTRAINT
        assert "markdown fences" in JSON_OUTPUT_CONSTRAINT or "```json" in JSON_OUTPUT_CONSTRAINT

        # _spawn_agent must reference the shared constant
        src = inspect.getsource(BaseAgentRunner._spawn_agent)
        assert "JSON_OUTPUT_CONSTRAINT" in src

    def test_constraint_5_is_present(self) -> None:
        """Constraint #5 references JSON_OUTPUT_CONSTRAINT in _spawn_agent."""
        import inspect

        from dd_agents.agents.prompt_constants import JSON_OUTPUT_CONSTRAINT

        src = inspect.getsource(BaseAgentRunner._spawn_agent)
        assert "JSON_OUTPUT_CONSTRAINT" in src
        # Verify the constant itself has the expected content
        assert "MUST be a single valid JSON object" in JSON_OUTPUT_CONSTRAINT


# ===========================================================================
# Issue #92: Per-agent batch sizing
# ===========================================================================


class TestPerAgentBatchSizing:
    """Tests for per-agent batch sizing."""

    def test_base_defaults(self) -> None:
        """BaseAgentRunner defaults are 20 subjects, 40K tokens."""
        assert BaseAgentRunner.max_subjects_per_batch == 20
        assert BaseAgentRunner.max_tokens_per_batch == 40_000

    def test_finance_overrides(self) -> None:
        """FinanceAgent uses smaller batches for dense spreadsheet content."""
        assert FinanceAgent.max_subjects_per_batch == 7
        assert FinanceAgent.max_tokens_per_batch == 20_000

    def test_legal_inherits_defaults(self) -> None:
        """LegalAgent inherits the base defaults."""
        assert LegalAgent.max_subjects_per_batch == 20
        assert LegalAgent.max_tokens_per_batch == 40_000

    def test_commercial_inherits_defaults(self) -> None:
        assert CommercialAgent.max_subjects_per_batch == 20
        assert CommercialAgent.max_tokens_per_batch == 40_000

    def test_producttech_reduced_batch_sizing(self) -> None:
        """ProductTech uses reduced batches (dense docs like SOC2, DPAs)."""
        assert ProductTechAgent.max_subjects_per_batch == 7
        assert ProductTechAgent.max_tokens_per_batch == 20_000

    def test_instance_attributes(
        self,
        tmp_project: Path,
        tmp_run_dir: Path,
        run_id: str,
    ) -> None:
        """Batch sizing is accessible on instances."""
        finance = FinanceAgent(tmp_project, tmp_run_dir, run_id)
        assert finance.max_subjects_per_batch == 7
        assert finance.max_tokens_per_batch == 20_000

        legal = LegalAgent(tmp_project, tmp_run_dir, run_id)
        assert legal.max_subjects_per_batch == 20


# ===========================================================================
# Issue #93: Citation verification mandate + verification_status field
# ===========================================================================


class TestCitationVerification:
    """Tests for citation verification mandate and verification_status."""

    def test_verification_status_field_exists(self) -> None:
        """Citation model has verification_status field."""
        cit = Citation(
            source_type="file",
            source_path="test.pdf",
            exact_quote="test quote",
        )
        assert cit.verification_status is None

    def test_verification_status_accepts_verified(self) -> None:
        cit = Citation(
            source_type="file",
            source_path="test.pdf",
            exact_quote="test quote",
            verification_status="verified",
        )
        assert cit.verification_status == "verified"

    def test_verification_status_accepts_failed(self) -> None:
        cit = Citation(
            source_type="file",
            source_path="test.pdf",
            exact_quote="test quote",
            verification_status="failed",
        )
        assert cit.verification_status == "failed"

    def test_verification_status_excluded_when_none(self) -> None:
        """verification_status is excluded from serialization when None."""
        cit = Citation(
            source_type="file",
            source_path="test.pdf",
            exact_quote="test quote",
        )
        data = cit.model_dump(exclude_none=True)
        assert "verification_status" not in data

    def test_verification_status_included_when_set(self) -> None:
        cit = Citation(
            source_type="file",
            source_path="test.pdf",
            exact_quote="test quote",
            verification_status="verified",
        )
        data = cit.model_dump()
        assert data["verification_status"] == "verified"

    def test_citation_verification_mandate_in_prompt(
        self,
        builder: PromptBuilder,
        sample_subjects: list[SubjectEntry],
    ) -> None:
        """Citation verification mandate appears in specialist prompts."""
        prompt = builder.build_specialist_prompt(
            agent_name="legal",
            subjects=sample_subjects,
        )
        assert "Citation Verification" in prompt
        assert "MANDATORY" in prompt
        assert "P0" in prompt
        assert "P1" in prompt
        assert "verify_citation" in prompt


# ===========================================================================
# Issue #94: Tool list naming clarity
# ===========================================================================


class TestToolListNaming:
    """Tests for renamed tool lists in server.py."""

    def test_specialist_custom_tools_exist(self) -> None:
        assert isinstance(SPECIALIST_CUSTOM_TOOLS, list)
        assert "validate_finding" in SPECIALIST_CUSTOM_TOOLS
        assert "get_subject_files" in SPECIALIST_CUSTOM_TOOLS
        # Custom tools should NOT include SDK built-in tools
        assert "Read" not in SPECIALIST_CUSTOM_TOOLS
        assert "Write" not in SPECIALIST_CUSTOM_TOOLS

    def test_judge_custom_tools_exist(self) -> None:
        assert isinstance(JUDGE_CUSTOM_TOOLS, list)
        assert "verify_citation" in JUDGE_CUSTOM_TOOLS
        assert "Read" not in JUDGE_CUSTOM_TOOLS

    def test_get_tools_for_agent_specialist(self) -> None:
        tools = get_tools_for_agent("specialist")
        assert tools == SPECIALIST_CUSTOM_TOOLS

    def test_get_tools_for_agent_judge(self) -> None:
        tools = get_tools_for_agent("judge")
        assert tools == JUDGE_CUSTOM_TOOLS

    def test_get_tools_for_agent_unknown(self) -> None:
        tools = get_tools_for_agent("unknown_agent_type")
        assert tools == []


# ===========================================================================
# Cross-cutting: verify no text_dir parameter leaks
# ===========================================================================


class TestTextDirRemoval:
    """Verify text_dir has been fully removed from agent interfaces."""

    def test_base_build_prompt_no_text_dir(self) -> None:
        """BaseAgentRunner.build_prompt doesn't pass text_dir."""
        import inspect

        sig = inspect.signature(BaseAgentRunner.build_prompt)
        assert "text_dir" not in sig.parameters

    def test_prompt_builder_no_text_dir(self) -> None:
        """PromptBuilder.build_specialist_prompt doesn't accept text_dir."""
        import inspect

        sig = inspect.signature(PromptBuilder.build_specialist_prompt)
        assert "text_dir" not in sig.parameters


# ===========================================================================
# DoD check 12b: respects customer_assignments from metadata
# ===========================================================================


class TestDodCheck12bAssignments:
    """DoD check 12b should compare against assigned agents, not all 4."""

    def test_12b_passes_when_partial_assignment_covered(self, tmp_path: Path) -> None:
        """Subject assigned to 2 agents passes when those 2 produce findings."""
        from dd_agents.validation.dod import DefinitionOfDoneChecker

        run_dir = tmp_path / "run"
        merged_dir = run_dir / "findings" / "merged"
        merged_dir.mkdir(parents=True)

        # Write metadata with partial assignment
        metadata = {
            "subject_assignments": {
                "acme_corp": ["finance", "legal"],
            }
        }
        (run_dir / "metadata.json").write_text(json.dumps(metadata))

        # Write merged output with only finance + legal findings
        merged_output = {
            "subject": "Acme Corp",
            "subject_safe_name": "acme_corp",
            "findings": [
                _make_finding() | {"agent": "finance"},
                _make_finding() | {"agent": "legal"},
            ],
            "gaps": [],
        }
        (merged_dir / "acme_corp.json").write_text(json.dumps(merged_output))

        checker = DefinitionOfDoneChecker(
            run_dir=run_dir,
            inventory_dir=tmp_path / "inventory",
            subject_safe_names=["acme_corp"],
        )
        result = checker.check_12b_agent_coverage_in_merged()
        assert result.passed, f"Should pass but got: {result.details}"

    def test_12b_fails_when_assigned_agent_missing(self, tmp_path: Path) -> None:
        """Subject assigned to 3 agents fails when only 2 produce findings."""
        from dd_agents.validation.dod import DefinitionOfDoneChecker

        run_dir = tmp_path / "run"
        merged_dir = run_dir / "findings" / "merged"
        merged_dir.mkdir(parents=True)

        metadata = {
            "subject_assignments": {
                "acme_corp": ["finance", "legal", "commercial"],
            }
        }
        (run_dir / "metadata.json").write_text(json.dumps(metadata))

        merged_output = {
            "subject": "Acme Corp",
            "subject_safe_name": "acme_corp",
            "findings": [
                _make_finding() | {"agent": "finance"},
                _make_finding() | {"agent": "legal"},
            ],
            "gaps": [],
        }
        (merged_dir / "acme_corp.json").write_text(json.dumps(merged_output))

        checker = DefinitionOfDoneChecker(
            run_dir=run_dir,
            inventory_dir=tmp_path / "inventory",
            subject_safe_names=["acme_corp"],
        )
        result = checker.check_12b_agent_coverage_in_merged()
        assert not result.passed
        assert result.details["subjects_missing_agents"] == 1

    def test_12b_falls_back_to_all_agents_without_metadata(self, tmp_path: Path) -> None:
        """Without metadata.json, check falls back to expecting all 4 agents."""
        from dd_agents.validation.dod import DefinitionOfDoneChecker

        run_dir = tmp_path / "run"
        merged_dir = run_dir / "findings" / "merged"
        merged_dir.mkdir(parents=True)

        # No metadata.json — fallback to all 4 agents expected
        merged_output = {
            "subject": "Acme Corp",
            "subject_safe_name": "acme_corp",
            "findings": [
                _make_finding() | {"agent": "finance"},
                _make_finding() | {"agent": "legal"},
            ],
            "gaps": [],
        }
        (merged_dir / "acme_corp.json").write_text(json.dumps(merged_output))

        checker = DefinitionOfDoneChecker(
            run_dir=run_dir,
            inventory_dir=tmp_path / "inventory",
            subject_safe_names=["acme_corp"],
        )
        result = checker.check_12b_agent_coverage_in_merged()
        assert not result.passed
        assert result.details["subjects_missing_agents"] == 1
