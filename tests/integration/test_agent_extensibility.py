"""Integration tests for agent extensibility architecture.

Comprehensive tests that verify the full agent registry, config-driven
agent disablement, reference file routing, prompt customization,
chat domain awareness, validation with dynamic agent sets, merge with
heterogeneous agent sets, HTML rendering with N agents, and checkpoint
resume behaviour.

These tests do NOT require an API key.  They exercise the architecture
layer — not the LLM agents themselves.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from dd_agents.agents.descriptor import AgentDescriptor
from dd_agents.agents.registry import AgentRegistry
from dd_agents.models.config import (
    AgentCustomization,
    BuyerInfo,
    DealConfig,
    DealInfo,
    ForensicDDConfig,
    SpecialistsConfig,
    TargetInfo,
)
from dd_agents.models.enums import AgentName, DealType

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

EXPECTED_BUILTIN_AGENTS = [
    "legal",
    "finance",
    "commercial",
    "producttech",
    "cybersecurity",
    "hr",
    "tax",
    "regulatory",
    "esg",
]


@pytest.fixture(autouse=True)
def _reset_registry():
    """Reset registry before each test, then restore."""
    AgentRegistry.reset()
    yield
    AgentRegistry.reset()


def _make_deal_config(
    disabled: list[str] | None = None,
    customizations: dict[str, AgentCustomization] | None = None,
) -> DealConfig:
    """Build a minimal valid DealConfig with optional specialist overrides."""
    specialists = SpecialistsConfig(
        disabled=disabled or [],
        customizations=customizations or {},
    )
    return DealConfig(
        config_version="1.0.0",
        buyer=BuyerInfo(name="AcquireCo"),
        target=TargetInfo(name="TargetCo"),
        deal=DealInfo(type=DealType.ACQUISITION, focus_areas=["contracts"]),
        forensic_dd=ForensicDDConfig(specialists=specialists),
    )


# ---------------------------------------------------------------------------
# 1. Registry behaviour
# ---------------------------------------------------------------------------


class TestRegistryEndToEnd:
    """Verify registry lifecycle: register → resolve → get → disable → re-enable."""

    def test_builtin_agents_register_on_first_access(self):
        """Lazy loading populates registry with all built-in agents."""
        names = AgentRegistry.all_specialist_names()
        assert names == EXPECTED_BUILTIN_AGENTS

    def test_get_returns_complete_descriptors(self):
        """Each built-in agent has all required descriptor fields populated."""
        for name in EXPECTED_BUILTIN_AGENTS:
            desc = AgentRegistry.get(name)
            assert desc.name == name
            assert desc.display_name  # non-empty
            assert desc.color.startswith("#")
            assert len(desc.focus_areas) >= 3
            assert desc.agent_class is not None
            assert desc.specialist_focus  # non-empty
            assert desc.max_subjects_per_batch > 0
            assert desc.max_tokens_per_batch > 0

    def test_disable_agents_via_config(self):
        """Disabled agents are excluded from resolve_active."""
        cfg = _make_deal_config(disabled=["producttech", "cybersecurity"])
        active = AgentRegistry.resolve_active(cfg)
        assert "producttech" not in active
        assert "cybersecurity" not in active
        assert len(active) == len(EXPECTED_BUILTIN_AGENTS) - 2

    def test_disable_all_agents(self):
        """Disabling all agents returns empty list (pipeline should refuse to start)."""
        cfg = _make_deal_config(disabled=EXPECTED_BUILTIN_AGENTS)
        active = AgentRegistry.resolve_active(cfg)
        assert active == []

    def test_disable_unknown_agent_logs_warning(self, caplog: pytest.LogCaptureFixture):
        """Unknown agent name in disabled list logs a warning but doesn't crash."""
        cfg = _make_deal_config(disabled=["nonexistent_agent"])
        active = AgentRegistry.resolve_active(cfg)
        assert len(active) == len(EXPECTED_BUILTIN_AGENTS)
        assert "nonexistent_agent" not in active
        assert any("unknown agents" in r.message.lower() for r in caplog.records)

    def test_no_config_returns_all_agents(self):
        """resolve_active(None) returns all registered agents."""
        active = AgentRegistry.resolve_active(None)
        assert active == EXPECTED_BUILTIN_AGENTS

    def test_register_external_agent(self):
        """External agents can register and appear in the active list."""

        @dataclass(frozen=True)
        class FakeAgent:
            pass

        external = AgentDescriptor(
            name="custom_esg_plus",
            display_name="ESG Plus",
            color="#10B981",
            focus_areas=("carbon_footprint", "dei_metrics"),
            reference_categories=("compliance",),
            agent_class=FakeAgent,  # type: ignore[arg-type]
            specialist_focus="Extended ESG analysis.",
        )
        AgentRegistry.register(external)
        names = AgentRegistry.all_specialist_names()
        assert "custom_esg_plus" in names
        assert len(names) == len(EXPECTED_BUILTIN_AGENTS) + 1

    def test_external_agent_can_be_disabled(self):
        """External agents respect the disabled list."""

        @dataclass(frozen=True)
        class FakeAgent:
            pass

        AgentRegistry.register(
            AgentDescriptor(
                name="custom_ext",
                display_name="Custom External",
                color="#10B981",
                focus_areas=("carbon",),
                reference_categories=(),
                agent_class=FakeAgent,  # type: ignore[arg-type]
                specialist_focus="Custom analysis.",
            )
        )
        assert "custom_ext" in AgentRegistry.all_specialist_names()
        cfg = _make_deal_config(disabled=["custom_ext"])
        active = AgentRegistry.resolve_active(cfg)
        assert "custom_ext" not in active
        assert len(active) == len(EXPECTED_BUILTIN_AGENTS)


