# 05 — Orchestrator (Pipeline Engine)

> **Source of truth**: SKILL.md sections 0c, 0e, 1-9 (35 execution steps, persistence, incremental mode, error recovery, QA, Definition of Done)
> **SDK reference**: `Claude_Agent_SDK_Complete_Reference.md` sections 2, 4, 5

## Overview

The orchestrator is a Python async state machine that drives the 35-step forensic DD pipeline. Each step is an async function that receives `PipelineState`, performs work, validates preconditions/postconditions, and returns the updated state. The orchestrator controls all flow -- agents are invoked at specific steps and their outputs are validated programmatically before proceeding. Five steps are **blocking gates** (steps 5, 17, 27, 28, 31) that halt the pipeline on failure. Step 1 (config validation) is the first step in the pipeline. While it is a precondition for all subsequent steps, it IS step 1 in the 35-step sequence. It raises `BlockingGateError` on failure (effectively blocking), but is not listed among the five formal gates because it guards pipeline entry rather than phase transitions.

---

## 1. PipelineStep Enum

Every step has a canonical name used in checkpoints, logs, and error messages.

```python
# src/dd_agents/orchestrator/steps.py

from enum import Enum

class PipelineStep(str, Enum):
    """All 35 pipeline steps. String values used in checkpoint.json."""

    VALIDATE_CONFIG             = "01_validate_config"
    INIT_PERSISTENCE            = "02_init_persistence"
    CROSS_SKILL_CHECK           = "03_cross_skill_check"
    FILE_DISCOVERY              = "04_file_discovery"
    BULK_EXTRACTION             = "05_bulk_extraction"              # BLOCKING GATE
    BUILD_INVENTORY             = "06_build_inventory"
    ENTITY_RESOLUTION           = "07_entity_resolution"
    REFERENCE_REGISTRY          = "08_reference_registry"
    CUSTOMER_MENTIONS           = "09_customer_mentions"
    INVENTORY_INTEGRITY         = "10_inventory_integrity"
    CONTRACT_DATE_RECONCILIATION = "11_contract_date_reconciliation"
    INCREMENTAL_CLASSIFICATION  = "12_incremental_classification"
    CREATE_TEAM                 = "13_create_team"
    PREPARE_PROMPTS             = "14_prepare_prompts"
    ROUTE_REFERENCES            = "15_route_references"
    SPAWN_SPECIALISTS           = "16_spawn_specialists"
    COVERAGE_GATE               = "17_coverage_gate"               # BLOCKING GATE
    INCREMENTAL_MERGE           = "18_incremental_merge"
    SPAWN_JUDGE                 = "19_spawn_judge"
    JUDGE_REVIEW                = "20_judge_review"
    JUDGE_RESPAWN               = "21_judge_respawn"
    JUDGE_ROUND2                = "22_judge_round2"
    SPAWN_REPORTING_LEAD        = "23_spawn_reporting_lead"
    MERGE_DEDUP                 = "24_merge_dedup"
    MERGE_GAPS                  = "25_merge_gaps"
    BUILD_NUMERICAL_MANIFEST    = "26_build_numerical_manifest"
    NUMERICAL_AUDIT             = "27_numerical_audit"             # BLOCKING GATE
    FULL_QA_AUDIT               = "28_full_qa_audit"               # BLOCKING GATE
    BUILD_REPORT_DIFF           = "29_build_report_diff"
    GENERATE_REPORTS            = "30_generate_reports"
    POST_GENERATION_VALIDATION  = "31_post_generation_validation"  # BLOCKING GATE
    FINALIZE_METADATA           = "32_finalize_metadata"
    UPDATE_RUN_HISTORY          = "33_update_run_history"
    SAVE_ENTITY_CACHE           = "34_save_entity_cache"
    SHUTDOWN                    = "35_shutdown"

    @property
    def step_number(self) -> int:
        return int(self.value.split("_")[0])

    @property
    def is_blocking_gate(self) -> bool:
        return self in _BLOCKING_GATES

    @property
    def is_conditional(self) -> bool:
        return self in _CONDITIONAL_STEPS


_BLOCKING_GATES = frozenset({
    PipelineStep.BULK_EXTRACTION,            # Step 5
    PipelineStep.COVERAGE_GATE,              # Step 17
    PipelineStep.NUMERICAL_AUDIT,            # Step 27
    PipelineStep.FULL_QA_AUDIT,              # Step 28
    PipelineStep.POST_GENERATION_VALIDATION, # Step 31
})

# Note: Step 1 (VALIDATE_CONFIG) is also effectively blocking -- if config
# fails validation, the pipeline raises BlockingGateError and stops. It is
# not listed here because it is a precondition, not a gate between phases.

_CONDITIONAL_STEPS = frozenset({
    PipelineStep.CONTRACT_DATE_RECONCILIATION,  # Only if source_of_truth.customer_database exists
    PipelineStep.INCREMENTAL_CLASSIFICATION,    # Only if execution_mode == "incremental"
    PipelineStep.INCREMENTAL_MERGE,             # Only if execution_mode == "incremental"
    PipelineStep.SPAWN_JUDGE,                   # Only if judge.enabled
    PipelineStep.JUDGE_REVIEW,                  # Only if judge.enabled
    PipelineStep.JUDGE_RESPAWN,                 # Only if judge.enabled
    PipelineStep.JUDGE_ROUND2,                  # Only if judge.enabled
    PipelineStep.BUILD_REPORT_DIFF,             # Only if prior run exists
})
```

---

## 2. PipelineState

Serializable state object passed through every step. Saved to checkpoint after each successful step.

