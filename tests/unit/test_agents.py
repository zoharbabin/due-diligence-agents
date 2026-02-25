"""Unit tests for the dd_agents.agents module.

Covers PromptBuilder, all four specialist agents, JudgeAgent,
ReportingLeadAgent, and BaseAgentRunner (abstract enforcement).
No actual API calls -- all agent behaviour is tested via class
attributes, prompt construction, and score calculations.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from dd_agents.agents.base import BaseAgentRunner
from dd_agents.agents.judge import (
    DEFAULT_MAX_ITERATION_ROUNDS,
    DEFAULT_SAMPLING_RATES,
    DEFAULT_SCORE_THRESHOLD,
    DIMENSION_WEIGHTS,
    JudgeAgent,
    blend_round_scores,
    calculate_agent_score,
)
from dd_agents.agents.prompt_builder import (
    SPECIALIST_FOCUS,
    AgentType,
    PromptBuilder,
)
from dd_agents.agents.reporting_lead import ReportingLeadAgent
from dd_agents.agents.specialists import (
    COMMERCIAL_FOCUS_AREAS,
    FINANCE_FOCUS_AREAS,
    LEGAL_FOCUS_AREAS,
    PRODUCTTECH_FOCUS_AREAS,
    SPECIALIST_CLASSES,
    SPECIALIST_TYPES,
    CommercialAgent,
    FinanceAgent,
    LegalAgent,
    ProductTechAgent,
)
from dd_agents.models.audit import AgentScoreDimensions, QualityScores
from dd_agents.models.inventory import CustomerEntry, ReferenceFile

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a minimal project directory."""
    project = tmp_path / "project"
    project.mkdir()
    return project


@pytest.fixture
def tmp_run_dir(tmp_path: Path) -> Path:
    """Create a minimal run directory."""
    run_dir = tmp_path / "_dd" / "forensic-dd" / "runs" / "20250218_143000"
    run_dir.mkdir(parents=True)
    return run_dir


@pytest.fixture
def run_id() -> str:
    return "20250218_143000"


