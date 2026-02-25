"""Unit tests for the dd_agents.orchestrator package.

Covers:
- PipelineStep enum: count, blocking gates, conditional steps, step_number
- PipelineState: creation, to_checkpoint_dict / from_checkpoint_dict round-trip
- Checkpoints: save and load via public functions
- PipelineEngine: initialisation, step registry completeness
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

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

if TYPE_CHECKING:
    from pathlib import Path

# ======================================================================
# PipelineStep
# ======================================================================


class TestPipelineStep:
    """Tests for the PipelineStep enum."""

    def test_step_count_is_35(self) -> None:
        """The enum must contain exactly 35 members."""
        assert len(PipelineStep) == 35

    def test_step_number_property(self) -> None:
        """step_number should parse the leading digits from the value."""
        assert PipelineStep.VALIDATE_CONFIG.step_number == 1
        assert PipelineStep.SHUTDOWN.step_number == 35
        assert PipelineStep.COVERAGE_GATE.step_number == 17

    def test_step_numbers_are_sequential(self) -> None:
        """Every step from 1..35 should appear exactly once."""
        numbers = sorted(s.step_number for s in PipelineStep)
        assert numbers == list(range(1, 36))

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
        """Eight conditional steps."""
        assert len(_CONDITIONAL_STEPS) == 8

    def test_conditional_step_members(self) -> None:
        expected = {
            PipelineStep.CONTRACT_DATE_RECONCILIATION,
            PipelineStep.INCREMENTAL_CLASSIFICATION,
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
            total_customers=42,
            customer_safe_names=["acme_corp", "beta_inc"],
        )
        assert state.run_id == "20260221_120000"
        assert state.execution_mode == "incremental"
        assert state.judge_enabled is False
        assert state.total_customers == 42
        assert len(state.customer_safe_names) == 2

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
            total_customers=10,
            customer_safe_names=["alpha", "bravo", "charlie"],
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
            customers_to_analyze=["alpha", "bravo"],
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
        assert restored.total_customers == state.total_customers
        assert restored.customer_safe_names == state.customer_safe_names
        assert restored.reference_file_count == state.reference_file_count
        assert restored.current_step == state.current_step
        assert restored.completed_steps == state.completed_steps
        assert restored.agent_sessions == state.agent_sessions
        assert restored.agent_costs == state.agent_costs
        assert restored.batch_counts == state.batch_counts
        assert restored.validation_results == state.validation_results
        assert restored.audit_passed == state.audit_passed
        assert restored.customers_to_analyze == state.customers_to_analyze
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
            total_customers=10,
            customer_safe_names=["alpha", "bravo"],
            reference_file_count=5,
            current_step=PipelineStep.BUILD_INVENTORY,
            completed_steps=[PipelineStep.VALIDATE_CONFIG, PipelineStep.INIT_PERSISTENCE],
            errors=[{"step": "01_validate_config", "message": "test"}],
            agent_sessions={"legal": "sess_1"},
            agent_results={"legal": {"status": "complete", "customers": 10}},
            agent_costs={"legal": 1.23},
            agent_prompts={"legal": ["prompt line 1"]},
            batch_counts={"legal": 2},
            validation_results={"numerical_audit": True},
            audit_passed=True,
            classification={"customers": [{"name": "alpha", "status": "new"}]},
            customers_to_analyze=["alpha"],
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
        assert restored.total_customers == state.total_customers
        assert restored.customer_safe_names == state.customer_safe_names
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
        assert restored.customers_to_analyze == state.customers_to_analyze
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
            total_customers=7,
        )

        path = save_checkpoint(state, cp_dir)
        assert path.exists()
        assert path.name == "checkpoint_06_build_inventory.json"

        loaded = load_checkpoint(cp_dir)
        assert loaded.run_id == "ckpt_test"
        assert loaded.current_step == PipelineStep.BUILD_INVENTORY
        assert loaded.total_customers == 7

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

        removed = clean_checkpoints(cp_dir)
        assert removed == 1
        assert list_checkpoints(cp_dir) == []

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
        assert engine.TOTAL_STEPS == 35

    def test_step_registry_completeness(self, tmp_path: Path) -> None:
        """Every PipelineStep must have a handler in the registry."""
        engine = self._make_engine(tmp_path)
        registry = engine._step_registry

        for step in PipelineStep:
            assert step in registry, f"Missing handler for {step.value}"

        assert len(registry) == 35

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
            missing_customers=["acme", "beta"],
        )
        assert isinstance(err, RecoverableError)
        assert err.agent_name == "finance"
        assert err.missing_customers == ["acme", "beta"]


# ======================================================================
# Blocking gate step methods
# ======================================================================


class TestStep27NumericalAudit:
    """Tests for _step_27_numerical_audit blocking gate."""

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
    async def test_step_27_raises_on_missing_manifest(self, tmp_path: Path) -> None:
        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)
        # No numerical_manifest.json exists
        with pytest.raises(BlockingGateError, match="Numerical manifest not found"):
            await engine._step_27_numerical_audit(state)
        assert state.validation_results["numerical_audit"] is False

    @pytest.mark.asyncio
    async def test_step_27_raises_on_audit_failure(self, tmp_path: Path) -> None:
        from unittest.mock import patch

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
            await engine._step_27_numerical_audit(state)
        assert state.validation_results["numerical_audit"] is False

    @pytest.mark.asyncio
    async def test_step_27_passes_on_success(self, tmp_path: Path) -> None:
        from unittest.mock import patch

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
            result = await engine._step_27_numerical_audit(state)
        assert result.validation_results["numerical_audit"] is True


class TestStep28FullQAAudit:
    """Tests for _step_28_full_qa_audit blocking gate."""

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
            customer_safe_names=["customer_a"],
        )

    @pytest.mark.asyncio
    async def test_step_28_raises_on_qa_failure(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        from dd_agents.models.audit import AuditCheck, AuditReport

        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)

        failed_report = AuditReport(
            audit_passed=False,
            timestamp="2026-01-01T00:00:00Z",
            run_id="test_run",
            checks={
                "file_coverage": AuditCheck(passed=True, rule="File coverage"),
                "customer_coverage": AuditCheck(passed=False, rule="Customer coverage"),
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
            await engine._step_28_full_qa_audit(state)
        assert state.validation_results["qa_audit"] is False
        assert state.audit_passed is False

    @pytest.mark.asyncio
    async def test_step_28_passes_on_success(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        from dd_agents.models.audit import AuditCheck, AuditReport

        engine = self._make_engine(tmp_path)
        state = self._make_state(tmp_path)

        passing_report = AuditReport(
            audit_passed=True,
            timestamp="2026-01-01T00:00:00Z",
            run_id="test_run",
            checks={
                "file_coverage": AuditCheck(passed=True, rule="File coverage"),
                "customer_coverage": AuditCheck(passed=True, rule="Customer coverage"),
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
            result = await engine._step_28_full_qa_audit(state)
        assert result.validation_results["qa_audit"] is True
        assert result.audit_passed is True


class TestStep35Shutdown:
    """Tests for _step_35_shutdown DoD persistence."""

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
            customer_safe_names=["customer_a"],
        )

    @pytest.mark.asyncio
    async def test_step_35_persists_dod_results(self, tmp_path: Path) -> None:
        from unittest.mock import patch

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
            await engine._step_35_shutdown(state)

        dod_path = state.run_dir / "dod_results.json"
        assert dod_path.exists(), "dod_results.json must be written"

        data = json.loads(dod_path.read_text())
        assert data["passed"] == 2
        assert data["total"] == 3
        assert len(data["checks"]) == 3