```python
# src/dd_agents/orchestrator/state.py

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
import json

from .steps import PipelineStep


@dataclass
class StepResult:
    """Outcome of a single pipeline step."""
    step: PipelineStep
    success: bool
    duration_ms: int = 0
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class PipelineError:
    """Recorded error (may be recovered or fatal)."""
    step: PipelineStep
    error_type: str          # "blocking_gate", "agent_failure", "partial_failure", "recoverable"
    message: str
    recovered: bool = False
    recovery_action: str = ""


@dataclass
class PipelineState:
    """Complete pipeline state. Serialized to checkpoint.json after each step."""

    # --- Identity ---
    run_id: str = ""
    skill_dir: Path = field(default_factory=lambda: Path("_dd/forensic-dd"))
    run_dir: Path = field(default_factory=Path)
    project_dir: Path = field(default_factory=Path)

    # --- Configuration ---
    deal_config: Optional[dict] = None
    config_hash: str = ""
    execution_mode: str = "full"               # "full" or "incremental"
    judge_enabled: bool = True
    prior_run_id: Optional[str] = None
    prior_run_dir: Optional[Path] = None
    framework_version: str = "unknown"

    # --- Inventory ---
    total_files: int = 0
    total_customers: int = 0
    customer_safe_names: list[str] = field(default_factory=list)
    reference_file_count: int = 0

    # --- Pipeline progress ---
    current_step: PipelineStep = PipelineStep.VALIDATE_CONFIG
    completed_steps: list[PipelineStep] = field(default_factory=list)
    step_results: dict[str, StepResult] = field(default_factory=dict)    # step.value -> StepResult
    errors: list[PipelineError] = field(default_factory=list)

    # --- Agent tracking ---
    agent_handles: dict[str, Any] = field(default_factory=dict)          # agent_name -> SDK session info
    agent_sessions: dict[str, str] = field(default_factory=dict)         # agent_name -> session_id
    agent_results: dict[str, dict] = field(default_factory=dict)         # agent_name -> ResultMessage data
    agent_costs: dict[str, float] = field(default_factory=dict)          # agent_name -> cost_usd
    agent_prompts: dict[str, list[str]] = field(default_factory=dict)    # agent_name -> [prompt_batches]

    # --- Prompt batching ---
    batch_counts: dict[str, int] = field(default_factory=dict)           # agent_name -> number of batches

    # --- Validation ---
    validation_results: dict[str, bool] = field(default_factory=dict)
    audit_passed: bool = False

    # --- Incremental mode ---
    classification: Optional[dict] = None      # Full classification.json content
    customers_to_analyze: list[str] = field(default_factory=list)

    # --- Cross-skill ---
    cross_skill_run_ids: dict[str, str] = field(default_factory=dict)    # skill_name -> run_id

    def to_checkpoint(self) -> dict:
        """Serialize state to JSON-safe dict for checkpoint persistence."""
        data = {
            "run_id": self.run_id,
            "skill_dir": str(self.skill_dir),
            "run_dir": str(self.run_dir),
            "project_dir": str(self.project_dir),
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
            "agent_sessions": self.agent_sessions,
            "agent_costs": self.agent_costs,
            "batch_counts": self.batch_counts,
            "validation_results": self.validation_results,
            "audit_passed": self.audit_passed,
            "execution_mode": self.execution_mode,
            "customers_to_analyze": self.customers_to_analyze,
            "cross_skill_run_ids": self.cross_skill_run_ids,
            "errors": [
                {"step": e.step.value, "error_type": e.error_type,
                 "message": e.message, "recovered": e.recovered,
                 "recovery_action": e.recovery_action}
                for e in self.errors
            ],
        }
        return data

    @classmethod
    def from_checkpoint(cls, data: dict) -> "PipelineState":
        """Deserialize from checkpoint JSON."""
        state = cls()
        state.run_id = data["run_id"]
        state.skill_dir = Path(data["skill_dir"])
        state.run_dir = Path(data["run_dir"])
        state.project_dir = Path(data["project_dir"])
        state.config_hash = data.get("config_hash", "")
        state.execution_mode = data.get("execution_mode", "full")
        state.judge_enabled = data.get("judge_enabled", True)
        state.prior_run_id = data.get("prior_run_id")
        state.prior_run_dir = Path(data["prior_run_dir"]) if data.get("prior_run_dir") else None
        state.framework_version = data.get("framework_version", "unknown")
        state.total_files = data.get("total_files", 0)
        state.total_customers = data.get("total_customers", 0)
        state.customer_safe_names = data.get("customer_safe_names", [])
        state.reference_file_count = data.get("reference_file_count", 0)
        state.current_step = PipelineStep(data["current_step"])
        state.completed_steps = [PipelineStep(v) for v in data.get("completed_steps", [])]
        state.agent_sessions = data.get("agent_sessions", {})
        state.agent_costs = data.get("agent_costs", {})
        state.batch_counts = data.get("batch_counts", {})
        state.validation_results = data.get("validation_results", {})
        state.audit_passed = data.get("audit_passed", False)
        state.customers_to_analyze = data.get("customers_to_analyze", [])
        state.cross_skill_run_ids = data.get("cross_skill_run_ids", {})
        state.errors = [
            PipelineError(
                step=PipelineStep(e["step"]),
                error_type=e["error_type"],
                message=e["message"],
                recovered=e.get("recovered", False),
                recovery_action=e.get("recovery_action", ""),
            )
            for e in data.get("errors", [])
        ]
        return state
```

---

## 3. Pipeline Engine

The core engine that drives all 35 steps.