# ---------------------------------------------------------------------------
# 2. Reference file routing
# ---------------------------------------------------------------------------


class TestReferenceFileRouting:
    """Verify cybersecurity agent receives compliance and operational files."""

    def test_compliance_routes_to_cybersecurity(self):
        from dd_agents.inventory.reference_files import ReferenceFileClassifier
        from dd_agents.models.enums import ReferenceFileCategory

        classifier = ReferenceFileClassifier()
        agents = classifier.route_to_agents(ReferenceFileCategory.COMPLIANCE)
        assert "cybersecurity" in agents
        assert "legal" in agents
        assert "producttech" in agents

    def test_operational_routes_to_cybersecurity(self):
        from dd_agents.inventory.reference_files import ReferenceFileClassifier
        from dd_agents.models.enums import ReferenceFileCategory

        classifier = ReferenceFileClassifier()
        agents = classifier.route_to_agents(ReferenceFileCategory.OPERATIONAL)
        assert "cybersecurity" in agents
        assert "producttech" in agents

    def test_unknown_category_routes_to_all_agents(self):
        from dd_agents.inventory.reference_files import ReferenceFileClassifier

        classifier = ReferenceFileClassifier()
        agents = classifier.route_to_agents("totally_unknown_category")
        assert len(agents) == len(EXPECTED_BUILTIN_AGENTS)

    def test_financial_does_not_route_to_cybersecurity(self):
        from dd_agents.inventory.reference_files import ReferenceFileClassifier
        from dd_agents.models.enums import ReferenceFileCategory

        classifier = ReferenceFileClassifier()
        agents = classifier.route_to_agents(ReferenceFileCategory.FINANCIAL)
        assert "cybersecurity" not in agents


# ---------------------------------------------------------------------------
# 3. Config customization
# ---------------------------------------------------------------------------


class TestConfigCustomization:
    """Verify deal-config customizations flow through to prompt builder."""

    def test_extra_focus_areas_applied(self):
        from dd_agents.agents.prompt_builder import apply_deal_config_customizations

        base_prompt = "Base prompt for finance agent."
        cfg = _make_deal_config(
            customizations={
                "finance": AgentCustomization(
                    extra_focus_areas=["pension_obligations", "insurance_analysis"],
                )
            }
        )
        result = apply_deal_config_customizations(base_prompt, cfg, "finance")
        assert "pension_obligations" in result
        assert "insurance_analysis" in result
        assert base_prompt in result

    def test_extra_instructions_applied(self):
        from dd_agents.agents.prompt_builder import apply_deal_config_customizations

        base_prompt = "Base prompt."
        cfg = _make_deal_config(
            customizations={
                "legal": AgentCustomization(
                    extra_instructions="Pay special attention to GDPR Article 28.",
                )
            }
        )
        result = apply_deal_config_customizations(base_prompt, cfg, "legal")
        assert "GDPR Article 28" in result

    def test_severity_overrides_applied(self):
        from dd_agents.agents.prompt_builder import apply_deal_config_customizations

        base_prompt = "Base prompt."
        cfg = _make_deal_config(
            customizations={
                "commercial": AgentCustomization(
                    severity_overrides={"change_of_control": "P2"},
                )
            }
        )
        result = apply_deal_config_customizations(base_prompt, cfg, "commercial")
        assert "change_of_control" in result
        assert "P2" in result

    def test_no_customization_returns_unchanged(self):
        from dd_agents.agents.prompt_builder import apply_deal_config_customizations

        base_prompt = "Base prompt."
        cfg = _make_deal_config()
        result = apply_deal_config_customizations(base_prompt, cfg, "legal")
        assert result == base_prompt

    def test_customization_for_unknown_agent_returns_unchanged(self):
        from dd_agents.agents.prompt_builder import apply_deal_config_customizations

        base_prompt = "Base prompt."
        cfg = _make_deal_config(
            customizations={
                "nonexistent": AgentCustomization(extra_instructions="Ignored."),
            }
        )
        result = apply_deal_config_customizations(base_prompt, cfg, "legal")
        assert result == base_prompt


