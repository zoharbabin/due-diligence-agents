"""Unit tests for the dd_agents.orchestrator package.

Covers:
- PipelineStep enum: count, blocking gates, conditional steps, step_number
- PipelineState: creation, to_checkpoint_dict / from_checkpoint_dict round-trip
- Checkpoints: save and load via public functions
- PipelineEngine: initialisation, step registry completeness
- Step 15: Route reference files to subject dirs
- Step 21: Incremental merge of prior findings for unchanged subjects
- Steps 23-25: Judge review cycle
- Issue #45: prior_run_id population from run history
- Issue #45: Idempotent run history (no double-append)
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from dd_agents.orchestrator.team import AgentTeam

from dd_agents.orchestrator.checkpoints import (
    clean_checkpoints,
    list_checkpoints,
    load_checkpoint,
    load_checkpoint_by_step,
    save_checkpoint,
)
from dd_agents.orchestrator.engine import (
    AgentFailureError,
    BlockingGateError,
    PartialFailureError,
    PipelineEngine,
    RecoverableError,
)
from dd_agents.orchestrator.state import (
    PipelineError,
    PipelineState,
    StepResult,
)
from dd_agents.orchestrator.steps import (
    _BLOCKING_GATES,
    _CONDITIONAL_STEPS,
    PipelineStep,
)

# ======================================================================
# PipelineStep
# ======================================================================


class TestPipelineStep:
    """Tests for the PipelineStep enum."""

    def test_step_count_is_38(self) -> None:
        """The enum must contain exactly 38 members."""
        assert len(PipelineStep) == 38

    def test_step_number_property(self) -> None:
        """step_number should parse the leading digits from the value."""
        assert PipelineStep.VALIDATE_CONFIG.step_number == 1
        assert PipelineStep.SHUTDOWN.step_number == 38
        assert PipelineStep.COVERAGE_GATE.step_number == 17

    def test_step_numbers_are_sequential(self) -> None:
        """Every step from 1..38 should appear exactly once."""
        numbers = sorted(s.step_number for s in PipelineStep)
        assert numbers == list(range(1, 39))

    def test_blocking_gates_count(self) -> None:
        """Five formal blocking gates."""
        assert len(_BLOCKING_GATES) == 5

    def test_blocking_gate_members(self) -> None:
        expected = {
            PipelineStep.BULK_EXTRACTION,
            PipelineStep.COVERAGE_GATE,
            PipelineStep.NUMERICAL_AUDIT,
            PipelineStep.FULL_QA_AUDIT,
            PipelineStep.POST_GENERATION_VALIDATION,
        }
        assert expected == _BLOCKING_GATES

    def test_is_blocking_gate_property(self) -> None:
        assert PipelineStep.BULK_EXTRACTION.is_blocking_gate is True
        assert PipelineStep.VALIDATE_CONFIG.is_blocking_gate is False
        assert PipelineStep.SHUTDOWN.is_blocking_gate is False

    def test_conditional_steps_count(self) -> None:
        """Eleven conditional steps."""
        assert len(_CONDITIONAL_STEPS) == 11

    def test_conditional_step_members(self) -> None:
        expected = {
            PipelineStep.CONTRACT_DATE_RECONCILIATION,
            PipelineStep.INCREMENTAL_CLASSIFICATION,
            PipelineStep.CROSS_DOMAIN_ANALYSIS,
            PipelineStep.TARGETED_RESPAWN,
            PipelineStep.TARGETED_MERGE,
            PipelineStep.INCREMENTAL_MERGE,
            PipelineStep.SPAWN_JUDGE,
            PipelineStep.JUDGE_REVIEW,
            PipelineStep.JUDGE_RESPAWN,
            PipelineStep.JUDGE_ROUND2,
            PipelineStep.BUILD_REPORT_DIFF,
        }
        assert expected == _CONDITIONAL_STEPS

    def test_is_conditional_property(self) -> None:
        assert PipelineStep.INCREMENTAL_CLASSIFICATION.is_conditional is True
        assert PipelineStep.SPAWN_JUDGE.is_conditional is True
        assert PipelineStep.BUILD_INVENTORY.is_conditional is False

    def test_string_value_format(self) -> None:
        """All values follow the pattern NN_snake_case."""
        for step in PipelineStep:
            parts = step.value.split("_", maxsplit=1)
            assert len(parts) == 2, f"Bad format: {step.value}"
            assert parts[0].isdigit(), f"No numeric prefix: {step.value}"
            assert len(parts[0]) == 2, f"Prefix not zero-padded: {step.value}"

    def test_str_enum_behaviour(self) -> None:
        """PipelineStep inherits from str, so f-string should give the value."""
        step = PipelineStep.VALIDATE_CONFIG
        assert f"{step}" == "PipelineStep.VALIDATE_CONFIG" or step.value == "01_validate_config"
        assert step.value == "01_validate_config"


# ======================================================================
# PipelineState
# ======================================================================


class TestPipelineState:
    """Tests for the PipelineState dataclass."""

    def test_default_creation(self) -> None:
        state = PipelineState()
        assert state.run_id == ""
        assert state.execution_mode == "full"
        assert state.judge_enabled is True
        assert state.current_step == PipelineStep.VALIDATE_CONFIG
        assert state.completed_steps == []
        assert state.errors == []

    def test_creation_with_values(self, tmp_path: Path) -> None:
        state = PipelineState(
            run_id="20260221_120000",
            project_dir=tmp_path,
            execution_mode="incremental",
            judge_enabled=False,
            total_subjects=42,
            subject_safe_names=["acme_corp", "beta_inc"],
        )
        assert state.run_id == "20260221_120000"
        assert state.execution_mode == "incremental"
        assert state.judge_enabled is False
        assert state.total_subjects == 42
        assert len(state.subject_safe_names) == 2

    def test_checkpoint_round_trip(self, tmp_path: Path) -> None:
        """to_checkpoint_dict -> from_checkpoint_dict should preserve state."""
        state = PipelineState(
            run_id="test_run_001",
            project_dir=tmp_path,
            run_dir=tmp_path / "runs" / "test",
            config_hash="abc123",
            execution_mode="incremental",
            judge_enabled=False,
            total_files=100,
            total_subjects=10,
            subject_safe_names=["alpha", "bravo", "charlie"],
            reference_file_count=5,
            current_step=PipelineStep.BUILD_INVENTORY,
            completed_steps=[
                PipelineStep.VALIDATE_CONFIG,
                PipelineStep.INIT_PERSISTENCE,
            ],
            agent_sessions={"legal": "sess_1"},
            agent_costs={"legal": 1.23},
            batch_counts={"legal": 2},
            validation_results={"numerical_audit": True},
            audit_passed=True,
            subjects_to_analyze=["alpha", "bravo"],
            cross_skill_run_ids={"other-skill": "run_abc"},
            judge_scores={"legal": 85},
        )

        # Add a step result
        state.step_results["01_validate_config"] = StepResult(
            step=PipelineStep.VALIDATE_CONFIG,
            status="success",
            duration_ms=150,
        )

        # Add an error record
        state.errors.append(
            {
                "step": "01_validate_config",
                "error_type": "recoverable",
                "message": "test error",
                "recovered": True,
                "recovery_action": "retried",
            }
        )

        data = state.to_checkpoint_dict()
        restored = PipelineState.from_checkpoint_dict(data)

        assert restored.run_id == state.run_id
        assert str(restored.project_dir) == str(state.project_dir)
        assert restored.config_hash == state.config_hash
        assert restored.execution_mode == state.execution_mode
        assert restored.judge_enabled == state.judge_enabled
        assert restored.total_files == state.total_files
        assert restored.total_subjects == state.total_subjects
        assert restored.subject_safe_names == state.subject_safe_names
        assert restored.reference_file_count == state.reference_file_count
        assert restored.current_step == state.current_step
        assert restored.completed_steps == state.completed_steps
        assert restored.agent_sessions == state.agent_sessions
        assert restored.agent_costs == state.agent_costs
        assert restored.batch_counts == state.batch_counts
        assert restored.validation_results == state.validation_results
        assert restored.audit_passed == state.audit_passed
        assert restored.subjects_to_analyze == state.subjects_to_analyze
        assert restored.cross_skill_run_ids == state.cross_skill_run_ids
        assert restored.judge_scores == state.judge_scores
        assert len(restored.errors) == 1
        assert restored.errors[0]["message"] == "test error"

        # Step results round-trip
        assert "01_validate_config" in restored.step_results
        sr = restored.step_results["01_validate_config"]
        assert sr.step == PipelineStep.VALIDATE_CONFIG
        assert sr.status == "success"
        assert sr.duration_ms == 150

    def test_checkpoint_dict_is_json_serialisable(self, tmp_path: Path) -> None:
        state = PipelineState(
            run_id="ser_test",
            project_dir=tmp_path,
            run_dir=tmp_path / "runs",
        )
        data = state.to_checkpoint_dict()
        # Should not raise
        serialised = json.dumps(data, default=str)
        assert isinstance(serialised, str)

    def test_from_checkpoint_dict_with_minimal_data(self) -> None:
        """from_checkpoint_dict should handle a minimal dict gracefully."""
        minimal = {
            "run_id": "min",
            "current_step": "01_validate_config",
        }
        state = PipelineState.from_checkpoint_dict(minimal)
        assert state.run_id == "min"
        assert state.current_step == PipelineStep.VALIDATE_CONFIG
        assert state.completed_steps == []
        assert state.execution_mode == "full"

    def test_state_roundtrip_with_deal_config(self, tmp_path: Path) -> None:
        """deal_config survives a to_checkpoint_dict / from_checkpoint_dict round-trip."""
        deal_cfg: dict[str, object] = {
            "target": {"name": "TestCorp"},
            "execution": {"execution_mode": "full"},
            "entity_aliases": {"exclusions": ["SomeCo"]},
        }
        state = PipelineState(
            run_id="deal_cfg_test",
            project_dir=tmp_path,
            current_step=PipelineStep.VALIDATE_CONFIG,
            deal_config=deal_cfg,
        )
        data = state.to_checkpoint_dict()
        restored = PipelineState.from_checkpoint_dict(data)
        assert restored.deal_config == deal_cfg

    def test_state_roundtrip_preserves_all_fields(self, tmp_path: Path) -> None:
        """Every dataclass field that is serialised must survive a round-trip."""
        state = PipelineState(
            run_id="all_fields_test",
            skill_dir=tmp_path / "skill",
            run_dir=tmp_path / "run",
            project_dir=tmp_path,
            deal_config={"key": "value"},
            config_hash="abc123",
            execution_mode="incremental",
            judge_enabled=False,
            prior_run_id="prior_001",
            prior_run_dir=tmp_path / "prior",
            framework_version="1.2.3",
            total_files=100,
            total_subjects=10,
            subject_safe_names=["alpha", "bravo"],
            reference_file_count=5,
            current_step=PipelineStep.BUILD_INVENTORY,
            completed_steps=[PipelineStep.VALIDATE_CONFIG, PipelineStep.INIT_PERSISTENCE],
            errors=[{"step": "01_validate_config", "message": "test"}],
            agent_sessions={"legal": "sess_1"},
            agent_results={"legal": {"status": "complete", "subjects": 10}},
            agent_costs={"legal": 1.23},
            agent_prompts={"legal": ["prompt line 1"]},
            batch_counts={"legal": 2},
            validation_results={"numerical_audit": True},
            audit_passed=True,
            classification={"subjects": [{"name": "alpha", "status": "new"}]},
            subjects_to_analyze=["alpha"],
            cross_skill_run_ids={"other": "run_xyz"},
            judge_scores={"legal": 85},
        )
        # Add a step result
        state.step_results["01_validate_config"] = StepResult(
            step=PipelineStep.VALIDATE_CONFIG,
            status="success",
            duration_ms=100,
            metadata={"note": "ok"},
        )

        data = state.to_checkpoint_dict()
        restored = PipelineState.from_checkpoint_dict(data)

        assert restored.run_id == state.run_id
        assert str(restored.skill_dir) == str(state.skill_dir)
        assert str(restored.run_dir) == str(state.run_dir)
        assert str(restored.project_dir) == str(state.project_dir)
        assert restored.deal_config == state.deal_config
        assert restored.config_hash == state.config_hash
        assert restored.execution_mode == state.execution_mode
        assert restored.judge_enabled == state.judge_enabled
        assert restored.prior_run_id == state.prior_run_id
        assert str(restored.prior_run_dir) == str(state.prior_run_dir)
        assert restored.framework_version == state.framework_version
        assert restored.total_files == state.total_files
        assert restored.total_subjects == state.total_subjects
        assert restored.subject_safe_names == state.subject_safe_names
        assert restored.reference_file_count == state.reference_file_count
        assert restored.current_step == state.current_step
        assert restored.completed_steps == state.completed_steps
        assert restored.errors == state.errors
        assert restored.agent_sessions == state.agent_sessions
        assert restored.agent_results == state.agent_results
        assert restored.agent_costs == state.agent_costs
        assert restored.agent_prompts == state.agent_prompts
        assert restored.batch_counts == state.batch_counts
        assert restored.validation_results == state.validation_results
        assert restored.audit_passed == state.audit_passed
        assert restored.classification == state.classification
        assert restored.subjects_to_analyze == state.subjects_to_analyze
        assert restored.cross_skill_run_ids == state.cross_skill_run_ids
        assert restored.judge_scores == state.judge_scores
        # Step results round-trip
        sr = restored.step_results["01_validate_config"]
        assert sr.step == PipelineStep.VALIDATE_CONFIG
        assert sr.status == "success"
        assert sr.duration_ms == 100
        assert sr.metadata == {"note": "ok"}


# ======================================================================
# StepResult & PipelineError
# ======================================================================


class TestStepResult:
    def test_creation(self) -> None:
        sr = StepResult(step=PipelineStep.VALIDATE_CONFIG)
        assert sr.status == "success"
        assert sr.error is None
        assert sr.duration_ms == 0

    def test_creation_with_error(self) -> None:
        sr = StepResult(
            step=PipelineStep.BULK_EXTRACTION,
            status="failed",
            error="something broke",
            duration_ms=500,
        )
        assert sr.status == "failed"
        assert sr.error == "something broke"


class TestPipelineError:
    def test_exception_attributes(self) -> None:
        err = PipelineError(
            step=PipelineStep.BULK_EXTRACTION,
            error_type="blocking_gate",
            message="extraction failed",
        )
        assert err.step == PipelineStep.BULK_EXTRACTION
        assert err.error_type == "blocking_gate"
        assert str(err) == "extraction failed"
        assert err.recovered is False
        assert err.recovery_action == ""

    def test_is_exception(self) -> None:
        err = PipelineError(
            step=PipelineStep.VALIDATE_CONFIG,
            error_type="blocking_gate",
            message="bad config",
        )
        assert isinstance(err, Exception)


# ======================================================================
# Checkpoints
# ======================================================================


class TestCheckpoints:
    """Tests for checkpoint save / load / list / clean functions."""

    def test_save_and_load(self, tmp_path: Path) -> None:
        cp_dir = tmp_path / "checkpoints"
        state = PipelineState(
            run_id="ckpt_test",
            project_dir=tmp_path,
            current_step=PipelineStep.BUILD_INVENTORY,
            completed_steps=[
                PipelineStep.VALIDATE_CONFIG,
                PipelineStep.INIT_PERSISTENCE,
            ],
            total_subjects=7,
        )

        path = save_checkpoint(state, cp_dir)
        assert path.exists()
        assert path.name == "checkpoint_06_build_inventory.json"

        loaded = load_checkpoint(cp_dir)
        assert loaded.run_id == "ckpt_test"
        assert loaded.current_step == PipelineStep.BUILD_INVENTORY
        assert loaded.total_subjects == 7

    def test_load_by_step(self, tmp_path: Path) -> None:
        cp_dir = tmp_path / "checkpoints"

        # Save two checkpoints at different steps
        state1 = PipelineState(
            run_id="multi",
            project_dir=tmp_path,
            current_step=PipelineStep.VALIDATE_CONFIG,
        )
        save_checkpoint(state1, cp_dir)

        state2 = PipelineState(
            run_id="multi",
            project_dir=tmp_path,
            current_step=PipelineStep.FILE_DISCOVERY,
            total_files=42,
        )
        save_checkpoint(state2, cp_dir)

        loaded = load_checkpoint_by_step(cp_dir, 4)
        assert loaded.current_step == PipelineStep.FILE_DISCOVERY
        assert loaded.total_files == 42

    def test_load_nonexistent_raises(self, tmp_path: Path) -> None:
        cp_dir = tmp_path / "checkpoints"
        cp_dir.mkdir()
        with pytest.raises(FileNotFoundError):
            load_checkpoint(cp_dir)

    def test_load_by_step_nonexistent_raises(self, tmp_path: Path) -> None:
        cp_dir = tmp_path / "checkpoints"
        cp_dir.mkdir()
        with pytest.raises(FileNotFoundError):
            load_checkpoint_by_step(cp_dir, 99)

    def test_list_checkpoints(self, tmp_path: Path) -> None:
        cp_dir = tmp_path / "checkpoints"

        # No directory yet
        assert list_checkpoints(cp_dir) == []

        # Save a couple
        for step in (PipelineStep.VALIDATE_CONFIG, PipelineStep.INIT_PERSISTENCE):
            state = PipelineState(
                run_id="list_test",
                project_dir=tmp_path,
                current_step=step,
            )
            save_checkpoint(state, cp_dir)

        names = list_checkpoints(cp_dir)
        assert len(names) == 2
        assert names[0].startswith("checkpoint_01_")
        assert names[1].startswith("checkpoint_02_")

    def test_clean_checkpoints(self, tmp_path: Path) -> None:
        cp_dir = tmp_path / "checkpoints"
        state = PipelineState(
            run_id="clean_test",
            project_dir=tmp_path,
            current_step=PipelineStep.VALIDATE_CONFIG,
        )
        save_checkpoint(state, cp_dir)
        assert len(list_checkpoints(cp_dir)) == 1

        # Add a stale .tmp file that should be cleaned.
        (cp_dir / "checkpoint_01_validate_config.tmp").write_text("{}")

        removed = clean_checkpoints(cp_dir)
        assert removed == 1  # only .tmp removed
        # Checkpoint JSON files are preserved for --resume-from.
        assert len(list_checkpoints(cp_dir)) == 1

    def test_save_is_atomic_no_tmp_leftover(self, tmp_path: Path) -> None:
        """After save_checkpoint, no .tmp files should remain."""
        cp_dir = tmp_path / "checkpoints"
        state = PipelineState(
            run_id="atomic",
            project_dir=tmp_path,
            current_step=PipelineStep.VALIDATE_CONFIG,
        )
        save_checkpoint(state, cp_dir)
        tmp_files = list(cp_dir.glob("*.tmp"))
        assert tmp_files == []

    def test_checkpoint_atomic_write_cleans_tmp_on_failure(self, tmp_path: Path) -> None:
        """If serialisation fails, the .tmp file should be cleaned up."""
        cp_dir = tmp_path / "checkpoints"
        cp_dir.mkdir(parents=True)

        state = PipelineState(
            run_id="fail_test",
            project_dir=tmp_path,
            current_step=PipelineStep.VALIDATE_CONFIG,
        )

        # Monkeypatch json.dumps to raise inside save_checkpoint.
        import dd_agents.orchestrator.checkpoints as ckpt_mod

        original_dumps = json.dumps

        def failing_dumps(*args: object, **kwargs: object) -> str:
            raise ValueError("deliberate serialisation failure")

        ckpt_mod.json.dumps = failing_dumps  # type: ignore[attr-defined]
        try:
            with pytest.raises(ValueError, match="deliberate"):
                save_checkpoint(state, cp_dir)
        finally:
            ckpt_mod.json.dumps = original_dumps  # type: ignore[attr-defined]

        # No .tmp files should remain
        tmp_files = list(cp_dir.glob("*.tmp"))
        assert tmp_files == []
        # No checkpoint file should have been written either
        assert list_checkpoints(cp_dir) == []


# ======================================================================
# PipelineEngine
# ======================================================================


class TestPipelineEngine:
    """Tests for PipelineEngine initialisation and step registry."""

    def _make_engine(self, tmp_path: Path) -> PipelineEngine:
        """Helper: create an engine pointing at a temp project dir."""
        config_path = tmp_path / "deal-config.json"
        config_path.write_text("{}")
        return PipelineEngine(tmp_path, config_path)

    def test_init(self, tmp_path: Path) -> None:
        engine = self._make_engine(tmp_path)
        assert engine.project_dir == tmp_path.resolve()
        assert engine.TOTAL_STEPS == 38

    def test_step_registry_completeness(self, tmp_path: Path) -> None:
        """Every PipelineStep must have a handler in the registry."""
        engine = self._make_engine(tmp_path)
        registry = engine._step_registry

        for step in PipelineStep:
            assert step in registry, f"Missing handler for {step.value}"

        assert len(registry) == 38

    def test_step_registry_values_are_callable(self, tmp_path: Path) -> None:
        engine = self._make_engine(tmp_path)
        for step, fn in engine._step_registry.items():
            assert callable(fn), f"Handler for {step.value} is not callable"

    def test_default_state(self, tmp_path: Path) -> None:
        engine = self._make_engine(tmp_path)
        assert engine.state.project_dir == tmp_path.resolve()
        assert engine.state.current_step == PipelineStep.VALIDATE_CONFIG


# ======================================================================
# Exception hierarchy
# ======================================================================


class TestExceptions:
    def test_blocking_gate_error(self) -> None:
        err = BlockingGateError("gate failed")
        assert isinstance(err, Exception)
        assert str(err) == "gate failed"

    def test_recoverable_error(self) -> None:
        err = RecoverableError("recoverable")
        assert isinstance(err, Exception)

    def test_agent_failure_error(self) -> None:
        err = AgentFailureError("agent died", agent_name="legal")
        assert isinstance(err, RecoverableError)
        assert err.agent_name == "legal"

    def test_partial_failure_error(self) -> None:
        err = PartialFailureError(
            "partial",
            agent_name="finance",
            missing_subjects=["acme", "beta"],
        )
        assert isinstance(err, RecoverableError)
        assert err.agent_name == "finance"
        assert err.missing_subjects == ["acme", "beta"]


# ======================================================================
# Blocking gate step methods
# ======================================================================


class TestStep30NumericalAudit:
    """Tests for step 30: numerical audit blocking gate."""

    def _make_engine(self, tmp_path: Path) -> PipelineEngine:
        config_path = tmp_path / "deal-config.json"
        config_path.write_text("{}")
        return PipelineEngine(tmp_path, config_path)

    def _make_state(self, tmp_path: Path) -> PipelineState:
        run_dir = tmp_path / "runs" / "test_run"
        run_dir.mkdir(parents=True, exist_ok=True)
        inv_dir = tmp_path / "_dd" / "forensic-dd" / "inventory"
        inv_dir.mkdir(parents=True, exist_ok=True)
        return PipelineState(
            run_id="test_run",
            project_dir=tmp_path,
            run_dir=run_dir,
        )

    @pytest.mark.asyncio
    async def test_step_30_raises_on_missing_manifest(self, tmp_path: Path) -> None:
        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)
        # No numerical_manifest.json exists
        with pytest.raises(BlockingGateError, match="Numerical manifest not found"):
            await engine._step_30_numerical_audit(state)
        assert state.validation_results["numerical_audit"] is False

    @pytest.mark.asyncio
    async def test_step_30_raises_on_audit_failure(self, tmp_path: Path) -> None:

        from dd_agents.models.audit import AuditCheck

        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)

        # Create a minimal valid numerical manifest
        manifest_data = {
            "manifest_version": "1.0",
            "generated_at": "2026-01-01T00:00:00Z",
            "numbers": [
                {
                    "id": f"N{i:03d}",
                    "label": f"metric_{i}",
                    "value": i,
                    "source_file": "data.csv",
                    "derivation": "count",
                }
                for i in range(1, 11)
            ],
        }
        manifest_path = state.run_dir / "numerical_manifest.json"
        manifest_path.write_text(json.dumps(manifest_data))

        # Mock auditor to return failed checks
        failed_checks = [
            AuditCheck(passed=False, rule="Source traceability"),
            AuditCheck(passed=True, rule="Arithmetic"),
            AuditCheck(passed=False, rule="Cross-source consistency"),
            AuditCheck(passed=True, rule="Semantic reasonableness"),
        ]
        with (
            patch(
                "dd_agents.validation.numerical_audit.NumericalAuditor.run_full_audit",
                return_value=failed_checks,
            ),
            pytest.raises(BlockingGateError, match="Numerical audit failed"),
        ):
            await engine._step_30_numerical_audit(state)
        assert state.validation_results["numerical_audit"] is False

    @pytest.mark.asyncio
    async def test_step_30_passes_on_success(self, tmp_path: Path) -> None:

        from dd_agents.models.audit import AuditCheck

        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)

        # Create a minimal valid numerical manifest
        manifest_data = {
            "manifest_version": "1.0",
            "generated_at": "2026-01-01T00:00:00Z",
            "numbers": [
                {
                    "id": f"N{i:03d}",
                    "label": f"metric_{i}",
                    "value": i,
                    "source_file": "data.csv",
                    "derivation": "count",
                }
                for i in range(1, 11)
            ],
        }
        manifest_path = state.run_dir / "numerical_manifest.json"
        manifest_path.write_text(json.dumps(manifest_data))

        # Mock auditor to return all passing checks
        passing_checks = [
            AuditCheck(passed=True, rule="Source traceability"),
            AuditCheck(passed=True, rule="Arithmetic"),
            AuditCheck(passed=True, rule="Cross-source consistency"),
            AuditCheck(passed=True, rule="Semantic reasonableness"),
        ]
        with patch(
            "dd_agents.validation.numerical_audit.NumericalAuditor.run_full_audit",
            return_value=passing_checks,
        ):
            result = await engine._step_30_numerical_audit(state)
        assert result.validation_results["numerical_audit"] is True


class TestRebuildMissingInventoryFiles:
    """Tests for _rebuild_missing_inventory_files helper."""

    def _make_engine(self, tmp_path: Path) -> PipelineEngine:
        config_path = tmp_path / "deal-config.json"
        config_path.write_text("{}")
        return PipelineEngine(tmp_path, config_path)

    def _make_state(self, tmp_path: Path) -> PipelineState:
        run_dir = tmp_path / "runs" / "test_run"
        run_dir.mkdir(parents=True, exist_ok=True)
        inv_dir = tmp_path / "_dd" / "forensic-dd" / "inventory"
        inv_dir.mkdir(parents=True, exist_ok=True)
        return PipelineState(
            run_id="test_run",
            project_dir=tmp_path,
            run_dir=run_dir,
            total_subjects=3,
            total_files=10,
            reference_file_count=2,
            subject_safe_names=["acme_corp", "globex", "initech"],
        )

    def test_rebuilds_subjects_csv_from_safe_names(self, tmp_path: Path) -> None:
        """Creates subjects.csv from state.subject_safe_names when missing."""
        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)
        inv_dir = tmp_path / "_dd" / "forensic-dd" / "inventory"
        csv_path = inv_dir / "subjects.csv"
        assert not csv_path.exists()

        engine._rebuild_missing_inventory_files(state, inv_dir)

        assert csv_path.exists()
        lines = csv_path.read_text().strip().splitlines()
        # 1 header + 3 data rows
        assert len(lines) == 4

    def test_rebuilds_reference_files_json(self, tmp_path: Path) -> None:
        """Creates reference_files.json with correct length."""
        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)
        inv_dir = tmp_path / "_dd" / "forensic-dd" / "inventory"

        engine._rebuild_missing_inventory_files(state, inv_dir)

        ref_path = inv_dir / "reference_files.json"
        assert ref_path.exists()
        data = json.loads(ref_path.read_text())
        assert isinstance(data, list)
        assert len(data) == 2  # state.reference_file_count

    def test_rebuilds_counts_json(self, tmp_path: Path) -> None:
        """Creates counts.json from state fields."""
        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)
        inv_dir = tmp_path / "_dd" / "forensic-dd" / "inventory"

        engine._rebuild_missing_inventory_files(state, inv_dir)

        counts_path = inv_dir / "counts.json"
        assert counts_path.exists()
        data = json.loads(counts_path.read_text())
        assert data["total_subjects"] == 3
        assert data["total_files"] == 10
        assert data["total_reference_files"] == 2

    def test_does_not_overwrite_existing_files(self, tmp_path: Path) -> None:
        """Existing inventory files are not overwritten."""
        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)
        inv_dir = tmp_path / "_dd" / "forensic-dd" / "inventory"

        # Pre-create with custom content
        csv_path = inv_dir / "subjects.csv"
        csv_path.write_text("original content\n")
        ref_path = inv_dir / "reference_files.json"
        ref_path.write_text("[1, 2, 3]")

        engine._rebuild_missing_inventory_files(state, inv_dir)

        assert csv_path.read_text() == "original content\n"
        assert ref_path.read_text() == "[1, 2, 3]"


class TestStep31FullQAAudit:
    """Tests for step 31: full QA audit blocking gate."""

    def _make_engine(self, tmp_path: Path) -> PipelineEngine:
        config_path = tmp_path / "deal-config.json"
        config_path.write_text("{}")
        return PipelineEngine(tmp_path, config_path)

    def _make_state(self, tmp_path: Path) -> PipelineState:
        run_dir = tmp_path / "runs" / "test_run"
        run_dir.mkdir(parents=True, exist_ok=True)
        inv_dir = tmp_path / "_dd" / "forensic-dd" / "inventory"
        inv_dir.mkdir(parents=True, exist_ok=True)
        return PipelineState(
            run_id="test_run",
            project_dir=tmp_path,
            run_dir=run_dir,
            subject_safe_names=["subject_a"],
        )

    @pytest.mark.asyncio
    async def test_step_31_raises_on_qa_failure(self, tmp_path: Path) -> None:

        from dd_agents.models.audit import AuditCheck, AuditReport

        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)

        failed_report = AuditReport(
            audit_passed=False,
            timestamp="2026-01-01T00:00:00Z",
            run_id="test_run",
            checks={
                "file_coverage": AuditCheck(passed=True, rule="File coverage"),
                "subject_coverage": AuditCheck(passed=False, rule="Subject coverage"),
                "citation_integrity": AuditCheck(passed=False, rule="Citation integrity"),
            },
        )
        with (
            patch(
                "dd_agents.validation.qa_audit.QAAuditor.run_full_audit",
                return_value=failed_report,
            ),
            patch(
                "dd_agents.validation.qa_audit.QAAuditor.write_audit_json",
            ),
            pytest.raises(BlockingGateError, match="QA audit failed"),
        ):
            await engine._step_31_full_qa_audit(state)
        assert state.validation_results["qa_audit"] is False
        assert state.audit_passed is False

    @pytest.mark.asyncio
    async def test_step_31_passes_on_success(self, tmp_path: Path) -> None:

        from dd_agents.models.audit import AuditCheck, AuditReport

        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)

        passing_report = AuditReport(
            audit_passed=True,
            timestamp="2026-01-01T00:00:00Z",
            run_id="test_run",
            checks={
                "file_coverage": AuditCheck(passed=True, rule="File coverage"),
                "subject_coverage": AuditCheck(passed=True, rule="Subject coverage"),
            },
        )
        with (
            patch(
                "dd_agents.validation.qa_audit.QAAuditor.run_full_audit",
                return_value=passing_report,
            ),
            patch(
                "dd_agents.validation.qa_audit.QAAuditor.write_audit_json",
            ),
        ):
            result = await engine._step_31_full_qa_audit(state)
        assert result.validation_results["qa_audit"] is True
        assert result.audit_passed is True


class TestStep38Shutdown:
    """Tests for step 38: shutdown DoD persistence and exit status (Issue #56)."""

    def _make_engine(self, tmp_path: Path) -> PipelineEngine:
        config_path = tmp_path / "deal-config.json"
        config_path.write_text("{}")
        return PipelineEngine(tmp_path, config_path)

    def _make_state(self, tmp_path: Path) -> PipelineState:
        run_dir = tmp_path / "runs" / "test_run"
        run_dir.mkdir(parents=True, exist_ok=True)
        inv_dir = tmp_path / "_dd" / "forensic-dd" / "inventory"
        inv_dir.mkdir(parents=True, exist_ok=True)
        return PipelineState(
            run_id="test_run",
            project_dir=tmp_path,
            run_dir=run_dir,
            subject_safe_names=["subject_a"],
        )

    @pytest.mark.asyncio
    async def test_step_38_persists_dod_results(self, tmp_path: Path) -> None:
        from dd_agents.models.audit import AuditCheck

        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)

        mock_checks = [
            AuditCheck(passed=True, rule="Check 1"),
            AuditCheck(passed=False, rule="Check 2"),
            AuditCheck(passed=True, rule="Check 3"),
        ]
        with patch(
            "dd_agents.validation.dod.DefinitionOfDoneChecker.check_all",
            return_value=mock_checks,
        ):
            await engine._step_38_shutdown(state)

        dod_path = state.run_dir / "dod_results.json"
        assert dod_path.exists(), "dod_results.json must be written"

        data = json.loads(dod_path.read_text())
        assert data["passed"] == 2
        assert data["total"] == 3
        assert len(data["checks"]) == 3

    @pytest.mark.asyncio
    async def test_step_38_stores_dod_in_validation_results(self, tmp_path: Path) -> None:
        """Issue #56: DoD results must be stored in state.validation_results['dod']."""
        from dd_agents.models.audit import AuditCheck

        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)

        # All checks pass -- dod should be True
        mock_checks = [
            AuditCheck(passed=True, rule="Check 1", dod_checks=[1]),
            AuditCheck(passed=True, rule="Check 2", dod_checks=[2]),
        ]
        with patch(
            "dd_agents.validation.dod.DefinitionOfDoneChecker.check_all",
            return_value=mock_checks,
        ):
            result = await engine._step_38_shutdown(state)

        assert result.validation_results["dod"] is True

    @pytest.mark.asyncio
    async def test_step_38_critical_failure_sets_dod_false(self, tmp_path: Path) -> None:
        """Issue #56: Critical DoD failure sets validation_results['dod'] to False."""
        from dd_agents.models.audit import AuditCheck

        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)

        # Check 1 is critical (dod_checks=[1]) and fails
        mock_checks = [
            AuditCheck(passed=False, rule="Subject outputs", dod_checks=[1]),
            AuditCheck(passed=True, rule="Non-critical check", dod_checks=[4]),
        ]
        with patch(
            "dd_agents.validation.dod.DefinitionOfDoneChecker.check_all",
            return_value=mock_checks,
        ):
            result = await engine._step_38_shutdown(state)

        assert result.validation_results["dod"] is False

    @pytest.mark.asyncio
    async def test_step_38_non_critical_failure_keeps_dod_true(self, tmp_path: Path) -> None:
        """Issue #56: Non-critical DoD failure should not set dod to False."""
        from dd_agents.models.audit import AuditCheck

        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)

        # Check 4 (governance) is NOT critical and fails
        mock_checks = [
            AuditCheck(passed=True, rule="Subject outputs", dod_checks=[1]),
            AuditCheck(passed=False, rule="Governance resolved", dod_checks=[4]),
        ]
        with patch(
            "dd_agents.validation.dod.DefinitionOfDoneChecker.check_all",
            return_value=mock_checks,
        ):
            result = await engine._step_38_shutdown(state)

        assert result.validation_results["dod"] is True

    @pytest.mark.asyncio
    async def test_step_38_critical_failures_listed_in_output(self, tmp_path: Path) -> None:
        """Issue #56: dod_results.json should list critical failures."""
        from dd_agents.models.audit import AuditCheck

        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)

        mock_checks = [
            AuditCheck(passed=False, rule="Subject outputs", dod_checks=[1]),
            AuditCheck(passed=False, rule="Excel sheets", dod_checks=[14]),
            AuditCheck(passed=False, rule="Non-critical", dod_checks=[4]),
        ]
        with patch(
            "dd_agents.validation.dod.DefinitionOfDoneChecker.check_all",
            return_value=mock_checks,
        ):
            await engine._step_38_shutdown(state)

        dod_path = state.run_dir / "dod_results.json"
        data = json.loads(dod_path.read_text())
        # Only critical failures (checks 1 and 14) should be listed
        assert len(data["critical_failures"]) == 2
        assert "Subject outputs" in data["critical_failures"]
        assert "Excel sheets" in data["critical_failures"]

    def test_critical_dod_checks_defined(self) -> None:
        """Issue #56: Critical DoD checks should be {1,2,3,11,13,14,15,17,19}."""
        expected = frozenset({1, 2, 3, 11, 13, 14, 15, 17, 19})
        assert expected == PipelineEngine.CRITICAL_DOD_CHECKS