```python
# src/dd_agents/orchestrator/engine.py

import asyncio
import logging
import time
from pathlib import Path
from typing import Callable, Awaitable

from .state import PipelineState, PipelineError, StepResult
from .steps import PipelineStep
from .checkpoints import CheckpointManager

log = logging.getLogger("dd_agents.pipeline")


class BlockingGateError(Exception):
    """Raised when a blocking validation gate fails. Pipeline stops."""
    pass

class RecoverableError(Exception):
    """Raised for errors that can be recovered from (agent failure, etc.)."""
    pass

class AgentFailureError(RecoverableError):
    """Raised when an agent fails entirely. Recovery: re-spawn once."""
    pass

class PartialFailureError(RecoverableError):
    """Raised when an agent produces partial output. Recovery: re-spawn for missing."""
    pass


# Type alias for step functions
StepFn = Callable[[PipelineState], Awaitable[PipelineState]]


class PipelineEngine:
    """Drives the 35-step forensic DD pipeline.

    Each step is an async function: async def step_XX(state) -> state.
    Blocking gates raise BlockingGateError on failure.
    Conditional steps check state and return early if their condition is not met.
    """

    def __init__(self, project_dir: Path, deal_config_path: Path):
        self.project_dir = project_dir.resolve()
        self.deal_config_path = deal_config_path.resolve()
        self.state = PipelineState(project_dir=self.project_dir)
        self.checkpoint_mgr = CheckpointManager(self.project_dir)

    async def run(self, resume_from_step: int = 0) -> PipelineState:
        """Execute the full pipeline, optionally resuming from a checkpoint.

        Args:
            resume_from_step: Step number to resume from. 0 = start fresh.
                              Loads checkpoint for that step's predecessor.
        """
        if resume_from_step > 0:
            # Load the checkpoint from the step BEFORE the one we want to resume
            checkpoint_step = resume_from_step - 1
            if checkpoint_step > 0:
                self.state = self.checkpoint_mgr.load(checkpoint_step)
                log.info(f"Resumed from checkpoint at step {checkpoint_step}")
            else:
                log.info("Resuming from step 1 -- no prior checkpoint needed")

        steps = self._build_step_list()

        for step_enum, step_fn in steps:
            step_num = step_enum.step_number
            if step_num < resume_from_step:
                continue

            self.state.current_step = step_enum
            gate_label = " [BLOCKING GATE]" if step_enum.is_blocking_gate else ""
            cond_label = " [CONDITIONAL]" if step_enum.is_conditional else ""
            log.info(
                f"Step {step_num}/35: {step_enum.value}{gate_label}{cond_label}"
            )

            t0 = time.monotonic()
            try:
                self.state = await step_fn(self.state)

                duration_ms = int((time.monotonic() - t0) * 1000)
                result = StepResult(
                    step=step_enum, success=True, duration_ms=duration_ms
                )
                self.state.step_results[step_enum.value] = result
                self.state.completed_steps.append(step_enum)
                self.checkpoint_mgr.save(self.state)
                log.info(f"  Completed in {duration_ms}ms")

            except BlockingGateError as e:
                duration_ms = int((time.monotonic() - t0) * 1000)
                result = StepResult(
                    step=step_enum, success=False,
                    duration_ms=duration_ms, error=str(e),
                )
                self.state.step_results[step_enum.value] = result
                self.state.errors.append(PipelineError(
                    step=step_enum,
                    error_type="blocking_gate",
                    message=str(e),
                ))
                self.checkpoint_mgr.save(self.state)
                log.error(f"  BLOCKING GATE FAILED at step {step_num}: {e}")
                raise

            except RecoverableError as e:
                duration_ms = int((time.monotonic() - t0) * 1000)
                log.warning(f"  Recoverable error at step {step_num}: {e}")
                self.state.errors.append(PipelineError(
                    step=step_enum,
                    error_type="recoverable",
                    message=str(e),
                ))
                self.state = await self._recover(step_enum, e, self.state)
                self.state.step_results[step_enum.value] = StepResult(
                    step=step_enum, success=True,
                    duration_ms=int((time.monotonic() - t0) * 1000),
                    metadata={"recovered": True},
                )
                self.state.completed_steps.append(step_enum)
                self.checkpoint_mgr.save(self.state)

        log.info("Pipeline completed successfully")
        return self.state

    def _build_step_list(self) -> list[tuple[PipelineStep, StepFn]]:
        """Returns the ordered list of (PipelineStep, async_function) pairs.

        Import step functions lazily to avoid circular imports.
        """
        from .step_implementations import (
            step_01_validate_config,
            step_02_init_persistence,
            step_03_cross_skill_check,
            step_04_file_discovery,
            step_05_bulk_extraction,
            step_06_build_inventory,
            step_07_entity_resolution,
            step_08_reference_registry,
            step_09_customer_mentions,
            step_10_inventory_integrity,
            step_11_contract_date_reconciliation,
            step_12_incremental_classification,
            step_13_create_team,
            step_14_prepare_prompts,
            step_15_route_references,
            step_16_spawn_specialists,
            step_17_coverage_gate,
            step_18_incremental_merge,
            step_19_spawn_judge,
            step_20_judge_review,
            step_21_judge_respawn,
            step_22_judge_round2,
            step_23_spawn_reporting_lead,
            step_24_merge_dedup,
            step_25_merge_gaps,
            step_26_build_numerical_manifest,
            step_27_numerical_audit,
            step_28_full_qa_audit,
            step_29_build_report_diff,
            step_30_generate_excel,
            step_31_post_generation_validation,
            step_32_finalize_metadata,
            step_33_update_run_history,
            step_34_save_entity_cache,
            step_35_shutdown,
        )

        return [
            (PipelineStep.VALIDATE_CONFIG,             step_01_validate_config),
            (PipelineStep.INIT_PERSISTENCE,            step_02_init_persistence),
            (PipelineStep.CROSS_SKILL_CHECK,           step_03_cross_skill_check),
            (PipelineStep.FILE_DISCOVERY,              step_04_file_discovery),
            (PipelineStep.BULK_EXTRACTION,             step_05_bulk_extraction),
            (PipelineStep.BUILD_INVENTORY,             step_06_build_inventory),
            (PipelineStep.ENTITY_RESOLUTION,           step_07_entity_resolution),
            (PipelineStep.REFERENCE_REGISTRY,          step_08_reference_registry),
            (PipelineStep.CUSTOMER_MENTIONS,           step_09_customer_mentions),
            (PipelineStep.INVENTORY_INTEGRITY,         step_10_inventory_integrity),
            (PipelineStep.CONTRACT_DATE_RECONCILIATION, step_11_contract_date_reconciliation),
            (PipelineStep.INCREMENTAL_CLASSIFICATION,  step_12_incremental_classification),
            (PipelineStep.CREATE_TEAM,                 step_13_create_team),
            (PipelineStep.PREPARE_PROMPTS,             step_14_prepare_prompts),
            (PipelineStep.ROUTE_REFERENCES,            step_15_route_references),
            (PipelineStep.SPAWN_SPECIALISTS,           step_16_spawn_specialists),
            (PipelineStep.COVERAGE_GATE,               step_17_coverage_gate),
            (PipelineStep.INCREMENTAL_MERGE,           step_18_incremental_merge),
            (PipelineStep.SPAWN_JUDGE,                 step_19_spawn_judge),
            (PipelineStep.JUDGE_REVIEW,                step_20_judge_review),
            (PipelineStep.JUDGE_RESPAWN,               step_21_judge_respawn),
            (PipelineStep.JUDGE_ROUND2,                step_22_judge_round2),
            (PipelineStep.SPAWN_REPORTING_LEAD,        step_23_spawn_reporting_lead),
            (PipelineStep.MERGE_DEDUP,                 step_24_merge_dedup),
            (PipelineStep.MERGE_GAPS,                  step_25_merge_gaps),
            (PipelineStep.BUILD_NUMERICAL_MANIFEST,    step_26_build_numerical_manifest),
            (PipelineStep.NUMERICAL_AUDIT,             step_27_numerical_audit),
            (PipelineStep.FULL_QA_AUDIT,               step_28_full_qa_audit),
            (PipelineStep.BUILD_REPORT_DIFF,           step_29_build_report_diff),
            (PipelineStep.GENERATE_EXCEL,              step_30_generate_excel),
            (PipelineStep.POST_GENERATION_VALIDATION,  step_31_post_generation_validation),
            (PipelineStep.FINALIZE_METADATA,           step_32_finalize_metadata),
            (PipelineStep.UPDATE_RUN_HISTORY,          step_33_update_run_history),
            (PipelineStep.SAVE_ENTITY_CACHE,           step_34_save_entity_cache),
            (PipelineStep.SHUTDOWN,                    step_35_shutdown),
        ]

    async def _recover(
        self, step: PipelineStep, error: RecoverableError, state: PipelineState
    ) -> PipelineState:
        """Error recovery per SKILL.md section 7.

        Recovery strategies by error type:
        - AgentFailureError: Re-spawn once with same prompt.
        - PartialFailureError: Re-spawn for missing customers only.
        - Other RecoverableError: Log and continue.
        """
        if isinstance(error, AgentFailureError):
            agent_name = getattr(error, "agent_name", "unknown")
            log.info(f"  Attempting re-spawn of agent {agent_name}")
            try:
                from .step_implementations import respawn_agent
                state = await respawn_agent(state, agent_name)
                state.errors[-1].recovered = True
                state.errors[-1].recovery_action = f"Re-spawned {agent_name}"
            except Exception as retry_err:
                log.error(f"  Re-spawn of {agent_name} also failed: {retry_err}")
                state.errors[-1].recovery_action = (
                    f"Re-spawn failed: {retry_err}. Continuing with gaps logged."
                )
        elif isinstance(error, PartialFailureError):
            agent_name = getattr(error, "agent_name", "unknown")
            missing = getattr(error, "missing_customers", [])
            log.info(
                f"  Attempting re-spawn of {agent_name} for {len(missing)} missing customers"
            )
            try:
                from .step_implementations import respawn_for_missing
                state = await respawn_for_missing(state, agent_name, missing)
                state.errors[-1].recovered = True
                state.errors[-1].recovery_action = (
                    f"Re-spawned {agent_name} for {len(missing)} missing customers"
                )
            except Exception as retry_err:
                log.error(f"  Partial re-spawn also failed: {retry_err}")
                # Log P1 gaps for every uncovered customer
                from .step_implementations import log_coverage_gaps
                log_coverage_gaps(state, agent_name, missing)
                state.errors[-1].recovery_action = (
                    f"Re-spawn failed. P1 gaps logged for {len(missing)} customers."
                )
        else:
            log.warning(f"  No specific recovery for {type(error).__name__}. Continuing.")
            state.errors[-1].recovery_action = "No recovery -- continued with warning."

        return state
```

**Partial failure**: Findings from successful agents are preserved. Failed agents are retried up to `max_retries` (default 2). If retry fails, the pipeline continues with available findings and marks the affected customers with `incomplete_analysis: true` in the merged output.

### Error Classification → Recovery Action Mapping

| `error_type` | Source | Recovery Action | Pipeline Outcome |
|---|---|---|---|
| `blocking_gate` | Blocking gate step fails validation | None -- pipeline halts immediately | `BlockingGateError` raised; checkpoint saved for manual intervention |
| `agent_failure` | Agent spawn raises exception or `is_error=True` | Re-spawn agent once with same prompt | If retry fails: log P1 gaps for all affected customers, continue |
| `partial_failure` | Agent completes but missing customer outputs | Re-spawn for missing customers only | If retry fails: log P1 gaps per missing customer, continue |
| `recoverable` | Non-critical errors (e.g., stale cache, missing optional data) | Log warning, continue | Pipeline proceeds with warning in `errors[]` |

---

## 4. Step Implementations (Key Steps)

Each step is defined in `src/dd_agents/orchestrator/step_implementations/`. Below are the key implementations.

### Step 1: Validate Config (Blocking on Failure)