# ---------------------------------------------------------------------------
# 4. Chat domain awareness
# ---------------------------------------------------------------------------


class TestChatDomainAwareness:
    """Verify chat system prompt includes agent domain descriptions."""

    def test_agent_descriptions_include_all_agents(self):
        from dd_agents.chat.context import _build_agent_descriptions

        desc = _build_agent_descriptions(EXPECTED_BUILTIN_AGENTS)
        assert "## Analysis Domains" in desc
        assert "Legal" in desc
        assert "Finance" in desc
        assert "Commercial" in desc
        assert "Cybersecurity" in desc

    def test_agent_descriptions_respects_active_list(self):
        from dd_agents.chat.context import _build_agent_descriptions

        desc = _build_agent_descriptions(["legal", "finance"])
        assert "Legal" in desc
        assert "Finance" in desc
        assert "Cybersecurity" not in desc

    def test_agent_descriptions_empty_list(self):
        from dd_agents.chat.context import _build_agent_descriptions

        desc = _build_agent_descriptions([])
        assert desc == ""

    def test_agent_descriptions_budget_respected(self):
        from dd_agents.chat.context import _BUDGET_AGENT_DESCRIPTIONS, _build_agent_descriptions

        desc = _build_agent_descriptions(EXPECTED_BUILTIN_AGENTS)
        assert len(desc) <= _BUDGET_AGENT_DESCRIPTIONS + 100  # small tolerance for final line


# ---------------------------------------------------------------------------
# 5. Validation with dynamic agent sets
# ---------------------------------------------------------------------------


class TestValidationDynamicAgents:
    """Verify DoD and QA audit work with N agents (not hardcoded 4)."""

    def test_dod_checker_accepts_active_agents(self, tmp_path: Path):
        from dd_agents.validation.dod import DefinitionOfDoneChecker

        checker = DefinitionOfDoneChecker(
            run_dir=tmp_path,
            inventory_dir=tmp_path / "inventory",
            subject_safe_names=["acme"],
            active_agents=["legal", "finance"],
        )
        assert checker._active_agents == ["legal", "finance"]

    def test_dod_checker_defaults_to_registry(self, tmp_path: Path):
        from dd_agents.validation.dod import DefinitionOfDoneChecker

        checker = DefinitionOfDoneChecker(
            run_dir=tmp_path,
            inventory_dir=tmp_path / "inventory",
            subject_safe_names=["acme"],
        )
        assert checker._active_agents == EXPECTED_BUILTIN_AGENTS

    def test_qa_auditor_accepts_active_agents(self, tmp_path: Path):
        from dd_agents.validation.qa_audit import QAAuditor

        auditor = QAAuditor(
            run_dir=tmp_path,
            inventory_dir=tmp_path / "inventory",
            subject_safe_names=["acme"],
            active_agents=["legal", "cybersecurity"],
        )
        assert auditor._active_agents == ["legal", "cybersecurity"]

    def test_pre_merge_validator_accepts_active_agents(self, tmp_path: Path):
        from dd_agents.validation.pre_merge import PreMergeValidator

        validator = PreMergeValidator(
            run_dir=tmp_path,
            findings_dir=tmp_path / "findings",
            subject_safe_names=["acme"],
            file_inventory=["contract.pdf"],
            active_agents=["legal", "finance", "cybersecurity"],
        )
        assert validator._active_agents == ["legal", "finance", "cybersecurity"]