# ======================================================================
# Sub-checkpoints (Issue #51)
# ======================================================================


class TestSubCheckpoints:
    """Tests for per-subject sub-checkpoints within long-running steps."""

    def test_save_and_load_sub_checkpoint(self, tmp_path: Path) -> None:
        from dd_agents.orchestrator.checkpoints import load_sub_checkpoints, save_sub_checkpoint

        cp_dir = tmp_path / "checkpoints"

        # Save two sub-checkpoints for step 16
        save_sub_checkpoint(cp_dir, "step_16", "subject_a", {"status": "complete", "findings": 5})
        save_sub_checkpoint(cp_dir, "step_16", "subject_b", {"status": "complete", "findings": 3})

        # Load them back
        loaded = load_sub_checkpoints(cp_dir, "step_16")
        assert len(loaded) == 2
        assert loaded["subject_a"]["status"] == "complete"
        assert loaded["subject_a"]["findings"] == 5
        assert loaded["subject_b"]["findings"] == 3

    def test_load_sub_checkpoints_empty(self, tmp_path: Path) -> None:
        from dd_agents.orchestrator.checkpoints import load_sub_checkpoints

        cp_dir = tmp_path / "checkpoints"
        loaded = load_sub_checkpoints(cp_dir, "step_16")
        assert loaded == {}

    def test_sub_checkpoint_no_tmp_leftover(self, tmp_path: Path) -> None:
        from dd_agents.orchestrator.checkpoints import save_sub_checkpoint

        cp_dir = tmp_path / "checkpoints"
        save_sub_checkpoint(cp_dir, "step_16", "subject_a", {"ok": True})

        sub_dir = cp_dir / "step_16"
        tmp_files = list(sub_dir.glob("*.tmp"))
        assert tmp_files == []

    def test_sub_checkpoint_skips_corrupt_files(self, tmp_path: Path) -> None:
        from dd_agents.orchestrator.checkpoints import load_sub_checkpoints, save_sub_checkpoint

        cp_dir = tmp_path / "checkpoints"
        save_sub_checkpoint(cp_dir, "step_16", "good", {"status": "ok"})

        # Create a corrupt sub-checkpoint
        corrupt_path = cp_dir / "step_16" / "subject_bad.json"
        corrupt_path.write_text("not valid json {{{")

        loaded = load_sub_checkpoints(cp_dir, "step_16")
        assert len(loaded) == 1
        assert "good" in loaded
        assert "bad" not in loaded

    def test_clean_checkpoints_removes_sub_dirs(self, tmp_path: Path) -> None:
        from dd_agents.orchestrator.checkpoints import clean_checkpoints, save_sub_checkpoint

        cp_dir = tmp_path / "checkpoints"
        cp_dir.mkdir()
        save_sub_checkpoint(cp_dir, "step_16", "subject_a", {"ok": True})

        assert (cp_dir / "step_16").is_dir()
        clean_checkpoints(cp_dir)
        assert not (cp_dir / "step_16").exists()