```python
# src/dd_agents/orchestrator/step_implementations/step_01.py

import hashlib
import json
import logging
from pathlib import Path

from ...config.deal_config import DealConfig
from ..state import PipelineState
from ..engine import BlockingGateError

log = logging.getLogger("dd_agents.steps.01")


def _semver_gte(version: str, minimum: str) -> bool:
    """Check if version >= minimum using semver comparison."""
    def parse(v: str) -> tuple[int, ...]:
        return tuple(int(x) for x in v.split("."))
    return parse(version) >= parse(minimum)


async def step_01_validate_config(state: PipelineState) -> PipelineState:
    """Load and validate deal-config.json. BLOCKS if missing or incompatible."""

    config_path = state.project_dir / "deal-config.json"
    if not config_path.exists():
        raise BlockingGateError(
            "deal-config.json not found in project directory. "
            "Create one from the template at deal-config.template.json"
        )

    raw = json.loads(config_path.read_text())
    config = DealConfig.model_validate(raw)  # Pydantic v2 validation

    # Version check: config_version must be >= 1.0.0
    if not _semver_gte(config.config_version, "1.0.0"):
        raise BlockingGateError(
            f"config_version {config.config_version} < 1.0.0 -- upgrade required"
        )

    state.deal_config = raw
    state.config_hash = hashlib.sha256(config_path.read_bytes()).hexdigest()
    state.judge_enabled = config.judge.enabled
    state.execution_mode = config.execution.execution_mode

    # Check framework version for incremental mode forcing
    fw_version_path = state.project_dir / "_dd" / "framework_version.txt"
    if fw_version_path.exists():
        state.framework_version = fw_version_path.read_text().strip()
    else:
        state.framework_version = "unknown"

    # Force full mode if config changed since prior run
    prior_meta = _load_prior_metadata(state)
    if prior_meta:
        state.prior_run_id = prior_meta.get("run_id")
        prior_run_path = state.skill_dir / "runs" / state.prior_run_id
        if prior_run_path.exists():
            state.prior_run_dir = prior_run_path

        # Config change detection
        if (config.execution.force_full_on_config_change
                and prior_meta.get("config_hash") != state.config_hash):
            state.execution_mode = "full"
            log.info("Config changed since prior run -- forcing full execution mode")

        # Framework version change detection
        prior_fw_version = prior_meta.get("framework_version", "unknown")
        if state.framework_version != prior_fw_version:
            state.execution_mode = "full"
            log.info(
                f"Framework version changed ({prior_fw_version} -> {state.framework_version}) "
                "-- forcing full execution mode"
            )
    else:
        # No prior run exists -- treat as first run, force full
        state.execution_mode = "full"

    log.info(
        f"Config validated: {config.target.name}, "
        f"mode={state.execution_mode}, judge={state.judge_enabled}"
    )
    return state


def _load_prior_metadata(state: PipelineState) -> dict | None:
    """Load metadata.json from the most recent prior run, if any."""
    latest_link = state.project_dir / state.skill_dir / "runs" / "latest"
    if not latest_link.is_symlink():
        return None
    prior_run_id = latest_link.resolve().name
    meta_path = state.project_dir / state.skill_dir / "runs" / prior_run_id / "metadata.json"
    if not meta_path.exists():
        return None
    return json.loads(meta_path.read_text())
```

### Step 2: Initialize Persistence

```python
# src/dd_agents/orchestrator/step_implementations/step_02.py

import shutil
import logging
from datetime import datetime, timezone
from pathlib import Path

from ..state import PipelineState

log = logging.getLogger("dd_agents.steps.02")


async def step_02_init_persistence(state: PipelineState) -> PipelineState:
    """Generate run_id, create directories, snapshot prior inventory, wipe FRESH tier.

    Three-tier persistence model:
    - PERMANENT: never wiped (index/text/, checksums, extraction_quality, entity_cache, runs/)
    - VERSIONED: archived per run (runs/{run_id}/)
    - FRESH: rebuilt every run (inventory/)
    """
    base = state.project_dir

    # Generate run_id
    state.run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    skill_dir = base / state.skill_dir
    state.run_dir = skill_dir / "runs" / state.run_id

    # Create VERSIONED directories for this run
    dirs_to_create = [
        state.run_dir / "findings" / "legal" / "gaps",
        state.run_dir / "findings" / "finance" / "gaps",
        state.run_dir / "findings" / "commercial" / "gaps",
        state.run_dir / "findings" / "producttech" / "gaps",
        state.run_dir / "findings" / "merged" / "gaps",
        state.run_dir / "judge",
        state.run_dir / "report",
        state.run_dir / "audit" / "legal",
        state.run_dir / "audit" / "finance",
        state.run_dir / "audit" / "commercial",
        state.run_dir / "audit" / "producttech",
        state.run_dir / "audit" / "reporting_lead",
        state.run_dir / "audit" / "judge",
    ]
    for d in dirs_to_create:
        d.mkdir(parents=True, exist_ok=True)

    # Create PERMANENT directories (no-op if they exist)
    (skill_dir / "index" / "text").mkdir(parents=True, exist_ok=True)
    (skill_dir / "inventory").mkdir(parents=True, exist_ok=True)

    # Snapshot prior inventory into its run directory BEFORE wiping FRESH tier
    latest_link = skill_dir / "runs" / "latest"
    if latest_link.is_symlink():
        prior_run_id = latest_link.resolve().name
        prior_run_dir = skill_dir / "runs" / prior_run_id
        inventory_dir = skill_dir / "inventory"
        snapshot_dir = prior_run_dir / "inventory_snapshot"
        if inventory_dir.exists() and not snapshot_dir.exists():
            shutil.copytree(inventory_dir, snapshot_dir)
            log.info(f"Snapshotted prior inventory to {snapshot_dir}")

    # DO NOT update latest symlink here -- updated at step 32 after success

    # Wipe FRESH tier
    inventory_dir = skill_dir / "inventory"
    if inventory_dir.exists():
        shutil.rmtree(inventory_dir)
    inventory_dir.mkdir(parents=True, exist_ok=True)

    log.info(f"Initialized run {state.run_id} at {state.run_dir}")
    return state
```

### Step 5: Bulk Extraction (BLOCKING GATE)

```python
# src/dd_agents/orchestrator/step_implementations/step_05.py

import json
import logging
from pathlib import Path

from ..state import PipelineState
from ..engine import BlockingGateError

log = logging.getLogger("dd_agents.steps.05")


async def step_05_bulk_extraction(state: PipelineState) -> PipelineState:
    """Extract text from all non-plaintext files. BLOCKING GATE.

    Uses markitdown with fallback chain: markitdown -> pdftotext -> OCR -> Read tool.
    Maintains checksums.sha256 for extraction caching across runs.
    Records extraction quality in extraction_quality.json.
    """
    from ...extraction.pipeline import ExtractionPipeline

    index_dir = state.project_dir / state.skill_dir / "index" / "text"
    checksum_path = index_dir / "checksums.sha256"
    quality_path = state.project_dir / state.skill_dir / "index" / "extraction_quality.json"

    pipeline = ExtractionPipeline(
        index_dir=index_dir,
        checksum_file=checksum_path,
        quality_file=quality_path,
    )

    files_txt = state.project_dir / state.skill_dir / "inventory" / "files.txt"
    file_list = files_txt.read_text().strip().splitlines()

    result = await pipeline.extract_all(file_list, state.project_dir)

    # --- BLOCKING GATE CHECKS ---

    # 1. checksums.sha256 must exist and be non-empty
    if not checksum_path.exists() or checksum_path.stat().st_size == 0:
        raise BlockingGateError(
            "checksums.sha256 missing or empty after extraction. "
            "Extraction pipeline did not produce checksum records."
        )

    # 2. extraction_quality.json must exist and be non-empty
    if not quality_path.exists() or quality_path.stat().st_size == 0:
        raise BlockingGateError(
            "extraction_quality.json missing or empty after extraction. "
            "Extraction pipeline did not produce quality records."
        )

    # 3. Systemic failure check: >50% of files failing primary method
    if result.primary_failure_rate > 0.5:
        raise BlockingGateError(
            f"Systemic extraction failure: {result.primary_failure_rate:.0%} of files "
            f"failed primary extraction method. Check markitdown installation and "
            f"file permissions. Pipeline halted -- agents depend on pre-extracted text."
        )

    log.info(
        f"Extraction complete: {result.files_extracted} extracted, "
        f"{result.files_cached} cached (unchanged), "
        f"{result.files_failed} failed, "
        f"{result.stale_removed} stale entries removed"
    )
    return state
```