# ---------------------------------------------------------------------------
# 6. Merge with heterogeneous agent sets
# ---------------------------------------------------------------------------


class TestMergeHeterogeneousAgents:
    """Verify merge and coverage check work with dynamic agent sets."""

    def _write_agent_findings(
        self,
        findings_dir: Path,
        agent: str,
        subject: str,
        findings: list[dict[str, Any]],
    ) -> None:
        agent_dir = findings_dir / agent
        agent_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "subject": subject,
            "findings": findings,
            "gaps": [],
        }
        (agent_dir / f"{subject}.json").write_text(json.dumps(data))

    def test_merge_with_5_agents(self, tmp_path: Path):
        from dd_agents.reporting.merge import FindingMerger

        findings_dir = tmp_path / "findings"
        for i, agent in enumerate(EXPECTED_BUILTIN_AGENTS):
            self._write_agent_findings(
                findings_dir,
                agent,
                "acme",
                [
                    {
                        "title": f"Finding from {agent}",
                        "severity": "P1",
                        "category": f"{agent}_category",
                        "description": f"Unique finding from {agent} domain analysis",
                        "citations": [
                            {"source_path": f"{agent}_report.pdf", "page": i + 1, "exact_quote": f"Quote from {agent}"}
                        ],
                        "confidence": "high",
                    }
                ],
            )

        merger = FindingMerger()
        merged = merger.merge_all(findings_dir, active_agents=EXPECTED_BUILTIN_AGENTS)
        assert "acme" in merged
        assert len(merged["acme"].findings) == len(EXPECTED_BUILTIN_AGENTS)

    def test_merge_with_3_agents_active(self, tmp_path: Path):
        from dd_agents.reporting.merge import FindingMerger

        findings_dir = tmp_path / "findings"
        active = ["legal", "finance", "commercial"]
        for agent in active:
            self._write_agent_findings(
                findings_dir,
                agent,
                "betaco",
                [
                    {
                        "title": f"Finding from {agent}",
                        "severity": "P2",
                        "category": "test",
                        "description": "Test finding",
                        "citations": [],
                        "confidence": "medium",
                    }
                ],
            )

        merger = FindingMerger()
        merged = merger.merge_all(findings_dir, active_agents=active)
        assert "betaco" in merged
        assert len(merged["betaco"].findings) == 3

    def test_coverage_check_with_active_agents(self, tmp_path: Path):
        from dd_agents.reporting.merge import FindingMerger

        findings_dir = tmp_path / "findings"
        active = ["legal", "finance", "cybersecurity"]
        for agent in active:
            self._write_agent_findings(
                findings_dir,
                agent,
                "delta",
                [
                    {
                        "title": "Finding",
                        "severity": "P1",
                        "category": "test",
                        "description": "Test",
                        "citations": [],
                        "confidence": "high",
                    }
                ],
            )

        merger = FindingMerger()
        merged = merger.merge_all(findings_dir, active_agents=active)
        gaps = FindingMerger.check_agent_coverage(merged, findings_dir, active_agents=active)
        assert gaps == []  # All active agents produced output

    def test_coverage_check_detects_missing_agent(self, tmp_path: Path):
        from dd_agents.reporting.merge import FindingMerger

        findings_dir = tmp_path / "findings"
        # Only write legal findings — finance and cybersecurity are "missing"
        self._write_agent_findings(
            findings_dir,
            "legal",
            "sigma",
            [
                {
                    "title": "Finding",
                    "severity": "P0",
                    "category": "test",
                    "description": "Test",
                    "citations": [],
                    "confidence": "high",
                }
            ],
        )

        merger = FindingMerger()
        merged = merger.merge_all(findings_dir, active_agents=["legal", "finance", "cybersecurity"])
        gaps = FindingMerger.check_agent_coverage(
            merged, findings_dir, active_agents=["legal", "finance", "cybersecurity"]
        )
        assert len(gaps) == 1
        assert "finance" in gaps[0]["missing_agents"] or "cybersecurity" in gaps[0]["missing_agents"]


# ---------------------------------------------------------------------------
# 7. HTML rendering with N agents
# ---------------------------------------------------------------------------