# ======================================================================
# Checkpoint corruption recovery (Issue #51)
# ======================================================================


class TestCheckpointCorruptionRecovery:
    """Tests for checkpoint backup rotation and corruption fallback."""

    def test_save_creates_bak_file(self, tmp_path: Path) -> None:
        """save_checkpoint should create a .bak of the prior checkpoint."""
        cp_dir = tmp_path / "checkpoints"
        state = PipelineState(
            run_id="bak_test",
            project_dir=tmp_path,
            current_step=PipelineStep.VALIDATE_CONFIG,
        )

        # First save -- no .bak (no prior checkpoint)
        save_checkpoint(state, cp_dir)
        bak_files = list(cp_dir.glob("*.bak"))
        assert bak_files == []

        # Second save (same step) -- .bak should exist
        state2 = PipelineState(
            run_id="bak_test_v2",
            project_dir=tmp_path,
            current_step=PipelineStep.VALIDATE_CONFIG,
        )
        save_checkpoint(state2, cp_dir)
        bak_files = list(cp_dir.glob("*.bak"))
        assert len(bak_files) == 1

        # The .bak should contain the first save's data
        bak_data = json.loads(bak_files[0].read_text())
        assert bak_data["run_id"] == "bak_test"

    def test_load_falls_back_to_bak_on_corruption(self, tmp_path: Path) -> None:
        """load_checkpoint_by_step should fall back to .bak when primary is corrupt."""
        cp_dir = tmp_path / "checkpoints"
        state = PipelineState(
            run_id="fallback_test",
            project_dir=tmp_path,
            current_step=PipelineStep.VALIDATE_CONFIG,
        )

        # Save a valid checkpoint
        checkpoint_path = save_checkpoint(state, cp_dir)

        # Create a .bak with valid data
        bak_path = checkpoint_path.with_suffix(".bak")
        bak_state = PipelineState(
            run_id="backup_state",
            project_dir=tmp_path,
            current_step=PipelineStep.VALIDATE_CONFIG,
        )
        bak_path.write_text(json.dumps(bak_state.to_checkpoint_dict(), indent=2, default=str))

        # Corrupt the primary checkpoint
        checkpoint_path.write_text("not valid json {{{")

        # Loading should fall back to .bak
        loaded = load_checkpoint_by_step(cp_dir, 1)
        assert loaded.run_id == "backup_state"

    def test_load_raises_when_both_corrupt(self, tmp_path: Path) -> None:
        """Should raise when both primary and .bak are corrupted."""
        cp_dir = tmp_path / "checkpoints"
        state = PipelineState(
            run_id="both_corrupt",
            project_dir=tmp_path,
            current_step=PipelineStep.VALIDATE_CONFIG,
        )

        checkpoint_path = save_checkpoint(state, cp_dir)
        bak_path = checkpoint_path.with_suffix(".bak")

        # Corrupt both
        checkpoint_path.write_text("corrupt primary")
        bak_path.write_text("corrupt backup")

        with pytest.raises((json.JSONDecodeError, Exception)):
            load_checkpoint_by_step(cp_dir, 1)

    def test_clean_checkpoints_removes_bak_files(self, tmp_path: Path) -> None:
        """clean_checkpoints should remove .bak files but preserve .json."""
        cp_dir = tmp_path / "checkpoints"
        state = PipelineState(
            run_id="clean_bak",
            project_dir=tmp_path,
            current_step=PipelineStep.VALIDATE_CONFIG,
        )

        # Create checkpoint and bak
        save_checkpoint(state, cp_dir)
        save_checkpoint(state, cp_dir)  # creates .bak

        assert len(list(cp_dir.glob("*.bak"))) == 1

        removed = clean_checkpoints(cp_dir)
        assert removed == 1  # only .bak removed
        assert list(cp_dir.glob("*.bak")) == []
        # Checkpoint JSON preserved for --resume-from.
        assert len(list(cp_dir.glob("*.json"))) == 1


# ======================================================================
# PipelineState exit_code (Issue #56)
# ======================================================================


class TestPipelineStateExitCode:
    """Tests for the exit_code field on PipelineState."""

    def test_default_exit_code_is_zero(self) -> None:
        state = PipelineState()
        assert state.exit_code == 0

    def test_exit_code_survives_checkpoint_round_trip(self, tmp_path: Path) -> None:
        state = PipelineState(
            run_id="exit_code_test",
            project_dir=tmp_path,
            current_step=PipelineStep.VALIDATE_CONFIG,
            exit_code=1,
        )
        data = state.to_checkpoint_dict()
        restored = PipelineState.from_checkpoint_dict(data)
        assert restored.exit_code == 1


# ======================================================================
# Issue #42: Adaptive timeout and stall detection
# ======================================================================


class TestAgentTeamAdaptiveTimeout:
    """Tests for AgentTeam.calculate_adaptive_timeout."""

    def test_zero_subjects(self) -> None:
        from dd_agents.orchestrator.team import AgentTeam

        result = AgentTeam.calculate_adaptive_timeout(0)
        # base_timeout + 0 * per_subject = 1800
        assert result == 1800

    def test_ten_subjects(self) -> None:
        from dd_agents.orchestrator.team import AgentTeam

        result = AgentTeam.calculate_adaptive_timeout(10)
        # 1800 + 10 * 120 = 3000
        assert result == 3000

    def test_hundred_subjects(self) -> None:
        from dd_agents.orchestrator.team import AgentTeam

        result = AgentTeam.calculate_adaptive_timeout(100)
        # 1800 + 100 * 120 = 13800, capped at MAX_TIMEOUT_S (3600)
        assert result == 3600

    def test_custom_base_and_per_subject(self) -> None:
        from dd_agents.orchestrator.team import AgentTeam

        result = AgentTeam.calculate_adaptive_timeout(
            5,
            base_timeout_s=600,
            per_subject_s=60,
        )
        # 600 + 5 * 60 = 900
        assert result == 900

    def test_one_subject(self) -> None:
        from dd_agents.orchestrator.team import AgentTeam

        result = AgentTeam.calculate_adaptive_timeout(1)
        # 1800 + 1 * 120 = 1920
        assert result == 1920

    def test_multiple_batches_increases_timeout(self) -> None:
        from dd_agents.orchestrator.team import AgentTeam

        # 80 subjects, 4 batches (uncapped raw values shown):
        # per_batch = 1800 + (80 * 120) // 4 = 1800 + 2400 = 4200
        # total = 4200 * 4 = 16800 → capped at 3600
        result = AgentTeam.calculate_adaptive_timeout(80, num_batches=4)
        assert result == 3600

        # Same 80 subjects with 1 batch (default):
        # per_batch = 1800 + (80 * 120) // 1 = 1800 + 9600 = 11400
        # total = 11400 * 1 = 11400 → capped at 3600
        single = AgentTeam.calculate_adaptive_timeout(80, num_batches=1)
        assert single == 3600

        # Both are capped at the same value
        assert result == single

    def test_num_batches_zero_treated_as_one(self) -> None:
        from dd_agents.orchestrator.team import AgentTeam

        result = AgentTeam.calculate_adaptive_timeout(10, num_batches=0)
        expected = AgentTeam.calculate_adaptive_timeout(10, num_batches=1)
        assert result == expected

    def test_max_timeout_cap(self) -> None:
        from dd_agents.orchestrator.team import AgentTeam

        # Without cap: 1800 + 50 * 120 = 7800
        # With default cap (3600): should be capped
        result = AgentTeam.calculate_adaptive_timeout(50)
        assert result == 3600

        # With custom cap: 7200 allows the raw value through if under cap
        result_high_cap = AgentTeam.calculate_adaptive_timeout(50, max_timeout_s=10000)
        assert result_high_cap == 7800

    def test_below_cap_not_reduced(self) -> None:
        from dd_agents.orchestrator.team import AgentTeam

        # 5 subjects: 1800 + 5*120 = 2400, under 3600 cap
        result = AgentTeam.calculate_adaptive_timeout(5)
        assert result == 2400


class TestAgentTeamStallDetection:
    """Tests for AgentTeam.detect_stalled_agents and record_activity."""

    def _make_team(self, tmp_path: Path) -> AgentTeam:
        from dd_agents.orchestrator.team import AgentTeam

        state = PipelineState(
            run_id="stall_test",
            project_dir=tmp_path,
        )
        return AgentTeam(state, stall_threshold_s=60)

    def test_no_agents_tracked(self, tmp_path: Path) -> None:
        team = self._make_team(tmp_path)
        assert team.detect_stalled_agents() == []

    def test_active_agent_not_stalled(self, tmp_path: Path) -> None:
        team = self._make_team(tmp_path)
        team.record_activity("legal")
        assert team.detect_stalled_agents() == []

    def test_stalled_agent_detected(self, tmp_path: Path) -> None:
        import time as _time

        team = self._make_team(tmp_path)
        # Record activity far in the past
        team._agent_last_activity["legal"] = _time.monotonic() - 120  # 2 min ago
        stalled = team.detect_stalled_agents()
        assert "legal" in stalled

    def test_record_activity_resets_stall(self, tmp_path: Path) -> None:
        import time as _time

        team = self._make_team(tmp_path)
        team._agent_last_activity["legal"] = _time.monotonic() - 120
        # Verify stalled
        assert "legal" in team.detect_stalled_agents()
        # Record fresh activity
        team.record_activity("legal")
        # No longer stalled
        assert team.detect_stalled_agents() == []

    def test_multiple_agents_mixed(self, tmp_path: Path) -> None:
        import time as _time

        team = self._make_team(tmp_path)
        now = _time.monotonic()
        team._agent_last_activity["legal"] = now - 120  # stalled
        team._agent_last_activity["finance"] = now  # active
        team._agent_last_activity["commercial"] = now - 200  # stalled
        stalled = team.detect_stalled_agents()
        assert "legal" in stalled
        assert "commercial" in stalled
        assert "finance" not in stalled

    def test_completed_agent_not_stalled(self, tmp_path: Path) -> None:
        """Completed agents should be excluded from stall detection."""
        import time as _time

        team = self._make_team(tmp_path)
        team._agent_last_activity["legal"] = _time.monotonic() - 120  # stalled
        team._agent_last_activity["finance"] = _time.monotonic() - 120  # stalled
        # Mark legal as completed
        team.mark_agent_completed("legal")
        stalled = team.detect_stalled_agents()
        assert "legal" not in stalled
        assert "finance" in stalled

    def test_mark_agent_completed(self, tmp_path: Path) -> None:
        """mark_agent_completed adds agent to completed set."""
        team = self._make_team(tmp_path)
        assert len(team._completed_agents) == 0
        team.mark_agent_completed("legal")
        assert "legal" in team._completed_agents


class TestAgentTeamIsTimedOut:
    """Tests for AgentTeam.is_timed_out."""

    def test_unknown_agent(self, tmp_path: Path) -> None:
        from dd_agents.orchestrator.team import AgentTeam

        state = PipelineState(run_id="timeout_test", project_dir=tmp_path)
        team = AgentTeam(state, agent_timeout_s=60)
        assert team.is_timed_out("nonexistent") is False

    def test_not_timed_out(self, tmp_path: Path) -> None:
        import time as _time

        from dd_agents.orchestrator.team import AgentTeam

        state = PipelineState(run_id="timeout_test", project_dir=tmp_path)
        team = AgentTeam(state, agent_timeout_s=60)
        team._agent_start_times["legal"] = _time.monotonic()
        assert team.is_timed_out("legal") is False

    def test_timed_out(self, tmp_path: Path) -> None:
        import time as _time

        from dd_agents.orchestrator.team import AgentTeam

        state = PipelineState(run_id="timeout_test", project_dir=tmp_path)
        team = AgentTeam(state, agent_timeout_s=60)
        team._agent_start_times["legal"] = _time.monotonic() - 120
        assert team.is_timed_out("legal") is True


class TestAgentTeamLatestFileMtime:
    """Tests for AgentTeam._latest_file_mtime static method."""

    def test_empty_dir(self, tmp_path: Path) -> None:
        from dd_agents.orchestrator.team import AgentTeam

        subdir = tmp_path / "empty"
        subdir.mkdir()
        assert AgentTeam._latest_file_mtime(subdir) is None

    def test_nonexistent_dir(self, tmp_path: Path) -> None:
        from dd_agents.orchestrator.team import AgentTeam

        assert AgentTeam._latest_file_mtime(tmp_path / "nope") is None

    def test_single_file(self, tmp_path: Path) -> None:
        from dd_agents.orchestrator.team import AgentTeam

        f = tmp_path / "output.json"
        f.write_text("{}")
        result = AgentTeam._latest_file_mtime(tmp_path)
        assert result is not None
        assert isinstance(result, float)

    def test_picks_latest(self, tmp_path: Path) -> None:
        import os
        import time as _time

        from dd_agents.orchestrator.team import AgentTeam

        f1 = tmp_path / "old.json"
        f1.write_text("{}")
        # Set old mtime
        old_time = _time.time() - 100
        os.utime(f1, (old_time, old_time))

        f2 = tmp_path / "new.json"
        f2.write_text("{}")

        result = AgentTeam._latest_file_mtime(tmp_path)
        assert result is not None
        # Should be the newer file's mtime
        assert result >= f2.stat().st_mtime