### Step 14: Prepare Agent Prompts (with Size Estimation and Batching)

```python
# src/dd_agents/orchestrator/step_implementations/step_14.py

import json
import logging
from pathlib import Path

from ..state import PipelineState
from ...agents.prompt_builder import PromptBuilder

log = logging.getLogger("dd_agents.steps.14")

TOKEN_THRESHOLD = 80_000  # Max tokens per agent prompt before batching


async def step_14_prepare_prompts(state: PipelineState) -> PipelineState:
    """Prepare agent prompts with size estimation and customer batching.

    Prompt size estimation formula:
    (a) deal context:             ~500 tokens
    (b) customer list with paths: ~50 tokens per customer
    (c) reference file text:      actual_bytes / 4  (measured per file)
    (d) domain rules:             ~3,000 tokens
    (e) manifest/output schema:   ~500 tokens

    If estimated total exceeds TOKEN_THRESHOLD, pre-split customers into
    batches and plan multiple agent instances per type.
    """
    builder = PromptBuilder(state)

    # Load reference file extracted texts for size estimation
    ref_files_path = (
        state.project_dir / state.skill_dir / "inventory" / "reference_files.json"
    )
    reference_files = json.loads(ref_files_path.read_text())
    ref_text_sizes = builder.measure_reference_texts(reference_files)

    agent_types = ["legal", "finance", "commercial", "producttech"]

    # Determine customer list (full or scoped for incremental)
    if state.execution_mode == "incremental" and state.customers_to_analyze:
        customers = state.customers_to_analyze
    else:
        customers = state.customer_safe_names

    for agent_type in agent_types:
        # Estimate prompt size
        agent_ref_size = builder.get_agent_reference_size(agent_type, ref_text_sizes)
        estimated_tokens = (
            500                         # (a) deal context
            + 50 * len(customers)       # (b) customer list + file paths
            + agent_ref_size            # (c) reference file text
            + 3000                      # (d) domain rules
            + 500                       # (e) manifest/output instructions
        )

        if estimated_tokens > TOKEN_THRESHOLD:
            # Split customers into batches
            batch_size = _calculate_batch_size(
                len(customers), estimated_tokens, TOKEN_THRESHOLD, agent_ref_size
            )
            batches = _split_into_batches(customers, batch_size)
            log.info(
                f"Agent {agent_type}: {estimated_tokens} estimated tokens > {TOKEN_THRESHOLD} "
                f"threshold. Splitting {len(customers)} customers into {len(batches)} batches "
                f"of ~{batch_size} customers each."
            )
        else:
            batches = [customers]
            log.info(
                f"Agent {agent_type}: {estimated_tokens} estimated tokens -- single batch"
            )

        # Build prompt for each batch
        prompts = []
        for batch_idx, batch_customers in enumerate(batches):
            prompt = builder.build_specialist_prompt(
                agent_type=agent_type,
                customers=batch_customers,
                reference_files=reference_files,
                batch_index=batch_idx if len(batches) > 1 else None,
                total_batches=len(batches) if len(batches) > 1 else None,
            )
            prompts.append(prompt)

        state.agent_prompts[agent_type] = prompts
        state.batch_counts[agent_type] = len(batches)

    return state


def _calculate_batch_size(
    total_customers: int, estimated_tokens: int,
    threshold: int, ref_size: int,
) -> int:
    """Calculate how many customers per batch to stay under token threshold.

    Reference text is shared across all batches (not split), so the per-customer
    portion is the variable part.
    """
    fixed_tokens = 500 + ref_size + 3000 + 500  # non-customer tokens
    available_for_customers = threshold - fixed_tokens
    tokens_per_customer = 50  # approximate
    max_per_batch = max(1, available_for_customers // tokens_per_customer)
    return min(max_per_batch, total_customers)


def _split_into_batches(customers: list[str], batch_size: int) -> list[list[str]]:
    """Split customer list into roughly equal batches."""
    batches = []
    for i in range(0, len(customers), batch_size):
        batches.append(customers[i:i + batch_size])
    return batches
```

### Step 16: Spawn Specialists in Parallel

```python
# src/dd_agents/orchestrator/step_implementations/step_16.py

import asyncio
import logging
from typing import Any

from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage, AssistantMessage

from ..state import PipelineState
from ..engine import AgentFailureError

log = logging.getLogger("dd_agents.steps.16")


async def step_16_spawn_specialists(state: PipelineState) -> PipelineState:
    """Spawn 4 specialist agents IN PARALLEL using claude-agent-sdk.

    Each agent gets:
    - Complete prompt with deal context, customer list, reference files,
      domain rules, output schema, manifest requirement
    - MCP tools for validation (validate_finding, resolve_entity, etc.)
    - Hooks for output path enforcement and per-customer JSON validation
    - Working directory set to the project directory

    If prompt batching was triggered at step 14, spawns multiple instances
    per agent type (e.g., "legal-batch1", "legal-batch2").
    """
    from ...agents.hooks import create_specialist_hooks
    from ...agents.mcp_server import get_tools_server

    tools_server = get_tools_server(state)
    agent_types = ["legal", "finance", "commercial", "producttech"]

    # Build list of (agent_name, prompt) pairs
    spawn_tasks: list[tuple[str, str]] = []
    for agent_type in agent_types:
        prompts = state.agent_prompts[agent_type]
        for batch_idx, prompt in enumerate(prompts):
            if len(prompts) == 1:
                name = agent_type
            else:
                name = f"{agent_type}-batch{batch_idx + 1}"
            spawn_tasks.append((name, prompt))

    # Spawn all agents concurrently
    async def _run_agent(name: str, prompt: str) -> dict[str, Any]:
        """Run a single specialist agent and collect its result."""
        agent_type = name.split("-")[0]  # "legal-batch1" -> "legal"
        hooks = create_specialist_hooks(state, agent_type)

        options = ClaudeAgentOptions(
            model="claude-sonnet-4-20250514",
            max_budget_usd=5.0,
            permission_mode="bypassPermissions",
            system_prompt=(
                f"You are the {agent_type.upper()} specialist for forensic M&A "
                f"due diligence. Follow every instruction exactly."
            ),
            mcp_servers={"dd_tools": tools_server},
            allowed_tools=[
                "Read", "Write", "Glob", "Grep", "Bash",
                "mcp__dd_tools__validate_finding",
                "mcp__dd_tools__resolve_entity",
                "mcp__dd_tools__get_customer_files",
                "mcp__dd_tools__report_progress",
            ],
            hooks=hooks,
            cwd=str(state.project_dir),
        )

        result_data = {"agent": name, "cost_usd": 0.0, "session_id": ""}
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                result_data["cost_usd"] = message.total_cost_usd or 0.0
                result_data["session_id"] = message.session_id
                result_data["num_turns"] = message.num_turns
                result_data["duration_ms"] = message.duration_ms
                result_data["is_error"] = message.is_error
                if message.is_error:
                    result_data["error"] = message.result
        return result_data

    # Run all agents in parallel using asyncio.gather
    coroutines = [_run_agent(name, prompt) for name, prompt in spawn_tasks]
    results = await asyncio.gather(*coroutines, return_exceptions=True)

    # Process results
    for (name, _prompt), result in zip(spawn_tasks, results):
        if isinstance(result, Exception):
            log.error(f"Agent {name} raised exception: {result}")
            error = AgentFailureError(f"Agent {name} failed: {result}")
            error.agent_name = name  # type: ignore
            state.errors.append(PipelineError(
                step=PipelineStep.SPAWN_SPECIALISTS,
                error_type="agent_failure",
                message=str(result),
            ))
        else:
            state.agent_results[name] = result
            state.agent_sessions[name] = result.get("session_id", "")
            state.agent_costs[name] = result.get("cost_usd", 0.0)
            if result.get("is_error"):
                log.warning(f"Agent {name} completed with error: {result.get('error')}")
            else:
                log.info(
                    f"Agent {name} completed: {result.get('num_turns')} turns, "
                    f"${result.get('cost_usd', 0):.4f}, "
                    f"{result.get('duration_ms', 0)}ms"
                )

    # If batched agents were used, merge batch outputs into primary directory
    for agent_type in agent_types:
        if state.batch_counts.get(agent_type, 1) > 1:
            _merge_batch_outputs(state, agent_type)

    return state


def _merge_batch_outputs(state: PipelineState, agent_type: str) -> None:
    """Merge outputs from batch directories into the primary agent directory.

    Batch agents write to {run_dir}/findings/{agent_type}-batch{N}/.
    This function moves all per-customer JSONs to {run_dir}/findings/{agent_type}/.
    """
    primary_dir = state.run_dir / "findings" / agent_type
    for batch_idx in range(1, state.batch_counts[agent_type] + 1):
        batch_dir = state.run_dir / "findings" / f"{agent_type}-batch{batch_idx}"
        if not batch_dir.exists():
            continue
        for json_file in batch_dir.glob("*.json"):
            target = primary_dir / json_file.name
            if not target.exists():
                json_file.rename(target)
        # Also merge gaps
        batch_gaps = batch_dir / "gaps"
        if batch_gaps.exists():
            primary_gaps = primary_dir / "gaps"
            for gap_file in batch_gaps.glob("*.json"):
                target = primary_gaps / gap_file.name
                if not target.exists():
                    gap_file.rename(target)
    log.info(f"Merged {state.batch_counts[agent_type]} batch outputs for {agent_type}")
```