class TestHTMLRenderingDynamicAgents:
    """Verify HTML report renders correctly with dynamic agent count."""

    def test_domain_display_includes_cybersecurity(self):
        from dd_agents.reporting.html_base import DOMAIN_COLORS, DOMAIN_DISPLAY

        assert "cybersecurity" in DOMAIN_DISPLAY
        assert DOMAIN_DISPLAY["cybersecurity"] == "Cybersecurity"
        assert "cybersecurity" in DOMAIN_COLORS

    def test_heatmap_css_uses_auto_fill(self):
        import inspect

        from dd_agents.reporting import html_base

        source = inspect.getsource(html_base)
        assert "repeat(auto-fill, minmax(200px, 1fr))" in source
        assert ".heatmap" in source

    def test_agent_to_domain_maps_cybersecurity(self):
        from dd_agents.reporting.html_base import SectionRenderer

        assert SectionRenderer.agent_to_domain("cybersecurity") == "cybersecurity"

    def test_agent_to_domain_keyword_fallback(self):
        from dd_agents.reporting.html_base import SectionRenderer

        assert SectionRenderer.agent_to_domain("security_assessment_agent") == "cybersecurity"
        assert SectionRenderer.agent_to_domain("legal_review") == "legal"
        assert SectionRenderer.agent_to_domain("financial_audit") == "finance"

    def test_computed_metrics_agent_to_domain(self):
        from dd_agents.reporting.computed_metrics import ReportDataComputer

        computer = ReportDataComputer()
        assert computer._agent_to_domain("cybersecurity") == "cybersecurity"
        assert computer._agent_to_domain("cyber_agent") == "cybersecurity"
        assert computer._agent_to_domain("security_team") == "cybersecurity"


# ---------------------------------------------------------------------------
# 8. Eval framework integrity
# ---------------------------------------------------------------------------


class TestEvalFrameworkIntegrity:
    """Verify eval ground truth files are valid and complete."""

    @staticmethod
    def _project_root() -> Path:
        """Resolve the project root from this file's location."""
        return Path(__file__).resolve().parent.parent.parent

    def test_ground_truth_files_validate_against_model(self):
        import importlib.util
        import sys

        root = self._project_root()
        # Dynamically import tests.evals.models
        spec = importlib.util.spec_from_file_location("evals_models", root / "tests" / "evals" / "models.py")
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        sys.modules["evals_models"] = mod
        spec.loader.exec_module(mod)
        GroundTruth = mod.GroundTruth  # noqa: N806

        gt_dir = root / "tests" / "evals" / "ground_truth" / "expected"
        json_files = list(gt_dir.rglob("*.json"))
        assert len(json_files) >= 11  # At least one per agent + adversarial/edge cases

        for jf in json_files:
            data = json.loads(jf.read_text())
            gt = GroundTruth.model_validate(data)
            assert gt.contract  # non-empty
            assert gt.agent  # non-empty
            assert len(gt.expected_findings) > 0 or len(gt.must_not_find) > 0

    def test_every_builtin_agent_has_ground_truth(self):
        gt_dir = self._project_root() / "tests" / "evals" / "ground_truth" / "expected"
        agent_dirs = {p.name for p in gt_dir.iterdir() if p.is_dir()}
        for agent in EXPECTED_BUILTIN_AGENTS:
            assert agent in agent_dirs, f"Missing ground truth for agent: {agent}"

    def test_ground_truth_contracts_exist(self):
        contracts_dir = self._project_root() / "tests" / "evals" / "ground_truth" / "contracts"
        contracts = list(contracts_dir.glob("*.md"))
        assert len(contracts) >= 10
        names = {c.stem for c in contracts}
        assert "coc_basic" in names
        assert "security_assessment" in names

    def test_eval_suite_passes(self):
        import subprocess

        root = self._project_root()
        result = subprocess.run(
            [
                "python",
                "-m",
                "pytest",
                "tests/evals/test_contract_tier.py",
                "tests/evals/test_agent_evals.py",
                "tests/evals/test_cross_agent_evals.py",
                "-x",
                "-q",
                "--tb=short",
                "-k",
                "not TestAgentEvals and not TestCrossAgentEvals",
            ],
            capture_output=True,
            text=True,
            cwd=str(root),
            timeout=60,
        )
        assert result.returncode == 0, f"Eval suite failed:\n{result.stdout}\n{result.stderr}"

    def test_eval_test_files_exist(self):
        root = self._project_root()
        assert (root / "tests" / "evals" / "test_agent_evals.py").exists()
        assert (root / "tests" / "evals" / "test_cross_agent_evals.py").exists()
        assert (root / "tests" / "evals" / "conftest.py").exists()


# ---------------------------------------------------------------------------
# 9. Agent enum completeness
# ---------------------------------------------------------------------------