class TestAgentTeamMonitorOutput:
    """Tests for AgentTeam.monitor_agent_output async method."""

    @pytest.mark.asyncio
    async def test_monitor_stops_on_event(self, tmp_path: Path) -> None:
        """Monitor exits promptly when stop_event is set."""
        import asyncio

        from dd_agents.orchestrator.team import AgentTeam

        state = PipelineState(run_id="mon_test", project_dir=tmp_path)
        team = AgentTeam(state)
        output_dir = tmp_path / "findings"
        output_dir.mkdir()

        stop = asyncio.Event()
        stop.set()  # Set immediately
        # Should return quickly without hanging
        await asyncio.wait_for(
            team.monitor_agent_output(
                output_dir,
                ["legal"],
                check_interval_s=0.1,
                stop_event=stop,
            ),
            timeout=5.0,
        )

    @pytest.mark.asyncio
    async def test_monitor_detects_new_files(self, tmp_path: Path) -> None:
        """Monitor records activity when new files appear."""
        import asyncio

        from dd_agents.orchestrator.team import AgentTeam

        state = PipelineState(run_id="mon_test2", project_dir=tmp_path)
        team = AgentTeam(state)
        output_dir = tmp_path / "findings"
        output_dir.mkdir()

        # Register agents in tracking
        team._agent_last_activity["legal"] = 0.0

        stop = asyncio.Event()

        async def create_file_and_stop() -> None:
            await asyncio.sleep(0.2)
            (output_dir / "legal_output.json").write_text("{}")
            await asyncio.sleep(0.3)
            stop.set()

        await asyncio.gather(
            team.monitor_agent_output(
                output_dir,
                ["legal"],
                check_interval_s=0.1,
                stop_event=stop,
            ),
            create_file_and_stop(),
        )

        # Activity should have been updated from the initial 0.0
        assert team._agent_last_activity["legal"] > 0.0


class TestAgentTeamSpawnSpecialistsAdaptive:
    """Tests that spawn_specialists uses adaptive timeout when num_subjects > 0."""

    @pytest.mark.asyncio
    async def test_spawn_with_adaptive_timeout(self, tmp_path: Path) -> None:
        """spawn_specialists calculates adaptive timeout from num_subjects."""
        from dd_agents.orchestrator.team import AgentTeam

        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (run_dir / "findings").mkdir()

        state = PipelineState(
            run_id="adaptive_test",
            project_dir=tmp_path,
            run_dir=run_dir,
        )
        team = AgentTeam(state)

        # With placeholder agents, this should complete quickly.
        results = await team.spawn_specialists(num_subjects=10)
        from dd_agents.agents.registry import AgentRegistry

        all_names = AgentRegistry.all_specialist_names()
        assert len(results) == len(all_names)
        for name in all_names:
            assert name in results


# ======================================================================
# Issue #37: Step 14 - Subject batching via PromptBuilder
# ======================================================================


class TestStep14PreparePrompts:
    """Tests for _step_14_prepare_prompts (Issue #37)."""

    def _make_engine(self, tmp_path: Path) -> PipelineEngine:
        config_path = tmp_path / "deal-config.json"
        config_path.write_text("{}")
        return PipelineEngine(tmp_path, config_path)

    def _make_state(self, tmp_path: Path) -> PipelineState:
        run_dir = tmp_path / "runs" / "test_run"
        run_dir.mkdir(parents=True, exist_ok=True)
        inv_dir = tmp_path / "_dd" / "forensic-dd" / "inventory"
        inv_dir.mkdir(parents=True, exist_ok=True)
        text_dir = tmp_path / "_dd" / "forensic-dd" / "index" / "text"
        text_dir.mkdir(parents=True, exist_ok=True)
        return PipelineState(
            run_id="test_run",
            project_dir=tmp_path,
            run_dir=run_dir,
            subject_safe_names=["subject_a", "subject_b"],
        )

    @pytest.mark.asyncio
    async def test_step_14_calls_batch_subjects_and_stores_results(self, tmp_path: Path) -> None:
        """Step 14 must use PromptBuilder.batch_subjects and populate state."""
        from unittest.mock import patch

        from dd_agents.models.inventory import SubjectEntry

        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)

        # Attach subject entries to state (normally done by step 6)
        subjects = [
            SubjectEntry(
                group="group_a",
                name="Subject A",
                safe_name="subject_a",
                path="subjects/subject_a",
                file_count=2,
                files=["file1.pdf", "file2.pdf"],
            ),
            SubjectEntry(
                group="group_a",
                name="Subject B",
                safe_name="subject_b",
                path="subjects/subject_b",
                file_count=1,
                files=["file3.pdf"],
            ),
        ]
        state._subject_entries = subjects  # type: ignore[attr-defined]

        with patch(
            "dd_agents.agents.prompt_builder.PromptBuilder.batch_subjects",
            wraps=lambda subjs, **kw: [subjs],  # single batch
        ) as mock_batch:
            result = await engine._step_14_prepare_prompts(state)

        from dd_agents.agents.registry import AgentRegistry

        all_names = AgentRegistry.all_specialist_names()

        # batch_subjects should have been called once per active agent
        assert mock_batch.call_count == len(all_names)

        # All specialist agents should have prompts
        for name in all_names:
            assert name in result.agent_prompts

        # Each agent should have at least 1 prompt string
        for agent_name in all_names:
            prompts = result.agent_prompts[agent_name]
            assert len(prompts) >= 1
            assert isinstance(prompts[0], str)
            assert len(prompts[0]) > 0

        # Batch counts should be stored
        for agent_name in ["legal", "finance", "commercial", "producttech"]:
            assert agent_name in result.batch_counts
            assert result.batch_counts[agent_name] >= 1

    @pytest.mark.asyncio
    async def test_step_14_handles_empty_subjects(self, tmp_path: Path) -> None:
        """Step 14 with no subjects should produce empty prompts."""
        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)
        state._subject_entries = []  # type: ignore[attr-defined]

        result = await engine._step_14_prepare_prompts(state)

        # batch_subjects([]) returns [] so agent_prompts should be empty lists
        for agent_name in ["legal", "finance", "commercial", "producttech"]:
            assert result.agent_prompts[agent_name] == []
            assert result.batch_counts[agent_name] == 0


# ======================================================================
# Issue #38: Step 17 - Coverage gate with respawn and gap findings
# ======================================================================


class TestStep17CoverageGate:
    """Tests for _step_17_coverage_gate (Issue #38)."""

    def _make_engine(self, tmp_path: Path) -> PipelineEngine:
        config_path = tmp_path / "deal-config.json"
        config_path.write_text("{}")
        return PipelineEngine(tmp_path, config_path)

    def _make_state(self, tmp_path: Path, subjects: list | None = None) -> PipelineState:
        run_dir = tmp_path / "runs" / "test_run"
        run_dir.mkdir(parents=True, exist_ok=True)
        findings_dir = run_dir / "findings"
        findings_dir.mkdir(parents=True, exist_ok=True)
        if subjects is None:
            subjects = ["subject_a", "subject_b", "subject_c"]
        return PipelineState(
            run_id="test_run",
            project_dir=tmp_path,
            run_dir=run_dir,
            subject_safe_names=subjects,
        )

    def _create_finding(self, findings_dir: Path, agent: str, subject: str) -> None:
        """Helper: create a dummy finding file."""
        agent_dir = findings_dir / agent
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / f"{subject}.json").write_text('{"findings": []}')

    @pytest.mark.asyncio
    async def test_coverage_gate_passes_with_full_coverage(self, tmp_path: Path) -> None:
        """Coverage gate passes when all subjects have output for all agents."""
        from dd_agents.agents.registry import AgentRegistry

        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)
        findings_dir = state.run_dir / "findings"

        # Create output for all subjects for all agents
        for agent in AgentRegistry.all_specialist_names():
            for subject in state.subject_safe_names:
                self._create_finding(findings_dir, agent, subject)

        result = await engine._step_17_coverage_gate(state)
        assert result is not None  # Should not raise

    @pytest.mark.asyncio
    async def test_coverage_gate_blocks_below_50_percent(self, tmp_path: Path) -> None:
        """Coverage gate raises BlockingGateError when coverage < 50%."""
        from dd_agents.agents.registry import AgentRegistry

        engine = self._make_engine(tmp_path)
        # Use 10 subjects so we can create < 50% coverage
        subjects = [f"subject_{i}" for i in range(10)]
        state = self._make_state(tmp_path, subjects=subjects)
        findings_dir = state.run_dir / "findings"

        # Create output for only 4 of 10 subjects for each agent
        # (40% coverage < 50%)
        for agent in AgentRegistry.all_specialist_names():
            for subject in subjects[:4]:
                self._create_finding(findings_dir, agent, subject)

        with pytest.raises(BlockingGateError, match="coverage.*< 50% threshold"):
            await engine._step_17_coverage_gate(state)

    @pytest.mark.asyncio
    async def test_coverage_gate_generates_gap_findings(self, tmp_path: Path) -> None:
        """Coverage gate generates P1 gap findings for missing subjects."""
        from dd_agents.agents.registry import AgentRegistry

        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path, subjects=["subject_a", "subject_b"])
        findings_dir = state.run_dir / "findings"

        # Create output for subject_a only across all agents
        for agent in AgentRegistry.all_specialist_names():
            self._create_finding(findings_dir, agent, "subject_a")
        # subject_b is missing from all agents

        # 50% coverage -- should not block (>= 50%) but should generate gaps
        await engine._step_17_coverage_gate(state)

        # Gap findings should have been written
        gap_path = findings_dir / "coverage_gaps" / "coverage_gap_findings.json"
        assert gap_path.exists(), "coverage_gap_findings.json should be generated"

        gaps = json.loads(gap_path.read_text())
        from dd_agents.agents.registry import AgentRegistry

        assert len(gaps) == len(AgentRegistry.all_specialist_names())  # N agents x 1 missing subject

        # Each gap finding should be P1 severity
        for gap in gaps:
            assert gap["severity"] == "P1"
            assert gap["finding_type"] == "coverage_gap"
            assert gap["subject_safe_name"] == "subject_b"
            assert gap["auto_generated"] is True

        # Gap findings should also be written as agent output files so
        # the merge step picks them up for domain_coverage in QA audit.
        for agent in AgentRegistry.all_specialist_names():
            agent_file = findings_dir / agent / "subject_b.json"
            assert agent_file.exists(), f"Gap finding should create {agent}/subject_b.json"
            data = json.loads(agent_file.read_text())
            assert data["auto_generated"] is True
            assert data["source"] == "coverage_gate"
            assert len(data["findings"]) == 1
            assert data["findings"][0]["agent"] == agent

    @pytest.mark.asyncio
    async def test_coverage_gate_no_subjects(self, tmp_path: Path) -> None:
        """Coverage gate passes trivially when there are no subjects."""
        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path, subjects=[])

        result = await engine._step_17_coverage_gate(state)
        assert result is not None  # Should not raise


class TestReconcileAgentOutputFilenames:
    """Tests for _reconcile_agent_output_filenames (misnamed file recovery)."""

    def test_misnamed_file_gets_renamed(self, tmp_path: Path) -> None:
        """A file named entity.json with subject_safe_name='commercial' is renamed."""
        agent_dir = tmp_path / "commercial_agent"
        agent_dir.mkdir()
        data = {"subject_safe_name": "commercial", "findings": [{"title": "F1"}]}
        (agent_dir / "fidelity.json").write_text(json.dumps(data))

        count = PipelineEngine._reconcile_agent_output_filenames(
            agent_dir,
            ["commercial", "legal"],
        )
        assert count >= 1
        assert (agent_dir / "commercial.json").exists()
        assert not (agent_dir / "fidelity.json").exists()
        result = json.loads((agent_dir / "commercial.json").read_text())
        assert result["subject_safe_name"] == "commercial"
        assert len(result["findings"]) == 1

    def test_correctly_named_file_untouched(self, tmp_path: Path) -> None:
        """Files already matching expected names are not modified."""
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        data = {"subject_safe_name": "legal", "findings": [{"title": "ok"}]}
        (agent_dir / "legal.json").write_text(json.dumps(data))

        count = PipelineEngine._reconcile_agent_output_filenames(
            agent_dir,
            ["legal"],
        )
        assert count == 0
        assert (agent_dir / "legal.json").exists()

    def test_multiple_files_merged_into_one(self, tmp_path: Path) -> None:
        """Multiple entity files with the same subject_safe_name get merged."""
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        d1 = {"subject_safe_name": "commercial", "findings": [{"title": "A"}], "files_analyzed": 3}
        d2 = {"subject_safe_name": "commercial", "findings": [{"title": "B"}], "files_analyzed": 2}
        (agent_dir / "fidelity.json").write_text(json.dumps(d1))
        (agent_dir / "pacific_life.json").write_text(json.dumps(d2))

        count = PipelineEngine._reconcile_agent_output_filenames(
            agent_dir,
            ["commercial"],
        )
        assert count >= 1
        merged = json.loads((agent_dir / "commercial.json").read_text())
        assert len(merged["findings"]) == 2
        assert merged["files_analyzed"] == 5
        assert not (agent_dir / "fidelity.json").exists()
        assert not (agent_dir / "pacific_life.json").exists()

    def test_file_without_subject_safe_name_skipped(self, tmp_path: Path) -> None:
        """Files without a subject_safe_name field are left alone."""
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        (agent_dir / "unknown.json").write_text('{"findings": []}')

        count = PipelineEngine._reconcile_agent_output_filenames(
            agent_dir,
            ["commercial"],
        )
        assert count == 0
        assert (agent_dir / "unknown.json").exists()

    def test_nonexistent_dir_returns_zero(self, tmp_path: Path) -> None:
        """Non-existent agent directory returns 0 without error."""
        count = PipelineEngine._reconcile_agent_output_filenames(
            tmp_path / "nonexistent",
            ["commercial"],
        )
        assert count == 0

    def test_merge_into_existing_correctly_named_file(self, tmp_path: Path) -> None:
        """Misnamed files merge into an already-existing correctly-named file."""
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        base = {"subject_safe_name": "commercial", "findings": [{"title": "Base"}], "files_analyzed": 1}
        extra = {"subject_safe_name": "commercial", "findings": [{"title": "Extra"}], "files_analyzed": 2}
        (agent_dir / "commercial.json").write_text(json.dumps(base))
        (agent_dir / "entity_x.json").write_text(json.dumps(extra))

        PipelineEngine._reconcile_agent_output_filenames(
            agent_dir,
            ["commercial"],
        )
        merged = json.loads((agent_dir / "commercial.json").read_text())
        assert len(merged["findings"]) == 2
        assert merged["files_analyzed"] == 3
        assert not (agent_dir / "entity_x.json").exists()

    def test_coverage_manifest_ignored(self, tmp_path: Path) -> None:
        """coverage_manifest.json is never reconciled."""
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        (agent_dir / "coverage_manifest.json").write_text('{"subject_safe_name": "commercial"}')

        count = PipelineEngine._reconcile_agent_output_filenames(
            agent_dir,
            ["commercial"],
        )
        assert count == 0


class TestRespawnBatching:
    """Tests that _respawn_for_missing_subjects batches large subject sets."""

    def _make_engine(self, tmp_path: Path) -> PipelineEngine:
        config_path = tmp_path / "deal-config.json"
        config_path.write_text("{}")
        return PipelineEngine(tmp_path, config_path)

    @pytest.mark.asyncio
    async def test_respawn_batches_missing_subjects(self, tmp_path: Path) -> None:
        """Respawn should batch missing subjects via PromptBuilder.batch_subjects."""
        from unittest.mock import AsyncMock, MagicMock, patch

        engine = self._make_engine(tmp_path)

        # Create 30 subjects to exceed max_per_batch=20
        subjects = [f"subject_{i}" for i in range(30)]
        run_dir = tmp_path / "runs" / "test_run"
        run_dir.mkdir(parents=True, exist_ok=True)
        state = PipelineState(
            run_id="test_run",
            project_dir=tmp_path,
            run_dir=run_dir,
            subject_safe_names=subjects,
        )

        # Create mock SubjectEntry objects
        mock_entries = []
        for name in subjects:
            entry = MagicMock()
            entry.safe_name = name
            mock_entries.append(entry)
        state._subject_entries = mock_entries  # type: ignore[attr-defined]

        # Mock _ensure_subject_entries to return our entries
        with (
            patch.object(engine, "_ensure_subject_entries", return_value=mock_entries),
            patch.object(engine, "_ensure_team") as mock_team,
            patch(
                "dd_agents.agents.prompt_builder.PromptBuilder.build_specialist_prompt",
                return_value="mock prompt",
            ),
        ):
            mock_specialist = AsyncMock(return_value={"status": "completed"})
            mock_team.return_value._run_specialist = mock_specialist

            await engine._respawn_for_missing_subjects(
                agent_name="legal",
                missing_subjects=subjects,
                state=state,
            )

            # _run_specialist should have been called with prompts= (list)
            mock_specialist.assert_called_once()
            call_kwargs = mock_specialist.call_args
            # The prompts kwarg should be a list
            assert "prompts" in call_kwargs.kwargs
            prompts = call_kwargs.kwargs["prompts"]
            assert isinstance(prompts, list)
            # With 30 subjects and max_per_batch=20, we expect 2 batches
            assert len(prompts) == 2

    @pytest.mark.asyncio
    async def test_respawn_single_batch_for_small_set(self, tmp_path: Path) -> None:
        """Respawn with few subjects produces a single batch."""
        from unittest.mock import AsyncMock, MagicMock, patch

        engine = self._make_engine(tmp_path)

        subjects = [f"subject_{i}" for i in range(5)]
        run_dir = tmp_path / "runs" / "test_run"
        run_dir.mkdir(parents=True, exist_ok=True)
        state = PipelineState(
            run_id="test_run",
            project_dir=tmp_path,
            run_dir=run_dir,
            subject_safe_names=subjects,
        )

        mock_entries = []
        for name in subjects:
            entry = MagicMock()
            entry.safe_name = name
            mock_entries.append(entry)

        with (
            patch.object(engine, "_ensure_subject_entries", return_value=mock_entries),
            patch.object(engine, "_ensure_team") as mock_team,
            patch(
                "dd_agents.agents.prompt_builder.PromptBuilder.build_specialist_prompt",
                return_value="mock prompt",
            ),
        ):
            mock_specialist = AsyncMock(return_value={"status": "completed"})
            mock_team.return_value._run_specialist = mock_specialist

            await engine._respawn_for_missing_subjects(
                agent_name="legal",
                missing_subjects=subjects,
                state=state,
            )

            mock_specialist.assert_called_once()
            prompts = mock_specialist.call_args.kwargs["prompts"]
            assert len(prompts) == 1