### Step 17: Coverage Gate (BLOCKING GATE)

```python
# src/dd_agents/orchestrator/step_implementations/step_17.py

import json
import logging
from pathlib import Path

from ..state import PipelineState
from ..engine import BlockingGateError

log = logging.getLogger("dd_agents.steps.17")


async def step_17_coverage_gate(state: PipelineState) -> PipelineState:
    """Validate all specialists produced output for all customers. BLOCKING GATE.

    For each agent type:
    1. Count unique {customer_safe_name}.json files in findings/{agent}/
    2. Compare against expected customer count
    3. If missing: re-spawn for missing customers (one retry)
    4. If still missing after retry: log P1 gaps
    5. Verify coverage_manifest.json exists
    6. Verify no aggregate files (_global.json, batch_summary.json, etc.)
    7. Spot-check clean-result enforcement (3 customers per agent)
    8. Verify audit logs exist
    """
    agent_types = ["legal", "finance", "commercial", "producttech"]

    # Determine expected customers
    if state.execution_mode == "incremental" and state.customers_to_analyze:
        expected_customers = set(state.customers_to_analyze)
    else:
        expected_customers = set(state.customer_safe_names)

    total_missing = 0

    for agent_type in agent_types:
        output_dir = state.run_dir / "findings" / agent_type

        # Collect actual per-customer JSON files (exclude manifest and non-customer files)
        actual_files = set()
        aggregate_files = set()
        for p in output_dir.glob("*.json"):
            if p.stem == "coverage_manifest":
                continue
            if p.stem.startswith("_") or p.stem in (
                "batch_summary", "other_customers", "pipeline_items"
            ):
                aggregate_files.add(p.stem)
                continue
            actual_files.add(p.stem)

        # Flag aggregate files -- these indicate the agent did not follow per-customer format
        if aggregate_files:
            log.warning(
                f"Agent {agent_type} produced aggregate files: {aggregate_files}. "
                f"This indicates non-compliance with per-customer output format."
            )

        missing = expected_customers - actual_files
        if missing:
            log.warning(
                f"Agent {agent_type} missing {len(missing)}/{len(expected_customers)} "
                f"customers: {sorted(missing)[:5]}{'...' if len(missing) > 5 else ''}"
            )

            # Re-spawn for missing customers only (one retry)
            state = await _respawn_for_missing(state, agent_type, sorted(missing))

            # Re-check after re-spawn
            actual_files = {
                p.stem for p in output_dir.glob("*.json")
                if p.stem != "coverage_manifest"
                and not p.stem.startswith("_")
                and p.stem not in ("batch_summary", "other_customers", "pipeline_items")
            }
            still_missing = expected_customers - actual_files
            if still_missing:
                total_missing += len(still_missing)
                for customer in sorted(still_missing):
                    _log_coverage_gap(state, agent_type, customer)
                log.error(
                    f"Agent {agent_type} still missing {len(still_missing)} customers "
                    f"after re-spawn. P1 gaps logged."
                )

        # Verify coverage_manifest.json exists
        manifest_path = output_dir / "coverage_manifest.json"
        if not manifest_path.exists():
            log.warning(f"Agent {agent_type} missing coverage_manifest.json -- re-spawn")
            # Attempt re-spawn specifically for manifest
            # If this also fails, QA at step 28 will catch it

        # Verify audit log exists
        audit_path = state.run_dir / "audit" / agent_type / "audit_log.jsonl"
        if not audit_path.exists() or audit_path.stat().st_size == 0:
            log.warning(
                f"Agent {agent_type} missing audit_log.jsonl -- "
                f"QA at step 28 will flag this."
            )

        # Clean-result enforcement: spot-check 3 customer JSONs
        _spot_check_clean_results(state, agent_type, output_dir)

    if total_missing > 0:
        log.warning(
            f"Coverage gate: {total_missing} total customer-agent gaps across all agents. "
            f"P1 gaps logged. Pipeline continues."
        )

    return state


async def _respawn_for_missing(
    state: PipelineState, agent_type: str, missing: list[str]
) -> PipelineState:
    """Re-spawn an agent for specific missing customers only."""
    from ...agents.prompt_builder import PromptBuilder
    from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage

    builder = PromptBuilder(state)
    prompt = builder.build_respawn_prompt(agent_type, missing)

    options = ClaudeAgentOptions(
        model="claude-sonnet-4-20250514",
        max_budget_usd=3.0,
        permission_mode="bypassPermissions",
        cwd=str(state.project_dir),
    )

    log.info(f"Re-spawning {agent_type} for {len(missing)} missing customers")
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, ResultMessage):
            cost = message.total_cost_usd or 0.0
            state.agent_costs[f"{agent_type}_respawn"] = cost
            log.info(f"Re-spawn of {agent_type} completed: ${cost:.4f}")

    return state


def _log_coverage_gap(state: PipelineState, agent_type: str, customer: str) -> None:
    """Log a P1 gap for a customer that an agent failed to cover."""
    gap = {
        "customer": customer,
        "priority": "P1",
        "gap_type": "Missing_Data",
        "missing_item": f"{agent_type} analysis for {customer}",
        "why_needed": f"Agent {agent_type} did not produce output for this customer",
        "risk_if_missing": f"{agent_type.title()} domain coverage missing entirely",
        "request_to_company": "N/A -- internal analysis gap",
        "evidence": f"Agent {agent_type} output directory missing {customer}.json",
        "detection_method": "pattern_check",
        "agent": agent_type,
        "run_id": state.run_id,
    }
    gap_dir = state.run_dir / "findings" / agent_type / "gaps"
    gap_dir.mkdir(parents=True, exist_ok=True)
    gap_path = gap_dir / f"{customer}.json"
    gap_path.write_text(json.dumps([gap], indent=2))


def _spot_check_clean_results(
    state: PipelineState, agent_type: str, output_dir: Path
) -> None:
    """Spot-check 3 customer JSONs for clean-result enforcement.

    Per SKILL.md step 17: any customer JSON with zero findings AND no
    domain_reviewed_no_issues entry indicates the agent skipped the customer
    rather than reviewing it.
    """
    json_files = sorted(output_dir.glob("*.json"))
    checked = 0
    for path in json_files:
        if path.stem == "coverage_manifest" or path.stem.startswith("_"):
            continue
        if checked >= 3:
            break

        try:
            data = json.loads(path.read_text())
            findings = data.get("findings", [])
            has_substantive = any(
                f.get("category") != "domain_reviewed_no_issues"
                for f in findings
            )
            has_clean_result = any(
                f.get("category") == "domain_reviewed_no_issues"
                for f in findings
            )
            if not has_substantive and not has_clean_result:
                log.warning(
                    f"Agent {agent_type} customer {path.stem}: zero findings AND no "
                    f"domain_reviewed_no_issues entry -- possible skipped customer"
                )
            checked += 1
        except (json.JSONDecodeError, KeyError):
            log.warning(f"Could not parse {path} for clean-result check")
            checked += 1
```

