"""PipelineStep enum enumerating all 35 pipeline steps.

Each step has a canonical string value used in checkpoints, logs, and error
messages.  Properties expose the step number, whether the step is a blocking
gate, and whether it is conditional on runtime configuration.
"""

from __future__ import annotations

from enum import StrEnum


class PipelineStep(StrEnum):
    """All 35 pipeline steps.  String values used in checkpoint filenames."""

    # Phase 1: Setup (Steps 1-3)
    VALIDATE_CONFIG = "01_validate_config"
    INIT_PERSISTENCE = "02_init_persistence"
    CROSS_SKILL_CHECK = "03_cross_skill_check"

    # Phase 2: Discovery & Extraction (Steps 4-5)
    FILE_DISCOVERY = "04_file_discovery"
    BULK_EXTRACTION = "05_bulk_extraction"  # BLOCKING GATE

    # Phase 3: Inventory (Steps 6-12)
    BUILD_INVENTORY = "06_build_inventory"
    ENTITY_RESOLUTION = "07_entity_resolution"
    REFERENCE_REGISTRY = "08_reference_registry"
    SUBJECT_MENTIONS = "09_subject_mentions"
    INVENTORY_INTEGRITY = "10_inventory_integrity"
    CONTRACT_DATE_RECONCILIATION = "11_contract_date_reconciliation"  # CONDITIONAL
    INCREMENTAL_CLASSIFICATION = "12_incremental_classification"  # CONDITIONAL

    # Phase 4: Agent Execution (Steps 13-17)
    CREATE_TEAM = "13_create_team"
    PREPARE_PROMPTS = "14_prepare_prompts"
    ROUTE_REFERENCES = "15_route_references"
    SPAWN_SPECIALISTS = "16_spawn_specialists"
    COVERAGE_GATE = "17_coverage_gate"  # BLOCKING GATE

    # Phase 5: Quality Review (Steps 18-22)
    INCREMENTAL_MERGE = "18_incremental_merge"  # CONDITIONAL
    SPAWN_JUDGE = "19_spawn_judge"  # CONDITIONAL
    JUDGE_REVIEW = "20_judge_review"  # CONDITIONAL
    JUDGE_RESPAWN = "21_judge_respawn"  # CONDITIONAL
    JUDGE_ROUND2 = "22_judge_round2"  # CONDITIONAL

    # Phase 6: Reporting (Steps 23-31)
    SPAWN_REPORTING_LEAD = (
        "23_spawn_reporting_lead"  # Pre-merge validation (was: Reporting Lead agent, removed as redundant)
    )
    PRE_MERGE_VALIDATION = "23_spawn_reporting_lead"  # Backward-compatible alias for SPAWN_REPORTING_LEAD
    MERGE_DEDUP = "24_merge_dedup"
    MERGE_GAPS = "25_merge_gaps"
    BUILD_NUMERICAL_MANIFEST = "26_build_numerical_manifest"
    NUMERICAL_AUDIT = "27_numerical_audit"  # BLOCKING GATE
    FULL_QA_AUDIT = "28_full_qa_audit"  # BLOCKING GATE
    BUILD_REPORT_DIFF = "29_build_report_diff"  # CONDITIONAL
    GENERATE_REPORTS = "30_generate_reports"
    POST_GENERATION_VALIDATION = "31_post_generation_validation"  # BLOCKING GATE

    # Phase 7: Finalization (Steps 32-35)
    FINALIZE_METADATA = "32_finalize_metadata"
    UPDATE_RUN_HISTORY = "33_update_run_history"
    SAVE_ENTITY_CACHE = "34_save_entity_cache"
    SHUTDOWN = "35_shutdown"

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def step_number(self) -> int:
        """Return the numeric step index (1-35) parsed from the value prefix."""
        return int(self.value.split("_")[0])

    @property
    def is_blocking_gate(self) -> bool:
        """True if this step is one of the five blocking validation gates."""
        return self in _BLOCKING_GATES

    @property
    def is_conditional(self) -> bool:
        """True if this step may be skipped based on runtime configuration."""
        return self in _CONDITIONAL_STEPS


# ---------------------------------------------------------------------------
# Blocking gates  (pipeline halts on failure)
# ---------------------------------------------------------------------------

_BLOCKING_GATES: frozenset[PipelineStep] = frozenset(
    {
        PipelineStep.BULK_EXTRACTION,  # Step 5
        PipelineStep.COVERAGE_GATE,  # Step 17
        PipelineStep.NUMERICAL_AUDIT,  # Step 27
        PipelineStep.FULL_QA_AUDIT,  # Step 28
        PipelineStep.POST_GENERATION_VALIDATION,  # Step 31
    }
)

# Note: Step 1 (VALIDATE_CONFIG) is also effectively blocking -- if config
# fails validation, the pipeline raises BlockingGateError and stops.  It is
# not listed here because it is a precondition, not a gate between phases.

# ---------------------------------------------------------------------------
# Conditional steps  (may be skipped at runtime)
# ---------------------------------------------------------------------------

_CONDITIONAL_STEPS: frozenset[PipelineStep] = frozenset(
    {
        PipelineStep.CONTRACT_DATE_RECONCILIATION,  # Only if source_of_truth.subject_database exists
        PipelineStep.INCREMENTAL_CLASSIFICATION,  # Only if execution_mode == "incremental"
        PipelineStep.INCREMENTAL_MERGE,  # Only if execution_mode == "incremental"
        PipelineStep.SPAWN_JUDGE,  # Only if judge.enabled
        PipelineStep.JUDGE_REVIEW,  # Only if judge.enabled
        PipelineStep.JUDGE_RESPAWN,  # Only if judge.enabled
        PipelineStep.JUDGE_ROUND2,  # Only if judge.enabled
        PipelineStep.BUILD_REPORT_DIFF,  # Only if prior run exists
    }
)
