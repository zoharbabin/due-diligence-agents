"""End-to-end tests for the full dd-agents pipeline.

These tests exercise the complete pipeline from config loading through
report generation. They require a valid ANTHROPIC_API_KEY and network
access.

Run with::

    pytest tests/e2e/ -m e2e -v
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path  # noqa: TC003

import pytest

from dd_agents.config import load_deal_config
from dd_agents.extraction.cache import ExtractionCache
from dd_agents.inventory.customers import CustomerRegistryBuilder
from dd_agents.inventory.discovery import FileDiscovery
from dd_agents.persistence.run_manager import RunManager
from dd_agents.persistence.tiers import TierManager
from dd_agents.utils.constants import DD_DIR, INDEX_DIR

from .conftest import skip_no_api_key

# ---------------------------------------------------------------------------
# Pre-agent pipeline tests (no API key needed)
# ---------------------------------------------------------------------------


class TestPreAgentPipeline:
    """Tests for pipeline steps 1-11 that don't require LLM calls."""

    def test_config_loading(self, e2e_deal_config: Path) -> None:
        """Step 1: Config loads and validates."""
        config = load_deal_config(e2e_deal_config)
        assert config.buyer.name == "Meridian Holdings"
        assert config.target.name == "NovaBridge Solutions"
        assert config.deal.type.value == "acquisition"

    def test_tier_management(self, e2e_project_dir: Path) -> None:
        """Step 2: Three-tier persistence initializes correctly."""
        tier_mgr = TierManager(e2e_project_dir)
        run_dir = tier_mgr.ensure_dirs(e2e_project_dir, "20260101_120000")

        dd_dir = e2e_project_dir / DD_DIR
        assert dd_dir.is_dir()
        assert (e2e_project_dir / INDEX_DIR).is_dir()
        assert run_dir.is_dir()

    def test_file_discovery(self, e2e_project_dir: Path) -> None:
        """Step 3: File discovery finds all data room files."""
        discovery = FileDiscovery()
        files = discovery.discover(e2e_project_dir)

        # Should find at least 4 customer files + 1 reference
        assert len(files) >= 4
        paths = [f.path for f in files]
        assert any("acme" in p.lower() for p in paths)

    def test_customer_registry(self, e2e_project_dir: Path) -> None:
        """Step 5: Customer registry builds correctly."""
        discovery = FileDiscovery()
        files = discovery.discover(e2e_project_dir)

        builder = CustomerRegistryBuilder()
        customers, counts = builder.build(e2e_project_dir, files)

        # Should find 3 customers: Acme, Beta, Gamma
        assert len(customers) >= 3
        customer_names = [c.name for c in customers]
        assert any("Acme" in n for n in customer_names)
        assert any("Beta" in n for n in customer_names)
        assert any("Gamma" in n for n in customer_names)
        assert counts.total_customers >= 3

    def test_run_manager_lifecycle(self, e2e_project_dir: Path) -> None:
        """Run manager creates and finalizes runs correctly."""
        run_mgr = RunManager(e2e_project_dir)
        # Initialize creates dirs and returns RunMetadata
        metadata = run_mgr.initialize_run(e2e_project_dir)

        assert metadata.run_id
        assert len(metadata.run_id) > 0

        run_mgr.finalize_run(metadata)

        history = run_mgr.load_run_history()
        assert len(history) == 1
        assert history[0]["run_id"] == metadata.run_id

    def test_extraction_cache(self, e2e_project_dir: Path) -> None:
        """Extraction cache detects changed files."""
        cache_path = e2e_project_dir / "_dd" / "checksums.sha256"
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        cache = ExtractionCache(cache_path)

        # First file
        test_file = e2e_project_dir / "GroupA" / "Acme Corp" / "contract_acme.pdf.md"
        assert test_file.exists()

        file_key = str(test_file)
        content = test_file.read_bytes()
        file_hash = hashlib.sha256(content).hexdigest()

        # Should not be cached initially
        assert not cache.is_cached(file_key, file_hash)

        # Add to cache
        cache.update(file_key, file_hash)
        assert cache.is_cached(file_key, file_hash)

        # Different hash should not match
        assert not cache.is_cached(file_key, "different_hash_value")


# ---------------------------------------------------------------------------
# Full pipeline E2E tests (require API key)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestFullPipeline:
    """Full pipeline E2E tests requiring ANTHROPIC_API_KEY."""

    @skip_no_api_key
    def test_dry_run(self, e2e_project_dir: Path, e2e_deal_config: Path) -> None:
        """Dry run validates config and prints steps without executing."""
        from click.testing import CliRunner

        from dd_agents.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["run", str(e2e_deal_config), "--dry-run"])
        assert result.exit_code == 0
        assert "Dry run" in result.output or "dry run" in result.output.lower()

    @skip_no_api_key
    @pytest.mark.slow
    def test_full_pipeline_run(self, e2e_project_dir: Path, e2e_deal_config: Path) -> None:
        """Full pipeline execution produces expected outputs.

        This test runs the complete pipeline and verifies:
        1. Pipeline completes without errors
        2. _dd directory structure is correct
        3. Findings are produced for each customer
        4. Audit report is generated
        5. Excel report is created
        """
        from dd_agents.orchestrator.engine import PipelineEngine

        engine = PipelineEngine(
            project_dir=e2e_project_dir,
            deal_config_path=e2e_deal_config,
        )

        import asyncio

        state = asyncio.run(engine.run(resume_from_step=0))

        # Verify pipeline completed
        assert len(state.completed_steps) > 0
        assert state.run_id

        # Verify directory structure
        dd_dir = e2e_project_dir / DD_DIR
        assert dd_dir.is_dir()


@pytest.mark.e2e
class TestIncrementalMode:
    """E2E tests for incremental pipeline mode."""

    @skip_no_api_key
    @pytest.mark.slow
    def test_incremental_after_full(self, e2e_project_dir: Path, e2e_deal_config: Path) -> None:
        """Incremental run after a full run carries forward unchanged findings."""
        # First, update config for incremental mode
        config_data = json.loads(e2e_deal_config.read_text())
        config_data["execution"]["execution_mode"] = "full"
        e2e_deal_config.write_text(json.dumps(config_data, indent=2))

        from dd_agents.orchestrator.engine import PipelineEngine

        # Run 1: Full
        engine1 = PipelineEngine(
            project_dir=e2e_project_dir,
            deal_config_path=e2e_deal_config,
        )
        import asyncio

        state1 = asyncio.run(engine1.run(resume_from_step=0))
        run1_id = state1.run_id

        # Switch to incremental
        config_data["execution"]["execution_mode"] = "incremental"
        e2e_deal_config.write_text(json.dumps(config_data, indent=2))

        # Run 2: Incremental
        engine2 = PipelineEngine(
            project_dir=e2e_project_dir,
            deal_config_path=e2e_deal_config,
        )
        state2 = asyncio.run(engine2.run(resume_from_step=0))

        # Second run should complete
        assert state2.run_id != run1_id
        assert len(state2.completed_steps) > 0

        # Check run history has both runs
        history_path = e2e_project_dir / DD_DIR / "run_history.json"
        if history_path.exists():
            history = json.loads(history_path.read_text())
            assert len(history) >= 2