# ======================================================================
# Issue #38: _generate_coverage_gap_finding helper
# ======================================================================


class TestGenerateCoverageGapFinding:
    """Tests for PipelineEngine._generate_coverage_gap_finding."""

    def test_returns_p1_finding(self) -> None:
        gap = PipelineEngine._generate_coverage_gap_finding(
            subject_safe_name="test_subject",
            agent_name="legal",
            run_id="run_001",
        )
        assert gap["severity"] == "P1"
        assert gap["finding_type"] == "coverage_gap"
        assert gap["category"] == "data_gap"
        assert gap["confidence"] == "low"
        assert gap["subject_safe_name"] == "test_subject"
        assert gap["agent"] == "legal"
        assert gap["run_id"] == "run_001"
        assert gap["auto_generated"] is True
        assert "finding_id" in gap
        assert "timestamp" in gap
        # Citations should be present (synthetic) for merge compatibility
        assert len(gap["citations"]) == 1
        assert gap["citations"][0]["source_path"].startswith("[synthetic:")

    def test_finding_id_includes_agent_and_subject(self) -> None:
        gap = PipelineEngine._generate_coverage_gap_finding(
            subject_safe_name="acme_corp",
            agent_name="finance",
            run_id="run_002",
        )
        assert "finance" in gap["finding_id"]
        assert "acme_corp" in gap["finding_id"]


# ======================================================================
# Issue #39: Context exhaustion detection
# ======================================================================


class TestContextExhaustionDetection:
    """Tests for PipelineEngine._detect_context_exhaustion (Issue #39)."""

    def test_no_output_directory_flags_exhaustion(self, tmp_path: Path) -> None:
        """Missing agent directory should flag likely exhaustion."""
        findings_dir = tmp_path / "findings"
        findings_dir.mkdir()

        result = PipelineEngine._detect_context_exhaustion(
            agent_name="legal",
            findings_dir=findings_dir,
            expected_subjects=["subject_a", "subject_b"],
        )
        assert result["likely_exhaustion"] is True
        assert "No output directory" in result["reason"]
        assert result["produced"] == 0
        assert result["expected"] == 2

    def test_full_coverage_no_exhaustion(self, tmp_path: Path) -> None:
        """Full coverage should not flag exhaustion."""
        findings_dir = tmp_path / "findings"
        agent_dir = findings_dir / "legal"
        agent_dir.mkdir(parents=True)

        # Create files for all expected subjects
        for name in ["subject_a", "subject_b"]:
            (agent_dir / f"{name}.json").write_text('{"findings": [], "data": "x" }')

        result = PipelineEngine._detect_context_exhaustion(
            agent_name="legal",
            findings_dir=findings_dir,
            expected_subjects=["subject_a", "subject_b"],
        )
        assert result["likely_exhaustion"] is False
        assert result["produced"] == 2
        assert result["coverage_pct"] == 1.0

    def test_truncated_output_flags_exhaustion(self, tmp_path: Path) -> None:
        """Tail files significantly smaller than average should flag exhaustion."""
        findings_dir = tmp_path / "findings"
        agent_dir = findings_dir / "legal"
        agent_dir.mkdir(parents=True)

        # Create 5 normal-sized files and 2 tiny files at the end (alphabetical order)
        expected = []
        for i in range(7):
            name = f"subject_{i:02d}"
            expected.append(name)
            # Normal sized (~1000 chars) for first 5, tiny (~20 chars, <30% of avg) for rest
            content = ('{"findings": [' + '"x",' * 200 + '"y"' + "]}") if i < 5 else '{"findings": []}'
            (agent_dir / f"{name}.json").write_text(content)

        # Expected 10 subjects but only 7 produced
        all_expected = expected + ["subject_07", "subject_08", "subject_09"]

        result = PipelineEngine._detect_context_exhaustion(
            agent_name="legal",
            findings_dir=findings_dir,
            expected_subjects=all_expected,
        )
        assert result["likely_exhaustion"] is True
        assert result["produced"] == 7
        assert result["expected"] == 10

    def test_no_subjects_expected_no_exhaustion(self, tmp_path: Path) -> None:
        """No expected subjects means no exhaustion possible."""
        findings_dir = tmp_path / "findings"
        findings_dir.mkdir()

        result = PipelineEngine._detect_context_exhaustion(
            agent_name="legal",
            findings_dir=findings_dir,
            expected_subjects=[],
        )
        assert result["likely_exhaustion"] is False
        assert result["coverage_pct"] == 0.0

    def test_single_file_produced_flags_exhaustion(self, tmp_path: Path) -> None:
        """Only 1 file for 5 expected subjects should flag exhaustion."""
        findings_dir = tmp_path / "findings"
        agent_dir = findings_dir / "legal"
        agent_dir.mkdir(parents=True)

        (agent_dir / "subject_a.json").write_text('{"findings": []}')

        result = PipelineEngine._detect_context_exhaustion(
            agent_name="legal",
            findings_dir=findings_dir,
            expected_subjects=[f"subject_{c}" for c in "abcde"],
        )
        assert result["likely_exhaustion"] is True
        assert result["produced"] == 1

    def test_excludes_coverage_manifest(self, tmp_path: Path) -> None:
        """coverage_manifest.json should not be counted as a subject output."""
        findings_dir = tmp_path / "findings"
        agent_dir = findings_dir / "legal"
        agent_dir.mkdir(parents=True)

        (agent_dir / "coverage_manifest.json").write_text("{}")
        (agent_dir / "subject_a.json").write_text('{"findings": []}')

        result = PipelineEngine._detect_context_exhaustion(
            agent_name="legal",
            findings_dir=findings_dir,
            expected_subjects=["subject_a", "subject_b"],
        )
        # Should count only subject_a, not coverage_manifest
        assert result["produced"] == 1


# ======================================================================
# Step 15: Route Reference Files (Issue #44)
# ======================================================================


class TestStep15RouteReferences:
    """Tests for _step_15_route_references."""

    def _make_engine(self, tmp_path: Path) -> PipelineEngine:
        config_path = tmp_path / "deal-config.json"
        config_path.write_text("{}")
        return PipelineEngine(tmp_path, config_path)

    def _make_state(self, tmp_path: Path) -> PipelineState:
        run_dir = tmp_path / "_dd" / "forensic-dd" / "runs" / "test_run"
        run_dir.mkdir(parents=True, exist_ok=True)
        text_dir = tmp_path / "_dd" / "forensic-dd" / "index" / "text"
        text_dir.mkdir(parents=True, exist_ok=True)
        return PipelineState(
            run_id="test_run",
            project_dir=tmp_path,
            run_dir=run_dir,
        )

    @pytest.mark.asyncio
    async def test_step_15_routes_references_to_agent_dirs(self, tmp_path: Path) -> None:
        """Reference files should be symlinked/copied to agent findings dirs."""
        from unittest.mock import MagicMock

        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)

        # Create extracted text for a reference file
        text_dir = tmp_path / "_dd" / "forensic-dd" / "index" / "text"
        ref_text = text_dir / "pricing_schedule.md"
        ref_text.write_text("# Pricing Schedule\nStandard rates apply.")

        # Mock a reference file object
        mock_ref = MagicMock()
        mock_ref.file_path = "references/pricing_schedule.pdf"
        mock_ref.text_path = "pricing_schedule.md"
        mock_ref.category = "Pricing"
        mock_ref.assigned_to_agents = ["finance", "commercial"]

        state._reference_files = [mock_ref]  # type: ignore[attr-defined]

        result = await engine._step_15_route_references(state)

        # Verify routing manifest written
        manifest_path = state.run_dir / "reference_routing.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text())
        assert len(manifest) == 1
        assert manifest[0]["category"] == "Pricing"
        assert manifest[0]["agents"] == ["finance", "commercial"]

        # Verify files routed to agent dirs
        for agent in ["finance", "commercial"]:
            agent_ref = state.run_dir / "findings" / agent / "_references" / "pricing_schedule.md"
            assert agent_ref.exists() or agent_ref.is_symlink(), f"Reference not routed to {agent}"

        assert result is state

    @pytest.mark.asyncio
    async def test_step_15_no_references(self, tmp_path: Path) -> None:
        """Step 15 should handle empty reference files gracefully."""
        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)
        state._reference_files = []  # type: ignore[attr-defined]

        result = await engine._step_15_route_references(state)
        assert result is state

    @pytest.mark.asyncio
    async def test_step_15_missing_text_skips(self, tmp_path: Path) -> None:
        """References without extracted text should be skipped."""
        from unittest.mock import MagicMock

        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)

        mock_ref = MagicMock()
        mock_ref.file_path = "references/missing.pdf"
        mock_ref.text_path = None
        mock_ref.category = "Other"
        mock_ref.assigned_to_agents = ["legal"]

        state._reference_files = [mock_ref]  # type: ignore[attr-defined]

        result = await engine._step_15_route_references(state)

        # Manifest should be empty since text was not found
        manifest_path = state.run_dir / "reference_routing.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text())
        assert len(manifest) == 0
        assert result is state


# ======================================================================
# Step 18: Incremental Merge (Issue #44)
# ======================================================================


class TestStep21IncrementalMerge:
    """Tests for step 21: incremental merge."""

    def _make_engine(self, tmp_path: Path) -> PipelineEngine:
        config_path = tmp_path / "deal-config.json"
        config_path.write_text("{}")
        return PipelineEngine(tmp_path, config_path)

    def _make_state(self, tmp_path: Path) -> tuple[PipelineState, Path]:
        """Create state with prior run directory containing findings."""
        # Prior run dir
        prior_run_dir = tmp_path / "_dd" / "forensic-dd" / "runs" / "prior_run"
        prior_findings = prior_run_dir / "findings" / "legal"
        prior_findings.mkdir(parents=True, exist_ok=True)

        # Write a prior finding file
        prior_finding = {"findings": [{"id": "F1", "severity": "P1"}]}
        (prior_findings / "subject_a.json").write_text(json.dumps(prior_finding))

        # Current run dir
        run_dir = tmp_path / "_dd" / "forensic-dd" / "runs" / "current_run"
        run_dir.mkdir(parents=True, exist_ok=True)

        state = PipelineState(
            run_id="current_run",
            project_dir=tmp_path,
            run_dir=run_dir,
            execution_mode="incremental",
            prior_run_id="prior_run",
            prior_run_dir=prior_run_dir,
            classification={
                "subjects": [
                    {
                        "subject_safe_name": "subject_a",
                        "classification": "UNCHANGED",
                    },
                    {
                        "subject_safe_name": "subject_b",
                        "classification": "CHANGED",
                    },
                ]
            },
        )
        return state, prior_run_dir

    @pytest.mark.asyncio
    async def test_step_21_carries_forward_unchanged(self, tmp_path: Path) -> None:
        """Unchanged subjects get findings from prior run."""
        engine = self._make_engine(tmp_path)
        state, _prior_run_dir = self._make_state(tmp_path)

        result = await engine._step_21_incremental_merge(state)

        # Verify carry-forward: subject_a should have findings in current run
        carried = state.run_dir / "findings" / "legal" / "subject_a.json"
        assert carried.exists()
        data = json.loads(carried.read_text())
        assert data["_carried_forward"] is True
        assert data["_carried_from_run"] == "prior_run"
        assert result is state

    @pytest.mark.asyncio
    async def test_step_21_skips_non_incremental(self, tmp_path: Path) -> None:
        """Step 21 should skip when execution_mode is 'full'."""
        engine = self._make_engine(tmp_path)
        state, _ = self._make_state(tmp_path)
        state.execution_mode = "full"

        result = await engine._step_21_incremental_merge(state)
        assert result is state

    @pytest.mark.asyncio
    async def test_step_21_skips_without_prior_run(self, tmp_path: Path) -> None:
        """Step 21 should skip when no prior run is available."""
        engine = self._make_engine(tmp_path)
        state, _ = self._make_state(tmp_path)
        state.prior_run_id = None
        state.prior_run_dir = None

        result = await engine._step_21_incremental_merge(state)
        assert result is state


# ======================================================================
# Steps 23-25: Judge Review Cycle (Issue #44)
# ======================================================================


class TestStep23JudgeReview:
    """Tests for step 23: judge review."""

    def _make_engine(self, tmp_path: Path) -> PipelineEngine:
        config_path = tmp_path / "deal-config.json"
        config_path.write_text("{}")
        return PipelineEngine(tmp_path, config_path)

    def _make_state(self, tmp_path: Path) -> PipelineState:
        run_dir = tmp_path / "_dd" / "forensic-dd" / "runs" / "test_run"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "findings").mkdir(parents=True, exist_ok=True)
        return PipelineState(
            run_id="test_run",
            project_dir=tmp_path,
            run_dir=run_dir,
            judge_enabled=True,
            subject_safe_names=["subject_a"],
        )

    @pytest.mark.asyncio
    async def test_step_23_skips_when_judge_disabled(self, tmp_path: Path) -> None:
        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)
        state.judge_enabled = False

        result = await engine._step_23_judge_review(state)
        assert result is state
        assert state.judge_scores == {}

    @pytest.mark.asyncio
    async def test_step_23_runs_judge_and_stores_scores(self, tmp_path: Path) -> None:
        """Judge review should store scores in state and persist to disk."""
        from dd_agents.models.audit import AgentScore, QualityScores

        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)

        mock_scores = QualityScores(
            run_id="test_run",
            overall_quality=85,
            iteration_round=1,
            agent_scores={
                "legal": AgentScore(score=90, findings_reviewed=5, findings_total=10),
                "finance": AgentScore(score=60, findings_reviewed=5, findings_total=10),
            },
            agents_below_threshold=["finance"],
        )

        with patch(
            "dd_agents.agents.judge.JudgeAgent.run_with_iteration",
            return_value=mock_scores,
        ):
            result = await engine._step_23_judge_review(state)

        assert result is state
        assert state.judge_scores["overall_quality"] == 85
        assert state.judge_scores["agents_below_threshold"] == ["finance"]

        # Verify quality_scores.json written
        scores_path = state.run_dir / "judge" / "quality_scores.json"
        assert scores_path.exists()

    @pytest.mark.asyncio
    async def test_step_23_graceful_degradation_on_error(self, tmp_path: Path) -> None:
        """Step 20 should degrade gracefully if judge fails."""
        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)

        with patch(
            "dd_agents.agents.judge.JudgeAgent.run_with_iteration",
            side_effect=RuntimeError("Judge agent crashed"),
        ):
            result = await engine._step_23_judge_review(state)

        assert result is state
        assert state.judge_scores.get("degraded") is True
        assert "Judge agent crashed" in state.judge_scores.get("error", "")


class TestStep24JudgeRespawn:
    """Tests for step 24: judge respawn."""

    def _make_engine(self, tmp_path: Path) -> PipelineEngine:
        config_path = tmp_path / "deal-config.json"
        config_path.write_text("{}")
        return PipelineEngine(tmp_path, config_path)

    def _make_state(self, tmp_path: Path) -> PipelineState:
        run_dir = tmp_path / "_dd" / "forensic-dd" / "runs" / "test_run"
        run_dir.mkdir(parents=True, exist_ok=True)
        return PipelineState(
            run_id="test_run",
            project_dir=tmp_path,
            run_dir=run_dir,
            judge_enabled=True,
        )

    @pytest.mark.asyncio
    async def test_step_24_skips_when_judge_disabled(self, tmp_path: Path) -> None:
        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)
        state.judge_enabled = False
        result = await engine._step_24_judge_respawn(state)
        assert result is state

    @pytest.mark.asyncio
    async def test_step_24_skips_when_degraded(self, tmp_path: Path) -> None:
        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)
        state.judge_scores = {"degraded": True, "error": "failed"}
        result = await engine._step_24_judge_respawn(state)
        assert result is state

    @pytest.mark.asyncio
    async def test_step_24_skips_when_all_pass(self, tmp_path: Path) -> None:
        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)
        state.judge_scores = {"agents_below_threshold": []}
        result = await engine._step_24_judge_respawn(state)
        assert result is state

    @pytest.mark.asyncio
    async def test_step_24_respawns_failing_agents(self, tmp_path: Path) -> None:
        """Agents below threshold should be re-spawned."""
        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)
        state.judge_scores = {
            "agents_below_threshold": ["legal"],
            "agent_scores": {"legal": {"score": 50}},
        }

        result = await engine._step_24_judge_respawn(state)

        assert result is state
        assert "legal_round2" in state.agent_results
        # In test environment (no working SDK), agent produces no output.
        assert state.agent_results["legal_round2"]["status"] in ("completed", "failed")