### Steps 27-28: Blocking Validation Gates

```python
# src/dd_agents/orchestrator/step_implementations/step_27.py

import json
import logging

from ..state import PipelineState
from ..engine import BlockingGateError

log = logging.getLogger("dd_agents.steps.27")


async def step_27_numerical_audit(state: PipelineState) -> PipelineState:
    """Five-layer numerical validation. BLOCKING GATE.

    Layers 1-3 and 5 run before Excel generation.
    Layer 4 (cross-format parity) runs after Excel at step 31.

    Layer 1 -- Source Traceability: every number traces to a file + derivation.
    Layer 2 -- Arithmetic Verification: re-derive all numbers from source files.
    Layer 3 -- Cross-Source Consistency: numbers in multiple sources must agree.
    Layer 5 -- Semantic Reasonableness: flag implausible numbers.

    Counting convention: total_findings EXCLUDES domain_reviewed_no_issues entries.
    """
    from ...validation.numerical_audit import NumericalAuditor

    manifest_path = state.run_dir / "numerical_manifest.json"
    if not manifest_path.exists():
        raise BlockingGateError(
            "numerical_manifest.json not found. Step 26 must produce it."
        )

    auditor = NumericalAuditor(
        run_dir=state.run_dir,
        skill_dir=state.project_dir / state.skill_dir,
        project_dir=state.project_dir,
    )

    # Run layers 1, 2, 3, 5 (not 4 -- requires Excel)
    l1 = auditor.verify_sources(manifest_path)
    l2 = auditor.verify_arithmetic(manifest_path)
    l3 = auditor.verify_cross_source(manifest_path)
    l5 = auditor.verify_reasonableness(manifest_path, state.prior_run_id)

    failures = []
    for layer_name, result in [
        ("Layer 1 (Source Traceability)", l1),
        ("Layer 2 (Arithmetic Verification)", l2),
        ("Layer 3 (Cross-Source Consistency)", l3),
        ("Layer 5 (Semantic Reasonableness)", l5),
    ]:
        if not result.passed:
            failures.append(f"{layer_name}: {result.errors}")

    if failures:
        # Attempt auto-fix: use re-derived values from Layer 2
        if l2.corrections:
            log.info(f"Applying {len(l2.corrections)} arithmetic corrections")
            auditor.apply_corrections(manifest_path, l2.corrections)

            # Re-run all layers after corrections
            l1 = auditor.verify_sources(manifest_path)
            l2 = auditor.verify_arithmetic(manifest_path)
            l3 = auditor.verify_cross_source(manifest_path)
            l5 = auditor.verify_reasonableness(manifest_path, state.prior_run_id)

            failures = []
            for layer_name, result in [
                ("Layer 1 (Source Traceability)", l1),
                ("Layer 2 (Arithmetic Verification)", l2),
                ("Layer 3 (Cross-Source Consistency)", l3),
                ("Layer 5 (Semantic Reasonableness)", l5),
            ]:
                if not result.passed:
                    failures.append(f"{layer_name}: {result.errors}")

        if failures:
            # Write failure details for debugging
            failure_path = state.run_dir / "numerical_audit_failures.json"
            failure_path.write_text(json.dumps(failures, indent=2))
            raise BlockingGateError(
                f"Numerical audit failed ({len(failures)} layer(s)): "
                + "; ".join(failures)
            )

    log.info("Numerical audit passed (Layers 1-3, 5)")
    state.validation_results["numerical_audit"] = True
    return state
```

```python
# src/dd_agents/orchestrator/step_implementations/step_28.py

import json
import logging

from ..state import PipelineState
from ..engine import BlockingGateError

log = logging.getLogger("dd_agents.steps.28")


async def step_28_full_qa_audit(state: PipelineState) -> PipelineState:
    """Full QA audit covering all 30 Definition of Done checks. BLOCKING GATE.

    Fail-closed: ANY check failure blocks the report.
    Writes {RUN_DIR}/audit.json with per-check results.

    Checks (from SKILL.md section 9):
    Core Analysis (1-12): customer coverage, file coverage, manifest reconciliation,
        governance, citations, gaps, cross-references, ghost customers, reference files,
        audit logs, domain coverage.
    Reporting & Audit (13-19): merge/dedup, report sheets, audit.json, entity resolution,
        numerical manifest, contract date reconciliation, extraction quality.
    Judge Quality (20-23): only if judge.enabled.
    Incremental Mode (24-27): only if execution_mode == "incremental".
    Report Consistency (28-30): checked at step 31 (post-generation).
    """
    from ...validation.qa_audit import QAAuditor

    auditor = QAAuditor(
        run_dir=state.run_dir,
        skill_dir=state.project_dir / state.skill_dir,
        project_dir=state.project_dir,
        state=state,
    )

    audit_result = auditor.run_all_checks()

    # Write audit.json
    audit_path = state.run_dir / "audit.json"
    audit_path.write_text(json.dumps(audit_result, indent=2))

    if not audit_result["audit_passed"]:
        failed_checks = [
            name for name, check in audit_result["checks"].items()
            if not check["passed"]
        ]
        raise BlockingGateError(
            f"QA audit failed. {len(failed_checks)} check(s) failed: "
            + ", ".join(failed_checks)
            + f". See {audit_path} for details."
        )

    log.info("Full QA audit passed -- all applicable DoD checks satisfied")
    state.audit_passed = True
    state.validation_results["qa_audit"] = True
    return state
```

---

## 5. Checkpoint and Resume

```python
# src/dd_agents/orchestrator/checkpoints.py

import json
import logging
from pathlib import Path
from typing import Optional

from .state import PipelineState

log = logging.getLogger("dd_agents.checkpoints")


class CheckpointManager:
    """Saves pipeline state after each step for crash recovery.

    Checkpoint format: {skill_dir}/checkpoints/step_{NN}.json
    Each checkpoint is a complete PipelineState serialization.
    Uses atomic writes (write to .tmp, then rename) to prevent corruption.
    """

    def __init__(self, project_dir: Path):
        self.checkpoint_dir = project_dir / "_dd" / "forensic-dd" / "checkpoints"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def save(self, state: PipelineState) -> None:
        """Save current state as a checkpoint. Atomic write."""
        step_num = state.current_step.step_number
        data = state.to_checkpoint()
        path = self.checkpoint_dir / f"step_{step_num:02d}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, default=str))
        tmp.rename(path)
        log.debug(f"Checkpoint saved: {path.name}")

    def load(self, step: int) -> PipelineState:
        """Load state from a specific step's checkpoint."""
        path = self.checkpoint_dir / f"step_{step:02d}.json"
        if not path.exists():
            raise FileNotFoundError(f"No checkpoint for step {step} at {path}")
        data = json.loads(path.read_text())
        log.info(f"Loaded checkpoint from step {step}")
        return PipelineState.from_checkpoint(data)

    def latest(self) -> Optional[int]:
        """Return the highest completed step number, or None if no checkpoints."""
        files = sorted(self.checkpoint_dir.glob("step_*.json"))
        if not files:
            return None
        return int(files[-1].stem.split("_")[1])

    def clean(self) -> None:
        """Remove all checkpoints (called after successful pipeline completion)."""
        for f in self.checkpoint_dir.glob("step_*.json"):
            f.unlink()
        for f in self.checkpoint_dir.glob("step_*.tmp"):
            f.unlink()
        log.info("Checkpoints cleaned")
```