class TestAgentEnumCompleteness:
    """Verify all registered agents have enum entries and constants."""

    def test_all_agents_have_enum_values(self):
        agent_enum_values = {e.value for e in AgentName}
        for name in EXPECTED_BUILTIN_AGENTS:
            assert name in agent_enum_values, f"AgentName enum missing value: {name}"

    def test_all_agents_have_specialist_focus(self):
        from dd_agents.agents.prompt_builder import SPECIALIST_FOCUS

        for name in EXPECTED_BUILTIN_AGENTS:
            found = False
            for key in SPECIALIST_FOCUS:
                if key.value == name or str(key) == name:
                    found = True
                    break
            assert found, f"SPECIALIST_FOCUS missing entry for: {name}"


# ---------------------------------------------------------------------------
# 10. Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    """Verify registry is safe under concurrent access."""

    def test_concurrent_registration(self):
        import threading

        @dataclass(frozen=True)
        class FakeAgent:
            pass

        errors: list[Exception] = []
        results: list[list[str]] = []

        def register_and_resolve(idx: int) -> None:
            try:
                AgentRegistry.register(
                    AgentDescriptor(
                        name=f"thread_agent_{idx}",
                        display_name=f"Thread Agent {idx}",
                        color="#000000",
                        focus_areas=("test",),
                        reference_categories=(),
                        agent_class=FakeAgent,  # type: ignore[arg-type]
                        specialist_focus="Test.",
                    )
                )
                names = AgentRegistry.all_specialist_names()
                results.append(names)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=register_and_resolve, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread safety violation: {errors}"
        # All 10 thread agents plus builtins should be registered
        final_names = AgentRegistry.all_specialist_names()
        assert len(final_names) >= 10 + len(EXPECTED_BUILTIN_AGENTS)


# ---------------------------------------------------------------------------
# 11. Backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Verify old deal-config.json formats still work."""

    def test_config_without_forensic_dd_section(self):
        """Config missing forensic_dd entirely should use defaults."""
        data = {
            "config_version": "1.0.0",
            "buyer": {"name": "AcquireCo"},
            "target": {"name": "TargetCo"},
            "deal": {"type": "acquisition", "focus_areas": ["contracts"]},
        }
        config = DealConfig.model_validate(data)
        assert config.forensic_dd.specialists.disabled == []
        assert config.forensic_dd.specialists.customizations == {}

    def test_config_with_empty_specialists(self):
        """Config with empty specialists section should work."""
        data = {
            "config_version": "1.0.0",
            "buyer": {"name": "AcquireCo"},
            "target": {"name": "TargetCo"},
            "deal": {"type": "acquisition", "focus_areas": ["contracts"]},
            "forensic_dd": {"specialists": {}},
        }
        config = DealConfig.model_validate(data)
        assert config.forensic_dd.specialists.disabled == []

    def test_config_with_extra_fields_accepted(self):
        """Extra fields in config are allowed (ConfigDict extra='allow')."""
        data = {
            "config_version": "1.0.0",
            "buyer": {"name": "AcquireCo"},
            "target": {"name": "TargetCo"},
            "deal": {"type": "acquisition", "focus_areas": ["contracts"]},
            "forensic_dd": {
                "specialists": {"disabled": [], "future_field": True},
            },
        }
        config = DealConfig.model_validate(data)
        assert config.forensic_dd.specialists.disabled == []

    def test_all_specialist_agents_constant_still_works(self):
        """The backward-compat ALL_SPECIALIST_AGENTS constant includes all 9 agents."""
        from dd_agents.utils.constants import ALL_SPECIALIST_AGENTS

        assert len(ALL_SPECIALIST_AGENTS) == 9
        assert "cybersecurity" in ALL_SPECIALIST_AGENTS
        assert "hr" in ALL_SPECIALIST_AGENTS
        assert "tax" in ALL_SPECIALIST_AGENTS
        assert "regulatory" in ALL_SPECIALIST_AGENTS
        assert "esg" in ALL_SPECIALIST_AGENTS

    def test_get_active_agents_function(self):
        """The convenience function delegates to registry."""
        from dd_agents.utils.constants import get_active_agents

        active = get_active_agents(None)
        assert active == EXPECTED_BUILTIN_AGENTS

        cfg = _make_deal_config(disabled=["cybersecurity"])
        active = get_active_agents(cfg)
        assert "cybersecurity" not in active
        assert len(active) == 8