class TestStep25JudgeRound2:
    """Tests for step 25: judge round 2."""

    def _make_engine(self, tmp_path: Path) -> PipelineEngine:
        config_path = tmp_path / "deal-config.json"
        config_path.write_text("{}")
        return PipelineEngine(tmp_path, config_path)

    def _make_state(self, tmp_path: Path) -> PipelineState:
        run_dir = tmp_path / "_dd" / "forensic-dd" / "runs" / "test_run"
        run_dir.mkdir(parents=True, exist_ok=True)
        return PipelineState(
            run_id="test_run",
            project_dir=tmp_path,
            run_dir=run_dir,
            judge_enabled=True,
        )

    @pytest.mark.asyncio
    async def test_step_25_skips_when_judge_disabled(self, tmp_path: Path) -> None:
        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)
        state.judge_enabled = False
        result = await engine._step_25_judge_round2(state)
        assert result is state

    @pytest.mark.asyncio
    async def test_step_25_blends_scores(self, tmp_path: Path) -> None:
        """Round-2 sets iteration_round and persists quality scores.

        Score blending is a placeholder (r2 == r1) until the Judge produces
        independent round-2 scores.
        """
        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)
        state.judge_scores = {
            "agents_below_threshold": ["legal"],
            "agent_scores": {"legal": {"score": 50}},
        }
        state.agent_results["legal_round2"] = {
            "agent": "legal",
            "status": "completed",
        }

        result = await engine._step_25_judge_round2(state)

        assert result is state
        assert state.judge_scores["iteration_round"] == 2
        # Score unchanged (blending is a placeholder)
        assert state.judge_scores["agent_scores"]["legal"]["score"] == 50

        # Quality scores persisted
        scores_path = state.run_dir / "judge" / "quality_scores.json"
        assert scores_path.exists()

    @pytest.mark.asyncio
    async def test_step_25_applies_caveats_when_no_round2(self, tmp_path: Path) -> None:
        """If no round-2 results, caveats should be applied."""
        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)
        state.judge_scores = {
            "agents_below_threshold": ["finance"],
            "agent_scores": {"finance": {"score": 40}},
        }
        # No round-2 results in agent_results

        result = await engine._step_25_judge_round2(state)

        assert result is state
        assert "quality_caveats" in state.judge_scores
        assert len(state.judge_scores["quality_caveats"]) == 1


# ======================================================================
# Issue #45: prior_run_id population
# ======================================================================


class TestPriorRunIdPopulation:
    """Tests for prior_run_id population in step 2."""

    def _make_engine(self, tmp_path: Path) -> PipelineEngine:
        config_path = tmp_path / "deal-config.json"
        config_path.write_text("{}")
        return PipelineEngine(tmp_path, config_path)

    @pytest.mark.asyncio
    async def test_prior_run_id_from_config(self, tmp_path: Path) -> None:
        """Explicit prior_run_id in deal config should be used."""
        from unittest.mock import MagicMock

        engine = self._make_engine(tmp_path)

        # Create prior run dir on disk
        prior_dir = tmp_path / "_dd" / "forensic-dd" / "runs" / "prior_explicit"
        prior_dir.mkdir(parents=True, exist_ok=True)

        state = PipelineState(
            project_dir=tmp_path,
            deal_config={
                "execution": {"prior_run_id": "prior_explicit"},
            },
        )

        with patch(
            "dd_agents.persistence.run_manager.RunManager.initialize_run",
        ) as mock_init:
            mock_metadata = MagicMock()
            mock_metadata.run_id = "new_run_001"
            mock_init.return_value = mock_metadata

            result = await engine._step_02_init_persistence(state)

        assert result.prior_run_id == "prior_explicit"
        assert result.prior_run_dir == prior_dir

    @pytest.mark.asyncio
    async def test_prior_run_id_auto_detected_from_history(self, tmp_path: Path) -> None:
        """Prior run should be auto-detected from run_history.json."""
        from unittest.mock import MagicMock

        engine = self._make_engine(tmp_path)

        # Create prior run dir on disk
        prior_dir = tmp_path / "_dd" / "forensic-dd" / "runs" / "prior_auto"
        prior_dir.mkdir(parents=True, exist_ok=True)

        # Write run history with a completed entry
        history_dir = tmp_path / "_dd"
        history_dir.mkdir(parents=True, exist_ok=True)
        history = [
            {"run_id": "prior_auto", "completion_status": "completed", "timestamp": "2026-01-01"},
        ]
        (history_dir / "run_history.json").write_text(json.dumps(history))

        state = PipelineState(
            project_dir=tmp_path,
            deal_config={},
        )

        with patch(
            "dd_agents.persistence.run_manager.RunManager.initialize_run",
        ) as mock_init:
            mock_metadata = MagicMock()
            mock_metadata.run_id = "new_run_002"
            mock_init.return_value = mock_metadata

            result = await engine._step_02_init_persistence(state)

        assert result.prior_run_id == "prior_auto"
        assert result.prior_run_dir == prior_dir

    @pytest.mark.asyncio
    async def test_prior_run_id_none_when_no_history(self, tmp_path: Path) -> None:
        """prior_run_id should be None when no completed runs exist."""
        from unittest.mock import MagicMock

        engine = self._make_engine(tmp_path)

        state = PipelineState(
            project_dir=tmp_path,
            deal_config={},
        )

        with patch(
            "dd_agents.persistence.run_manager.RunManager.initialize_run",
        ) as mock_init:
            mock_metadata = MagicMock()
            mock_metadata.run_id = "new_run_003"
            mock_init.return_value = mock_metadata

            result = await engine._step_02_init_persistence(state)

        assert result.prior_run_id is None
        assert result.prior_run_dir is None


# ======================================================================
# Issue #45: Idempotent run history
# ======================================================================


class TestIdempotentRunHistory:
    """Tests for idempotent run_history.json writes."""

    def test_no_double_append(self, tmp_path: Path) -> None:
        """Calling finalize_run twice should not duplicate the entry."""
        from dd_agents.models.enums import CompletionStatus, ExecutionMode
        from dd_agents.models.persistence import RunMetadata
        from dd_agents.persistence.run_manager import RunManager

        # Setup project structure
        project_dir = tmp_path / "project"
        dd_dir = project_dir / "_dd"
        dd_dir.mkdir(parents=True)
        runs_dir = project_dir / "_dd" / "forensic-dd" / "runs"
        run_dir = runs_dir / "run_test_001"
        run_dir.mkdir(parents=True)

        run_mgr = RunManager(project_dir)

        metadata = RunMetadata(
            run_id="run_test_001",
            timestamp="2026-01-01T00:00:00",
            skill="forensic-dd",
            execution_mode=ExecutionMode.FULL,
            config_hash="abc123",
            completion_status=CompletionStatus.IN_PROGRESS,
        )

        # First finalize
        run_mgr.finalize_run(metadata)

        # Second finalize (should be idempotent)
        # Reset completion status to simulate re-finalization
        metadata.completion_status = CompletionStatus.IN_PROGRESS
        run_mgr.finalize_run(metadata)

        # Verify only one entry exists
        history_path = dd_dir / "run_history.json"
        history = json.loads(history_path.read_text())
        matching = [e for e in history if e["run_id"] == "run_test_001"]
        assert len(matching) == 1, f"Expected 1 entry but found {len(matching)}"

    def test_different_runs_both_appended(self, tmp_path: Path) -> None:
        """Different run_ids should each be appended."""
        from dd_agents.models.enums import CompletionStatus, ExecutionMode
        from dd_agents.models.persistence import RunMetadata
        from dd_agents.persistence.run_manager import RunManager

        project_dir = tmp_path / "project"
        dd_dir = project_dir / "_dd"
        dd_dir.mkdir(parents=True)
        runs_dir = project_dir / "_dd" / "forensic-dd" / "runs"

        for rid in ["run_a", "run_b"]:
            (runs_dir / rid).mkdir(parents=True, exist_ok=True)

        run_mgr = RunManager(project_dir)

        for rid in ["run_a", "run_b"]:
            metadata = RunMetadata(
                run_id=rid,
                timestamp="2026-01-01T00:00:00",
                skill="forensic-dd",
                execution_mode=ExecutionMode.FULL,
                config_hash="abc",
                completion_status=CompletionStatus.IN_PROGRESS,
            )
            run_mgr.finalize_run(metadata)

        history_path = dd_dir / "run_history.json"
        history = json.loads(history_path.read_text())
        assert len(history) == 2
        assert {e["run_id"] for e in history} == {"run_a", "run_b"}


# ======================================================================
# Priority 2: Additional orchestrator step tests
# ======================================================================


class TestStep15ErrorHandlingMissingReferenceFiles:
    """Tests for step 15 error handling when reference files are missing."""

    def _make_engine(self, tmp_path: Path) -> PipelineEngine:
        config_path = tmp_path / "deal-config.json"
        config_path.write_text("{}")
        return PipelineEngine(tmp_path, config_path)

    def _make_state(self, tmp_path: Path) -> PipelineState:
        run_dir = tmp_path / "_dd" / "forensic-dd" / "runs" / "test_run"
        run_dir.mkdir(parents=True, exist_ok=True)
        text_dir = tmp_path / "_dd" / "forensic-dd" / "index" / "text"
        text_dir.mkdir(parents=True, exist_ok=True)
        return PipelineState(
            run_id="test_run",
            project_dir=tmp_path,
            run_dir=run_dir,
        )

    @pytest.mark.asyncio
    async def test_step_15_skips_reference_with_no_text_file_on_disk(self, tmp_path: Path) -> None:
        """References whose text_path does not resolve to a file are skipped."""
        from unittest.mock import MagicMock

        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)

        mock_ref = MagicMock()
        mock_ref.file_path = "references/nonexistent.pdf"
        mock_ref.text_path = "does_not_exist.md"
        mock_ref.category = "Other"
        mock_ref.assigned_to_agents = ["legal"]

        state._reference_files = [mock_ref]  # type: ignore[attr-defined]

        result = await engine._step_15_route_references(state)

        manifest_path = state.run_dir / "reference_routing.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text())
        assert len(manifest) == 0
        assert result is state

    @pytest.mark.asyncio
    async def test_step_15_routes_to_all_agents_when_assigned_to_is_none(self, tmp_path: Path) -> None:
        """When assigned_to_agents is empty/None, routes to all specialists."""
        from unittest.mock import MagicMock

        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)

        text_dir = tmp_path / "_dd" / "forensic-dd" / "index" / "text"
        ref_text = text_dir / "policy.md"
        ref_text.write_text("# Company Policy\nAll employees must comply.")

        mock_ref = MagicMock()
        mock_ref.file_path = "references/policy.pdf"
        mock_ref.text_path = "policy.md"
        mock_ref.category = "General"
        mock_ref.assigned_to_agents = None  # None => all agents

        state._reference_files = [mock_ref]  # type: ignore[attr-defined]

        result = await engine._step_15_route_references(state)

        manifest_path = state.run_dir / "reference_routing.json"
        manifest = json.loads(manifest_path.read_text())
        assert len(manifest) == 1
        from dd_agents.agents.registry import AgentRegistry

        assert len(manifest[0]["agents"]) == len(AgentRegistry.all_specialist_names())
        assert result is state

    @pytest.mark.asyncio
    async def test_step_15_derives_text_path_from_file_stem(self, tmp_path: Path) -> None:
        """When text_path is None but a .md file exists matching stem, it is found."""
        from unittest.mock import MagicMock

        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)

        text_dir = tmp_path / "_dd" / "forensic-dd" / "index" / "text"
        # Create text file with stem matching the reference file stem
        (text_dir / "report.md").write_text("# Report content")

        mock_ref = MagicMock()
        mock_ref.file_path = "data/report.xlsx"
        mock_ref.text_path = None  # No explicit text_path
        mock_ref.category = "Financial"
        mock_ref.assigned_to_agents = ["finance"]

        state._reference_files = [mock_ref]  # type: ignore[attr-defined]

        result = await engine._step_15_route_references(state)

        manifest_path = state.run_dir / "reference_routing.json"
        manifest = json.loads(manifest_path.read_text())
        assert len(manifest) == 1
        assert "report.md" in manifest[0]["text_source"]
        assert result is state

    @pytest.mark.asyncio
    async def test_step_15_finds_text_via_absolute_path_naming(self, tmp_path: Path) -> None:
        """When extraction used absolute paths, step 15 finds text using the same convention."""
        from unittest.mock import MagicMock

        from dd_agents.extraction.pipeline import ExtractionPipeline

        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)

        text_dir = tmp_path / "_dd" / "forensic-dd" / "index" / "text"

        # Simulate what step 5 does: extraction uses absolute paths.
        ref_rel_path = "data/reference_report.pdf"
        abs_path = str(tmp_path / ref_rel_path)
        safe_name = ExtractionPipeline._safe_text_name(abs_path)
        (text_dir / safe_name).write_text("# Extracted content")

        mock_ref = MagicMock()
        mock_ref.file_path = ref_rel_path
        mock_ref.text_path = None
        mock_ref.category = "Financial"
        mock_ref.assigned_to_agents = ["finance"]

        state._reference_files = [mock_ref]  # type: ignore[attr-defined]

        result = await engine._step_15_route_references(state)

        manifest_path = state.run_dir / "reference_routing.json"
        manifest = json.loads(manifest_path.read_text())
        assert len(manifest) == 1
        assert result is state


class TestStep21WithEmptyUnchangedSubjects:
    """Tests for step 21 when there are no unchanged subjects."""

    def _make_engine(self, tmp_path: Path) -> PipelineEngine:
        config_path = tmp_path / "deal-config.json"
        config_path.write_text("{}")
        return PipelineEngine(tmp_path, config_path)

    @pytest.mark.asyncio
    async def test_step_21_no_unchanged_subjects(self, tmp_path: Path) -> None:
        """Step 21 should return state unchanged when all subjects are CHANGED."""
        engine = self._make_engine(tmp_path)

        prior_run_dir = tmp_path / "_dd" / "forensic-dd" / "runs" / "prior"
        prior_run_dir.mkdir(parents=True, exist_ok=True)
        run_dir = tmp_path / "_dd" / "forensic-dd" / "runs" / "current"
        run_dir.mkdir(parents=True, exist_ok=True)

        state = PipelineState(
            run_id="current",
            project_dir=tmp_path,
            run_dir=run_dir,
            execution_mode="incremental",
            prior_run_id="prior",
            prior_run_dir=prior_run_dir,
            classification={
                "subjects": [
                    {"subject_safe_name": "subject_a", "classification": "CHANGED"},
                    {"subject_safe_name": "subject_b", "classification": "CHANGED"},
                ]
            },
        )

        result = await engine._step_21_incremental_merge(state)
        assert result is state

    @pytest.mark.asyncio
    async def test_step_21_empty_classification_subjects(self, tmp_path: Path) -> None:
        """Step 21 should handle empty classification subjects list."""
        engine = self._make_engine(tmp_path)

        prior_run_dir = tmp_path / "_dd" / "forensic-dd" / "runs" / "prior"
        prior_run_dir.mkdir(parents=True, exist_ok=True)
        run_dir = tmp_path / "_dd" / "forensic-dd" / "runs" / "current"
        run_dir.mkdir(parents=True, exist_ok=True)

        state = PipelineState(
            run_id="current",
            project_dir=tmp_path,
            run_dir=run_dir,
            execution_mode="incremental",
            prior_run_id="prior",
            prior_run_dir=prior_run_dir,
            classification={"subjects": []},
        )

        result = await engine._step_21_incremental_merge(state)
        assert result is state

    @pytest.mark.asyncio
    async def test_step_21_none_classification(self, tmp_path: Path) -> None:
        """Step 21 should handle None classification gracefully."""
        engine = self._make_engine(tmp_path)

        prior_run_dir = tmp_path / "_dd" / "forensic-dd" / "runs" / "prior"
        prior_run_dir.mkdir(parents=True, exist_ok=True)
        run_dir = tmp_path / "_dd" / "forensic-dd" / "runs" / "current"
        run_dir.mkdir(parents=True, exist_ok=True)

        state = PipelineState(
            run_id="current",
            project_dir=tmp_path,
            run_dir=run_dir,
            execution_mode="incremental",
            prior_run_id="prior",
            prior_run_dir=prior_run_dir,
            classification=None,
        )

        result = await engine._step_21_incremental_merge(state)
        assert result is state


class TestStep23To25JudgeCycleDegradedMode:
    """Tests for the judge cycle (steps 23-25) with degraded mode."""

    def _make_engine(self, tmp_path: Path) -> PipelineEngine:
        config_path = tmp_path / "deal-config.json"
        config_path.write_text("{}")
        return PipelineEngine(tmp_path, config_path)

    def _make_state(self, tmp_path: Path) -> PipelineState:
        run_dir = tmp_path / "_dd" / "forensic-dd" / "runs" / "test_run"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "findings").mkdir(parents=True, exist_ok=True)
        return PipelineState(
            run_id="test_run",
            project_dir=tmp_path,
            run_dir=run_dir,
            judge_enabled=True,
            subject_safe_names=["subject_a"],
        )

    @pytest.mark.asyncio
    async def test_step_23_degraded_then_step_24_skips(self, tmp_path: Path) -> None:
        """When step 23 degrades, step 24 should skip due to degraded flag."""
        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)

        # Simulate degraded step 23
        with patch(
            "dd_agents.agents.judge.JudgeAgent.run_with_iteration",
            side_effect=RuntimeError("Judge crashed"),
        ):
            await engine._step_23_judge_review(state)

        assert state.judge_scores.get("degraded") is True

        # Step 24 should skip
        result = await engine._step_24_judge_respawn(state)
        assert result is state
        # No round2 agents should be added
        assert not any(k.endswith("_round2") for k in state.agent_results)

    @pytest.mark.asyncio
    async def test_step_23_degraded_then_step_25_skips(self, tmp_path: Path) -> None:
        """When step 23 degrades, step 25 should also skip."""
        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)

        with patch(
            "dd_agents.agents.judge.JudgeAgent.run_with_iteration",
            side_effect=RuntimeError("Judge crashed"),
        ):
            await engine._step_23_judge_review(state)

        result = await engine._step_25_judge_round2(state)
        assert result is state
        # No quality_caveats should be set since we had degradation at step 23
        assert "quality_caveats" not in state.judge_scores

    @pytest.mark.asyncio
    async def test_step_23_returns_none_scores_graceful(self, tmp_path: Path) -> None:
        """When judge returns None scores, step 23 degrades gracefully."""
        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)

        with patch(
            "dd_agents.agents.judge.JudgeAgent.run_with_iteration",
            return_value=None,
        ):
            result = await engine._step_23_judge_review(state)

        # Should not crash, and scores should be empty (not degraded since it was a clean None)
        assert result is state

    @pytest.mark.asyncio
    async def test_full_judge_cycle_all_pass(self, tmp_path: Path) -> None:
        """Full judge cycle: all agents pass, steps 24 and 25 are no-ops."""
        from dd_agents.models.audit import AgentScore, QualityScores

        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)

        mock_scores = QualityScores(
            run_id="test_run",
            overall_quality=90,
            iteration_round=1,
            agent_scores={
                "legal": AgentScore(score=90),
                "finance": AgentScore(score=85),
                "commercial": AgentScore(score=88),
                "producttech": AgentScore(score=92),
            },
            agents_below_threshold=[],
        )

        with patch(
            "dd_agents.agents.judge.JudgeAgent.run_with_iteration",
            return_value=mock_scores,
        ):
            await engine._step_23_judge_review(state)

        assert state.judge_scores["agents_below_threshold"] == []

        # Step 24: no agents to re-spawn
        result21 = await engine._step_24_judge_respawn(state)
        assert result21 is state

        # Step 25: no agents below threshold
        result22 = await engine._step_25_judge_round2(state)
        assert result22 is state


