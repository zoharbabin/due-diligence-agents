"""Integration tests for the PipelineEngine.

Tests the pipeline through step 11 (everything before agent spawning),
using a realistic synthetic data room created in tmp_path.

These tests do NOT require an API key and do NOT spawn agents.
"""

from __future__ import annotations

import asyncio
import json
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from dd_agents.orchestrator.engine import PipelineEngine
from dd_agents.orchestrator.steps import PipelineStep

if TYPE_CHECKING:
    from dd_agents.orchestrator.state import PipelineState

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _create_data_room(root: Path) -> Path:
    """Build a realistic data room structure under *root*.

    Layout::

        data_room/
            GroupA/
                Acme Corp/
                    contract_acme.txt
                    financial_summary.txt
                    addendum_acme.txt
                Globex Inc/
                    master_agreement_globex.txt
                    sla_globex.txt
                BetaCo/
                    purchase_order_betaco.txt
                    beta_terms.txt
            GroupB/
                Delta Ltd/
                    delta_contract.txt
                    delta_sow.txt
                Epsilon/
                    epsilon_agreement.txt
                    epsilon_pricing.txt
                Zeta Corp/
                    zeta_nda.txt
            financial_overview.txt        (reference file)
            compliance_report.csv         (reference file)
    """
    data_room = root / "data_room"
    data_room.mkdir(parents=True, exist_ok=True)

    # --- GroupA customers ---
    _write_file(
        data_room / "GroupA" / "Acme Corp" / "contract_acme.txt",
        textwrap.dedent("""\
            MASTER SERVICE AGREEMENT
            Customer: Acme Corp
            Start Date: 2023-01-15
            End Date: 2025-01-14
            Annual Value: $120,000
            Auto-renewal: Yes (12-month periods)
            Governing Law: Delaware

            SCOPE OF SERVICES
            Provider shall deliver the SaaS platform to Customer, including:
            - Enterprise tier access
            - Priority support (4h SLA)
            - Custom integrations

            TERMINATION
            Either party may terminate with 90-day written notice.
        """),
    )
    _write_file(
        data_room / "GroupA" / "Acme Corp" / "financial_summary.txt",
        textwrap.dedent("""\
            Acme Corp Financial Summary
            ARR: $120,000
            Payment Terms: Net 30
            Outstanding Invoice: $10,000 (Q3 2024)
        """),
    )
    _write_file(
        data_room / "GroupA" / "Acme Corp" / "addendum_acme.txt",
        textwrap.dedent("""\
            ADDENDUM TO MASTER SERVICE AGREEMENT
            Effective: 2024-06-01
            Additional seats: +50 (total 150)
            Revised ARR: $180,000
        """),
    )

    _write_file(
        data_room / "GroupA" / "Globex Inc" / "master_agreement_globex.txt",
        textwrap.dedent("""\
            SAAS SUBSCRIPTION AGREEMENT
            Customer: Globex Inc
            Term: 2022-03-01 to 2024-02-28
            Annual Fee: $85,000
            Governing Law: California
        """),
    )
    _write_file(
        data_room / "GroupA" / "Globex Inc" / "sla_globex.txt",
        textwrap.dedent("""\
            SERVICE LEVEL AGREEMENT
            Customer: Globex Inc
            Uptime: 99.9%
            Response Time: 2 hours (P1), 8 hours (P2)
        """),
    )

    _write_file(
        data_room / "GroupA" / "BetaCo" / "purchase_order_betaco.txt",
        textwrap.dedent("""\
            PURCHASE ORDER
            Customer: BetaCo
            Order Date: 2024-01-15
            Amount: $45,000
            Products: Standard Tier
        """),
    )
    _write_file(
        data_room / "GroupA" / "BetaCo" / "beta_terms.txt",
        textwrap.dedent("""\
            TERMS AND CONDITIONS
            Customer: BetaCo
            Payment Terms: Net 45
            Liability Cap: $100,000
        """),
    )

    # --- GroupB customers ---
    _write_file(
        data_room / "GroupB" / "Delta Ltd" / "delta_contract.txt",
        textwrap.dedent("""\
            SUBSCRIPTION AGREEMENT
            Customer: Delta Ltd
            Start: 2023-06-01
            End: 2025-05-31
            Annual Fee: $200,000
        """),
    )
    _write_file(
        data_room / "GroupB" / "Delta Ltd" / "delta_sow.txt",
        textwrap.dedent("""\
            STATEMENT OF WORK
            Customer: Delta Ltd
            Project: Platform Integration
            Duration: 6 months
            Professional Services Fee: $50,000
        """),
    )

    _write_file(
        data_room / "GroupB" / "Epsilon" / "epsilon_agreement.txt",
        textwrap.dedent("""\
            LICENSE AGREEMENT
            Licensee: Epsilon
            Effective Date: 2024-03-01
            Annual License Fee: $60,000
        """),
    )
    _write_file(
        data_room / "GroupB" / "Epsilon" / "epsilon_pricing.txt",
        textwrap.dedent("""\
            PRICING SCHEDULE
            Customer: Epsilon
            Base Fee: $5,000/month
            Overage Rate: $0.10 per unit
        """),
    )

    _write_file(
        data_room / "GroupB" / "Zeta Corp" / "zeta_nda.txt",
        textwrap.dedent("""\
            NON-DISCLOSURE AGREEMENT
            Parties: Provider, Zeta Corp
            Effective: 2024-01-01
            Duration: 2 years
        """),
    )

    # --- Reference files (root level) ---
    _write_file(
        data_room / "financial_overview.txt",
        textwrap.dedent("""\
            CONSOLIDATED FINANCIAL OVERVIEW

            Customer Revenue Summary (FY 2024):
            - Acme Corp: $180,000 ARR
            - Globex Inc: $85,000 ARR
            - BetaCo: $45,000 ARR
            - Delta Ltd: $200,000 ARR (includes PS)
            - Epsilon: $60,000 ARR
            - Zeta Corp: NDA only, no revenue

            Total ARR: $570,000
            YoY Growth: 23%
        """),
    )
    _write_file(
        data_room / "compliance_report.csv",
        textwrap.dedent("""\
            customer,soc2_compliant,gdpr_compliant,last_audit
            Acme Corp,Yes,Yes,2024-06-15
            Globex Inc,Yes,No,2024-03-01
            Delta Ltd,Yes,Yes,2024-09-10
        """),
    )

    return data_room


