"""PipelineState -- complete mutable state for the forensic DD pipeline.

Serialised to a checkpoint JSON file after every successful step so that
the pipeline can be resumed from any point after a crash.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any,
    ClassVar,  # noqa: F401, UP035
)

from dd_agents.orchestrator.steps import PipelineStep

# ---------------------------------------------------------------------------
# StepResult
# ---------------------------------------------------------------------------


@dataclass
class StepResult:
    """Outcome of a single pipeline step."""

    step: PipelineStep
    status: str = "success"  # "success", "skipped", "failed"
    error: str | None = None
    duration_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# PipelineError  (exception class)
# ---------------------------------------------------------------------------


class PipelineError(Exception):
    """Raised when the pipeline encounters an unrecoverable error.

    Attributes
    ----------
    step : PipelineStep
        The step during which the error occurred.
    error_type : str
        Classification label (``"blocking_gate"``, ``"agent_failure"``,
        ``"partial_failure"``, ``"recoverable"``).
    message : str
        Human-readable description.
    recovered : bool
        Whether automatic recovery was successful.
    recovery_action : str
        Description of what the recovery engine did.
    """

    def __init__(
        self,
        step: PipelineStep,
        error_type: str,
        message: str,
        *,
        recovered: bool = False,
        recovery_action: str = "",
    ) -> None:
        super().__init__(message)
        self.step = step
        self.error_type = error_type
        self.recovered = recovered
        self.recovery_action = recovery_action


# ---------------------------------------------------------------------------
# PipelineState
# ---------------------------------------------------------------------------


@dataclass
class PipelineState:
    """Complete pipeline state.  Serialised to checkpoint JSON after each step."""

    # --- Identity -----------------------------------------------------------
    run_id: str = ""
    skill_dir: Path = field(default_factory=lambda: Path("_dd/forensic-dd"))
    run_dir: Path = field(default_factory=Path)
    project_dir: Path = field(default_factory=Path)

    # --- Configuration ------------------------------------------------------
    deal_config: dict[str, Any] | None = None
    config_hash: str = ""
    execution_mode: str = "full"  # "full" or "incremental"
    judge_enabled: bool = True
    prior_run_id: str | None = None
    prior_run_dir: Path | None = None
    framework_version: str = "unknown"

    # --- Inventory ----------------------------------------------------------
    total_files: int = 0
    total_customers: int = 0
    customer_safe_names: list[str] = field(default_factory=list)
    reference_file_count: int = 0

    # --- Pipeline progress --------------------------------------------------
    current_step: PipelineStep = PipelineStep.VALIDATE_CONFIG
    completed_steps: list[PipelineStep] = field(default_factory=list)
    step_results: dict[str, StepResult] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)

    # --- Agent tracking -----------------------------------------------------
    agent_handles: dict[str, Any] = field(default_factory=dict)
    agent_sessions: dict[str, str] = field(default_factory=dict)
    agent_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    agent_costs: dict[str, float] = field(default_factory=dict)
    agent_prompts: dict[str, list[str]] = field(default_factory=dict)

    # --- Prompt batching ----------------------------------------------------
    batch_counts: dict[str, int] = field(default_factory=dict)

    # --- Validation ---------------------------------------------------------
    validation_results: dict[str, bool] = field(default_factory=dict)
    audit_passed: bool = False

    # --- Incremental mode ---------------------------------------------------
    classification: dict[str, Any] | None = None
    customers_to_analyze: list[str] = field(default_factory=list)

    # --- Cross-skill --------------------------------------------------------
    cross_skill_run_ids: dict[str, str] = field(default_factory=dict)

    # --- Judge scores -------------------------------------------------------
    judge_scores: dict[str, Any] = field(default_factory=dict)

    # --- Exit status (Issue #56) --------------------------------------------
    exit_code: int = 0

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_checkpoint_dict(self) -> dict[str, Any]:
        """Serialise the state to a JSON-safe dictionary for persistence."""

        step_results_ser: dict[str, dict[str, Any]] = {}
        for key, sr in self.step_results.items():
            step_results_ser[key] = {
                "step": sr.step.value,
                "status": sr.status,
                "error": sr.error,
                "duration_ms": sr.duration_ms,
                "metadata": sr.metadata,
            }

        # Persist dynamic attributes that downstream steps depend on.
        # ``_customer_entries`` is set via setattr in step 6 and consumed
        # by step 14 (prompt building) and the respawn path (step 17).
        customer_entries_ser: list[dict[str, Any]] = []
        _entries: list[Any] = getattr(self, "_customer_entries", [])
        for entry in _entries:
            if hasattr(entry, "model_dump"):
                customer_entries_ser.append(entry.model_dump())
            elif isinstance(entry, dict):
                customer_entries_ser.append(entry)

        return {
            "run_id": self.run_id,
            "skill_dir": str(self.skill_dir),
            "run_dir": str(self.run_dir),
            "project_dir": str(self.project_dir),
            "deal_config": self.deal_config,
            "config_hash": self.config_hash,
            "execution_mode": self.execution_mode,
            "judge_enabled": self.judge_enabled,
            "prior_run_id": self.prior_run_id,
            "prior_run_dir": str(self.prior_run_dir) if self.prior_run_dir else None,
            "framework_version": self.framework_version,
            "total_files": self.total_files,
            "total_customers": self.total_customers,
            "customer_safe_names": self.customer_safe_names,
            "reference_file_count": self.reference_file_count,
            "current_step": self.current_step.value,
            "completed_steps": [s.value for s in self.completed_steps],
            "step_results": step_results_ser,
            "errors": self.errors,
            "agent_sessions": self.agent_sessions,
            "agent_results": self.agent_results,
            "agent_costs": self.agent_costs,
            "agent_prompts": self.agent_prompts,
            "batch_counts": self.batch_counts,
            "validation_results": self.validation_results,
            "audit_passed": self.audit_passed,
            "classification": self.classification,
            "customers_to_analyze": self.customers_to_analyze,
            "cross_skill_run_ids": self.cross_skill_run_ids,
            "judge_scores": self.judge_scores,
            "exit_code": self.exit_code,
            "_customer_entries": customer_entries_ser,
        }

    # Step value migrations: old checkpoint string → current enum value.
    # Keeps backward compatibility when loading checkpoints from prior versions.
    _STEP_MIGRATIONS: ClassVar[dict[str, str]] = {
        "30_generate_excel": "30_generate_reports",
    }

    @classmethod
    def _migrate_step_value(cls, value: str) -> str:
        """Map legacy checkpoint step values to current enum values."""
        return cls._STEP_MIGRATIONS.get(value, value)

    @classmethod
    def from_checkpoint_dict(cls, data: dict[str, Any]) -> PipelineState:
        """Restore a ``PipelineState`` from a checkpoint dictionary."""

        step_results: dict[str, StepResult] = {}
        for key, sr_dict in data.get("step_results", {}).items():
            step_results[key] = StepResult(
                step=PipelineStep(cls._migrate_step_value(sr_dict["step"])),
                status=sr_dict.get("status", "success"),
                error=sr_dict.get("error"),
                duration_ms=sr_dict.get("duration_ms", 0),
                metadata=sr_dict.get("metadata", {}),
            )

        state = cls(
            run_id=data.get("run_id", ""),
            skill_dir=Path(data.get("skill_dir", "_dd/forensic-dd")),
            run_dir=Path(data.get("run_dir", "")),
            project_dir=Path(data.get("project_dir", "")),
            deal_config=data.get("deal_config"),
            config_hash=data.get("config_hash", ""),
            execution_mode=data.get("execution_mode", "full"),
            judge_enabled=data.get("judge_enabled", True),
            prior_run_id=data.get("prior_run_id"),
            prior_run_dir=(Path(data["prior_run_dir"]) if data.get("prior_run_dir") else None),
            framework_version=data.get("framework_version", "unknown"),
            total_files=data.get("total_files", 0),
            total_customers=data.get("total_customers", 0),
            customer_safe_names=data.get("customer_safe_names", []),
            reference_file_count=data.get("reference_file_count", 0),
            current_step=PipelineStep(cls._migrate_step_value(data["current_step"])),
            completed_steps=[PipelineStep(cls._migrate_step_value(v)) for v in data.get("completed_steps", [])],
            step_results=step_results,
            errors=data.get("errors", []),
            agent_sessions=data.get("agent_sessions", {}),
            agent_results=data.get("agent_results", {}),
            agent_costs=data.get("agent_costs", {}),
            agent_prompts=data.get("agent_prompts", {}),
            batch_counts=data.get("batch_counts", {}),
            validation_results=data.get("validation_results", {}),
            audit_passed=data.get("audit_passed", False),
            classification=data.get("classification"),
            customers_to_analyze=data.get("customers_to_analyze", []),
            cross_skill_run_ids=data.get("cross_skill_run_ids", {}),
            judge_scores=data.get("judge_scores", {}),
            exit_code=data.get("exit_code", 0),
        )

        # Restore dynamic attribute ``_customer_entries`` so that respawn
        # and prompt rebuilding work correctly after checkpoint resume.
        raw_entries = data.get("_customer_entries", [])
        if raw_entries:
            import contextlib

            from dd_agents.models.inventory import CustomerEntry

            restored: list[CustomerEntry] = []
            for item in raw_entries:
                if isinstance(item, dict):
                    with contextlib.suppress(Exception):
                        restored.append(CustomerEntry.model_validate(item))
            if restored:
                state._customer_entries = restored  # type: ignore[attr-defined]

        return state
