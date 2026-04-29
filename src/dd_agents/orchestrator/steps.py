"""PipelineStep enum enumerating all 38 pipeline steps.

Each step has a canonical string value used in checkpoints, logs, and error
messages.  Properties expose the step number, whether the step is a blocking
gate, and whether it is conditional on runtime configuration.
"""

from __future__ import annotations

from enum import StrEnum


class PipelineStep(StrEnum):
    """All 38 pipeline steps.  String values used in checkpoint filenames."""

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

    # Phase 4b: Cross-Domain Analysis (Steps 18-20)  — Issue #189
    CROSS_DOMAIN_ANALYSIS = "18_cross_domain_analysis"  # CONDITIONAL
    TARGETED_RESPAWN = "19_targeted_respawn"  # CONDITIONAL
    TARGETED_MERGE = "20_targeted_merge"  # CONDITIONAL

    # Phase 5: Quality Review (Steps 21-25)
    INCREMENTAL_MERGE = "21_incremental_merge"  # CONDITIONAL
    SPAWN_JUDGE = "22_spawn_judge"  # CONDITIONAL
    JUDGE_REVIEW = "23_judge_review"  # CONDITIONAL
    JUDGE_RESPAWN = "24_judge_respawn"  # CONDITIONAL
    JUDGE_ROUND2 = "25_judge_round2"  # CONDITIONAL

    # Phase 6: Reporting (Steps 26-34)
    PRE_MERGE_VALIDATION = "26_pre_merge_validation"
    MERGE_DEDUP = "27_merge_dedup"
    MERGE_GAPS = "28_merge_gaps"
    BUILD_NUMERICAL_MANIFEST = "29_build_numerical_manifest"
    NUMERICAL_AUDIT = "30_numerical_audit"  # BLOCKING GATE
    FULL_QA_AUDIT = "31_full_qa_audit"  # BLOCKING GATE
    BUILD_REPORT_DIFF = "32_build_report_diff"  # CONDITIONAL
    GENERATE_REPORTS = "33_generate_reports"
    POST_GENERATION_VALIDATION = "34_post_generation_validation"  # BLOCKING GATE

    # Phase 7: Finalization (Steps 35-38)
    FINALIZE_METADATA = "35_finalize_metadata"
    UPDATE_RUN_HISTORY = "36_update_run_history"
    SAVE_ENTITY_CACHE = "37_save_entity_cache"
    SHUTDOWN = "38_shutdown"

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def step_number(self) -> int:
        """Return the numeric step index (1-38) parsed from the value prefix."""
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
        PipelineStep.NUMERICAL_AUDIT,  # Step 30
        PipelineStep.FULL_QA_AUDIT,  # Step 31
        PipelineStep.POST_GENERATION_VALIDATION,  # Step 34
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
        PipelineStep.CROSS_DOMAIN_ANALYSIS,  # Only if cross_domain.enabled
        PipelineStep.TARGETED_RESPAWN,  # Only if cross_domain triggers fired
        PipelineStep.TARGETED_MERGE,  # Only if cross_domain triggers fired
        PipelineStep.INCREMENTAL_MERGE,  # Only if execution_mode == "incremental"
        PipelineStep.SPAWN_JUDGE,  # Only if judge.enabled
        PipelineStep.JUDGE_REVIEW,  # Only if judge.enabled
        PipelineStep.JUDGE_RESPAWN,  # Only if judge.enabled
        PipelineStep.JUDGE_ROUND2,  # Only if judge.enabled
        PipelineStep.BUILD_REPORT_DIFF,  # Only if prior run exists
    }
)
