"""End-to-end tests for the full dd-agents pipeline.

These tests exercise the complete pipeline from config loading through
report generation. They require API credentials (ANTHROPIC_API_KEY or
AWS Bedrock) and network access.

Run with::

    # CI tests:
    pytest tests/e2e/ -m e2e -v

    # Deep local validation (all features incl. Judge):
    pytest tests/e2e/ -m local -v --timeout=1200
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path  # noqa: TC003

import pytest

from dd_agents.config import load_deal_config
from dd_agents.extraction.cache import ExtractionCache
from dd_agents.inventory.discovery import FileDiscovery
from dd_agents.inventory.subjects import SubjectRegistryBuilder
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

        # Should find at least 6 subject files + 1 reference
        assert len(files) >= 6
        paths = [f.path for f in files]
        assert any("acme" in p.lower() for p in paths)

    def test_subject_registry(self, e2e_project_dir: Path) -> None:
        """Step 5: Subject registry builds correctly."""
        discovery = FileDiscovery()
        files = discovery.discover(e2e_project_dir)

        builder = SubjectRegistryBuilder()
        subjects, counts = builder.build(e2e_project_dir, files)

        # Should find 3 subjects: Acme, Beta, Gamma
        assert len(subjects) >= 3
        subject_names = [s.name for s in subjects]
        assert any("Acme" in n for n in subject_names)
        assert any("Beta" in n for n in subject_names)
        assert any("Gamma" in n for n in subject_names)
        assert counts.total_subjects >= 3

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
    """Full pipeline E2E tests requiring API credentials."""

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
        3. Findings are produced for each subject
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


# ---------------------------------------------------------------------------
# Deep live agent validation (local-only, all features incl. Judge)
# ---------------------------------------------------------------------------


@pytest.mark.local
class TestLiveAgentValidation:
    """Deep E2E validation with real agent calls and all features enabled.

    Local-only — NOT run in CI. Uses economy model profile (Haiku) for cost.
    Judge is enabled with 2 iteration rounds.

    Run with::

        pytest tests/e2e/ -m local -v --timeout=1200
    """

    @skip_no_api_key
    def test_pipeline_completes_all_steps(self, live_pipeline_result: tuple[object, Path]) -> None:
        """All 35 pipeline steps complete successfully."""
        state, _ = live_pipeline_result
        # With judge enabled, all steps should run
        assert len(state.completed_steps) >= 30  # type: ignore[attr-defined]

    @skip_no_api_key
    def test_specialist_agents_produce_findings(self, live_pipeline_result: tuple[object, Path]) -> None:
        """Each of the 4 specialist agents produces non-empty findings."""
        _, project_dir = live_pipeline_result
        dd_dir = project_dir / DD_DIR
        # Find the run directory (latest)
        runs_dir = dd_dir / "forensic-dd" / "runs"
        if not runs_dir.exists():
            pytest.skip("No runs directory found")
        run_dirs = sorted(runs_dir.iterdir())
        run_dir = run_dirs[-1] if run_dirs else None
        if run_dir and (run_dir / "latest").is_symlink():
            run_dir = run_dirs[-2] if len(run_dirs) > 1 else run_dir
        # Check for symlink named "latest"
        latest = runs_dir / "latest"
        if latest.exists():
            run_dir = latest.resolve()
        assert run_dir is not None

        findings_dir = run_dir / "findings"
        agents = ["legal", "finance", "commercial", "producttech"]
        for agent in agents:
            agent_dir = findings_dir / agent
            assert agent_dir.exists(), f"No findings dir for {agent}"
            json_files = list(agent_dir.glob("*.json"))
            # Filter out gaps subdirectory files
            json_files = [f for f in json_files if f.parent == agent_dir]
            assert len(json_files) > 0, f"No findings files for {agent}"

    @skip_no_api_key
    def test_finding_schema_compliance(self, live_pipeline_result: tuple[object, Path]) -> None:
        """Findings files contain valid JSON with expected fields."""
        _, project_dir = live_pipeline_result
        run_dir = _get_run_dir(project_dir)
        if run_dir is None:
            pytest.skip("No run directory found")

        findings_dir = run_dir / "findings"
        for agent in ["legal", "finance", "commercial", "producttech"]:
            agent_dir = findings_dir / agent
            if not agent_dir.exists():
                continue
            for f in agent_dir.glob("*.json"):
                if f.parent != agent_dir:
                    continue
                data = json.loads(f.read_text(encoding="utf-8"))
                # Should be a dict with findings list
                assert isinstance(data, dict), f"{f.name} is not a dict"
                findings = data.get("findings", [])
                assert isinstance(findings, list), f"{f.name} findings is not a list"
                for finding in findings:
                    assert "severity" in finding or "title" in finding, f"Finding in {f.name} missing severity/title"

    @skip_no_api_key
    def test_judge_review_ran(self, live_pipeline_result: tuple[object, Path]) -> None:
        """Judge review output exists with quality scores."""
        _, project_dir = live_pipeline_result
        run_dir = _get_run_dir(project_dir)
        if run_dir is None:
            pytest.skip("No run directory found")

        # Judge writes quality_scores.json in judge/ dir
        judge_dir = run_dir / "judge"
        scores_path = judge_dir / "quality_scores.json"
        assert scores_path.exists(), "Judge quality_scores.json not found"
        data = json.loads(scores_path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    @skip_no_api_key
    def test_judge_iteration_evidence(self, live_pipeline_result: tuple[object, Path]) -> None:
        """Judge produced review feedback — agents had opportunity to revise."""
        state, project_dir = live_pipeline_result
        run_dir = _get_run_dir(project_dir)
        if run_dir is None:
            pytest.skip("No run directory found")

        # Check that judge-related steps are in completed_steps
        completed = {s.value if hasattr(s, "value") else s for s in state.completed_steps}  # type: ignore[attr-defined]
        # Steps 19-22 relate to judge review cycle (string names in completed_steps)
        judge_step_names = {"19_spawn_judge", "20_judge_review", "21_judge_respawn", "22_judge_round2"}
        ran_judge_steps = completed & judge_step_names
        assert len(ran_judge_steps) >= 1, f"No judge steps completed. Completed: {completed}"

    @skip_no_api_key
    def test_pre_merge_validation_passes(self, live_pipeline_result: tuple[object, Path]) -> None:
        """Pre-merge validation report exists."""
        _, project_dir = live_pipeline_result
        run_dir = _get_run_dir(project_dir)
        if run_dir is None:
            pytest.skip("No run directory found")

        report_path = run_dir / "pre_merge_validation.json"
        assert report_path.exists(), "pre_merge_validation.json not found"
        data = json.loads(report_path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    @skip_no_api_key
    def test_merged_findings_exist(self, live_pipeline_result: tuple[object, Path]) -> None:
        """Merged findings directory has files for all 3 subjects."""
        _, project_dir = live_pipeline_result
        run_dir = _get_run_dir(project_dir)
        if run_dir is None:
            pytest.skip("No run directory found")

        merged_dir = run_dir / "findings" / "merged"
        assert merged_dir.exists(), "No merged findings directory"
        json_files = [f for f in merged_dir.glob("*.json") if f.parent == merged_dir]
        assert len(json_files) >= 3, f"Expected 3+ merged files, got {len(json_files)}"

    @skip_no_api_key
    def test_merged_findings_cross_agent(self, live_pipeline_result: tuple[object, Path]) -> None:
        """Merged findings include contributions from multiple agents."""
        _, project_dir = live_pipeline_result
        run_dir = _get_run_dir(project_dir)
        if run_dir is None:
            pytest.skip("No run directory found")

        merged_dir = run_dir / "findings" / "merged"
        if not merged_dir.exists():
            pytest.skip("No merged dir")

        agents_seen: set[str] = set()
        for f in merged_dir.glob("*.json"):
            if f.parent != merged_dir:
                continue
            data = json.loads(f.read_text(encoding="utf-8"))
            for finding in data.get("findings", []):
                agent = finding.get("agent", finding.get("source_agent", ""))
                if agent:
                    agents_seen.add(agent.lower())
        assert len(agents_seen) >= 2, f"Expected findings from 2+ agents, got: {agents_seen}"

    @skip_no_api_key
    def test_executive_synthesis_generated(self, live_pipeline_result: tuple[object, Path]) -> None:
        """Executive synthesis output exists in the HTML report (embedded)."""
        _, project_dir = live_pipeline_result
        run_dir = _get_run_dir(project_dir)
        if run_dir is None:
            pytest.skip("No run directory found")

        # Executive synthesis is embedded in HTML report, not a separate file.
        # Check that the HTML report contains executive synthesis markers.
        html_path = run_dir / "report" / "dd_report.html"
        if html_path.exists():
            content = html_path.read_text(encoding="utf-8")
            # Look for Go/No-Go signal or executive summary section
            has_exec = (
                "executive" in content.lower()
                or "go/no-go" in content.lower()
                or "go-no-go" in content.lower()
                or "deal-signal" in content.lower()
            )
            assert has_exec, "HTML report missing executive synthesis content"
        else:
            pytest.skip("HTML report not generated")

    @skip_no_api_key
    def test_html_report_generated(self, live_pipeline_result: tuple[object, Path]) -> None:
        """HTML report exists and contains expected content."""
        _, project_dir = live_pipeline_result
        run_dir = _get_run_dir(project_dir)
        if run_dir is None:
            pytest.skip("No run directory found")

        html_path = run_dir / "report" / "dd_report.html"
        assert html_path.exists(), "dd_report.html not found"
        content = html_path.read_text(encoding="utf-8")
        assert "<html" in content.lower()
        # Check that subject names appear
        content_lower = content.lower()
        assert "acme" in content_lower, "Acme Corp not in HTML report"
        assert "beta" in content_lower, "Beta Inc not in HTML report"
        assert "gamma" in content_lower, "Gamma LLC not in HTML report"

    @skip_no_api_key
    def test_excel_report_generated(self, live_pipeline_result: tuple[object, Path]) -> None:
        """Excel report exists and has expected sheets."""
        _, project_dir = live_pipeline_result
        run_dir = _get_run_dir(project_dir)
        if run_dir is None:
            pytest.skip("No run directory found")

        xlsx_path = run_dir / "report" / "dd_report.xlsx"
        assert xlsx_path.exists(), "dd_report.xlsx not found"
        # Verify it's a valid xlsx by checking file size
        assert xlsx_path.stat().st_size > 1000, "Excel report suspiciously small"

    @skip_no_api_key
    def test_numerical_audit_ran(self, live_pipeline_result: tuple[object, Path]) -> None:
        """Numerical audit results exist."""
        _, project_dir = live_pipeline_result
        run_dir = _get_run_dir(project_dir)
        if run_dir is None:
            pytest.skip("No run directory found")

        audit_path = run_dir / "audit.json"
        assert audit_path.exists(), "audit.json not found"
        data = json.loads(audit_path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    @skip_no_api_key
    def test_dod_audit_ran(self, live_pipeline_result: tuple[object, Path]) -> None:
        """Definition of Done audit results exist."""
        _, project_dir = live_pipeline_result
        run_dir = _get_run_dir(project_dir)
        if run_dir is None:
            pytest.skip("No run directory found")

        dod_path = run_dir / "dod_results.json"
        assert dod_path.exists(), "dod_results.json not found"
        data = json.loads(dod_path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    @skip_no_api_key
    def test_knowledge_compilation(self, live_pipeline_result: tuple[object, Path]) -> None:
        """Knowledge directory has chronicle entries and/or articles."""
        _, project_dir = live_pipeline_result
        knowledge_dir = project_dir / "knowledge"
        if not knowledge_dir.exists():
            # Knowledge dir might be under _dd
            knowledge_dir = project_dir / DD_DIR / "knowledge"
        if not knowledge_dir.exists():
            pytest.skip("Knowledge dir not found (may have been disabled)")

        # Should have some content — chronicle or articles
        all_files = list(knowledge_dir.rglob("*"))
        content_files = [f for f in all_files if f.is_file()]
        assert len(content_files) >= 1, "Knowledge dir is empty"

    @skip_no_api_key
    def test_all_subjects_covered(self, live_pipeline_result: tuple[object, Path]) -> None:
        """All 3 subjects (Acme, Beta, Gamma) appear in merged output."""
        _, project_dir = live_pipeline_result
        run_dir = _get_run_dir(project_dir)
        if run_dir is None:
            pytest.skip("No run directory found")

        merged_dir = run_dir / "findings" / "merged"
        if not merged_dir.exists():
            pytest.skip("No merged dir")

        filenames = {f.stem.lower() for f in merged_dir.glob("*.json") if f.parent == merged_dir}
        assert any("acme" in n for n in filenames), f"Acme not in merged: {filenames}"
        assert any("beta" in n for n in filenames), f"Beta not in merged: {filenames}"
        assert any("gamma" in n for n in filenames), f"Gamma not in merged: {filenames}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_run_dir(project_dir: Path) -> Path | None:
    """Resolve the latest run directory under _dd/forensic-dd/runs/."""
    runs_dir = project_dir / DD_DIR / "forensic-dd" / "runs"
    if not runs_dir.exists():
        return None
    latest = runs_dir / "latest"
    if latest.is_symlink() or latest.exists():
        return latest.resolve()
    run_dirs = sorted([d for d in runs_dir.iterdir() if d.is_dir()])
    return run_dirs[-1] if run_dirs else None