@pytest.fixture
def sample_customers() -> list[CustomerEntry]:
    """Minimal customer list for prompt testing."""
    return [
        CustomerEntry(
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
        CustomerEntry(
            group="Below 200K USD",
            name="Beta Inc",
            safe_name="beta",
            path="./Below 200K USD/Beta Inc/",
            file_count=1,
            files=["./Below 200K USD/Beta Inc/Contract.docx"],
        ),
    ]


@pytest.fixture
def sample_reference_files() -> list[ReferenceFile]:
    return [
        ReferenceFile(
            file_path="./Reference Data/Customers Cube.xlsx",
            text_path="_dd/forensic-dd/index/text/Customers_Cube.xlsx.md",
            category="Financial",
            subcategory="revenue_by_customer",
            description="Customer revenue cube Q4 2024",
            customers_mentioned=["Acme Corp", "Beta Inc"],
            customers_mentioned_count=2,
            assigned_to_agents=["finance"],
        ),
    ]


@pytest.fixture
def builder(tmp_project: Path, tmp_run_dir: Path, run_id: str) -> PromptBuilder:
    return PromptBuilder(
        project_dir=tmp_project,
        run_dir=tmp_run_dir,
        run_id=run_id,
    )


# =========================================================================
# PromptBuilder tests
# =========================================================================


class TestPromptBuilder:
    """Tests for PromptBuilder."""

    def test_build_specialist_prompt_includes_required_sections(
        self,
        builder: PromptBuilder,
        sample_customers: list[CustomerEntry],
        sample_reference_files: list[ReferenceFile],
    ) -> None:
        prompt = builder.build_specialist_prompt(
            agent_name="legal",
            customers=sample_customers,
            reference_files=sample_reference_files,
        )

        # Role section
        assert "LEGAL SPECIALIST AGENT" in prompt
        assert "legal" in prompt

        # Customer list
        assert "Acme Corp" in prompt
        assert "acme_corp" in prompt
        assert "Beta Inc" in prompt
        assert "beta" in prompt
        assert "ALL CUSTOMERS" in prompt

        # Reference files
        assert "Customers Cube" in prompt
        assert "Financial" in prompt

        # Focus area
        assert "SPECIALIST FOCUS" in prompt
        assert "governance graph" in prompt.lower() or "governance" in prompt.lower()

        # Output format
        assert "OUTPUT FORMAT" in prompt
        assert "customer_safe_name" in prompt

        # Manifest
        assert "COVERAGE MANIFEST" in prompt
        assert "coverage_pct" in prompt

    def test_build_specialist_prompt_finance(
        self,
        builder: PromptBuilder,
        sample_customers: list[CustomerEntry],
    ) -> None:
        prompt = builder.build_specialist_prompt(
            agent_name="finance",
            customers=sample_customers,
        )
        assert "FINANCE SPECIALIST AGENT" in prompt
        assert "Cross-reference" in prompt

    def test_build_specialist_prompt_commercial(
        self,
        builder: PromptBuilder,
        sample_customers: list[CustomerEntry],
    ) -> None:
        prompt = builder.build_specialist_prompt(
            agent_name="commercial",
            customers=sample_customers,
        )
        assert "COMMERCIAL SPECIALIST AGENT" in prompt
        assert "renewal" in prompt.lower()

    def test_build_specialist_prompt_producttech(
        self,
        builder: PromptBuilder,
        sample_customers: list[CustomerEntry],
    ) -> None:
        prompt = builder.build_specialist_prompt(
            agent_name="producttech",
            customers=sample_customers,
        )
        assert "PRODUCTTECH SPECIALIST AGENT" in prompt
        assert "DPA" in prompt

    def test_build_specialist_prompt_no_reference_files(
        self,
        builder: PromptBuilder,
        sample_customers: list[CustomerEntry],
    ) -> None:
        prompt = builder.build_specialist_prompt(
            agent_name="legal",
            customers=sample_customers,
            reference_files=None,
        )
        assert "No reference files assigned" in prompt

    def test_build_judge_prompt(self, builder: PromptBuilder) -> None:
        prompt = builder.build_judge_prompt(
            findings_dir="/tmp/findings",
            quality_targets={"score_threshold": 70},
            sampling_rates={"p0": 1.0, "p1": 0.2, "p2": 0.1, "p3": 0.0},
        )
        assert "JUDGE AGENT" in prompt
        assert "SAMPLING RATES" in prompt
        assert "100%" in prompt  # P0
        assert "20%" in prompt  # P1
        assert "SPOT-CHECK PROTOCOL" in prompt
        assert "quality_scores.json" in prompt

    def test_build_reporting_lead_prompt(self, builder: PromptBuilder) -> None:
        prompt = builder.build_reporting_lead_prompt(
            findings_dir="/tmp/findings",
            schema_path="/config/report_schema.json",
        )
        assert "REPORTING LEAD AGENT" in prompt
        assert "merge" in prompt.lower() or "Merge" in prompt
        assert "/tmp/findings" in prompt
        assert "report_schema.json" in prompt

    def test_estimate_tokens(self) -> None:
        text = "a" * 400
        assert PromptBuilder.estimate_tokens(text) == 100

    def test_estimate_tokens_empty(self) -> None:
        assert PromptBuilder.estimate_tokens("") == 0

    def test_batch_customers_single_batch(self, sample_customers: list[CustomerEntry]) -> None:
        batches = PromptBuilder.batch_customers(sample_customers, max_tokens=80_000)
        assert len(batches) == 1
        assert len(batches[0]) == 2

    def test_batch_customers_multiple_batches(self, sample_customers: list[CustomerEntry]) -> None:
        # Force splitting by setting a very low max_tokens.
        batches = PromptBuilder.batch_customers(
            sample_customers,
            max_tokens=100,
            tokens_per_customer=50,
            overhead_tokens=10,
        )
        # With 90 available tokens and 50 per customer, max 1 per batch.
        assert len(batches) == 2
        assert len(batches[0]) == 1
        assert len(batches[1]) == 1

    def test_batch_customers_empty(self) -> None:
        batches = PromptBuilder.batch_customers([])
        assert batches == []

    def test_batch_customers_large_overhead(self, sample_customers: list[CustomerEntry]) -> None:
        """When overhead exceeds max_tokens, still returns at least 1 per batch."""
        batches = PromptBuilder.batch_customers(
            sample_customers,
            max_tokens=100,
            tokens_per_customer=50,
            overhead_tokens=200,  # exceeds max_tokens
        )
        # Falls back to max_tokens as available => max 2 per batch.
        assert len(batches) >= 1

    def test_specialist_focus_all_agents_have_entries(self) -> None:
        specialist_types = [
            AgentType.LEGAL,
            AgentType.FINANCE,
            AgentType.COMMERCIAL,
            AgentType.PRODUCTTECH,
        ]
        for agent_type in specialist_types:
            assert agent_type in SPECIALIST_FOCUS
            assert len(SPECIALIST_FOCUS[agent_type]) > 0


# =========================================================================
# Specialist agent tests
# =========================================================================


class TestLegalAgent:
    """Tests for LegalAgent."""

    def test_name(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = LegalAgent(tmp_project, tmp_run_dir, run_id)
        assert agent.get_agent_name() == "legal"

    def test_model(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = LegalAgent(tmp_project, tmp_run_dir, run_id)
        assert agent.get_model_id() == "claude-sonnet-4-20250514"

    def test_focus_areas(self) -> None:
        assert "change_of_control" in LEGAL_FOCUS_AREAS
        assert "assignment_consent" in LEGAL_FOCUS_AREAS
        assert "termination" in LEGAL_FOCUS_AREAS
        assert "non_compete" in LEGAL_FOCUS_AREAS
        assert "ip_ownership" in LEGAL_FOCUS_AREAS
        assert "data_privacy" in LEGAL_FOCUS_AREAS
        assert "indemnification" in LEGAL_FOCUS_AREAS
        assert "liability_caps" in LEGAL_FOCUS_AREAS
        assert "warranty" in LEGAL_FOCUS_AREAS
        assert "dispute_resolution" in LEGAL_FOCUS_AREAS
        assert len(LEGAL_FOCUS_AREAS) == 10

    def test_tools_include_specialist_tools(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = LegalAgent(tmp_project, tmp_run_dir, run_id)
        tools = agent.get_tools()
        assert "Read" in tools
        assert "Write" in tools
        assert "validate_finding" in tools
        assert "verify_citation" in tools
        assert "resolve_entity" in tools

    def test_system_prompt_mentions_legal(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = LegalAgent(tmp_project, tmp_run_dir, run_id)
        prompt = agent.get_system_prompt()
        assert "Legal" in prompt

    def test_max_turns(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = LegalAgent(tmp_project, tmp_run_dir, run_id)
        assert agent.max_turns == 200

    def test_reference_categories(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = LegalAgent(tmp_project, tmp_run_dir, run_id)
        assert "corporate_legal" in agent.reference_categories
        assert "compliance" in agent.reference_categories


class TestFinanceAgent:
    """Tests for FinanceAgent."""

    def test_name(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = FinanceAgent(tmp_project, tmp_run_dir, run_id)
        assert agent.get_agent_name() == "finance"

    def test_model(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = FinanceAgent(tmp_project, tmp_run_dir, run_id)
        assert agent.get_model_id() == "claude-sonnet-4-20250514"

    def test_focus_areas(self) -> None:
        assert "payment_terms" in FINANCE_FOCUS_AREAS
        assert "pricing" in FINANCE_FOCUS_AREAS
        assert "revenue_recognition" in FINANCE_FOCUS_AREAS
        assert "financial_commitments" in FINANCE_FOCUS_AREAS
        assert "penalties" in FINANCE_FOCUS_AREAS
        assert "insurance" in FINANCE_FOCUS_AREAS
        assert len(FINANCE_FOCUS_AREAS) == 6

    def test_tools(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = FinanceAgent(tmp_project, tmp_run_dir, run_id)
        tools = agent.get_tools()
        assert "validate_finding" in tools
        assert "get_customer_files" in tools

    def test_reference_categories(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = FinanceAgent(tmp_project, tmp_run_dir, run_id)
        assert "financial" in agent.reference_categories
        assert "pricing" in agent.reference_categories


class TestCommercialAgent:
    """Tests for CommercialAgent."""

    def test_name(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = CommercialAgent(tmp_project, tmp_run_dir, run_id)
        assert agent.get_agent_name() == "commercial"

    def test_model(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = CommercialAgent(tmp_project, tmp_run_dir, run_id)
        assert agent.get_model_id() == "claude-sonnet-4-20250514"

    def test_focus_areas(self) -> None:
        assert "sla_compliance" in COMMERCIAL_FOCUS_AREAS
        assert "renewal_terms" in COMMERCIAL_FOCUS_AREAS
        assert "volume_commitments" in COMMERCIAL_FOCUS_AREAS
        assert "exclusivity" in COMMERCIAL_FOCUS_AREAS
        assert "territory" in COMMERCIAL_FOCUS_AREAS
        assert "customer_satisfaction" in COMMERCIAL_FOCUS_AREAS
        assert len(COMMERCIAL_FOCUS_AREAS) == 6

    def test_tools(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = CommercialAgent(tmp_project, tmp_run_dir, run_id)
        tools = agent.get_tools()
        assert "Read" in tools
        assert "report_progress" in tools

    def test_reference_categories(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = CommercialAgent(tmp_project, tmp_run_dir, run_id)
        assert "pricing" in agent.reference_categories
        assert "sales" in agent.reference_categories
        assert "operational" in agent.reference_categories


class TestProductTechAgent:
    """Tests for ProductTechAgent."""

    def test_name(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = ProductTechAgent(tmp_project, tmp_run_dir, run_id)
        assert agent.get_agent_name() == "producttech"

    def test_model(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = ProductTechAgent(tmp_project, tmp_run_dir, run_id)
        assert agent.get_model_id() == "claude-sonnet-4-20250514"

    def test_focus_areas(self) -> None:
        assert "product_scope" in PRODUCTTECH_FOCUS_AREAS
        assert "technology_stack" in PRODUCTTECH_FOCUS_AREAS
        assert "integration_requirements" in PRODUCTTECH_FOCUS_AREAS
        assert "support_obligations" in PRODUCTTECH_FOCUS_AREAS
        assert "documentation" in PRODUCTTECH_FOCUS_AREAS
        assert "training" in PRODUCTTECH_FOCUS_AREAS
        assert len(PRODUCTTECH_FOCUS_AREAS) == 6

    def test_tools(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = ProductTechAgent(tmp_project, tmp_run_dir, run_id)
        tools = agent.get_tools()
        assert "validate_gap" in tools
        assert "Grep" in tools

    def test_reference_categories(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = ProductTechAgent(tmp_project, tmp_run_dir, run_id)
        assert "operational" in agent.reference_categories
        assert "compliance" in agent.reference_categories


# =========================================================================
# Specialist registry tests
# =========================================================================


class TestSpecialistRegistry:
    """Tests for the specialist type/class registries."""

    def test_specialist_types_has_four(self) -> None:
        assert len(SPECIALIST_TYPES) == 4

    def test_specialist_classes_keys(self) -> None:
        assert AgentType.LEGAL in SPECIALIST_CLASSES
        assert AgentType.FINANCE in SPECIALIST_CLASSES
        assert AgentType.COMMERCIAL in SPECIALIST_CLASSES
        assert AgentType.PRODUCTTECH in SPECIALIST_CLASSES

    def test_specialist_classes_are_subclasses(self) -> None:
        for cls in SPECIALIST_CLASSES.values():
            assert issubclass(cls, BaseAgentRunner)


# =========================================================================
# JudgeAgent tests
# =========================================================================


class TestJudgeAgent:
    """Tests for JudgeAgent."""

    def test_name(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = JudgeAgent(tmp_project, tmp_run_dir, run_id)
        assert agent.get_agent_name() == "judge"

    def test_model(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = JudgeAgent(tmp_project, tmp_run_dir, run_id)
        assert agent.get_model_id() == "claude-sonnet-4-20250514"

    def test_max_turns(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = JudgeAgent(tmp_project, tmp_run_dir, run_id)
        assert agent.max_turns == 150

    def test_max_budget(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = JudgeAgent(tmp_project, tmp_run_dir, run_id)
        assert agent.max_budget_usd == 3.0

    def test_default_sampling_rates(self) -> None:
        assert DEFAULT_SAMPLING_RATES["p0"] == 1.0
        assert DEFAULT_SAMPLING_RATES["p1"] == 0.20
        assert DEFAULT_SAMPLING_RATES["p2"] == 0.10
        assert DEFAULT_SAMPLING_RATES["p3"] == 0.0

    def test_default_score_threshold(self) -> None:
        assert DEFAULT_SCORE_THRESHOLD == 70

    def test_default_max_iteration_rounds(self) -> None:
        assert DEFAULT_MAX_ITERATION_ROUNDS == 2

    def test_dimension_weights_sum_to_one(self) -> None:
        total = sum(DIMENSION_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9

    def test_dimension_weights_correct_values(self) -> None:
        assert DIMENSION_WEIGHTS["citation_verification"] == 0.30
        assert DIMENSION_WEIGHTS["contextual_validation"] == 0.25
        assert DIMENSION_WEIGHTS["financial_accuracy"] == 0.20
        assert DIMENSION_WEIGHTS["cross_agent_consistency"] == 0.15
        assert DIMENSION_WEIGHTS["completeness"] == 0.10

    def test_calculate_agent_score_perfect(self) -> None:
        dims = AgentScoreDimensions(
            citation_verification=100,
            contextual_validation=100,
            financial_accuracy=100,
            cross_agent_consistency=100,
            completeness=100,
        )
        assert calculate_agent_score(dims) == 100

    def test_calculate_agent_score_zero(self) -> None:
        dims = AgentScoreDimensions(
            citation_verification=0,
            contextual_validation=0,
            financial_accuracy=0,
            cross_agent_consistency=0,
            completeness=0,
        )
        assert calculate_agent_score(dims) == 0

    def test_calculate_agent_score_mixed(self) -> None:
        dims = AgentScoreDimensions(
            citation_verification=90,
            contextual_validation=85,
            financial_accuracy=80,
            cross_agent_consistency=85,
            completeness=80,
        )
        expected = round(0.30 * 90 + 0.25 * 85 + 0.20 * 80 + 0.15 * 85 + 0.10 * 80)
        assert calculate_agent_score(dims) == expected

    def test_blend_round_scores(self) -> None:
        # 70% of 80 + 30% of 60 = 56 + 18 = 74
        assert blend_round_scores(round1_score=60, round2_score=80) == 74

    def test_blend_round_scores_same(self) -> None:
        assert blend_round_scores(round1_score=70, round2_score=70) == 70

    def test_tools_include_verify_citation(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = JudgeAgent(tmp_project, tmp_run_dir, run_id)
        tools = agent.get_tools()
        assert "verify_citation" in tools
        assert "get_customer_files" in tools
        # Judge should NOT have specialist-only tools.
        assert "validate_finding" not in tools
        assert "resolve_entity" not in tools

    def test_system_prompt_mentions_judge(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = JudgeAgent(tmp_project, tmp_run_dir, run_id)
        prompt = agent.get_system_prompt()
        assert "Judge" in prompt

    def test_build_prompt_includes_sampling(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = JudgeAgent(tmp_project, tmp_run_dir, run_id)
        prompt = agent.build_prompt({"findings_dir": "/tmp/findings"})
        assert "SAMPLING RATES" in prompt
        assert "100%" in prompt


# =========================================================================
# ReportingLeadAgent tests
# =========================================================================


class TestReportingLeadAgent:
    """Tests for ReportingLeadAgent."""

    def test_name(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = ReportingLeadAgent(tmp_project, tmp_run_dir, run_id)
        assert agent.get_agent_name() == "reporting_lead"

    def test_model(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = ReportingLeadAgent(tmp_project, tmp_run_dir, run_id)
        assert agent.get_model_id() == "claude-sonnet-4-20250514"

    def test_max_turns(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = ReportingLeadAgent(tmp_project, tmp_run_dir, run_id)
        assert agent.max_turns == 300

    def test_max_budget(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = ReportingLeadAgent(tmp_project, tmp_run_dir, run_id)
        assert agent.max_budget_usd == 8.0

    def test_tools_include_bash(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = ReportingLeadAgent(tmp_project, tmp_run_dir, run_id)
        tools = agent.get_tools()
        assert "Bash" in tools
        assert "Read" in tools
        assert "validate_manifest" in tools

    def test_system_prompt_mentions_reporting(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = ReportingLeadAgent(tmp_project, tmp_run_dir, run_id)
        prompt = agent.get_system_prompt()
        assert "Reporting Lead" in prompt

    def test_build_prompt_includes_merge(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = ReportingLeadAgent(tmp_project, tmp_run_dir, run_id)
        prompt = agent.build_prompt({"findings_dir": "/tmp/findings"})
        assert "REPORTING LEAD" in prompt
        assert "merge" in prompt.lower() or "Merge" in prompt


# =========================================================================
# BaseAgentRunner abstract enforcement
# =========================================================================


class TestBaseAgentRunner:
    """Tests for BaseAgentRunner abstract class."""

    def test_cannot_instantiate_directly(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        with pytest.raises(TypeError, match="abstract method"):
            BaseAgentRunner(tmp_project, tmp_run_dir, run_id)

    def test_subclass_must_implement_all_abstracts(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        """A subclass missing any abstract method cannot be instantiated."""

        class IncompleteAgent(BaseAgentRunner):
            def get_agent_name(self) -> str:
                return "incomplete"

            # Missing: get_system_prompt, get_tools

        with pytest.raises(TypeError):
            IncompleteAgent(tmp_project, tmp_run_dir, run_id)

    def test_concrete_subclass_instantiates(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        """A fully implemented subclass should instantiate fine."""

        class ConcreteAgent(BaseAgentRunner):
            def get_agent_name(self) -> str:
                return "test"

            def get_model_id(self) -> str:
                return "test-model"

            def get_system_prompt(self) -> str:
                return "test prompt"

            def get_tools(self) -> list[str]:
                return ["Read"]

        agent = ConcreteAgent(tmp_project, tmp_run_dir, run_id)
        assert agent.get_agent_name() == "test"


# =========================================================================
# BaseAgentRunner._parse_agent_output tests
# =========================================================================


class TestParseAgentOutput:
    """Tests for BaseAgentRunner._parse_agent_output static method."""

    def test_empty_string(self) -> None:
        assert BaseAgentRunner._parse_agent_output("") == []

    def test_plain_json_object(self) -> None:
        data = {"key": "value"}
        result = BaseAgentRunner._parse_agent_output(json.dumps(data))
        assert result == [data]

    def test_json_array(self) -> None:
        data = [{"a": 1}, {"b": 2}]
        result = BaseAgentRunner._parse_agent_output(json.dumps(data))
        assert result == data

    def test_json_in_markdown_fence(self) -> None:
        raw = 'Some text\n```json\n{"key": "value"}\n```\nMore text'
        result = BaseAgentRunner._parse_agent_output(raw)
        assert result == [{"key": "value"}]

    def test_json_in_plain_fence(self) -> None:
        raw = 'Text\n```\n{"key": "value"}\n```'
        result = BaseAgentRunner._parse_agent_output(raw)
        assert result == [{"key": "value"}]

    def test_no_valid_json(self) -> None:
        assert BaseAgentRunner._parse_agent_output("just plain text") == []

    def test_mixed_prose_and_json(self) -> None:
        raw = 'Analysis: {"severity": "P0", "title": "Issue"} is concerning.'
        result = BaseAgentRunner._parse_agent_output(raw)
        assert len(result) >= 1
        assert result[0]["severity"] == "P0"

    def test_parse_empty_output_returns_empty(self) -> None:
        """Empty and whitespace-only inputs return an empty list."""
        assert BaseAgentRunner._parse_agent_output("") == []
        assert BaseAgentRunner._parse_agent_output("   ") == []
        assert BaseAgentRunner._parse_agent_output("\n\t\n") == []

    def test_parse_valid_json_array(self) -> None:
        """A valid JSON array is parsed into a list of dicts."""
        data = [{"finding": "A"}, {"finding": "B"}]
        result = BaseAgentRunner._parse_agent_output(json.dumps(data))
        assert result == data
        assert len(result) == 2

    def test_parse_valid_json_object(self) -> None:
        """A valid JSON object is wrapped in a list."""
        data = {"severity": "P1", "title": "Test finding"}
        result = BaseAgentRunner._parse_agent_output(json.dumps(data))
        assert result == [data]

    def test_parse_markdown_wrapped_json(self) -> None:
        """JSON wrapped in ```json fences is extracted correctly."""
        inner = {"customer_safe_name": "acme", "risk": "high"}
        raw = "Here is the output:\n```json\n" + json.dumps(inner) + "\n```\nDone."
        result = BaseAgentRunner._parse_agent_output(raw)
        assert result == [inner]

    def test_parse_trailing_comma_json(self) -> None:
        """Trailing commas in JSON are auto-repaired."""
        raw = '{"key": "value", "items": [1, 2, 3,],}'
        result = BaseAgentRunner._parse_agent_output(raw)
        assert len(result) == 1
        assert result[0]["key"] == "value"
        assert result[0]["items"] == [1, 2, 3]

    def test_parse_bom_prefix(self) -> None:
        """UTF-8 BOM prefix is stripped before parsing."""
        import json as _json

        data = {"status": "ok"}
        raw = "\ufeff" + _json.dumps(data)
        result = BaseAgentRunner._parse_agent_output(raw)
        assert result == [data]

    def test_parse_no_json_logs_error(self, caplog: pytest.LogCaptureFixture) -> None:
        """When no JSON is found in non-empty output, an ERROR is logged."""
        import logging as _logging

        with caplog.at_level(_logging.WARNING, logger="dd_agents.agents.base"):
            result = BaseAgentRunner._parse_agent_output("This is plain text with no JSON at all")

        assert result == []
        # Check that an ERROR-level record was emitted.
        error_messages = [r.message for r in caplog.records if r.levelno >= _logging.ERROR]
        assert len(error_messages) >= 1
        assert "no parseable JSON" in error_messages[0]
        assert "38 chars" in error_messages[0]  # length of the input

    def test_parse_preserves_raw_on_failure(self, tmp_path: Path) -> None:
        """When raw_output_path is provided and parse fails, raw output is saved."""
        import pathlib

        raw_path = pathlib.Path(str(tmp_path)) / "debug" / "raw_output.txt"
        raw_text = "This output has no valid JSON whatsoever."
        result = BaseAgentRunner._parse_agent_output(
            raw_text,
            raw_output_path=raw_path,
        )
        assert result == []
        assert raw_path.exists()
        assert raw_path.read_text(encoding="utf-8") == raw_text

    def test_parse_no_file_written_on_success(self, tmp_path: Path) -> None:
        """When parsing succeeds, no raw output file is written even if path given."""
        import pathlib

        raw_path = pathlib.Path(str(tmp_path)) / "debug" / "raw_output.txt"
        data = {"key": "value"}
        result = BaseAgentRunner._parse_agent_output(
            json.dumps(data),
            raw_output_path=raw_path,
        )
        assert result == [data]
        assert not raw_path.exists()


# =========================================================================
# BaseAgentRunner._repair_json_text tests
# =========================================================================


class TestRepairJsonText:
    """Tests for BaseAgentRunner._repair_json_text static method."""

    def test_strips_bom(self) -> None:
        assert BaseAgentRunner._repair_json_text('\ufeff{"a": 1}') == '{"a": 1}'

    def test_strips_markdown_fences(self) -> None:
        raw = '```json\n{"a": 1}\n```'
        assert BaseAgentRunner._repair_json_text(raw) == '{"a": 1}'

    def test_removes_trailing_commas(self) -> None:
        raw = '{"a": 1, "b": [2,],}'
        expected = '{"a": 1, "b": [2]}'
        assert BaseAgentRunner._repair_json_text(raw) == expected

    def test_no_change_for_valid_json(self) -> None:
        raw = '{"a": 1}'
        assert BaseAgentRunner._repair_json_text(raw) == raw


# =========================================================================
# BaseAgentRunner.run async tests
# =========================================================================


class TestBaseAgentRunnerRun:
    """Tests for the async run method."""

    @pytest.mark.asyncio
    async def test_run_returns_success(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        agent = LegalAgent(tmp_project, tmp_run_dir, run_id)
        result = await agent.run({"customers": []})
        assert result["agent_name"] == "legal"
        assert result["status"] == "success"
        assert result["error"] is None
        assert result["elapsed_seconds"] >= 0

    @pytest.mark.asyncio
    async def test_run_handles_exception(self, tmp_project: Path, tmp_run_dir: Path, run_id: str) -> None:
        """Exceptions during build_prompt or spawn are caught gracefully."""

        class FailingAgent(BaseAgentRunner):
            def get_agent_name(self) -> str:
                return "failing"

            def get_model_id(self) -> str:
                return "test"

            def get_system_prompt(self) -> str:
                return "test"

            def get_tools(self) -> list[str]:
                return []

            def build_prompt(self, state: dict) -> str:
                raise RuntimeError("boom")

        agent = FailingAgent(tmp_project, tmp_run_dir, run_id)
        result = await agent.run({})
        assert result["status"] == "error"
        assert "RuntimeError" in result["error"]
        assert "boom" in result["error"]


# =========================================================================
# AgentType enum tests
# =========================================================================


class TestAgentType:
    """Tests for the AgentType enum."""

    def test_all_values(self) -> None:
        assert AgentType.LEGAL == "legal"
        assert AgentType.FINANCE == "finance"
        assert AgentType.COMMERCIAL == "commercial"
        assert AgentType.PRODUCTTECH == "producttech"
        assert AgentType.JUDGE == "judge"
        assert AgentType.REPORTING_LEAD == "reporting_lead"

    def test_judge_and_reporting_not_in_specialist_focus(self) -> None:
        assert AgentType.JUDGE not in SPECIALIST_FOCUS
        assert AgentType.REPORTING_LEAD not in SPECIALIST_FOCUS


# =========================================================================
# Issue #33: _spawn_agent SDK wiring tests
# =========================================================================


class TestSpawnAgentSDKWiring:
    """Tests for BaseAgentRunner._spawn_agent with/without claude_agent_sdk."""

    @pytest.mark.asyncio
    async def test_spawn_agent_returns_empty_when_sdk_unavailable(
        self,
        tmp_project: Path,
        tmp_run_dir: Path,
        run_id: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When _HAS_SDK is False, _spawn_agent returns empty string."""
        import dd_agents.agents.base as base_mod

        monkeypatch.setattr(base_mod, "_HAS_SDK", False)
        agent = LegalAgent(tmp_project, tmp_run_dir, run_id)
        result = await agent._spawn_agent("test prompt")
        assert result == ""

    @pytest.mark.asyncio
    async def test_spawn_agent_returns_text_when_sdk_available(
        self,
        tmp_project: Path,
        tmp_run_dir: Path,
        run_id: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When SDK is available, _spawn_agent calls query() and returns text."""
        import dd_agents.agents.base as base_mod

        # Create mock SDK types.
        class MockTextBlock:
            def __init__(self, text: str) -> None:
                self.text = text

        class MockAssistantMessage:
            def __init__(self, text: str) -> None:
                self.content = [MockTextBlock(text)]

        class MockResultMessage:
            is_error = False
            result = ""

        # Create an async generator that yields mock messages.
        async def mock_query(prompt: str, options: object) -> object:  # type: ignore[misc]
            yield MockAssistantMessage("Hello from agent")
            yield MockAssistantMessage(" part two")

        monkeypatch.setattr(base_mod, "_HAS_SDK", True)
        monkeypatch.setattr(base_mod, "_query", mock_query)
        monkeypatch.setattr(base_mod, "_AssistantMessage", MockAssistantMessage)
        monkeypatch.setattr(base_mod, "_TextBlock", MockTextBlock)
        monkeypatch.setattr(base_mod, "_ResultMessage", MockResultMessage)

        # Need to also mock _ClaudeAgentOptions.
        class MockOptions:
            def __init__(self, **kwargs: object) -> None:
                pass

        monkeypatch.setattr(base_mod, "_ClaudeAgentOptions", MockOptions)

        agent = LegalAgent(tmp_project, tmp_run_dir, run_id)
        result = await agent._spawn_agent("analyze contracts")
        assert "Hello from agent" in result
        assert "part two" in result

    @pytest.mark.asyncio
    async def test_spawn_agent_handles_sdk_error(
        self,
        tmp_project: Path,
        tmp_run_dir: Path,
        run_id: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When SDK returns an error message, _spawn_agent breaks and returns what it has."""
        import dd_agents.agents.base as base_mod

        class MockTextBlock:
            def __init__(self, text: str) -> None:
                self.text = text

        class MockAssistantMessage:
            def __init__(self, text: str) -> None:
                self.content = [MockTextBlock(text)]

        class MockResultMessage:
            is_error = True
            result = "Rate limit exceeded"

        async def mock_query(prompt: str, options: object) -> object:  # type: ignore[misc]
            yield MockAssistantMessage("partial output")
            yield MockResultMessage()

        monkeypatch.setattr(base_mod, "_HAS_SDK", True)
        monkeypatch.setattr(base_mod, "_query", mock_query)
        monkeypatch.setattr(base_mod, "_AssistantMessage", MockAssistantMessage)
        monkeypatch.setattr(base_mod, "_TextBlock", MockTextBlock)
        monkeypatch.setattr(base_mod, "_ResultMessage", MockResultMessage)

        class MockOptions:
            def __init__(self, **kwargs: object) -> None:
                pass

        monkeypatch.setattr(base_mod, "_ClaudeAgentOptions", MockOptions)

        agent = LegalAgent(tmp_project, tmp_run_dir, run_id)
        result = await agent._spawn_agent("test")
        # Should have partial output collected before the error.
        assert result == "partial output"

    @pytest.mark.asyncio
    async def test_spawn_agent_signature_compatible_with_mocks(
        self,
        tmp_project: Path,
        tmp_run_dir: Path,
        run_id: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """_spawn_agent can still be monkey-patched to return a string directly (test compat)."""
        agent = LegalAgent(tmp_project, tmp_run_dir, run_id)

        async def mock_spawn(prompt: str) -> str:
            return '{"findings": []}'

        monkeypatch.setattr(agent, "_spawn_agent", mock_spawn)
        result = await agent._spawn_agent("test")
        assert result == '{"findings": []}'


# =========================================================================
# Issue #58: Judge score extraction and threshold tests
# =========================================================================


class TestJudgeScoreExtraction:
    """Tests for JudgeAgent._build_scores_from_result."""

    def test_extract_scores_from_valid_output(self) -> None:
        """_build_scores_from_result correctly parses agent output with scores."""
        result: dict[str, object] = {
            "run_id": "test_run",
            "output": [
                {
                    "agent_scores": {
                        "legal": {
                            "score": 85,
                            "findings_reviewed": 10,
                            "findings_total": 12,
                            "pass": 8,
                            "partial": 1,
                            "fail": 1,
                            "dimensions": {
                                "citation_verification": 90,
                                "contextual_validation": 85,
                                "financial_accuracy": 80,
                                "cross_agent_consistency": 85,
                                "completeness": 80,
                            },
                        },
                        "finance": {
                            "score": 60,
                            "findings_reviewed": 8,
                            "findings_total": 10,
                            "pass": 5,
                            "partial": 2,
                            "fail": 1,
                            "dimensions": {
                                "citation_verification": 70,
                                "contextual_validation": 60,
                                "financial_accuracy": 50,
                                "cross_agent_consistency": 55,
                                "completeness": 65,
                            },
                        },
                    },
                    "overall_quality": 72,
                }
            ],
        }

        scores = JudgeAgent._build_scores_from_result(result, round_num=1)

        assert "legal" in scores.agent_scores
        assert "finance" in scores.agent_scores
        assert scores.agent_scores["legal"].score == 85
        assert scores.agent_scores["finance"].score == 60
        assert scores.agent_scores["legal"].findings_reviewed == 10
        assert scores.agent_scores["finance"].pass_count == 5
        assert scores.agent_scores["legal"].dimensions.citation_verification == 90
        # Overall should be average of 85 and 60 = 72 (rounded).
        assert scores.overall_quality == 72

    def test_extract_scores_no_output(self) -> None:
        """When output is empty, returns zeroed QualityScores."""
        result: dict[str, object] = {"run_id": "test", "output": []}
        scores = JudgeAgent._build_scores_from_result(result, round_num=1)
        assert scores.overall_quality == 0
        assert scores.agent_scores == {}

    def test_extract_scores_none_output(self) -> None:
        """When output is None, returns zeroed QualityScores."""
        result: dict[str, object] = {"run_id": "test", "output": None}
        scores = JudgeAgent._build_scores_from_result(result, round_num=1)
        assert scores.overall_quality == 0
        assert scores.agent_scores == {}

    def test_extract_scores_computes_from_dimensions(self) -> None:
        """When no explicit score is given, score is computed from dimensions."""
        result: dict[str, object] = {
            "run_id": "test",
            "output": [
                {
                    "agent_scores": {
                        "legal": {
                            "dimensions": {
                                "citation_verification": 90,
                                "contextual_validation": 85,
                                "financial_accuracy": 80,
                                "cross_agent_consistency": 85,
                                "completeness": 80,
                            },
                        },
                    },
                }
            ],
        }
        scores = JudgeAgent._build_scores_from_result(result, round_num=1)
        expected = round(0.30 * 90 + 0.25 * 85 + 0.20 * 80 + 0.15 * 85 + 0.10 * 80)
        assert scores.agent_scores["legal"].score == expected

    def test_round_num_propagated(self) -> None:
        """iteration_round in the returned QualityScores matches round_num."""
        result: dict[str, object] = {
            "run_id": "test",
            "output": [{"agent_scores": {"legal": {"score": 90}}}],
        }
        scores = JudgeAgent._build_scores_from_result(result, round_num=2)
        assert scores.iteration_round == 2


class TestJudgeThresholdCheck:
    """Tests for JudgeAgent threshold checks."""

    def test_threshold_identifies_failing_agents(self) -> None:
        """Agents below score_threshold are correctly identified as failing."""
        from dd_agents.models.audit import AgentScore

        scores = QualityScores(
            run_id="test",
            overall_quality=65,
            iteration_round=1,
            agent_scores={
                "legal": AgentScore(score=85),
                "finance": AgentScore(score=60),
                "commercial": AgentScore(score=45),
                "producttech": AgentScore(score=72),
            },
        )

        threshold = DEFAULT_SCORE_THRESHOLD  # 70
        failing = [name for name, agent_score in scores.agent_scores.items() if agent_score.score < threshold]
        assert "finance" in failing
        assert "commercial" in failing
        assert "legal" not in failing
        assert "producttech" not in failing

    def test_threshold_all_pass(self) -> None:
        """When all agents meet threshold, no failing agents."""
        from dd_agents.models.audit import AgentScore

        scores = QualityScores(
            run_id="test",
            overall_quality=80,
            iteration_round=1,
            agent_scores={
                "legal": AgentScore(score=85),
                "finance": AgentScore(score=75),
            },
        )
        failing = [name for name, agent_score in scores.agent_scores.items() if agent_score.score < 70]
        assert failing == []

    def test_threshold_zero_scores_fail(self) -> None:
        """Zero scores should be below the default threshold of 70."""
        from dd_agents.models.audit import AgentScore

        scores = QualityScores(
            run_id="test",
            overall_quality=0,
            iteration_round=1,
            agent_scores={
                "legal": AgentScore(score=0),
                "finance": AgentScore(score=0),
            },
        )
        failing = [name for name, agent_score in scores.agent_scores.items() if agent_score.score < 70]
        assert len(failing) == 2


class TestJudgeMutableDefault:
    """Tests that judge sampling_rates mutable default is fixed."""

    def test_instances_have_independent_sampling_rates(
        self,
        tmp_project: Path,
        tmp_run_dir: Path,
        run_id: str,
    ) -> None:
        """Mutating sampling_rates on one instance must not affect another."""
        agent1 = JudgeAgent(tmp_project, tmp_run_dir, run_id)
        agent2 = JudgeAgent(tmp_project, tmp_run_dir, run_id)

        # Mutate agent1's sampling_rates.
        agent1.sampling_rates["p0"] = 0.5

        # agent2 should still have the default.
        assert agent2.sampling_rates["p0"] == 1.0

    def test_default_sampling_rates_not_mutated(
        self,
        tmp_project: Path,
        tmp_run_dir: Path,
        run_id: str,
    ) -> None:
        """Module-level DEFAULT_SAMPLING_RATES should not be affected by instance mutations."""
        agent = JudgeAgent(tmp_project, tmp_run_dir, run_id)
        agent.sampling_rates["p0"] = 0.0

        # Module constant must remain unchanged.
        assert DEFAULT_SAMPLING_RATES["p0"] == 1.0

    def test_custom_sampling_rates_via_init(
        self,
        tmp_project: Path,
        tmp_run_dir: Path,
        run_id: str,
    ) -> None:
        """JudgeAgent accepts custom sampling_rates via __init__."""
        custom = {"p0": 0.5, "p1": 0.3, "p2": 0.2, "p3": 0.1}
        agent = JudgeAgent(tmp_project, tmp_run_dir, run_id, sampling_rates=custom)
        assert agent.sampling_rates == custom
        # Must be a copy, not the same object.
        assert agent.sampling_rates is not custom


class TestJudgeBlendFormula:
    """Tests for round-score blending in the judge iteration loop."""

    @pytest.mark.asyncio
    async def test_blend_applied_on_second_round(
        self,
        tmp_project: Path,
        tmp_run_dir: Path,
        run_id: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Score blending is applied when judge runs a second round."""
        agent = JudgeAgent(tmp_project, tmp_run_dir, run_id)
        agent.max_iteration_rounds = 2
        agent.score_threshold = 80  # Set high so first round fails

        call_count = 0
        round_outputs = [
            # Round 1: finance fails with score 60
            [
                {
                    "agent_scores": {
                        "legal": {"score": 85},
                        "finance": {"score": 60},
                    }
                }
            ],
            # Round 2: finance improves to 90
            [
                {
                    "agent_scores": {
                        "legal": {"score": 90},
                        "finance": {"score": 90},
                    }
                }
            ],
        ]

        async def mock_run(state: dict[str, object]) -> dict[str, object]:
            nonlocal call_count
            output = round_outputs[call_count]
            call_count += 1
            return {"status": "success", "output": output, "run_id": "test"}

        monkeypatch.setattr(agent, "run", mock_run)

        scores = await agent.run_with_iteration({})
        assert scores is not None

        # Finance round 2: blend(60, 90) = 0.7*90 + 0.3*60 = 63+18 = 81
        assert scores.agent_scores["finance"].score == blend_round_scores(60, 90)
        # Legal round 2: blend(85, 90) = 0.7*90 + 0.3*85 = 63+25.5 = 89
        assert scores.agent_scores["legal"].score == blend_round_scores(85, 90)


# =========================================================================
# Issue #52: LLM robustness instructions in prompts
# =========================================================================


class TestRobustnessInstructions:
    """Tests that robustness mitigations from spec doc 22 appear in prompts."""

    def test_robustness_instructions_returns_non_empty(self) -> None:
        """The static method must return a non-empty string."""
        text = PromptBuilder.robustness_instructions()
        assert isinstance(text, str)
        assert len(text) > 0

    def test_robustness_includes_structured_output(self) -> None:
        text = PromptBuilder.robustness_instructions()
        assert "Structured Output" in text
        assert "customer_safe_name" in text
        assert "severity" in text

    def test_robustness_includes_answer_normalization(self) -> None:
        text = PromptBuilder.robustness_instructions()
        assert "YES, NO, or NOT_ADDRESSED" in text

    def test_robustness_includes_citation_format(self) -> None:
        text = PromptBuilder.robustness_instructions()
        assert "file_path" in text
        assert "page" in text
        assert "section_ref" in text
        assert "exact_quote" in text

    def test_robustness_includes_anti_hallucination(self) -> None:
        text = PromptBuilder.robustness_instructions()
        assert "VERBATIM" in text
        assert "Do NOT generate quotes from memory" in text
        assert "Do NOT fabricate" in text

    def test_robustness_includes_context_window_awareness(self) -> None:
        text = PromptBuilder.robustness_instructions()
        assert "truncated" in text
        assert "120KB" in text

    def test_robustness_includes_conflict_handling(self) -> None:
        text = PromptBuilder.robustness_instructions()
        assert "Conflict Handling" in text
        assert "Cite BOTH" in text

    def test_robustness_includes_completeness_checklist(self) -> None:
        text = PromptBuilder.robustness_instructions()
        assert "Completeness Checklist" in text
        assert "ALL customers" in text
        assert "ALL files" in text
        assert "YOU MAY HAVE MISSED CRITICAL INFORMATION" in text

    def test_robustness_includes_not_found_protocol(self) -> None:
        text = PromptBuilder.robustness_instructions()
        assert "Not-Found Protocol" in text
        assert "gap_type" in text
        assert "Not_Found" in text

    def test_robustness_in_specialist_prompt(
        self,
        builder: PromptBuilder,
        sample_customers: list[CustomerEntry],
    ) -> None:
        """Robustness instructions are appended to every specialist prompt."""
        for agent_name in ("legal", "finance", "commercial", "producttech"):
            prompt = builder.build_specialist_prompt(
                agent_name=agent_name,
                customers=sample_customers,
            )
            assert "ROBUSTNESS INSTRUCTIONS" in prompt
            assert "Anti-Hallucination" in prompt
            assert "Completeness Checklist" in prompt

    def test_robustness_not_in_judge_prompt(self, builder: PromptBuilder) -> None:
        """Judge prompt does NOT include specialist robustness instructions."""
        prompt = builder.build_judge_prompt()
        # Judge has its own protocol; robustness instructions are specialist-specific.
        assert "ROBUSTNESS INSTRUCTIONS" not in prompt


class TestDomainRobustness:
    """Tests for domain-specific robustness instructions per specialist."""

    def test_legal_domain_robustness(self) -> None:
        text = LegalAgent.domain_robustness()
        assert "Change of Control" in text
        assert "Anti-Assignment" in text
        assert "Cap on Liability" in text
        assert "Exclusivity" in text
        assert "Not_Found" in text

    def test_finance_domain_robustness(self) -> None:
        text = FinanceAgent.domain_robustness()
        assert "Cap on Liability" in text
        assert "Insurance" in text
        assert "Excel date serial" in text
        assert "currency units" in text
        assert "cite BOTH" in text.upper() or "Cite BOTH" in text or "cite BOTH" in text

    def test_commercial_domain_robustness(self) -> None:
        text = CommercialAgent.domain_robustness()
        assert "Most Favored Nation" in text
        assert "Exclusivity" in text
        assert "Termination for Convenience" in text
        assert "Not_Found" in text

    def test_producttech_domain_robustness(self) -> None:
        text = ProductTechAgent.domain_robustness()
        assert "Data Processing Agreement" in text or "DPA" in text
        assert "SOC 2" in text or "SOC2" in text
        assert "Not_Found" in text or "not_found" in text.lower()

    def test_all_specialists_have_domain_robustness(
        self,
        tmp_project: Path,
        tmp_run_dir: Path,
        run_id: str,
    ) -> None:
        """Every specialist class must expose a domain_robustness() method."""
        for cls in (LegalAgent, FinanceAgent, CommercialAgent, ProductTechAgent):
            agent = cls(tmp_project, tmp_run_dir, run_id)
            text = agent.domain_robustness()
            assert isinstance(text, str)
            assert len(text) > 100  # Non-trivial content