def _create_deal_config(data_room: Path) -> Path:
    """Write a valid deal-config.json referencing *data_room*."""
    config = {
        "config_version": "1.0.0",
        "buyer": {
            "name": "Buyer Holdings LLC",
            "industry": "Technology",
        },
        "target": {
            "name": "TargetCo SaaS Inc",
            "industry": "SaaS",
            "subsidiaries": [],
        },
        "deal": {
            "type": "acquisition",
            "focus_areas": [
                "contract_analysis",
                "revenue_verification",
                "compliance_review",
            ],
        },
        "data_room": {
            "path": str(data_room),
        },
        "execution": {
            "execution_mode": "full",
            "max_retries": 1,
            "parallel_agents": 4,
        },
        "judge": {
            "enabled": False,
            "threshold": 70,
        },
        "entity_aliases": {
            "canonical_to_variants": {
                "Acme Corp": ["Acme Corporation", "ACME"],
                "Globex Inc": ["Globex", "Globex Incorporated"],
            },
        },
        "reporting": {
            "include_diff_sheet": False,
            "include_metadata_sheet": False,
        },
    }

    config_path = data_room / "deal-config.json"
    config_path.write_text(json.dumps(config, indent=2))
    return config_path


def _write_file(path: Path, content: str) -> None:
    """Write a file, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _run_pipeline_through_step(
    data_room: Path,
    config_path: Path,
    stop_after_step: int,
) -> PipelineState:
    """Run the pipeline, stopping after step *stop_after_step*.

    We achieve this by running the full pipeline but catching the
    agent-team step which would require an API key.
    """
    engine = PipelineEngine(
        project_dir=data_room,
        deal_config_path=config_path,
        max_retries=0,
    )

    # Run the pipeline -- it will proceed through the pre-agent steps.
    # We modify the engine to stop after the target step by intercepting
    # the run method.

    async def limited_run(**kwargs):  # noqa: ANN003
        """Execute only up to stop_after_step."""
        state = engine.state
        ordered_steps = list(PipelineStep)

        for step_enum in ordered_steps:
            step_num = step_enum.step_number
            if step_num > stop_after_step:
                break

            step_fn = engine._step_registry[step_enum]
            state.current_step = step_enum

            state = await step_fn(state)
            state.completed_steps.append(step_enum)

        engine.state = state
        return state

    return await limited_run()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPipelineInitialization:
    """Test pipeline engine creation and configuration."""

    def test_engine_creation(self, tmp_path: Path) -> None:
        """Engine initializes with correct defaults."""
        data_room = _create_data_room(tmp_path)
        config_path = _create_deal_config(data_room)

        engine = PipelineEngine(
            project_dir=data_room,
            deal_config_path=config_path,
        )

        assert engine.project_dir == data_room.resolve()
        assert engine.deal_config_path == config_path.resolve()
        assert engine.max_retries == 1
        assert engine.TOTAL_STEPS == 35
        assert len(engine._step_registry) == 35

    def test_all_steps_registered(self, tmp_path: Path) -> None:
        """Every PipelineStep has a registered handler."""
        data_room = _create_data_room(tmp_path)
        config_path = _create_deal_config(data_room)

        engine = PipelineEngine(
            project_dir=data_room,
            deal_config_path=config_path,
        )

        for step in PipelineStep:
            assert step in engine._step_registry, f"Missing handler for {step}"


class TestConfigValidation:
    """Test step 1: config validation."""

    def test_valid_config(self, tmp_path: Path) -> None:
        """Valid config loads and populates state."""
        data_room = _create_data_room(tmp_path)
        config_path = _create_deal_config(data_room)

        async def run():
            return await _run_pipeline_through_step(data_room, config_path, 1)

        state = asyncio.run(run())
        assert state.deal_config is not None
        assert state.deal_config["buyer"]["name"] == "Buyer Holdings LLC"
        assert state.execution_mode == "full"
        assert state.judge_enabled is False
        assert state.config_hash != ""

    def test_missing_config_raises(self, tmp_path: Path) -> None:
        """Missing config raises BlockingGateError."""
        from dd_agents.orchestrator.engine import BlockingGateError

        data_room = _create_data_room(tmp_path)
        config_path = data_room / "nonexistent.json"

        engine = PipelineEngine(
            project_dir=data_room,
            deal_config_path=config_path,
        )

        async def run():
            state = engine.state
            return await engine._step_01_validate_config(state)

        with pytest.raises(BlockingGateError, match="not found"):
            asyncio.run(run())


class TestPersistenceSetup:
    """Test step 2: persistence initialization."""

    def test_creates_run_directory(self, tmp_path: Path) -> None:
        """Step 2 creates the run directory and sets run_id."""
        data_room = _create_data_room(tmp_path)
        config_path = _create_deal_config(data_room)

        async def run():
            return await _run_pipeline_through_step(data_room, config_path, 2)

        state = asyncio.run(run())
        assert state.run_id != ""
        assert state.run_dir != Path()


class TestFileDiscovery:
    """Test step 4: file discovery."""

    def test_discovers_all_files(self, tmp_path: Path) -> None:
        """Step 4 discovers all files in the data room."""
        data_room = _create_data_room(tmp_path)
        config_path = _create_deal_config(data_room)

        async def run():
            return await _run_pipeline_through_step(data_room, config_path, 4)

        state = asyncio.run(run())

        # 13 customer files + 2 reference files + 1 deal-config = 16
        # (deal-config.json is in the root, so it's a reference file too)
        assert state.total_files >= 14  # At least the files we created

        # Check inventory outputs exist
        inv_dir = data_room / "_dd" / "forensic-dd" / "inventory"
        assert (inv_dir / "tree.txt").exists()
        assert (inv_dir / "files.txt").exists()

    def test_tree_file_content(self, tmp_path: Path) -> None:
        """tree.txt contains expected directory structure."""
        data_room = _create_data_room(tmp_path)
        config_path = _create_deal_config(data_room)

        async def run():
            return await _run_pipeline_through_step(data_room, config_path, 4)

        asyncio.run(run())

        inv_dir = data_room / "_dd" / "forensic-dd" / "inventory"
        tree_content = (inv_dir / "tree.txt").read_text()
        assert "GroupA" in tree_content
        assert "GroupB" in tree_content


class TestExtraction:
    """Test step 5: text extraction."""

    def test_extracts_text_files(self, tmp_path: Path) -> None:
        """Step 5 extracts text from simple text files."""
        data_room = _create_data_room(tmp_path)
        config_path = _create_deal_config(data_room)

        async def run():
            return await _run_pipeline_through_step(data_room, config_path, 5)

        asyncio.run(run())

        # Text dir should exist with extracted files
        text_dir = data_room / "_dd" / "forensic-dd" / "index" / "text"
        assert text_dir.exists()

        # At least some .md files should be generated
        md_files = list(text_dir.glob("*.md"))
        assert len(md_files) > 0, "No extracted text files found"


class TestInventoryBuilding:
    """Test step 6: build inventory."""

    def test_builds_customer_registry(self, tmp_path: Path) -> None:
        """Step 6 builds the customer registry with correct counts."""
        data_room = _create_data_room(tmp_path)
        config_path = _create_deal_config(data_room)

        async def run():
            return await _run_pipeline_through_step(data_room, config_path, 6)

        state = asyncio.run(run())

        assert state.total_customers == 6  # 3 in GroupA + 3 in GroupB
        assert len(state.customer_safe_names) == 6

        # Check inventory files exist
        inv_dir = data_room / "_dd" / "forensic-dd" / "inventory"
        assert (inv_dir / "customers.csv").exists()
        assert (inv_dir / "counts.json").exists()

    def test_counts_json_content(self, tmp_path: Path) -> None:
        """counts.json has correct aggregate values."""
        data_room = _create_data_room(tmp_path)
        config_path = _create_deal_config(data_room)

        async def run():
            return await _run_pipeline_through_step(data_room, config_path, 6)

        asyncio.run(run())

        inv_dir = data_room / "_dd" / "forensic-dd" / "inventory"
        counts = json.loads((inv_dir / "counts.json").read_text())

        assert counts["total_customers"] == 6
        assert counts["total_files"] >= 14
        assert counts["total_reference_files"] >= 2
        assert "GroupA" in counts["customers_by_group"]
        assert "GroupB" in counts["customers_by_group"]
        assert counts["customers_by_group"]["GroupA"] == 3
        assert counts["customers_by_group"]["GroupB"] == 3


class TestEntityResolution:
    """Test step 7: entity resolution."""

    def test_entity_resolution_initializes(self, tmp_path: Path) -> None:
        """Step 7 initializes the entity resolver without errors."""
        data_room = _create_data_room(tmp_path)
        config_path = _create_deal_config(data_room)

        async def run():
            return await _run_pipeline_through_step(data_room, config_path, 7)

        asyncio.run(run())

        # Entity matches file should exist
        inv_dir = data_room / "_dd" / "forensic-dd" / "inventory"
        assert (inv_dir / "entity_matches.json").exists()


class TestReferenceRegistry:
    """Test step 8: reference file classification."""

    def test_classifies_reference_files(self, tmp_path: Path) -> None:
        """Step 8 classifies reference files correctly."""
        data_room = _create_data_room(tmp_path)
        config_path = _create_deal_config(data_room)

        async def run():
            return await _run_pipeline_through_step(data_room, config_path, 8)

        state = asyncio.run(run())
        assert state.reference_file_count >= 2

        inv_dir = data_room / "_dd" / "forensic-dd" / "inventory"
        assert (inv_dir / "reference_files.json").exists()

        ref_files = json.loads((inv_dir / "reference_files.json").read_text())
        assert len(ref_files) >= 2

        # Check that each reference file has an assigned agent
        for rf in ref_files:
            assert len(rf["assigned_to_agents"]) >= 1


class TestCustomerMentions:
    """Test step 9: customer mention building."""

    def test_builds_mention_index(self, tmp_path: Path) -> None:
        """Step 9 builds the customer mention index."""
        data_room = _create_data_room(tmp_path)
        config_path = _create_deal_config(data_room)

        async def run():
            return await _run_pipeline_through_step(data_room, config_path, 9)

        asyncio.run(run())

        inv_dir = data_room / "_dd" / "forensic-dd" / "inventory"
        assert (inv_dir / "customer_mentions.json").exists()


class TestInventoryIntegrity:
    """Test step 10: inventory integrity verification."""

    def test_integrity_check_runs(self, tmp_path: Path) -> None:
        """Step 10 runs integrity checks without crashing."""
        data_room = _create_data_room(tmp_path)
        config_path = _create_deal_config(data_room)

        async def run():
            return await _run_pipeline_through_step(data_room, config_path, 10)

        # Should not raise
        state = asyncio.run(run())
        assert PipelineStep.INVENTORY_INTEGRITY in state.completed_steps


class TestFullPreAgentPipeline:
    """Test the full pipeline through step 11 (pre-agent)."""

    def test_runs_through_step_11(self, tmp_path: Path) -> None:
        """The entire pre-agent pipeline runs without errors."""
        data_room = _create_data_room(tmp_path)
        config_path = _create_deal_config(data_room)

        async def run():
            return await _run_pipeline_through_step(data_room, config_path, 11)

        state = asyncio.run(run())

        # All pre-agent steps should have completed
        completed_nums = {s.step_number for s in state.completed_steps}
        for step_num in range(1, 12):
            assert step_num in completed_nums, f"Step {step_num} not in completed steps"

    def test_pipeline_directory_structure(self, tmp_path: Path) -> None:
        """Pipeline creates the expected directory structure."""
        data_room = _create_data_room(tmp_path)
        config_path = _create_deal_config(data_room)

        async def run():
            return await _run_pipeline_through_step(data_room, config_path, 6)

        asyncio.run(run())

        # Check expected directories exist
        dd_dir = data_room / "_dd" / "forensic-dd"
        assert dd_dir.exists()

        inv_dir = dd_dir / "inventory"
        assert inv_dir.exists()

        text_dir = dd_dir / "index" / "text"
        assert text_dir.exists()

    def test_conditional_step_skipped(self, tmp_path: Path) -> None:
        """Steps 11 and 12 are correctly skipped when conditions are not met."""
        data_room = _create_data_room(tmp_path)
        config_path = _create_deal_config(data_room)

        async def run():
            return await _run_pipeline_through_step(data_room, config_path, 12)

        state = asyncio.run(run())

        # Step 11 should complete (but do nothing -- no customer_database)
        assert PipelineStep.CONTRACT_DATE_RECONCILIATION in state.completed_steps

        # Step 12 should complete (but do nothing -- not incremental mode)
        assert PipelineStep.INCREMENTAL_CLASSIFICATION in state.completed_steps
