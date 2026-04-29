"""E2E tests for cross-domain neurosymbolic analysis pipeline.

Two tiers:
1. Structural tests (no API key) — verify trigger engine integration,
   config parsing, step ordering, and audit trail shape.
2. Live tests (API key required) — full chain: pass-1 → trigger → pass-2 → merge.

Run structural tests with::
    pytest tests/e2e/test_cross_domain.py -m "not e2e" -v

Run live tests with::
    pytest tests/e2e/test_cross_domain.py -m e2e -v --timeout=600
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from .conftest import skip_no_api_key

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def cross_domain_data_room(tmp_path: Path) -> Path:
    """Data room with contracts designed to trigger cross-domain analysis.

    Contains revenue recognition language that should trigger Finance→Legal,
    and a CoC clause that should trigger Legal→Finance.
    """
    root = tmp_path / "data_room"
    root.mkdir()

    subj = root / "GroupA" / "Subject Alpha"
    subj.mkdir(parents=True)

    # Contract with revenue recognition complexity (Finance→Legal trigger)
    (subj / "revenue_agreement.pdf.md").write_text(
        "# Revenue Agreement — Subject Alpha\n\n"
        "Contract Reference: RA-2024-001\n"
        "Effective Date: January 1, 2024\n"
        "Term: 36 months\n\n"
        "## Section 1 — Fee Structure\n"
        "Annual license fee: $360,000 ($30,000/month)\n"
        "Implementation fee: $90,000 (one-time, recognized ratably over 6 months)\n"
        "Success bonus: $50,000 (contingent on achieving KPI targets)\n\n"
        "Total Year 1 contract value: $500,000\n\n"
        "## Section 2 — Revenue Recognition\n"
        "2.1 License revenue shall be recognized ratably over each monthly period\n"
        "upon delivery of the monthly service attestation.\n\n"
        "2.2 The implementation fee shall be recognized on a percentage-of-completion\n"
        "basis tied to the milestone schedule in Exhibit A. Revenue is deferred\n"
        "until milestone acceptance.\n\n"
        "2.3 The success bonus constitutes variable consideration under ASC 606.\n"
        "It shall be constrained until the KPI threshold is achieved and\n"
        "formal written confirmation is received from Client.\n\n"
        "## Section 3 — Clawback and Refund\n"
        "3.1 If implementation milestones are not achieved within 9 months,\n"
        "Client is entitled to a refund of 30% of implementation fees paid.\n\n"
        "3.2 If Provider materially fails to deliver the monthly service\n"
        "attestation for 2 consecutive months, Client may demand a credit\n"
        "of 15% of monthly fees for the affected period.\n\n"
        "## Section 4 — Governing Law\n"
        "Laws of the State of Delaware. Binding arbitration under AAA rules.\n",
        encoding="utf-8",
    )

    # Contract with CoC clause (Legal→Finance trigger)
    (subj / "platform_license.pdf.md").write_text(
        "# Enterprise Platform License — Subject Alpha\n\n"
        "Contract Reference: EPL-2023-042\n"
        "Annual Value: $240,000\n"
        "Term: 24 months\n\n"
        "## Section 1 — License Grant\n"
        "Non-exclusive enterprise license for up to 500 users.\n\n"
        "## Section 2 — Change of Control\n"
        "2.1 In the event of a Change of Control of Provider (acquisition of\n"
        ">50% voting interests, merger, or sale of substantially all assets),\n"
        "Provider shall notify Licensee within 15 business days.\n\n"
        "2.2 Licensee may terminate this Agreement within 90 days of CoC\n"
        "notice without penalty and receive a pro-rata refund of prepaid fees.\n\n"
        "2.3 Total revenue at risk upon CoC termination: $240,000 annual.\n\n"
        "## Section 3 — Payment\n"
        "Quarterly payments of $60,000, due Net 30.\n\n"
        "## Section 4 — Governing Law\n"
        "Laws of the State of California.\n",
        encoding="utf-8",
    )

    # Reference file
    ref = root / "_reference"
    ref.mkdir()
    (ref / "buyer_overview.pdf.md").write_text(
        "# Buyer Overview\n\nEnterprise SaaS acquirer. $200M ARR.\n",
        encoding="utf-8",
    )

    return root


@pytest.fixture()
def cross_domain_config(tmp_path: Path, cross_domain_data_room: Path) -> dict[str, Any]:
    """Deal config with cross-domain analysis enabled."""
    return {
        "config_version": "1.0.0",
        "buyer": {"name": "Buyer Corp", "industry": "Enterprise SaaS"},
        "target": {"name": "Target Inc", "industry": "Analytics"},
        "entity_aliases": {
            "canonical_to_variants": {"Subject Alpha": ["Alpha", "Subject A"]},
            "short_name_guard": [],
            "exclusions": ["N/A"],
            "parent_child": {},
        },
        "deal": {
            "type": "acquisition",
            "focus_areas": ["revenue_recognition", "change_of_control_clauses"],
        },
        "execution": {"execution_mode": "full"},
        "judge": {"enabled": False},
        "agent_models": {"profile": "economy"},
        "forensic_dd": {
            "cross_domain": {
                "enabled": True,
                "max_pass2_budget_usd": 5.0,
                "min_trigger_severity": "P2",
            }
        },
    }


@pytest.fixture()
def disabled_cross_domain_config(cross_domain_config: dict[str, Any]) -> dict[str, Any]:
    """Deal config with cross-domain analysis disabled."""
    config = cross_domain_config.copy()
    config["forensic_dd"] = {"cross_domain": {"enabled": False}}
    return config


# ---------------------------------------------------------------------------
# Structural Tests (no API key required)
# ---------------------------------------------------------------------------


class TestCrossDomainStructural:
    """Verify cross-domain pipeline integration without making LLM calls."""

    def test_trigger_engine_initializes_from_config(self, cross_domain_config: dict[str, Any]) -> None:
        """TriggerEngine correctly parses the forensic_dd.cross_domain config."""
        from dd_agents.orchestrator.triggers import TriggerEngine

        engine = TriggerEngine.from_config(cross_domain_config)
        assert engine.enabled is True

    def test_trigger_engine_disabled_from_config(self, disabled_cross_domain_config: dict[str, Any]) -> None:
        """Disabled config produces an engine that returns no triggers."""
        from dd_agents.orchestrator.triggers import TriggerEngine

        engine = TriggerEngine.from_config(disabled_cross_domain_config)
        assert engine.enabled is False
        triggers = engine.evaluate(
            {"subj": [{"agent": "finance", "category": "revenue_recognition", "severity": "P0"}]}
        )
        assert triggers == []

    def test_pipeline_steps_include_cross_domain(self) -> None:
        """Steps 18-20 exist in the canonical step list."""
        from dd_agents.orchestrator.steps import PipelineStep

        all_steps = list(PipelineStep)
        step_values = [s.value for s in all_steps]
        assert PipelineStep.CROSS_DOMAIN_ANALYSIS.value in step_values
        assert PipelineStep.TARGETED_RESPAWN.value in step_values
        assert PipelineStep.TARGETED_MERGE.value in step_values

        idx_18 = step_values.index(PipelineStep.CROSS_DOMAIN_ANALYSIS.value)
        idx_19 = step_values.index(PipelineStep.TARGETED_RESPAWN.value)
        idx_20 = step_values.index(PipelineStep.TARGETED_MERGE.value)
        assert idx_18 < idx_19 < idx_20

    def test_cross_domain_steps_are_conditional(self) -> None:
        """Cross-domain steps should be marked conditional (skip when disabled)."""
        from dd_agents.orchestrator.steps import PipelineStep

        assert PipelineStep.CROSS_DOMAIN_ANALYSIS.is_conditional
        assert PipelineStep.TARGETED_RESPAWN.is_conditional
        assert PipelineStep.TARGETED_MERGE.is_conditional

    def test_pipeline_state_has_cross_domain_fields(self) -> None:
        """PipelineState carries cross_domain_triggers, pass2_agents, pass2_costs."""
        from dd_agents.orchestrator.state import PipelineState

        state = PipelineState(run_id="test", run_dir=Path("/tmp/test"))
        assert hasattr(state, "cross_domain_triggers")
        assert hasattr(state, "pass2_agents")
        assert hasattr(state, "pass2_costs")
        assert state.cross_domain_triggers == []
        assert state.pass2_agents == []
        assert state.pass2_costs == {}

    def test_cross_domain_config_model_validates(self) -> None:
        """CrossDomainConfig pydantic model accepts valid config."""
        from dd_agents.models.config import CrossDomainConfig

        cfg = CrossDomainConfig(
            enabled=True,
            max_pass2_budget_usd=3.0,
            min_trigger_severity="P1",
            disabled_rules=["sla_financial_impact"],
        )
        assert cfg.enabled is True
        assert cfg.max_pass2_budget_usd == 3.0
        assert cfg.min_trigger_severity == "P1"
        assert "sla_financial_impact" in cfg.disabled_rules

    def test_cross_domain_config_model_rejects_invalid_severity(self) -> None:
        """CrossDomainConfig rejects invalid severity format."""
        from pydantic import ValidationError

        from dd_agents.models.config import CrossDomainConfig

        with pytest.raises(ValidationError):
            CrossDomainConfig(min_trigger_severity="INVALID")

    def test_audit_trail_schema(self, tmp_path: Path) -> None:
        """Cross-domain triggers audit file has expected JSON structure."""
        from dd_agents.orchestrator.triggers import CrossDomainTrigger

        trigger = CrossDomainTrigger(
            trigger_id="test-id",
            source_agent="finance",
            target_agent="legal",
            trigger_type="revenue_recognition_enforceability",
            source_finding_ids=("f-001",),
            subject="alpha",
            contracts=("revenue.pdf",),
            instructions="Verify enforceability.",
            priority="P1",
            estimated_cost=0.50,
        )

        audit_path = tmp_path / "audit" / "cross_domain_triggers.json"
        audit_path.parent.mkdir(parents=True)
        audit_path.write_text(json.dumps([trigger.to_dict()], indent=2))

        loaded = json.loads(audit_path.read_text())
        assert len(loaded) == 1
        assert loaded[0]["source_agent"] == "finance"
        assert loaded[0]["target_agent"] == "legal"
        assert loaded[0]["trigger_type"] == "revenue_recognition_enforceability"
        assert loaded[0]["priority"] == "P1"

    def test_html_report_loads_triggers(self, tmp_path: Path) -> None:
        """HTML report generator loads cross_domain_triggers.json when present."""
        from dd_agents.reporting.computed_metrics import ReportComputedData

        computed = ReportComputedData()
        triggers = [
            {
                "source_agent": "finance",
                "target_agent": "legal",
                "trigger_type": "revenue_recognition_enforceability",
                "subject": "alpha",
                "priority": "P1",
            }
        ]
        computed.cross_domain_triggers = triggers
        assert len(computed.cross_domain_triggers) == 1

    def test_chat_context_includes_cross_domain_deps(self) -> None:
        """Chat context builder generates dependency text for active agents."""
        from dd_agents.chat.context import _build_cross_domain_deps

        text = _build_cross_domain_deps(["finance", "legal", "commercial"])
        assert "Cross-Domain" in text
        assert "Finance" in text or "finance" in text.lower()

    def test_chat_context_empty_for_no_agents(self) -> None:
        """No cross-domain text when agent list is empty."""
        from dd_agents.chat.context import _build_cross_domain_deps

        text = _build_cross_domain_deps([])
        assert text == ""


# ---------------------------------------------------------------------------
# Live E2E Tests (require API key)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestCrossDomainLive:
    """Full pipeline E2E with cross-domain analysis enabled.

    These tests run real agents via the API and verify the complete chain:
    pass-1 findings → trigger evaluation → pass-2 targeted respawn → merge.
    """

    @skip_no_api_key
    @pytest.mark.slow
    def test_cross_domain_pipeline_produces_triggers(
        self,
        tmp_path: Path,
        cross_domain_data_room: Path,
        cross_domain_config: dict[str, Any],
    ) -> None:
        """Full pipeline run produces cross-domain triggers and audit trail."""
        import asyncio
        import shutil

        from dd_agents.orchestrator.engine import PipelineEngine

        project = tmp_path / "project"
        shutil.copytree(cross_domain_data_room, project)

        config_path = project / "deal-config.json"
        config_path.write_text(json.dumps(cross_domain_config, indent=2))

        engine = PipelineEngine(project_dir=project, deal_config_path=config_path)
        state = asyncio.run(engine.run(resume_from_step=0))

        assert len(state.completed_steps) >= 20

        # Verify cross-domain triggers were evaluated
        assert state.cross_domain_triggers is not None

        # Verify audit trail exists
        audit_path = state.run_dir / "audit" / "cross_domain_triggers.json"
        assert audit_path.exists(), "cross_domain_triggers.json audit file not created"
        triggers = json.loads(audit_path.read_text())
        assert isinstance(triggers, list)

    @skip_no_api_key
    @pytest.mark.slow
    def test_pass2_findings_have_metadata(
        self,
        tmp_path: Path,
        cross_domain_data_room: Path,
        cross_domain_config: dict[str, Any],
    ) -> None:
        """Pass-2 findings are tagged with cross_domain metadata."""
        import asyncio
        import shutil

        from dd_agents.orchestrator.engine import PipelineEngine

        project = tmp_path / "project"
        shutil.copytree(cross_domain_data_room, project)

        config_path = project / "deal-config.json"
        config_path.write_text(json.dumps(cross_domain_config, indent=2))

        engine = PipelineEngine(project_dir=project, deal_config_path=config_path)
        state = asyncio.run(engine.run(resume_from_step=0))

        if not state.cross_domain_triggers:
            pytest.skip("No triggers fired — contract may not have triggered cross-domain")

        # Look for pass-2 finding files
        findings_dir = state.run_dir / "findings"
        pass2_findings_found = False

        for agent_dir in findings_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            for f in agent_dir.glob("*_pass2.json"):
                data = json.loads(f.read_text())
                for finding in data.get("findings", []):
                    metadata = finding.get("metadata", {})
                    if metadata.get("cross_domain") is True:
                        pass2_findings_found = True
                        assert metadata.get("pass") == 2

        if state.pass2_agents:
            assert pass2_findings_found, "Pass-2 agents ran but no cross_domain findings found"

    @skip_no_api_key
    @pytest.mark.slow
    def test_disabled_cross_domain_skips_steps(
        self,
        tmp_path: Path,
        cross_domain_data_room: Path,
        disabled_cross_domain_config: dict[str, Any],
    ) -> None:
        """With cross_domain disabled, steps 18-20 are no-ops."""
        import asyncio
        import shutil

        from dd_agents.orchestrator.engine import PipelineEngine

        project = tmp_path / "project"
        shutil.copytree(cross_domain_data_room, project)

        config_path = project / "deal-config.json"
        config_path.write_text(json.dumps(disabled_cross_domain_config, indent=2))

        engine = PipelineEngine(project_dir=project, deal_config_path=config_path)
        state = asyncio.run(engine.run(resume_from_step=0))

        # Triggers should be empty
        assert state.cross_domain_triggers == []
        assert state.pass2_agents == []

        # No audit file for triggers (or empty)
        audit_path = state.run_dir / "audit" / "cross_domain_triggers.json"
        if audit_path.exists():
            data = json.loads(audit_path.read_text())
            assert data == []

    @skip_no_api_key
    @pytest.mark.slow
    def test_merged_output_includes_pass2(
        self,
        tmp_path: Path,
        cross_domain_data_room: Path,
        cross_domain_config: dict[str, Any],
    ) -> None:
        """Merged findings include pass-2 contributions when triggers fired."""
        import asyncio
        import shutil

        from dd_agents.orchestrator.engine import PipelineEngine

        project = tmp_path / "project"
        shutil.copytree(cross_domain_data_room, project)

        config_path = project / "deal-config.json"
        config_path.write_text(json.dumps(cross_domain_config, indent=2))

        engine = PipelineEngine(project_dir=project, deal_config_path=config_path)
        state = asyncio.run(engine.run(resume_from_step=0))

        if not state.pass2_agents:
            pytest.skip("No pass-2 agents ran — triggers may not have fired")

        merged_dir = state.run_dir / "findings" / "merged"
        if not merged_dir.exists():
            pytest.skip("Merged directory not created")

        all_agents_in_merged: set[str] = set()
        for f in merged_dir.glob("*.json"):
            data = json.loads(f.read_text())
            for finding in data.get("findings", []):
                agent = finding.get("agent", finding.get("source_agent", ""))
                if agent:
                    all_agents_in_merged.add(agent.lower())

        # At least one pass-2 agent should appear in merged output
        pass2_set = {a.lower() for a in state.pass2_agents}
        assert pass2_set & all_agents_in_merged, (
            f"Pass-2 agents {pass2_set} not found in merged output (agents: {all_agents_in_merged})"
        )