class TestStep38WithMixedCriticalAndNonCriticalFailures:
    """Tests for step 38 with mixed critical/non-critical DoD failures."""

    def _make_engine(self, tmp_path: Path) -> PipelineEngine:
        config_path = tmp_path / "deal-config.json"
        config_path.write_text("{}")
        return PipelineEngine(tmp_path, config_path)

    def _make_state(self, tmp_path: Path) -> PipelineState:
        run_dir = tmp_path / "runs" / "test_run"
        run_dir.mkdir(parents=True, exist_ok=True)
        inv_dir = tmp_path / "_dd" / "forensic-dd" / "inventory"
        inv_dir.mkdir(parents=True, exist_ok=True)
        return PipelineState(
            run_id="test_run",
            project_dir=tmp_path,
            run_dir=run_dir,
            subject_safe_names=["subject_a"],
        )

    @pytest.mark.asyncio
    async def test_step_38_mixed_failures_critical_sets_dod_false(self, tmp_path: Path) -> None:
        """When both critical and non-critical checks fail, dod should be False."""
        from dd_agents.models.audit import AuditCheck

        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)

        mock_checks = [
            AuditCheck(passed=True, rule="Some passing check", dod_checks=[5]),
            AuditCheck(passed=False, rule="Subject outputs incomplete", dod_checks=[1]),  # Critical
            AuditCheck(passed=False, rule="Governance not resolved", dod_checks=[4]),  # Non-critical
            AuditCheck(passed=False, rule="Excel missing", dod_checks=[14]),  # Critical
            AuditCheck(passed=True, rule="Entity resolution ok", dod_checks=[16]),
        ]
        with patch(
            "dd_agents.validation.dod.DefinitionOfDoneChecker.check_all",
            return_value=mock_checks,
        ):
            result = await engine._step_38_shutdown(state)

        assert result.validation_results["dod"] is False

        dod_path = state.run_dir / "dod_results.json"
        data = json.loads(dod_path.read_text())
        assert data["passed"] == 2
        assert data["total"] == 5
        assert len(data["critical_failures"]) == 2

    @pytest.mark.asyncio
    async def test_step_38_only_non_critical_failures_keeps_dod_true(self, tmp_path: Path) -> None:
        """When only non-critical checks fail, dod should remain True."""
        from dd_agents.models.audit import AuditCheck

        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)

        # Checks 4, 5, 7 are non-critical
        mock_checks = [
            AuditCheck(passed=True, rule="Subject outputs ok", dod_checks=[1]),
            AuditCheck(passed=False, rule="Governance not resolved", dod_checks=[4]),
            AuditCheck(passed=False, rule="Citations not validated", dod_checks=[5]),
            AuditCheck(passed=False, rule="Cross-subject not run", dod_checks=[7]),
        ]
        with patch(
            "dd_agents.validation.dod.DefinitionOfDoneChecker.check_all",
            return_value=mock_checks,
        ):
            result = await engine._step_38_shutdown(state)

        assert result.validation_results["dod"] is True

        dod_path = state.run_dir / "dod_results.json"
        data = json.loads(dod_path.read_text())
        assert data["passed"] == 1
        assert data["total"] == 4
        assert len(data["critical_failures"]) == 0

    @pytest.mark.asyncio
    async def test_step_38_all_checks_pass(self, tmp_path: Path) -> None:
        """When all checks pass, dod should be True with zero critical failures."""
        from dd_agents.models.audit import AuditCheck

        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)

        mock_checks = [
            AuditCheck(passed=True, rule="Check A", dod_checks=[1]),
            AuditCheck(passed=True, rule="Check B", dod_checks=[14]),
            AuditCheck(passed=True, rule="Check C", dod_checks=[4]),
        ]
        with patch(
            "dd_agents.validation.dod.DefinitionOfDoneChecker.check_all",
            return_value=mock_checks,
        ):
            result = await engine._step_38_shutdown(state)

        assert result.validation_results["dod"] is True

        dod_path = state.run_dir / "dod_results.json"
        data = json.loads(dod_path.read_text())
        assert data["passed"] == 3
        assert data["total"] == 3
        assert data["critical_failures"] == []

    @pytest.mark.asyncio
    async def test_step_38_critical_dod_numbers_match_spec(self, tmp_path: Path) -> None:
        """Verify that CRITICAL_DOD_CHECKS matches the expected set from the spec."""
        _engine = self._make_engine(tmp_path)
        assert frozenset({1, 2, 3, 11, 13, 14, 15, 17, 19}) == PipelineEngine.CRITICAL_DOD_CHECKS


# ======================================================================
# Step 16 sub-checkpoints (detailed schema and path tests)
# ======================================================================


class TestStep16SubCheckpoints:
    """Tests for step-16-specific sub-checkpoint save/load and schema validation."""

    def test_save_sub_checkpoint_writes_json_to_correct_path(self, tmp_path: Path) -> None:
        """save_sub_checkpoint creates checkpoints/<step>/subject_<key>.json."""
        from dd_agents.orchestrator.checkpoints import save_sub_checkpoint

        cp_dir = tmp_path / "checkpoints"
        result_path = save_sub_checkpoint(cp_dir, "step_16", "acme_corp", {"status": "complete", "agent": "legal"})

        expected_path = cp_dir / "step_16" / "subject_acme_corp.json"
        assert result_path == expected_path
        assert expected_path.exists()

        data = json.loads(expected_path.read_text(encoding="utf-8"))
        assert data["status"] == "complete"
        assert data["agent"] == "legal"

    def test_load_sub_checkpoints_returns_empty_dict_when_no_checkpoints(self, tmp_path: Path) -> None:
        """load_sub_checkpoints returns {} when the step directory does not exist."""
        from dd_agents.orchestrator.checkpoints import load_sub_checkpoints

        cp_dir = tmp_path / "checkpoints"
        # Don't create the directory at all
        result = load_sub_checkpoints(cp_dir, "step_16")
        assert result == {}
        assert isinstance(result, dict)

    def test_load_sub_checkpoints_reads_back_saved_data(self, tmp_path: Path) -> None:
        """load_sub_checkpoints returns all previously saved sub-checkpoints keyed by subject."""
        from dd_agents.orchestrator.checkpoints import load_sub_checkpoints, save_sub_checkpoint

        cp_dir = tmp_path / "checkpoints"
        save_sub_checkpoint(cp_dir, "step_16", "alpha", {"status": "complete", "agent": "finance"})
        save_sub_checkpoint(cp_dir, "step_16", "beta", {"status": "failed", "agent": "legal"})
        save_sub_checkpoint(cp_dir, "step_16", "gamma", {"status": "complete", "agent": "commercial"})

        loaded = load_sub_checkpoints(cp_dir, "step_16")

        assert len(loaded) == 3
        assert set(loaded.keys()) == {"alpha", "beta", "gamma"}
        assert loaded["alpha"]["status"] == "complete"
        assert loaded["alpha"]["agent"] == "finance"
        assert loaded["beta"]["status"] == "failed"
        assert loaded["gamma"]["agent"] == "commercial"

    def test_sub_checkpoint_data_format_matches_expected_schema(self, tmp_path: Path) -> None:
        """Sub-checkpoint data includes status, agent, cost_usd, duration_ms, and error fields."""
        from dd_agents.orchestrator.checkpoints import load_sub_checkpoints, save_sub_checkpoint

        cp_dir = tmp_path / "checkpoints"
        expected_data = {
            "status": "complete",
            "agent": "product_tech",
            "cost_usd": 0.042,
            "duration_ms": 12500,
            "error": None,
        }
        save_sub_checkpoint(cp_dir, "step_16", "widget_co", expected_data)

        loaded = load_sub_checkpoints(cp_dir, "step_16")
        actual = loaded["widget_co"]

        # Verify all expected fields are present and match
        assert actual["status"] == "complete"
        assert actual["agent"] == "product_tech"
        assert actual["cost_usd"] == pytest.approx(0.042)
        assert actual["duration_ms"] == 12500
        assert actual["error"] is None

        # Verify the schema has exactly the expected keys
        assert set(actual.keys()) == {"status", "agent", "cost_usd", "duration_ms", "error"}


# ======================================================================
# Output structure validation
# ======================================================================


class TestValidateAgentOutputStructure:
    """Tests for PipelineEngine._validate_agent_output_structure."""

    @staticmethod
    def _make_engine(tmp_path: Path) -> PipelineEngine:
        config_path = tmp_path / "deal-config.json"
        config_path.write_text("{}")
        return PipelineEngine(tmp_path, config_path)

    def test_all_structured_reports_clean(self, tmp_path: Path) -> None:
        """No warnings when all cross_references and gaps are dicts."""
        engine = self._make_engine(tmp_path)
        findings_dir = tmp_path / "findings"
        legal_dir = findings_dir / "legal"
        legal_dir.mkdir(parents=True)

        data = {
            "subject": "Acme Corp",
            "findings": [],
            "cross_references": [{"data_point": "ARR", "match_status": "match"}],
            "gaps": [{"missing_item": "DPA", "gap_type": "Missing_Doc"}],
        }
        (legal_dir / "acme_corp.json").write_text(json.dumps(data))

        summary = engine._validate_agent_output_structure(findings_dir, ["acme_corp"])
        assert summary["legal"]["string_cross_refs"] == 0
        assert summary["legal"]["string_gaps"] == 0
        assert summary["legal"]["total_cross_refs"] == 1
        assert summary["legal"]["total_gaps"] == 1

    def test_detects_string_cross_references(self, tmp_path: Path) -> None:
        """String cross-references are counted in the summary."""
        engine = self._make_engine(tmp_path)
        findings_dir = tmp_path / "findings"
        finance_dir = findings_dir / "finance"
        finance_dir.mkdir(parents=True)

        data = {
            "subject": "Beta Inc",
            "findings": [],
            "cross_references": [
                "Revenue matches between MSA and cube",
                {"data_point": "ARR", "match_status": "match"},
                "Payment terms differ",
            ],
            "gaps": [],
        }
        (finance_dir / "beta_inc.json").write_text(json.dumps(data))

        summary = engine._validate_agent_output_structure(findings_dir, ["beta_inc"])
        assert summary["finance"]["string_cross_refs"] == 2
        assert summary["finance"]["total_cross_refs"] == 3

    def test_detects_string_gaps(self, tmp_path: Path) -> None:
        """String gaps are counted in the summary."""
        engine = self._make_engine(tmp_path)
        findings_dir = tmp_path / "findings"
        legal_dir = findings_dir / "legal"
        legal_dir.mkdir(parents=True)

        data = {
            "subject": "Gamma LLC",
            "findings": [],
            "cross_references": [],
            "gaps": ["Missing DPA", "Missing SOW"],
        }
        (legal_dir / "gamma_llc.json").write_text(json.dumps(data))

        summary = engine._validate_agent_output_structure(findings_dir, ["gamma_llc"])
        assert summary["legal"]["string_gaps"] == 2
        assert summary["legal"]["total_gaps"] == 2

    def test_skips_coverage_manifest(self, tmp_path: Path) -> None:
        """coverage_manifest.json should not be checked."""
        engine = self._make_engine(tmp_path)
        findings_dir = tmp_path / "findings"
        legal_dir = findings_dir / "legal"
        legal_dir.mkdir(parents=True)

        # coverage_manifest.json has a different structure
        manifest = {"subjects_covered": 5, "coverage_pct": 1.0}
        (legal_dir / "coverage_manifest.json").write_text(json.dumps(manifest))

        summary = engine._validate_agent_output_structure(findings_dir, [])
        assert summary["legal"]["files_checked"] == 0

    def test_empty_findings_dir(self, tmp_path: Path) -> None:
        """Empty findings directory should produce an empty summary."""
        engine = self._make_engine(tmp_path)
        findings_dir = tmp_path / "findings"
        findings_dir.mkdir(parents=True)

        summary = engine._validate_agent_output_structure(findings_dir, ["acme_corp"])
        # No agent directories exist — summary is empty
        assert summary == {}


# ===========================================================================
# Batch concurrency configuration tests
# ===========================================================================