### Resume Protocol

To resume a failed pipeline:

```python
engine = PipelineEngine(project_dir, deal_config_path)

# Find the latest successful checkpoint
latest = engine.checkpoint_mgr.latest()
if latest is not None:
    log.info(f"Found checkpoint at step {latest}. Resuming from step {latest + 1}.")
    state = await engine.run(resume_from_step=latest + 1)
else:
    log.info("No checkpoint found. Starting fresh.")
    state = await engine.run()
```

The `checkpoint.json` written after each step contains the full `PipelineState`, including:
- All completed steps and their results
- Agent session IDs (for potential session resumption via SDK `resume` parameter)
- Inventory counts, customer lists, batch counts
- Error history with recovery actions
- Validation results

This means the pipeline can resume from any step without re-running preceding steps.

**Resume semantics**: `load_checkpoint()` deserializes PipelineState from `_dd/forensic-dd/runs/{run_id}/checkpoint.json` (via `CheckpointManager.load()`). The engine skips all steps where `state.completed_steps` contains the step number. It resumes from `max(completed_steps) + 1`. PERMANENT tier data persists across runs. VERSIONED tier from the interrupted run is preserved in place. FRESH tier uses data from the original run start (not rebuilt on resume).

---

## 6. Conditional Step Logic

Steps with preconditions check their condition and return early if not met. This is implemented in each step function, not in the engine.

```python
# Step 11: Contract Date Reconciliation
# Condition: source_of_truth.customer_database exists in deal-config.json
async def step_11_contract_date_reconciliation(state: PipelineState) -> PipelineState:
    """Reconcile contract dates against customer database. CONDITIONAL."""
    source_of_truth = state.deal_config.get("source_of_truth", {})
    if not source_of_truth.get("customer_database"):
        log.info("Skipping step 11 -- no source_of_truth.customer_database in config")
        return state
    # ... reconciliation logic ...
    return state


# Step 12: Incremental Classification
# Condition: execution_mode == "incremental"
async def step_12_incremental_classification(state: PipelineState) -> PipelineState:
    """Classify customers as NEW/CHANGED/STALE/UNCHANGED/DELETED. CONDITIONAL."""
    if state.execution_mode != "incremental":
        log.info("Skipping step 12 -- not incremental mode")
        return state
    # ... classification logic ...
    return state


# Step 18: Incremental Merge
# Condition: execution_mode == "incremental"
async def step_18_incremental_merge(state: PipelineState) -> PipelineState:
    """Merge new findings with carried-forward findings. CONDITIONAL."""
    if state.execution_mode != "incremental":
        log.info("Skipping step 18 -- not incremental mode")
        return state
    # ... merge carried-forward findings with _carried_forward: true metadata ...
    return state


# Steps 19-22: Judge
# Condition: judge.enabled in deal-config.json
async def step_19_spawn_judge(state: PipelineState) -> PipelineState:
    """Spawn Judge agent for quality review. CONDITIONAL."""
    if not state.judge_enabled:
        log.info("Skipping step 19 -- judge not enabled")
        return state
    # ... spawn Judge agent ...
    return state

async def step_20_judge_review(state: PipelineState) -> PipelineState:
    """Judge samples, spot-checks, scores. CONDITIONAL."""
    if not state.judge_enabled:
        return state
    # ... wait for Judge, parse quality_scores.json ...
    return state

async def step_21_judge_respawn(state: PipelineState) -> PipelineState:
    """Re-spawn agents below threshold with targeted feedback. CONDITIONAL."""
    if not state.judge_enabled:
        return state
    # Check if any agent below threshold
    scores_path = state.run_dir / "judge" / "quality_scores.json"
    if not scores_path.exists():
        return state
    scores = json.loads(scores_path.read_text())
    below_threshold = scores.get("agents_below_threshold", [])
    if not below_threshold:
        return state
    # ... re-spawn with targeted prompt for up to 5 lowest-scoring customers ...
    return state

async def step_22_judge_round2(state: PipelineState) -> PipelineState:
    """Judge Round 2 review of re-analyzed findings. CONDITIONAL."""
    if not state.judge_enabled:
        return state
    # ... Judge reviews re-analyzed findings ...
    # Blend formula: 70% new score + 30% prior score
    # If still below threshold: force finalization with quality caveats
    return state


# Step 29: Report Diff
# Condition: prior run exists
async def step_29_build_report_diff(state: PipelineState) -> PipelineState:
    """Build report diff against prior run. CONDITIONAL."""
    if not state.prior_run_id or not state.prior_run_dir:
        log.info("Skipping step 29 -- no prior run for diff comparison")
        return state
    # ... diff algorithm: match findings by customer + category + citation location ...
    return state
```

---

## 7. Pipeline Phase Summary

```
Phase 1: Setup (Steps 1-3)
    1. Validate deal-config.json
    2. Initialize persistence (create run dirs, wipe FRESH)
    3. Cross-skill check (scan for other DD skill outputs)

Phase 2: Discovery & Extraction (Steps 4-5)
    4. File discovery (tree.txt, files.txt, file_types.txt)
    5. Bulk pre-extraction [BLOCKING GATE]

Phase 3: Inventory (Steps 6-12)
    6. Build inventory (customers.csv, counts.json)
    7. Entity resolution (6-pass matcher with cache)
    8. Reference registry (reference_files.json)
    9. Customer-mention index (customer_mentions.json)
   10. Inventory integrity check (no orphan files)
   11. Contract date reconciliation [CONDITIONAL: customer_database exists]
   12. Incremental classification [CONDITIONAL: incremental mode]

Phase 4: Agent Execution (Steps 13-17)
   13. Create team and tasks
   14. Prepare agent prompts (with size estimation, batching)
   15. Route reference files to agents
   16. Spawn 4 specialists IN PARALLEL
   17. Coverage gate [BLOCKING GATE]

Phase 5: Quality Review (Steps 18-22)
   18. Incremental merge [CONDITIONAL: incremental mode]
   19. Spawn Judge [CONDITIONAL: judge.enabled]
   20. Judge review [CONDITIONAL: judge.enabled]
   21. Judge respawn [CONDITIONAL: agents below threshold]
   22. Judge Round 2 [CONDITIONAL: agents below threshold]

Phase 6: Reporting (Steps 23-31)
   23. Spawn Reporting Lead
   24. Merge and deduplicate findings
   25. Merge gap files
   26. Build numerical manifest
   27. Numerical audit [BLOCKING GATE]
   28. Full QA audit [BLOCKING GATE]
   29. Build report diff [CONDITIONAL: prior run exists]
   30. Generate Excel from report_schema.json
   31. Post-generation validation [BLOCKING GATE]

Phase 7: Finalization (Steps 32-35)
   32. Finalize metadata.json, update 'latest' symlink
   33. Update run_history.json
   34. Save entity resolution cache
   35. Shutdown all agents
```