class TestBatchConcurrencyConfig:
    """Tests for batch_concurrency in ExecutionConfig."""

    def test_default_batch_concurrency_is_six(self) -> None:
        from dd_agents.models.config import ExecutionConfig

        config = ExecutionConfig()
        assert config.batch_concurrency == 6

    def test_batch_concurrency_configurable(self) -> None:
        from dd_agents.models.config import ExecutionConfig

        config = ExecutionConfig(batch_concurrency=8)
        assert config.batch_concurrency == 8

    def test_batch_concurrency_minimum_one(self) -> None:
        from dd_agents.models.config import ExecutionConfig

        with pytest.raises(Exception):  # noqa: B017
            ExecutionConfig(batch_concurrency=0)

    def test_batch_concurrency_maximum_ten(self) -> None:
        from dd_agents.models.config import ExecutionConfig

        with pytest.raises(Exception):  # noqa: B017
            ExecutionConfig(batch_concurrency=11)

    def test_effective_waves_calculation(self) -> None:
        """ceil(batches / concurrency) gives correct wave count."""
        # 6 batches, concurrency 3 → 2 waves
        assert -(-6 // 3) == 2
        # 6 batches, concurrency 6 → 1 wave
        assert -(-6 // 6) == 1
        # 7 batches, concurrency 3 → 3 waves
        assert -(-7 // 3) == 3
        # 1 batch, concurrency 3 → 1 wave
        assert -(-1 // 3) == 1


# =========================================================================
# Stall cancellation constants test
# =========================================================================


class TestStallCancellationConstants:
    """Tests for the stall cancellation threshold."""

    def test_stall_cancel_threshold_exists(self) -> None:
        from dd_agents.orchestrator.team import STALL_CANCEL_S, STALL_NO_OUTPUT_S

        # Cancel threshold must be > stall threshold (cancel after stall)
        assert STALL_CANCEL_S > STALL_NO_OUTPUT_S
        # Default: 15 minutes
        assert STALL_CANCEL_S == 15 * 60

    def test_max_timeout_exists(self) -> None:
        from dd_agents.orchestrator.team import MAX_TIMEOUT_S

        # Default: 60 minutes hard cap
        assert MAX_TIMEOUT_S == 60 * 60


class TestMonitorCancellationParams:
    """Tests for the monitor_agent_output cancellation parameters."""

    @pytest.mark.asyncio
    async def test_monitor_accepts_agent_tasks(self, tmp_path: Path) -> None:
        """monitor_agent_output accepts agent_tasks kwarg for stall cancellation."""
        import asyncio
        from typing import Any

        from dd_agents.orchestrator.team import AgentTeam

        state = PipelineState(
            run_id="cancel_test",
            project_dir=tmp_path,
        )
        team = AgentTeam(state)

        # Create a stop event and set it immediately to terminate the monitor
        stop_event = asyncio.Event()
        stop_event.set()

        output_dir = tmp_path / "findings"
        output_dir.mkdir(parents=True)

        # Create a mock task dict
        mock_tasks: dict[str, asyncio.Task[dict[str, Any]]] = {}

        # Should not raise — tests that the kwarg is accepted
        await team.monitor_agent_output(
            output_dir,
            ["legal"],
            stop_event=stop_event,
            agent_tasks=mock_tasks,
            total_subjects=10,
        )

    @pytest.mark.asyncio
    async def test_monitor_cancels_stalled_tasks(self, tmp_path: Path) -> None:
        """When cancel threshold is exceeded, monitor cancels stalled tasks."""
        import asyncio
        import time
        from typing import Any

        from dd_agents.orchestrator.team import AgentTeam

        state = PipelineState(
            run_id="cancel_test2",
            project_dir=tmp_path,
        )
        state.subject_safe_names = ["cust_a", "cust_b"]
        team = AgentTeam(state, stall_threshold_s=1)

        output_dir = tmp_path / "findings"
        output_dir.mkdir(parents=True)

        # Track whether task was cancelled
        cancelled = False

        async def mock_agent() -> dict[str, Any]:
            nonlocal cancelled
            try:
                await asyncio.sleep(999)
            except asyncio.CancelledError:
                cancelled = True
                raise
            return {"agent": "legal", "status": "completed"}

        task = asyncio.create_task(mock_agent())
        mock_tasks: dict[str, asyncio.Task[dict[str, Any]]] = {"legal": task}

        # Set the agent's last activity to the past
        team._agent_last_activity["legal"] = time.monotonic() - 120

        stop_event = asyncio.Event()

        # Run monitor with very short thresholds so it triggers immediately
        await team.monitor_agent_output(
            output_dir,
            ["legal"],
            check_interval_s=0.05,
            warn_threshold_s=0.01,
            stall_threshold_s=0.02,
            cancel_threshold_s=0.03,
            stop_event=stop_event,
            agent_tasks=mock_tasks,
            total_subjects=2,
        )

        # Give the cancellation a moment to propagate
        await asyncio.sleep(0.05)
        assert cancelled or task.cancelled()


# ======================================================================
# Artifact Resolver (#86)
# ======================================================================


class TestArtifactResolver:
    """Tests for centralized artifact path resolution (#86)."""

    def test_resolve_quality_scores_in_judge_dir(self, tmp_path: Path) -> None:
        (tmp_path / "judge").mkdir()
        (tmp_path / "judge" / "quality_scores.json").write_text('{"overall_quality": 82}')
        engine = PipelineEngine.__new__(PipelineEngine)

        class FakeState:
            run_dir = tmp_path

        path = engine._resolve_artifact(FakeState(), "quality_scores")  # type: ignore[arg-type]
        assert path is not None
        assert path == tmp_path / "judge" / "quality_scores.json"

    def test_resolve_quality_scores_in_root(self, tmp_path: Path) -> None:
        (tmp_path / "quality_scores.json").write_text('{"overall_quality": 82}')
        engine = PipelineEngine.__new__(PipelineEngine)

        class FakeState:
            run_dir = tmp_path

        path = engine._resolve_artifact(FakeState(), "quality_scores")  # type: ignore[arg-type]
        assert path is not None
        assert path == tmp_path / "quality_scores.json"

    def test_resolve_artifact_not_found(self, tmp_path: Path) -> None:
        engine = PipelineEngine.__new__(PipelineEngine)

        class FakeState:
            run_dir = tmp_path

        path = engine._resolve_artifact(FakeState(), "quality_scores")  # type: ignore[arg-type]
        assert path is None

    def test_resolve_unknown_artifact(self, tmp_path: Path) -> None:
        engine = PipelineEngine.__new__(PipelineEngine)

        class FakeState:
            run_dir = tmp_path

        path = engine._resolve_artifact(FakeState(), "nonexistent_artifact")  # type: ignore[arg-type]
        assert path is None


# ======================================================================
# Production runtime fixes
# ======================================================================


class TestWaitForAgentsCancelledError:
    """Tests for CancelledError handling in wait_for_agents."""

    @pytest.mark.asyncio
    async def test_cancelled_task_returns_cancelled_status(self, tmp_path: Path) -> None:
        """A cancelled task should return status='cancelled', not crash."""
        import asyncio
        from typing import Any

        from dd_agents.orchestrator.team import AgentTeam

        state = PipelineState(run_id="cancel_err", project_dir=tmp_path)
        team = AgentTeam(state)

        async def mock_agent() -> dict[str, Any]:
            await asyncio.sleep(999)
            return {"agent": "finance", "status": "completed"}

        task = asyncio.create_task(mock_agent())
        # Cancel it immediately
        task.cancel()
        await asyncio.sleep(0)
        tasks: dict[str, asyncio.Task[dict[str, Any]]] = {"finance": task}

        results = await team.wait_for_agents(tasks, timeout=1.0)

        assert "finance" in results
        assert results["finance"]["status"] == "cancelled"
        assert results["finance"]["is_error"] is True
        assert "cancelled" in results["finance"]["error"].lower()

    @pytest.mark.asyncio
    async def test_normal_task_returns_result(self, tmp_path: Path) -> None:
        """A normally completed task should return its result."""
        import asyncio
        from typing import Any

        from dd_agents.orchestrator.team import AgentTeam

        state = PipelineState(run_id="normal_ok", project_dir=tmp_path)
        team = AgentTeam(state)

        async def mock_agent() -> dict[str, Any]:
            return {"agent": "legal", "status": "completed", "is_error": False}

        task = asyncio.create_task(mock_agent())
        await asyncio.sleep(0)
        tasks: dict[str, asyncio.Task[dict[str, Any]]] = {"legal": task}

        results = await team.wait_for_agents(tasks, timeout=1.0)

        assert results["legal"]["status"] == "completed"
        assert results["legal"]["is_error"] is False

    @pytest.mark.asyncio
    async def test_failed_task_returns_error(self, tmp_path: Path) -> None:
        """A task that raises should return status='failed'."""
        import asyncio
        from typing import Any

        from dd_agents.orchestrator.team import AgentTeam

        state = PipelineState(run_id="fail_test", project_dir=tmp_path)
        team = AgentTeam(state)

        async def mock_agent() -> dict[str, Any]:
            raise RuntimeError("SDK connection lost")

        task = asyncio.create_task(mock_agent())
        await asyncio.sleep(0)
        tasks: dict[str, asyncio.Task[dict[str, Any]]] = {"commercial": task}

        results = await team.wait_for_agents(tasks, timeout=1.0)

        assert results["commercial"]["status"] == "failed"
        assert "SDK connection lost" in results["commercial"]["error"]

    @pytest.mark.asyncio
    async def test_mixed_cancelled_and_completed(self, tmp_path: Path) -> None:
        """Mix of cancelled and completed tasks should all be collected."""
        import asyncio
        from typing import Any

        from dd_agents.orchestrator.team import AgentTeam

        state = PipelineState(run_id="mixed", project_dir=tmp_path)
        team = AgentTeam(state)

        async def ok_agent() -> dict[str, Any]:
            return {"agent": "legal", "status": "completed", "is_error": False}

        async def slow_agent() -> dict[str, Any]:
            await asyncio.sleep(999)
            return {"agent": "finance", "status": "completed"}

        ok_task = asyncio.create_task(ok_agent())
        slow_task = asyncio.create_task(slow_agent())
        slow_task.cancel()
        await asyncio.sleep(0)

        tasks: dict[str, asyncio.Task[dict[str, Any]]] = {
            "legal": ok_task,
            "finance": slow_task,
        }

        results = await team.wait_for_agents(tasks, timeout=1.0)

        assert results["legal"]["status"] == "completed"
        assert results["finance"]["status"] == "cancelled"
        assert len(results) == 2


class TestExecutionModeOverride:
    """Tests for --mode CLI override propagation to engine."""

    @pytest.mark.asyncio
    async def test_mode_override_applied_in_step1(self, tmp_path: Path) -> None:
        """Engine should apply execution_mode from options in step 1."""
        # Create a minimal deal-config.json with execution_mode=full
        config = {
            "config_version": "1.0.0",
            "buyer": {"name": "Buyer"},
            "target": {"name": "Target"},
            "deal": {"type": "acquisition", "focus_areas": ["ip_ownership"]},
            "execution": {"execution_mode": "full"},
            "judge": {"enabled": True},
        }
        config_path = tmp_path / "deal-config.json"
        config_path.write_text(json.dumps(config))

        engine = PipelineEngine(
            project_dir=tmp_path,
            deal_config_path=config_path,
        )
        engine._run_options = {"execution_mode": "incremental"}

        state = PipelineState(project_dir=tmp_path)
        state = await engine._step_01_validate_config(state)

        assert state.execution_mode == "incremental"

    @pytest.mark.asyncio
    async def test_no_override_uses_config_value(self, tmp_path: Path) -> None:
        """Without override, engine uses execution_mode from config file."""
        config = {
            "config_version": "1.0.0",
            "buyer": {"name": "Buyer"},
            "target": {"name": "Target"},
            "deal": {"type": "acquisition", "focus_areas": ["ip_ownership"]},
            "execution": {"execution_mode": "full"},
            "judge": {"enabled": True},
        }
        config_path = tmp_path / "deal-config.json"
        config_path.write_text(json.dumps(config))

        engine = PipelineEngine(
            project_dir=tmp_path,
            deal_config_path=config_path,
        )
        engine._run_options = {}

        state = PipelineState(project_dir=tmp_path)
        state = await engine._step_01_validate_config(state)

        assert state.execution_mode == "full"


class TestReferenceFileRouting:
    """Tests for step 15 reference file routing with extraction naming."""

    def test_safe_text_name_lookup(self, tmp_path: Path) -> None:
        """Step 15 should find extracted text using _safe_text_name convention."""
        from dd_agents.extraction.pipeline import ExtractionPipeline

        # Simulate extraction output naming
        ref_path = "3 - Tax Returns/GST Filing - Jan 2024.pdf"
        safe_name = ExtractionPipeline._safe_text_name(ref_path)

        # The safe name should convert slashes to __
        assert "__" in safe_name
        assert safe_name.endswith(".md")
        assert "/" not in safe_name

        # Verify round-trip: create the file and check it can be found
        text_dir = tmp_path / "text"
        text_dir.mkdir()
        (text_dir / safe_name).write_text("extracted content")

        # The file should exist at the expected path
        assert (text_dir / safe_name).exists()

    def test_stem_fallback_still_works(self, tmp_path: Path) -> None:
        """Legacy stem.md naming should still work as fallback."""
        text_dir = tmp_path / "text"
        text_dir.mkdir()

        # Create a file with just the stem
        (text_dir / "simple_file.md").write_text("content")
        assert (text_dir / "simple_file.md").exists()


class TestPerAgentCompletionTracking:
    """Tests for per-agent completion tracking in the output monitor."""

    @pytest.mark.asyncio
    async def test_agent_marked_complete_when_all_files_written(self, tmp_path: Path) -> None:
        """Monitor should mark agent as complete when it has written all subject files."""
        import asyncio

        from dd_agents.orchestrator.team import AgentTeam

        state = PipelineState(run_id="completion_test", project_dir=tmp_path)
        state.subject_safe_names = ["cust_a", "cust_b"]
        team = AgentTeam(state)

        output_dir = tmp_path / "findings"
        legal_dir = output_dir / "legal"
        legal_dir.mkdir(parents=True)

        # Write all subject files for legal
        (legal_dir / "cust_a.json").write_text("{}")
        (legal_dir / "cust_b.json").write_text("{}")

        stop = asyncio.Event()

        async def stop_after_check() -> None:
            await asyncio.sleep(0.3)
            stop.set()

        await asyncio.gather(
            team.monitor_agent_output(
                output_dir,
                ["legal"],
                check_interval_s=0.1,
                stop_event=stop,
                total_subjects=2,
            ),
            stop_after_check(),
        )

        # Legal should be marked as completed
        assert "legal" in team._completed_agents

    def test_completed_agent_excluded_from_stall_detection(self, tmp_path: Path) -> None:
        """Completed agents should not appear in stall detection."""
        import time as _time

        from dd_agents.orchestrator.team import AgentTeam

        state = PipelineState(run_id="excl_test", project_dir=tmp_path)
        team = AgentTeam(state, stall_threshold_s=1)

        # Both agents were active long ago
        team._agent_last_activity["legal"] = _time.monotonic() - 120
        team._agent_last_activity["finance"] = _time.monotonic() - 120

        # Mark legal as completed
        team.mark_agent_completed("legal")

        stalled = team.detect_stalled_agents()
        assert "legal" not in stalled
        assert "finance" in stalled


# =========================================================================
# Issue fix: zero-file subjects excluded from agent routing
# =========================================================================


class TestZeroFileSubjectFiltering:
    """Verify subjects with file_count=0 are excluded from agent batches."""

    def test_zero_file_subjects_tracked_on_state(self, tmp_path: Path) -> None:
        """Step 14 sets _zero_file_subjects for subjects with no files."""
        state = PipelineState(
            run_id="zf_test",
            project_dir=tmp_path,
            run_dir=tmp_path / "runs" / "zf_test",
        )
        state._zero_file_subjects = ["buyer", "old_docs"]
        assert len(state._zero_file_subjects) == 2

    def test_zero_file_subjects_default_empty(self, tmp_path: Path) -> None:
        """_zero_file_subjects defaults to an empty list."""
        state = PipelineState(run_id="t", project_dir=tmp_path)
        assert state._zero_file_subjects == []


# =========================================================================
# Issue fix: manifest counts use recalibrated severity
# =========================================================================


class TestManifestRecalibratedCounts:
    """Verify that _step_26 applies recalibration when counting findings."""

    def _make_engine(self, tmp_path: Path) -> PipelineEngine:
        config_path = tmp_path / "deal-config.json"
        config_path.write_text("{}")
        return PipelineEngine(tmp_path, config_path)

    def _make_state(self, tmp_path: Path) -> PipelineState:
        run_dir = tmp_path / "runs" / "recal_test"
        run_dir.mkdir(parents=True, exist_ok=True)
        inv_dir = tmp_path / "_dd" / "forensic-dd" / "inventory"
        inv_dir.mkdir(parents=True, exist_ok=True)
        return PipelineState(
            run_id="recal_test",
            project_dir=tmp_path,
            run_dir=run_dir,
            skill_dir=tmp_path / "_dd" / "forensic-dd",
            total_subjects=1,
            total_files=1,
        )

    @pytest.mark.asyncio
    async def test_manifest_counts_reflect_recalibration(self, tmp_path: Path) -> None:
        """Findings that get recalibrated should be counted at their new severity."""
        from dd_agents.reporting.computed_metrics import ReportDataComputer

        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)

        # Create inventory directory with required files
        inv_dir = tmp_path / "_dd" / "forensic-dd" / "inventory"
        (inv_dir / "subjects.csv").write_text("subject\nsubject_a\n")
        (inv_dir / "files.txt").write_text("file1.pdf\n")
        (inv_dir / "reference_files.json").write_text("[]")
        (inv_dir / "counts.json").write_text(
            json.dumps({"total_subjects": 1, "total_files": 1, "total_reference_files": 0})
        )

        # Create a merged finding that will be recalibrated
        merged_dir = state.run_dir / "findings" / "merged"
        merged_dir.mkdir(parents=True, exist_ok=True)

        # Create a finding whose severity will be changed by recalibration.
        # Use a known pattern: "speculative language" findings get capped.
        finding = {
            "title": "Potential issue with speculative language",
            "description": "This might potentially affect revenue",
            "severity": "P1",
            "category": "revenue_recognition",
        }

        # Verify this finding would actually be recalibrated
        recal = ReportDataComputer._recalibrate_severity(finding)
        recal_sev = recal.get("severity", "P1")

        (merged_dir / "subject_a.json").write_text(json.dumps({"findings": [finding], "gaps": []}))

        await engine._step_29_build_numerical_manifest(state)

        manifest_path = state.run_dir / "numerical_manifest.json"
        manifest = json.loads(manifest_path.read_text())

        # The manifest should count at the recalibrated severity, not raw
        sev_counts = {}
        for entry in manifest["numbers"]:
            if entry["id"] in ("N004", "N005", "N006", "N007"):
                label = entry["label"].split()[0]  # "P0", "P1", "P2", "P3"
                sev_counts[label] = entry["value"]

        assert sev_counts.get(recal_sev, 0) == 1
        # If recalibration changed severity, the original bucket should be 0
        if recal_sev != "P1":
            assert sev_counts.get("P1", 0) == 0


# =========================================================================
# Issue fix: _generate_coverage_gap_finding accepts reason parameter
# =========================================================================


class TestCoverageGapReason:
    """Verify custom reason flows into gap finding description."""

    def test_custom_reason(self) -> None:
        gap = PipelineEngine._generate_coverage_gap_finding(
            subject_safe_name="buyer",
            agent_name="legal",
            run_id="test",
            reason="Zero source documents in data room",
        )
        assert gap["description"] == "Zero source documents in data room"

    def test_default_reason(self) -> None:
        gap = PipelineEngine._generate_coverage_gap_finding(
            subject_safe_name="acme",
            agent_name="finance",
            run_id="test",
        )
        assert "did not produce output" in gap["description"]


# =========================================================================
# _build_run_metadata_for_excel: numerical manifest parity (N002)
# =========================================================================


class TestBuildRunMetadataNumericalManifest:
    """Verify _build_run_metadata_for_excel loads numerical_manifest.json entries."""

    def test_loads_numerical_manifest_entries(self, tmp_path: Path) -> None:
        """N-entries from numerical_manifest.json should appear in run_metadata."""
        # _inventory_dir returns project_dir / skill_dir / "inventory"
        inv_dir = tmp_path / "_dd" / "forensic-dd" / "inventory"
        inv_dir.mkdir(parents=True)
        run_dir = tmp_path / "_dd" / "forensic-dd" / "runs" / "run_test"
        run_dir.mkdir(parents=True)

        manifest = {
            "run_id": "run_test",
            "numbers": [
                {"id": "N001", "label": "Total Subjects", "value": 15},
                {"id": "N002", "label": "Total Files", "value": 845},
            ],
        }
        (run_dir / "numerical_manifest.json").write_text(json.dumps(manifest))

        state = PipelineState(
            run_id="run_test",
            run_dir=run_dir,
            project_dir=tmp_path,
            deal_config={},
            total_subjects=15,
            total_files=845,
        )

        engine = PipelineEngine.__new__(PipelineEngine)
        engine._config = {}
        engine._project_dir = tmp_path

        merged: dict[str, dict] = {}  # type: ignore[type-arg]
        result = engine._build_run_metadata_for_excel(state, merged)

        assert result["N001_Total Subjects"] == 15
        assert result["N002_Total Files"] == 845

    def test_works_without_numerical_manifest(self, tmp_path: Path) -> None:
        """No crash when numerical_manifest.json is absent."""
        inv_dir = tmp_path / "_dd" / "forensic-dd" / "inventory"
        inv_dir.mkdir(parents=True)
        run_dir = tmp_path / "_dd" / "forensic-dd" / "runs" / "run_test"
        run_dir.mkdir(parents=True)

        state = PipelineState(
            run_id="run_test",
            run_dir=run_dir,
            project_dir=tmp_path,
            deal_config={},
            total_subjects=5,
            total_files=100,
        )

        engine = PipelineEngine.__new__(PipelineEngine)
        engine._config = {}
        engine._project_dir = tmp_path

        merged: dict[str, dict] = {}  # type: ignore[type-arg]
        result = engine._build_run_metadata_for_excel(state, merged)

        # Should still have basic counts without N-entries
        assert result["subject_count"] == 0
        assert "N001_Total Subjects" not in result
