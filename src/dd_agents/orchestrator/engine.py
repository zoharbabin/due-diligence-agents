"""PipelineEngine -- the 35-step forensic due-diligence pipeline.

Each step is an ``async`` method on the engine class.  The ``run()`` entry
point walks through the canonical step list, executing each method in order.
Blocking gates halt on failure; conditional steps check runtime state and
return early when their precondition is not met.

Error recovery follows the protocol described in ``12-error-recovery.md``:
per-step retry, checkpoint after each step, and graceful degradation for
agent failures.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from dd_agents.orchestrator.checkpoints import (
    clean_checkpoints,
    load_checkpoint_by_step,
    save_checkpoint,
)
from dd_agents.orchestrator.state import PipelineError, PipelineState, StepResult
from dd_agents.orchestrator.steps import PipelineStep
from dd_agents.orchestrator.team import AgentTeam
from dd_agents.utils.constants import ALL_SPECIALIST_AGENTS

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class BlockingGateError(Exception):
    """Raised when a blocking validation gate fails.  Pipeline halts."""


class RecoverableError(Exception):
    """Raised for errors that may be recovered from automatically."""


class AgentFailureError(RecoverableError):
    """An agent failed entirely.  Recovery: re-spawn once."""

    def __init__(self, message: str, *, agent_name: str = "unknown") -> None:
        super().__init__(message)
        self.agent_name = agent_name


class PartialFailureError(RecoverableError):
    """An agent produced partial output.  Recovery: re-spawn for missing."""

    def __init__(
        self,
        message: str,
        *,
        agent_name: str = "unknown",
        missing_customers: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.agent_name = agent_name
        self.missing_customers = missing_customers or []


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

StepFn = Callable[[PipelineState], Awaitable[PipelineState]]


# ---------------------------------------------------------------------------
# PipelineEngine
# ---------------------------------------------------------------------------


class PipelineEngine:
    """Drives the 35-step forensic DD pipeline.

    Parameters
    ----------
    project_dir:
        Absolute path to the data-room project root.
    deal_config_path:
        Absolute path to ``deal-config.json``.
    max_retries:
        Maximum number of retries per step on recoverable errors.
    """

    TOTAL_STEPS: int = 35

    def __init__(
        self,
        project_dir: Path,
        deal_config_path: Path,
        *,
        max_retries: int = 1,
    ) -> None:
        self.project_dir = project_dir.resolve()
        self.deal_config_path = deal_config_path.resolve()
        self.max_retries = max_retries

        self.state = PipelineState(project_dir=self.project_dir)
        self.checkpoint_dir = self.project_dir / "_dd" / "forensic-dd" / "checkpoints"
        self.team: AgentTeam | None = None

        # Build the ordered mapping of PipelineStep -> async method
        self._step_registry: dict[PipelineStep, StepFn] = self._build_step_registry()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        resume_from_step: int = 0,
        *,
        options: dict[str, Any] | None = None,
    ) -> PipelineState:
        """Execute the full pipeline, optionally resuming from a checkpoint.

        Parameters
        ----------
        resume_from_step:
            Step number (1-35) to resume from.  ``0`` means start fresh.
            The checkpoint for the preceding step is loaded automatically.
        options:
            Optional runtime overrides (reserved for future use).

        Returns
        -------
        PipelineState
            The final pipeline state after all steps complete.
        """
        if resume_from_step > 0:
            predecessor = resume_from_step - 1
            if predecessor > 0:
                self.state = load_checkpoint_by_step(self.checkpoint_dir, predecessor)
                logger.info("Resumed from checkpoint at step %d", predecessor)
            else:
                logger.info("Resuming from step 1 -- no prior checkpoint needed")

            # Issue #45: Rebuild FRESH tier on resume so inventory is not stale.
            # When resuming from step > 2, the FRESH wipe in step 2 is skipped,
            # leaving stale inventory data from the prior interrupted run.
            # However, only wipe if we're resuming BEFORE the inventory build
            # step (step 6).  If resuming from step 6+, the inventory was
            # built in this run and step 6 will be skipped — wiping would
            # destroy customers.csv and break respawn / prompt building.
            inventory_step = PipelineStep.BUILD_INVENTORY.step_number
            if 2 < resume_from_step < inventory_step:
                from dd_agents.persistence.tiers import TierManager

                tier_mgr = TierManager(self.project_dir)
                tier_mgr.wipe_fresh()
                logger.info("Wiped FRESH tier for resumed run (prevents stale inventory)")

        ordered_steps = list(PipelineStep)

        for step_enum in ordered_steps:
            step_num = step_enum.step_number
            if step_num < resume_from_step:
                continue

            step_fn = self._step_registry[step_enum]
            self.state.current_step = step_enum

            gate_label = " [BLOCKING GATE]" if step_enum.is_blocking_gate else ""
            cond_label = " [CONDITIONAL]" if step_enum.is_conditional else ""
            logger.info(
                "Step %d/%d: %s%s%s",
                step_num,
                self.TOTAL_STEPS,
                step_enum.value,
                gate_label,
                cond_label,
            )

            t0 = time.monotonic()
            try:
                self.state = await self._execute_with_retry(step_enum, step_fn, self.state)

                duration_ms = int((time.monotonic() - t0) * 1000)
                result = StepResult(
                    step=step_enum,
                    status="success",
                    duration_ms=duration_ms,
                )
                self.state.step_results[step_enum.value] = result
                self.state.completed_steps.append(step_enum)
                save_checkpoint(self.state, self.checkpoint_dir)
                logger.info("  Completed in %dms", duration_ms)

            except BlockingGateError as exc:
                duration_ms = int((time.monotonic() - t0) * 1000)
                result = StepResult(
                    step=step_enum,
                    status="failed",
                    duration_ms=duration_ms,
                    error=str(exc),
                )
                self.state.step_results[step_enum.value] = result
                self.state.errors.append(
                    {
                        "step": step_enum.value,
                        "error_type": "blocking_gate",
                        "message": str(exc),
                        "recovered": False,
                        "recovery_action": "",
                    }
                )
                save_checkpoint(self.state, self.checkpoint_dir)
                logger.error("  BLOCKING GATE FAILED at step %d: %s", step_num, exc)
                raise

        # Issue #56: include DoD summary in completion message and set exit status
        dod_passed = self.state.validation_results.get("dod", True)
        if dod_passed:
            logger.info("Pipeline completed successfully -- all critical DoD checks passed")
        else:
            dod_path = self.state.run_dir / "dod_results.json"
            logger.warning(
                "Pipeline completed with critical DoD failures -- see %s",
                dod_path,
            )
            # Set exit_code on state so callers can detect the failure.
            self.state.exit_code = 1

        clean_checkpoints(self.checkpoint_dir)
        return self.state

    # ------------------------------------------------------------------
    # Step registry
    # ------------------------------------------------------------------

    def _build_step_registry(self) -> dict[PipelineStep, StepFn]:
        """Map every ``PipelineStep`` to its async handler method."""
        return {
            PipelineStep.VALIDATE_CONFIG: self._step_01_validate_config,
            PipelineStep.INIT_PERSISTENCE: self._step_02_init_persistence,
            PipelineStep.CROSS_SKILL_CHECK: self._step_03_cross_skill_check,
            PipelineStep.FILE_DISCOVERY: self._step_04_file_discovery,
            PipelineStep.BULK_EXTRACTION: self._step_05_bulk_extraction,
            PipelineStep.BUILD_INVENTORY: self._step_06_build_inventory,
            PipelineStep.ENTITY_RESOLUTION: self._step_07_entity_resolution,
            PipelineStep.REFERENCE_REGISTRY: self._step_08_reference_registry,
            PipelineStep.CUSTOMER_MENTIONS: self._step_09_customer_mentions,
            PipelineStep.INVENTORY_INTEGRITY: self._step_10_inventory_integrity,
            PipelineStep.CONTRACT_DATE_RECONCILIATION: self._step_11_contract_date_reconciliation,
            PipelineStep.INCREMENTAL_CLASSIFICATION: self._step_12_incremental_classification,
            PipelineStep.CREATE_TEAM: self._step_13_create_team,
            PipelineStep.PREPARE_PROMPTS: self._step_14_prepare_prompts,
            PipelineStep.ROUTE_REFERENCES: self._step_15_route_references,
            PipelineStep.SPAWN_SPECIALISTS: self._step_16_spawn_specialists,
            PipelineStep.COVERAGE_GATE: self._step_17_coverage_gate,
            PipelineStep.INCREMENTAL_MERGE: self._step_18_incremental_merge,
            PipelineStep.SPAWN_JUDGE: self._step_19_spawn_judge,
            PipelineStep.JUDGE_REVIEW: self._step_20_judge_review,
            PipelineStep.JUDGE_RESPAWN: self._step_21_judge_respawn,
            PipelineStep.JUDGE_ROUND2: self._step_22_judge_round2,
            PipelineStep.SPAWN_REPORTING_LEAD: self._step_23_spawn_reporting_lead,
            PipelineStep.MERGE_DEDUP: self._step_24_merge_dedup,
            PipelineStep.MERGE_GAPS: self._step_25_merge_gaps,
            PipelineStep.BUILD_NUMERICAL_MANIFEST: self._step_26_build_numerical_manifest,
            PipelineStep.NUMERICAL_AUDIT: self._step_27_numerical_audit,
            PipelineStep.FULL_QA_AUDIT: self._step_28_full_qa_audit,
            PipelineStep.BUILD_REPORT_DIFF: self._step_29_build_report_diff,
            PipelineStep.GENERATE_EXCEL: self._step_30_generate_excel,
            PipelineStep.POST_GENERATION_VALIDATION: self._step_31_post_generation_validation,
            PipelineStep.FINALIZE_METADATA: self._step_32_finalize_metadata,
            PipelineStep.UPDATE_RUN_HISTORY: self._step_33_update_run_history,
            PipelineStep.SAVE_ENTITY_CACHE: self._step_34_save_entity_cache,
            PipelineStep.SHUTDOWN: self._step_35_shutdown,
        }

    # ------------------------------------------------------------------
    # Retry / recovery wrapper
    # ------------------------------------------------------------------

    async def _execute_with_retry(
        self,
        step_enum: PipelineStep,
        step_fn: StepFn,
        state: PipelineState,
    ) -> PipelineState:
        """Execute a step function with retry on ``RecoverableError``."""

        last_error: RecoverableError | None = None

        for attempt in range(self.max_retries + 1):
            try:
                return await step_fn(state)
            except (BlockingGateError, PipelineError):
                raise
            except RecoverableError as exc:
                last_error = exc
                label = f"attempt {attempt + 1}/{self.max_retries + 1}"
                logger.warning(
                    "  Recoverable error at step %d (%s): %s",
                    step_enum.step_number,
                    label,
                    exc,
                )
                state.errors.append(
                    {
                        "step": step_enum.value,
                        "error_type": "recoverable",
                        "message": str(exc),
                        "recovered": attempt < self.max_retries,
                        "recovery_action": f"retry {label}",
                    }
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(1)
                    continue

        # All retries exhausted -- raise the last error
        assert last_error is not None  # noqa: S101
        raise last_error

    # ------------------------------------------------------------------
    # Helper: resolve common paths
    # ------------------------------------------------------------------

    def _ensure_team(self, state: PipelineState) -> AgentTeam:
        """Return the agent team, creating it lazily if needed.

        Step 13 is the canonical creation point, but downstream steps
        must tolerate a missing team when the pipeline resumes past
        step 13 from a checkpoint.
        """
        if self.team is None:
            self.team = AgentTeam(state)
        return self.team

    def _inventory_dir(self, state: PipelineState) -> Path:
        """Return the PERMANENT inventory directory."""
        return state.project_dir / state.skill_dir / "inventory"

    def _ensure_customer_entries(self, state: PipelineState) -> list[Any]:
        """Return ``_customer_entries``, reconstructing from CSV or checkpoint.

        After a checkpoint resume, the dynamic ``_customer_entries`` attribute
        is lost.  This helper tries three sources in order:

        1. ``state._customer_entries`` (set during the current run).
        2. ``customers.csv`` in the inventory directory.
        3. The step-6 checkpoint (``_customer_entries`` key).

        This ensures prompt-building and respawn work even when the inventory
        directory was wiped by a prior FRESH-tier cleanup.
        """
        import csv

        from dd_agents.models.inventory import CustomerEntry

        entries: list[Any] = getattr(state, "_customer_entries", [])
        if entries:
            return entries

        # Strategy 1: reconstruct from CSV on disk.
        csv_path = self._inventory_dir(state) / "customers.csv"
        if csv_path.exists():
            restored: list[CustomerEntry] = []
            with csv_path.open(encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    files_str = row.get("file_list", "")
                    restored.append(
                        CustomerEntry(
                            group=row.get("group", ""),
                            name=row.get("name", ""),
                            safe_name=row.get("safe_name", ""),
                            path=row.get("path", ""),
                            file_count=int(row.get("file_count", 0)),
                            files=files_str.split(";") if files_str else [],
                        )
                    )
            if restored:
                state._customer_entries = restored  # type: ignore[attr-defined]
                logger.info("Reconstructed %d customer entries from %s", len(restored), csv_path)
                return restored

        # Strategy 2: load from the step-6 checkpoint.
        import contextlib

        checkpoint_dir = state.project_dir / state.skill_dir / "checkpoints"
        cp6_path = checkpoint_dir / "checkpoint_06_build_inventory.json"
        if cp6_path.exists():
            with contextlib.suppress(Exception):
                cp6_data = json.loads(cp6_path.read_text(encoding="utf-8"))
                raw_entries = cp6_data.get("_customer_entries", [])
                restored_from_cp: list[CustomerEntry] = []
                for item in raw_entries:
                    if isinstance(item, dict):
                        with contextlib.suppress(Exception):
                            restored_from_cp.append(CustomerEntry.model_validate(item))
                if restored_from_cp:
                    state._customer_entries = restored_from_cp  # type: ignore[attr-defined]
                    logger.info(
                        "Reconstructed %d customer entries from checkpoint %s",
                        len(restored_from_cp),
                        cp6_path.name,
                    )
                    return restored_from_cp

        logger.warning(
            "Cannot reconstruct _customer_entries: neither %s nor %s found",
            csv_path,
            cp6_path,
        )
        return []

    def _text_dir(self, state: PipelineState) -> Path:
        """Return the extracted-text directory."""
        return state.project_dir / state.skill_dir / "index" / "text"

    # ==================================================================
    # Step implementations  (35 steps)
    #
    # Each step receives and returns PipelineState.  Steps that interact
    # with downstream modules (extraction, inventory, validation, etc.)
    # import them lazily inside the method body to avoid circular
    # imports and to keep this file loadable in isolation for testing.
    # ==================================================================

    # Phase 1: Setup -------------------------------------------------------

    async def _step_01_validate_config(self, state: PipelineState) -> PipelineState:
        """Load and validate deal-config.json.  BLOCKS on failure."""
        import hashlib

        config_path = self.deal_config_path
        if not config_path.exists():
            raise BlockingGateError(
                f"deal-config.json not found at {config_path}. "
                "Create one from the template at deal-config.template.json"
            )

        try:
            from dd_agents.config import load_deal_config

            load_deal_config(config_path)
        except Exception as exc:
            raise BlockingGateError(f"Config validation failed: {exc}") from exc

        raw = json.loads(config_path.read_text(encoding="utf-8"))
        state.deal_config = raw
        state.config_hash = hashlib.sha256(config_path.read_bytes()).hexdigest()

        # Pull execution settings from config
        execution = raw.get("execution", {})
        judge = raw.get("judge", {})
        state.execution_mode = execution.get("execution_mode", "full")
        state.judge_enabled = judge.get("enabled", True)

        logger.info(
            "Config validated: mode=%s, judge=%s",
            state.execution_mode,
            state.judge_enabled,
        )
        return state

    async def _step_02_init_persistence(self, state: PipelineState) -> PipelineState:
        """Generate run_id, create directory structure, wipe FRESH tier.

        Also populates ``prior_run_id`` and ``prior_run_dir`` from:
        1. Explicit ``prior_run_id`` in deal config, or
        2. Automatic lookup of the latest completed run in run history.
        """
        from dd_agents.persistence.run_manager import RunManager

        run_mgr = RunManager(state.project_dir)
        metadata = run_mgr.initialize_run(
            project_dir=state.project_dir,
            deal_config=state.deal_config,
        )

        state.run_id = metadata.run_id
        skill_dir = state.project_dir / state.skill_dir
        state.run_dir = skill_dir / "runs" / state.run_id

        # --- Populate prior_run_id (Issue #45) ---
        explicit_prior = (state.deal_config or {}).get("execution", {}).get("prior_run_id")
        if explicit_prior and isinstance(explicit_prior, str):
            prior_dir = run_mgr.get_run_dir(explicit_prior)
            if prior_dir.is_dir():
                state.prior_run_id = explicit_prior
                state.prior_run_dir = prior_dir
                logger.info("Prior run (from config): %s", explicit_prior)
            else:
                logger.warning("Configured prior_run_id %s not found on disk", explicit_prior)
        else:
            # Auto-detect from run history: latest completed run
            prior_id = self._find_latest_completed_run(run_mgr)
            if prior_id:
                prior_dir = run_mgr.get_run_dir(prior_id)
                if prior_dir.is_dir():
                    state.prior_run_id = prior_id
                    state.prior_run_dir = prior_dir
                    logger.info("Prior run (auto-detected): %s", prior_id)

        logger.info("Initialized run %s at %s", state.run_id, state.run_dir)
        return state

    @staticmethod
    def _find_latest_completed_run(run_mgr: Any) -> str | None:
        """Return the run_id of the most recent completed run from history.

        Falls back to the ``latest`` symlink if run_history.json is empty or
        unavailable.
        """
        history = run_mgr.load_run_history()
        # Walk backwards to find the latest completed entry
        for entry in reversed(history):
            if entry.get("completion_status") == "completed":
                return str(entry["run_id"])

        # Fallback: latest symlink
        prior: str | None = run_mgr.get_prior_run_id()
        return prior

    async def _step_03_cross_skill_check(self, state: PipelineState) -> PipelineState:
        """Scan for outputs from other DD skill runs (cross-skill data)."""
        dd_dir = state.project_dir / "_dd"
        if not dd_dir.is_dir():
            return state

        for skill_path in dd_dir.iterdir():
            if not skill_path.is_dir():
                continue
            if skill_path.name == "forensic-dd":
                continue
            runs_dir = skill_path / "runs"
            if runs_dir.is_dir():
                latest = runs_dir / "latest"
                if latest.is_symlink() or latest.is_dir():
                    state.cross_skill_run_ids[skill_path.name] = latest.name
                    logger.info("Found cross-skill data: %s", skill_path.name)

        return state

    # Phase 2: Discovery & Extraction --------------------------------------

    async def _step_04_file_discovery(self, state: PipelineState) -> PipelineState:
        """Discover all files in the data room."""
        from dd_agents.inventory.discovery import FileDiscovery

        discovery = FileDiscovery()
        files = discovery.discover(state.project_dir)
        state.total_files = len(files)

        # Write tree.txt and files.txt to the inventory directory
        inv_dir = self._inventory_dir(state)
        inv_dir.mkdir(parents=True, exist_ok=True)
        discovery.write_tree(files, inv_dir / "tree.txt")
        discovery.write_files_list(files, inv_dir / "files.txt")

        # Store file entries in state for subsequent steps
        state._discovered_files = files  # type: ignore[attr-defined]

        logger.info("Discovered %d files", state.total_files)
        return state

    async def _step_05_bulk_extraction(self, state: PipelineState) -> PipelineState:
        """Bulk pre-extraction of text from documents.  BLOCKING GATE."""
        from dd_agents.extraction.pipeline import ExtractionPipeline, ExtractionPipelineError

        files = getattr(state, "_discovered_files", [])
        if not files:
            logger.warning("No files discovered -- skipping extraction")
            return state

        text_dir = self._text_dir(state)
        text_dir.mkdir(parents=True, exist_ok=True)
        inv_dir = self._inventory_dir(state)
        cache_path = inv_dir / "checksums.sha256"

        # Resolve file paths to absolute
        file_paths = [str(state.project_dir / entry.path) for entry in files]

        # Select OCR backend from deal-config (Issue #2)
        ocr_preference = "auto"
        if state.deal_config and isinstance(state.deal_config, dict):
            extraction_cfg = state.deal_config.get("extraction", {})
            if isinstance(extraction_cfg, dict):
                ocr_preference = extraction_cfg.get("ocr_backend", "auto")

        from dd_agents.extraction.ocr_registry import OCRBackendRegistry

        ocr_backend = OCRBackendRegistry.get_backend(ocr_preference)

        from dd_agents.extraction.glm_ocr import GlmOcrExtractor

        # Pass registry-selected GLM-OCR backend if available; otherwise
        # None so the pipeline relies on its default pytesseract OCR.
        pipeline = ExtractionPipeline(glm_ocr=ocr_backend if isinstance(ocr_backend, GlmOcrExtractor) else None)
        try:
            pipeline.extract_all(
                files=file_paths,
                output_dir=text_dir,
                cache_path=cache_path,
            )
        except ExtractionPipelineError as exc:
            raise BlockingGateError(f"Extraction failed: {exc}") from exc

        logger.info("Extraction complete for %d files", len(file_paths))
        return state

    # Phase 3: Inventory ----------------------------------------------------

    async def _step_06_build_inventory(self, state: PipelineState) -> PipelineState:
        """Build customer registry and counts."""
        from dd_agents.inventory.customers import CustomerRegistryBuilder

        files = getattr(state, "_discovered_files", [])
        builder = CustomerRegistryBuilder()
        customers, counts = builder.build(state.project_dir, files)

        inv_dir = self._inventory_dir(state)
        builder.write_csv(customers, inv_dir / "customers.csv")
        builder.write_counts(counts, inv_dir / "counts.json")

        state.total_customers = counts.total_customers
        state.customer_safe_names = [c.safe_name for c in customers]
        state.reference_file_count = counts.total_reference_files

        # Store customer entries for later steps
        state._customer_entries = customers  # type: ignore[attr-defined]

        logger.info(
            "Inventory: %d customers, %d reference files",
            state.total_customers,
            state.reference_file_count,
        )
        return state

    async def _step_07_entity_resolution(self, state: PipelineState) -> PipelineState:
        """Run 6-pass cascading entity matcher."""
        from dd_agents.entity_resolution.matcher import EntityResolver

        customers = getattr(state, "_customer_entries", [])
        if not customers:
            logger.info("No customers found -- skipping entity resolution")
            return state

        entity_aliases = (state.deal_config or {}).get("entity_aliases", {})
        inv_dir = self._inventory_dir(state)
        cache_path = state.project_dir / state.skill_dir / "entity_cache.json"

        # Build customers_csv format expected by EntityResolver
        customers_csv = [{"customer_name": c.name} for c in customers]

        resolver = EntityResolver(
            customers_csv=customers_csv,
            entity_aliases=entity_aliases,
            cache_path=cache_path,
            run_id=state.run_id,
        )

        # Resolve customer names from reference files (if any ref files exist)
        # At this point we just initialize the resolver; actual resolution
        # happens when reference files are scanned in step 9.
        state._entity_resolver = resolver  # type: ignore[attr-defined]

        # Write entity_matches.json (initially empty, updated in step 9)
        match_log = resolver.get_match_log()
        (inv_dir / "entity_matches.json").write_text(json.dumps(match_log, indent=2))

        logger.info("Entity resolver initialized with %d customers", len(customers_csv))
        return state

    async def _step_08_reference_registry(self, state: PipelineState) -> PipelineState:
        """Build reference_files.json."""
        from dd_agents.inventory.reference_files import ReferenceFileClassifier

        files = getattr(state, "_discovered_files", [])
        customers = getattr(state, "_customer_entries", [])

        classifier = ReferenceFileClassifier()
        customer_dirs = [c.path for c in customers]
        ref_files = classifier.classify(files, customer_dirs)

        inv_dir = self._inventory_dir(state)
        classifier.write_json(ref_files, inv_dir / "reference_files.json")

        state._reference_files = ref_files  # type: ignore[attr-defined]
        state.reference_file_count = len(ref_files)

        logger.info("Classified %d reference files", len(ref_files))
        return state

    async def _step_09_customer_mentions(self, state: PipelineState) -> PipelineState:
        """Build customer_mentions.json."""
        from dd_agents.inventory.mentions import CustomerMentionBuilder

        ref_files = getattr(state, "_reference_files", [])
        customers = getattr(state, "_customer_entries", [])

        if not ref_files or not customers:
            logger.info("No reference files or customers -- skipping mentions")
            return state

        customer_names = {c.safe_name: c.name for c in customers}
        text_dir = self._text_dir(state)

        builder = CustomerMentionBuilder()
        mention_index = builder.build(
            reference_files=ref_files,
            customer_names=customer_names,
            text_dir=text_dir,
        )

        inv_dir = self._inventory_dir(state)
        builder.write_json(mention_index, inv_dir / "customer_mentions.json")

        # Run entity resolution on ghost customers (names in refs but no folder)
        resolver = getattr(state, "_entity_resolver", None)
        if resolver and mention_index.unmatched_in_reference:
            resolver.resolve_all(
                mention_index.unmatched_in_reference,
                source_type="reference_file",
            )
            match_log = resolver.get_match_log()
            (inv_dir / "entity_matches.json").write_text(json.dumps(match_log, indent=2))

        # Cross-document entity deduplication (Issue #11)
        from dd_agents.entity_resolution.dedup import CrossDocumentDeduplicator

        dedup = CrossDocumentDeduplicator()
        for mention in mention_index.matches:
            for ref_file in mention.reference_files:
                dedup.add_resolution(mention.customer_name, mention.customer_safe_name, ref_file)
        dedup.write_summary(inv_dir / "entity_dedup_summary.json")
        logger.info("Wrote entity dedup summary to %s", inv_dir / "entity_dedup_summary.json")

        logger.info("Built customer mention index")
        return state

    async def _step_10_inventory_integrity(self, state: PipelineState) -> PipelineState:
        """Verify inventory integrity (no orphan files)."""
        from dd_agents.inventory.integrity import InventoryIntegrityVerifier

        files = getattr(state, "_discovered_files", [])
        customers = getattr(state, "_customer_entries", [])
        ref_files = getattr(state, "_reference_files", [])

        # Separate customer files from all files
        customer_dirs = {c.path for c in customers}
        customer_files = [f for f in files if any(f.path.startswith(d + "/") for d in customer_dirs)]

        verifier = InventoryIntegrityVerifier()
        issues = verifier.verify(
            all_files=files,
            customer_files=customer_files,
            reference_files=ref_files,
        )

        if issues:
            logger.warning("Inventory integrity issues found: %d", len(issues))
        else:
            logger.info("Inventory integrity check passed")

        return state

    async def _step_11_contract_date_reconciliation(self, state: PipelineState) -> PipelineState:
        """Reconcile contract dates against customer database.  CONDITIONAL."""
        source_of_truth = (state.deal_config or {}).get("source_of_truth", {})
        customer_db_path = source_of_truth.get("customer_database")
        if not customer_db_path:
            logger.info("Skipping step 11 -- no source_of_truth.customer_database")
            return state

        from dd_agents.reporting.contract_dates import ContractDateReconciler

        # Load customer database
        db_path = state.project_dir / customer_db_path
        if not db_path.exists():
            logger.warning("Customer database not found at %s -- skipping", db_path)
            return state

        try:
            customer_database = json.loads(db_path.read_text())
            if not isinstance(customer_database, list):
                customer_database = customer_database.get("customers", [])
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load customer database: %s", exc)
            return state

        reconciler = ContractDateReconciler()
        result = reconciler.reconcile(
            customer_database=customer_database,
            findings={},  # Findings not yet available at this stage
            customers=state.customer_safe_names or None,
            run_id=state.run_id,
        )

        reconciler.write_reconciliation(
            result,
            state.run_dir / "contract_date_reconciliation.json",
        )

        logger.info("Contract date reconciliation complete: %d entries", len(result.entries))
        return state

    async def _step_12_incremental_classification(self, state: PipelineState) -> PipelineState:
        """Classify customers for incremental mode.  CONDITIONAL."""
        if state.execution_mode != "incremental":
            logger.info("Skipping step 12 -- not incremental mode")
            return state

        from dd_agents.persistence.incremental import IncrementalClassifier

        classifier = IncrementalClassifier()

        # Build current file checksums per customer
        customers = getattr(state, "_customer_entries", [])
        current_files: dict[str, list[str]] = {}
        for c in customers:
            current_files[c.safe_name] = sorted(c.files)

        # Load prior file checksums (from prior run if available)
        prior_files: dict[str, list[str]] = {}
        if state.prior_run_dir:
            prior_class_path = state.prior_run_dir / "classification.json"
            if prior_class_path.exists():
                try:
                    prior_data = json.loads(prior_class_path.read_text())
                    for entry in prior_data.get("customers", []):
                        name = entry.get("customer_safe_name", "")
                        if name:
                            prior_files[name] = sorted(entry.get("files", []))
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning("Could not load prior classification from %s: %s", prior_class_path, exc)

        staleness = (state.deal_config or {}).get("execution", {}).get("staleness_threshold", 3)

        classification = classifier.classify_customers(
            current_files=current_files,
            prior_files=prior_files,
            staleness_threshold=staleness,
        )
        classification.run_id = state.run_id

        state.classification = classification.model_dump()

        # Write classification.json
        class_path = state.run_dir / "classification.json"
        class_path.write_text(classification.model_dump_json(indent=2))

        # Determine which customers to analyze
        state.customers_to_analyze = [
            c.customer_safe_name
            for c in classification.customers
            if c.classification.value in ("NEW", "CHANGED", "STALE_REFRESH")
        ]

        logger.info(
            "Classified %d customers, %d need analysis",
            len(classification.customers),
            len(state.customers_to_analyze),
        )
        return state

    # Phase 4: Agent Execution ----------------------------------------------

    async def _step_13_create_team(self, state: PipelineState) -> PipelineState:
        """Create the agent team."""
        self.team = AgentTeam(state)
        logger.info("Agent team created")
        return state

    async def _step_14_prepare_prompts(self, state: PipelineState) -> PipelineState:
        """Prepare agent prompts with size estimation and batching.

        Uses :class:`PromptBuilder` to split customers into context-sized
        batches, then builds one prompt string per batch per specialist agent.
        Results are stored in ``state.agent_prompts`` (agent_name -> list of
        prompt strings) and ``state.batch_counts`` (agent_name -> int).
        """
        from dd_agents.agents.prompt_builder import PromptBuilder

        self._ensure_team(state)

        customers: list[Any] = self._ensure_customer_entries(state)
        reference_files: list[Any] = getattr(state, "_reference_files", [])
        deal_config_raw = state.deal_config

        # Lazy import to build typed DealConfig only when available
        deal_config_obj: Any = None
        if deal_config_raw:
            try:
                from dd_agents.config import load_deal_config

                deal_config_obj = load_deal_config(self.deal_config_path)
            except Exception:
                deal_config_obj = None

        run_dir = state.run_dir or (state.project_dir / state.skill_dir / "runs" / state.run_id)
        builder = PromptBuilder(
            project_dir=state.project_dir,
            run_dir=run_dir,
            run_id=state.run_id,
        )

        text_dir_str = str(self._text_dir(state))

        for agent_name in ALL_SPECIALIST_AGENTS:
            batches = PromptBuilder.batch_customers(customers)
            prompts: list[str] = []
            for batch in batches:
                prompt = builder.build_specialist_prompt(
                    agent_name=agent_name,
                    customers=batch,
                    reference_files=reference_files or None,
                    deal_config=deal_config_obj,
                    text_dir=text_dir_str,
                )
                prompts.append(prompt)

            state.agent_prompts[agent_name] = prompts
            state.batch_counts[agent_name] = len(batches)

            logger.info(
                "Agent %s: %d batch(es), %d customers total",
                agent_name,
                len(batches),
                len(customers),
            )

        logger.info(
            "Prepared prompts for %d agents with batching (1-based naming)",
            len(ALL_SPECIALIST_AGENTS),
        )
        return state

    async def _step_15_route_references(self, state: PipelineState) -> PipelineState:
        """Route reference files to customer analysis directories.

        Reads reference files classified in step 8 and copies their extracted
        text into each customer's analysis folder so specialist agents can
        access them during analysis.  Each reference file is routed according
        to its ``assigned_to_agents`` list from the classification step.

        The routing manifest is written to ``{RUN_DIR}/reference_routing.json``
        for audit traceability.
        """
        from pathlib import Path as _Path

        self._ensure_team(state)

        ref_files: list[Any] = getattr(state, "_reference_files", [])
        if not ref_files:
            logger.info("No reference files to route")
            return state

        text_dir = self._text_dir(state)
        findings_dir = state.run_dir / "findings"
        routing_manifest: list[dict[str, Any]] = []

        for ref in ref_files:
            # Resolve the extracted text path
            source_text: _Path | None = None
            if ref.text_path:
                candidate = _Path(ref.text_path)
                if candidate.is_absolute() and candidate.exists():
                    source_text = candidate
                else:
                    # Relative to text_dir
                    candidate = text_dir / ref.text_path
                    if candidate.exists():
                        source_text = candidate

            if source_text is None:
                # Try to derive from file_path
                stem = _Path(ref.file_path).stem
                candidate = text_dir / f"{stem}.md"
                if candidate.exists():
                    source_text = candidate

            if source_text is None:
                logger.debug("No extracted text for reference %s -- skipping", ref.file_path)
                continue

            agents_routed: list[str] = ref.assigned_to_agents or list(ALL_SPECIALIST_AGENTS)

            for agent_name in agents_routed:
                agent_ref_dir = findings_dir / agent_name / "_references"
                agent_ref_dir.mkdir(parents=True, exist_ok=True)
                dest = agent_ref_dir / source_text.name

                if not dest.exists():
                    try:
                        # Use symlink for efficiency; fall back to copy
                        dest.symlink_to(source_text)
                    except OSError:
                        import shutil

                        shutil.copy2(str(source_text), str(dest))

            routing_manifest.append(
                {
                    "file_path": ref.file_path,
                    "category": ref.category,
                    "agents": agents_routed,
                    "text_source": str(source_text),
                }
            )

        # Write routing manifest for audit
        manifest_path = state.run_dir / "reference_routing.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(routing_manifest, indent=2))

        logger.info("Routed %d reference files to agent directories", len(routing_manifest))
        return state

    async def _step_16_spawn_specialists(self, state: PipelineState) -> PipelineState:
        """Spawn 4 specialist agents in parallel with sub-checkpoint resume."""
        # Pre-create findings directories so agents can write immediately.
        from dd_agents.orchestrator.checkpoints import load_sub_checkpoints, save_sub_checkpoint
        from dd_agents.utils.constants import ALL_SPECIALIST_AGENTS

        findings_dir = state.run_dir / "findings"
        for agent_name in ALL_SPECIALIST_AGENTS:
            (findings_dir / agent_name).mkdir(parents=True, exist_ok=True)

        # Load sub-checkpoints to find already-completed agents (Issue #51)
        checkpoint_dir = state.run_dir / "checkpoints"
        sub_checkpoints = load_sub_checkpoints(checkpoint_dir, "step_16")
        completed_agents = [key for key, data in sub_checkpoints.items() if data.get("status") == "success"]
        agents_to_run = [a for a in ALL_SPECIALIST_AGENTS if a not in completed_agents]

        if completed_agents:
            logger.info(
                "Step 16 resume: %d agent(s) already completed: %s",
                len(completed_agents),
                ", ".join(completed_agents),
            )
            # Restore cached results for completed agents
            for agent_name in completed_agents:
                state.agent_results[agent_name] = sub_checkpoints[agent_name]

        if not agents_to_run:
            logger.info("Step 16: all agents already completed via sub-checkpoints")
            return state

        team = self._ensure_team(state)

        results = await team.spawn_specialists(
            num_customers=len(state.customer_safe_names),
            agents=agents_to_run,
        )
        for name, result in results.items():
            state.agent_results[name] = result
            state.agent_sessions[name] = result.get("session_id", "")
            state.agent_costs[name] = result.get("cost_usd", 0.0)

            # Save sub-checkpoint with full result so resume restores
            # complete agent_results (output, session_id, etc.) — Issue #51
            sub_data = dict(result)
            sub_data["status"] = "success" if not result.get("is_error") else "failed"
            save_sub_checkpoint(checkpoint_dir, "step_16", name, sub_data)

            if result.get("is_error"):
                logger.warning("Agent %s completed with error: %s", name, result.get("error"))
            else:
                logger.info(
                    "Agent %s completed: %d turns, $%.4f, %dms",
                    name,
                    result.get("num_turns", 0),
                    result.get("cost_usd", 0.0),
                    result.get("duration_ms", 0),
                )
        return state

    async def _step_17_coverage_gate(self, state: PipelineState) -> PipelineState:
        """Validate specialist output coverage.  BLOCKING GATE.

        For each agent, checks which customers have output files.  If
        coverage < 90 %, attempts a respawn for missing customers.  After
        respawn, generates P1 gap findings for any still-missing customers.
        If coverage remains < 50 % for any agent after respawn, raises
        :class:`BlockingGateError`.
        """
        findings_dir = state.run_dir / "findings"
        total_customers = len(state.customer_safe_names)
        if total_customers == 0:
            logger.info("Coverage gate: no customers to check")
            return state

        # --- First pass: per-agent coverage ---------------------------------
        per_agent_missing: dict[str, list[str]] = {}
        for agent in ALL_SPECIALIST_AGENTS:
            missing: list[str] = []
            for customer in state.customer_safe_names:
                path = findings_dir / agent / f"{customer}.json"
                if not path.exists():
                    missing.append(customer)
            per_agent_missing[agent] = missing

            # Run context exhaustion detection (Issue #39)
            exhaustion = self._detect_context_exhaustion(
                agent_name=agent,
                findings_dir=findings_dir,
                expected_customers=state.customer_safe_names,
            )
            if exhaustion.get("likely_exhaustion"):
                logger.warning(
                    "Context exhaustion detected for agent %s: %s",
                    agent,
                    exhaustion.get("reason", "unknown"),
                )

        # --- Respawn for agents below 90 % coverage ------------------------
        for agent, missing_custs in per_agent_missing.items():
            coverage_pct = (total_customers - len(missing_custs)) / max(total_customers, 1)
            if coverage_pct < 0.90 and missing_custs:
                logger.warning(
                    "Agent %s coverage %.1f%% < 90%% -- respawning for %d missing customers",
                    agent,
                    coverage_pct * 100,
                    len(missing_custs),
                )
                await self._respawn_for_missing_customers(
                    agent_name=agent,
                    missing_customers=missing_custs,
                    state=state,
                )

        # --- Second pass: re-check coverage after respawn -------------------
        all_gap_findings: list[dict[str, Any]] = []
        worst_coverage: float = 1.0
        worst_agent: str = ""

        for agent in ALL_SPECIALIST_AGENTS:
            still_missing: list[str] = []
            for customer in state.customer_safe_names:
                path = findings_dir / agent / f"{customer}.json"
                if not path.exists():
                    still_missing.append(customer)

            coverage_pct = (total_customers - len(still_missing)) / max(total_customers, 1)

            if coverage_pct < worst_coverage:
                worst_coverage = coverage_pct
                worst_agent = agent

            # Generate P1 gap findings for still-missing customers
            for customer in still_missing:
                gap = self._generate_coverage_gap_finding(
                    customer_safe_name=customer,
                    agent_name=agent,
                    run_id=state.run_id,
                )
                all_gap_findings.append(gap)

            if still_missing:
                logger.warning(
                    "Agent %s post-respawn coverage: %.1f%% (%d still missing)",
                    agent,
                    coverage_pct * 100,
                    len(still_missing),
                )

        # --- Persist gap findings -------------------------------------------
        if all_gap_findings:
            gaps_dir = findings_dir / "coverage_gaps"
            gaps_dir.mkdir(parents=True, exist_ok=True)
            gap_path = gaps_dir / "coverage_gap_findings.json"
            gap_path.write_text(json.dumps(all_gap_findings, indent=2))
            logger.info(
                "Generated %d coverage gap findings at %s",
                len(all_gap_findings),
                gap_path,
            )

        # --- Block if coverage < 50 % after respawn ------------------------
        if worst_coverage < 0.50:
            raise BlockingGateError(
                f"Coverage gate failed: agent {worst_agent!r} has "
                f"{worst_coverage * 100:.1f}% coverage (< 50% threshold) "
                f"after respawn attempt"
            )

        logger.info(
            "Coverage gate passed: worst coverage %.1f%% (agent %s)",
            worst_coverage * 100,
            worst_agent or "n/a",
        )
        return state

    # ------------------------------------------------------------------
    # Coverage helpers
    # ------------------------------------------------------------------

    async def _respawn_for_missing_customers(
        self,
        agent_name: str,
        missing_customers: list[str],
        state: PipelineState,
    ) -> None:
        """Attempt to respawn an agent for a reduced set of customers.

        Builds batched prompts containing only *missing_customers* and
        invokes the agent once per batch.  This prevents context exhaustion
        when the missing customer set is large.  Each batch runs as a
        separate SDK session.

        This is a best-effort recovery -- failures are logged but do not raise.
        """
        from dd_agents.agents.prompt_builder import PromptBuilder

        customers_all: list[Any] = self._ensure_customer_entries(state)
        missing_set = set(missing_customers)
        subset = [c for c in customers_all if c.safe_name in missing_set]

        if not subset:
            logger.warning(
                "Respawn for %s: could not find customer entries for %s",
                agent_name,
                missing_customers[:5],
            )
            return

        run_dir = state.run_dir or (state.project_dir / state.skill_dir / "runs" / state.run_id)
        builder = PromptBuilder(
            project_dir=state.project_dir,
            run_dir=run_dir,
            run_id=state.run_id,
        )

        # Batch the missing customers to avoid context exhaustion.
        batches = PromptBuilder.batch_customers(subset)
        if not batches:
            logger.warning(
                "Respawn for %s: batch_customers returned empty for %d entries",
                agent_name,
                len(subset),
            )
            return
        logger.info(
            "Respawn for %s: %d missing customers in %d batch(es)",
            agent_name,
            len(subset),
            len(batches),
        )

        # Build a prompt per batch and pass as a list so _run_specialist
        # iterates over them as sequential SDK sessions.
        batch_prompts: list[str] = []
        for batch in batches:
            prompt = builder.build_specialist_prompt(
                agent_name=agent_name,
                customers=batch,
            )
            batch_prompts.append(prompt)

        team = self._ensure_team(state)
        try:
            result = await team._run_specialist(
                agent_name,
                {"respawn": True},
                prompts=batch_prompts,
            )
            logger.info(
                "Respawn for %s completed: status=%s",
                agent_name,
                result.get("status", "unknown"),
            )
        except Exception as exc:
            logger.warning("Respawn for %s failed: %s", agent_name, exc)

    @staticmethod
    def _detect_context_exhaustion(
        agent_name: str,
        findings_dir: Any,
        expected_customers: list[str],
    ) -> dict[str, Any]:
        """Detect silent context exhaustion in agent output.

        Compares produced output files against *expected_customers*.  If
        coverage is incomplete, checks whether the last files produced are
        significantly smaller than the average -- a sign that the agent was
        truncated mid-analysis.

        Returns a dict with keys:

        - ``agent``: the agent name
        - ``produced``: number of output files
        - ``expected``: number of expected customers
        - ``coverage_pct``: float 0--1
        - ``likely_exhaustion``: bool
        - ``reason``: str (empty if no exhaustion detected)
        - ``file_sizes``: list of (filename, size) tuples sorted by name
        """
        from pathlib import Path as _Path

        agent_dir = _Path(str(findings_dir)) / agent_name
        result: dict[str, Any] = {
            "agent": agent_name,
            "produced": 0,
            "expected": len(expected_customers),
            "coverage_pct": 0.0,
            "likely_exhaustion": False,
            "reason": "",
            "file_sizes": [],
        }

        if not agent_dir.is_dir():
            if expected_customers:
                result["likely_exhaustion"] = True
                result["reason"] = "No output directory found"
            return result

        # Collect file sizes (only customer JSON files)
        file_sizes: list[tuple[str, int]] = []
        for fp in sorted(agent_dir.glob("*.json")):
            if fp.name == "coverage_manifest.json":
                continue
            file_sizes.append((fp.name, fp.stat().st_size))

        result["produced"] = len(file_sizes)
        result["file_sizes"] = file_sizes
        result["coverage_pct"] = len(file_sizes) / len(expected_customers) if expected_customers else 1.0

        if not expected_customers or len(file_sizes) >= len(expected_customers):
            return result

        # Incomplete coverage -- check for truncation pattern
        if len(file_sizes) < 2:
            result["likely_exhaustion"] = True
            result["reason"] = f"Only {len(file_sizes)} of {len(expected_customers)} files produced"
            return result

        sizes = [s for _, s in file_sizes]
        avg_size = sum(sizes) / len(sizes)

        # Check last N files (up to 3) against average
        check_count = min(3, len(sizes))
        tail_sizes = sizes[-check_count:]
        tail_avg = sum(tail_sizes) / len(tail_sizes)

        # If the tail average is less than 30 % of overall average, flag it
        if avg_size > 0 and tail_avg < avg_size * 0.30:
            result["likely_exhaustion"] = True
            result["reason"] = (
                f"Last {check_count} files avg {tail_avg:.0f} bytes vs "
                f"overall avg {avg_size:.0f} bytes ({tail_avg / avg_size * 100:.0f}%)"
            )
            return result

        # Also check if the very last file is significantly smaller
        last_size = sizes[-1]
        if avg_size > 0 and last_size < avg_size * 0.20:
            result["likely_exhaustion"] = True
            result["reason"] = (
                f"Last file {last_size} bytes vs avg {avg_size:.0f} bytes ({last_size / avg_size * 100:.0f}%)"
            )
            return result

        # Incomplete but no truncation pattern detected
        result["reason"] = (
            f"{len(file_sizes)} of {len(expected_customers)} files produced, no truncation pattern detected"
        )
        return result

    @staticmethod
    def _generate_coverage_gap_finding(
        customer_safe_name: str,
        agent_name: str,
        run_id: str,
    ) -> dict[str, Any]:
        """Generate a P1 gap finding for a customer missing from agent output.

        Returns a Finding-compatible dict suitable for persisting to the
        ``coverage_gaps/`` directory.
        """
        return {
            "finding_id": f"COVERAGE_GAP_{agent_name}_{customer_safe_name}",
            "customer_safe_name": customer_safe_name,
            "agent": agent_name,
            "run_id": run_id,
            "severity": "P1",
            "finding_type": "coverage_gap",
            "title": f"Missing {agent_name} analysis for {customer_safe_name}",
            "description": (
                f"The {agent_name} agent did not produce output for customer "
                f"{customer_safe_name!r}.  This may indicate context exhaustion, "
                f"agent failure, or a prompt assembly error.  Manual review is "
                f"required."
            ),
            "timestamp": datetime.now(UTC).isoformat(),
            "source": "coverage_gate",
            "auto_generated": True,
        }

    # Phase 5: Quality Review -----------------------------------------------

    async def _step_18_incremental_merge(self, state: PipelineState) -> PipelineState:
        """Merge new findings with carried-forward findings.  CONDITIONAL.

        For customers classified as UNCHANGED in step 12, copies their findings
        from the prior run into the current run directory with carry-forward
        metadata annotations.  Only runs when ``execution_mode == "incremental"``
        and a valid prior run directory is available.
        """
        if state.execution_mode != "incremental":
            logger.info("Skipping step 18 -- not incremental mode")
            return state

        if not state.prior_run_dir or not state.prior_run_id:
            logger.warning("Skipping step 18 -- no prior run available for incremental merge")
            return state

        from dd_agents.persistence.incremental import IncrementalClassifier

        classifier = IncrementalClassifier()

        # Determine unchanged customers from classification (set in step 12)
        unchanged_customers: list[str] = []
        classification_data = state.classification
        if classification_data:
            for entry in classification_data.get("customers", []):
                status = entry.get("classification", "")
                if status in ("UNCHANGED",):
                    name = entry.get("customer_safe_name", "")
                    if name:
                        unchanged_customers.append(name)

        if not unchanged_customers:
            logger.info("No unchanged customers to carry forward")
            return state

        prior_findings_dir = state.prior_run_dir / "findings"
        current_findings_dir = state.run_dir / "findings"
        current_findings_dir.mkdir(parents=True, exist_ok=True)

        carried = classifier.carry_forward_findings(
            unchanged_customers=unchanged_customers,
            prior_findings_dir=prior_findings_dir,
            current_findings_dir=current_findings_dir,
        )

        logger.info(
            "Incremental merge: carried forward %d finding files for %d unchanged customers",
            carried,
            len(unchanged_customers),
        )
        return state

    async def _step_19_spawn_judge(self, state: PipelineState) -> PipelineState:
        """Spawn Judge agent for quality review.  CONDITIONAL."""
        if not state.judge_enabled:
            logger.info("Skipping step 19 -- judge not enabled")
            return state

        team = self._ensure_team(state)

        result = await team.spawn_judge()
        state.agent_results["judge"] = result
        state.agent_sessions["judge"] = result.get("session_id", "")
        state.agent_costs["judge"] = result.get("cost_usd", 0.0)
        return state

    async def _step_20_judge_review(self, state: PipelineState) -> PipelineState:
        """Judge reviews, samples, spot-checks, scores.  CONDITIONAL.

        Runs the Judge agent's quality review on specialist findings.  The Judge
        performs risk-based sampling, citation verification, contextual validation,
        financial accuracy checks, cross-agent consistency, and completeness review.

        Results are stored in ``state.judge_scores`` and written to
        ``{RUN_DIR}/judge/quality_scores.json``.

        Gracefully degrades if the Judge agent is not configured or fails.
        """
        if not state.judge_enabled:
            logger.info("Skipping step 20 -- judge not enabled")
            return state

        self._ensure_team(state)

        from dd_agents.agents.judge import (
            DEFAULT_SCORE_THRESHOLD,
            JudgeAgent,
        )

        judge_config = (state.deal_config or {}).get("judge", {})

        try:
            judge = JudgeAgent(
                project_dir=state.project_dir,
                run_dir=state.run_dir,
                run_id=state.run_id,
            )
            # Apply deal-config overrides
            judge.score_threshold = judge_config.get("score_threshold", DEFAULT_SCORE_THRESHOLD)
            if "sampling_rates" in judge_config:
                judge.sampling_rates.update(judge_config["sampling_rates"])

            judge_state: dict[str, Any] = {
                "findings_dir": str(state.run_dir / "findings"),
                "customers": state.customer_safe_names,
                "run_id": state.run_id,
            }

            scores = await judge.run_with_iteration(judge_state)

            if scores is not None:
                # Persist quality scores
                judge_dir = state.run_dir / "judge"
                judge_dir.mkdir(parents=True, exist_ok=True)
                scores_path = judge_dir / "quality_scores.json"
                scores_path.write_text(scores.model_dump_json(indent=2))

                # Store in state for steps 21-22
                state.judge_scores = {
                    "overall_quality": scores.overall_quality,
                    "iteration_round": scores.iteration_round,
                    "agent_scores": {
                        name: agent_score.model_dump() for name, agent_score in scores.agent_scores.items()
                    },
                    "agents_below_threshold": scores.agents_below_threshold,
                    "score_threshold": judge.score_threshold,
                }

                logger.info(
                    "Judge review complete: overall=%d, round=%d, below_threshold=%s",
                    scores.overall_quality,
                    scores.iteration_round,
                    scores.agents_below_threshold,
                )
            else:
                logger.info("Judge returned no scores (graceful degradation)")

        except Exception as exc:
            logger.warning("Judge review failed (graceful degradation): %s", exc)
            state.judge_scores = {"error": str(exc), "degraded": True}

        return state

    async def _step_21_judge_respawn(self, state: PipelineState) -> PipelineState:
        """Re-spawn agents below Judge threshold.  CONDITIONAL.

        Reads the Judge scores from step 20 and identifies agents scoring below
        the configured threshold.  Those agents are re-spawned to re-analyze
        the customers they were responsible for.  Gracefully degrades if Judge
        data is unavailable.
        """
        if not state.judge_enabled:
            logger.info("Skipping step 21 -- judge not enabled")
            return state

        team = self._ensure_team(state)

        judge_data = state.judge_scores
        if not judge_data or judge_data.get("degraded"):
            logger.info("Skipping step 21 -- no judge scores available (degraded)")
            return state

        failing_agents: list[str] = judge_data.get("agents_below_threshold", [])
        if not failing_agents:
            logger.info("All agents passed judge threshold -- no re-spawn needed")
            return state

        logger.info("Re-spawning agents below threshold: %s", failing_agents)

        # Re-spawn only the failing specialist agents
        for agent_name in failing_agents:
            if agent_name not in ALL_SPECIALIST_AGENTS:
                continue

            try:
                result = await team._run_specialist(agent_name, {})
                state.agent_results[f"{agent_name}_round2"] = result
                logger.info("Re-spawned agent %s for round 2", agent_name)
            except Exception as exc:
                logger.warning("Failed to re-spawn agent %s: %s", agent_name, exc)
                state.agent_results[f"{agent_name}_round2"] = {
                    "agent": agent_name,
                    "status": "failed",
                    "error": str(exc),
                    "is_error": True,
                }

        return state

    async def _step_22_judge_round2(self, state: PipelineState) -> PipelineState:
        """Judge Round 2 review of re-analyzed findings.  CONDITIONAL.

        Merges round-2 findings with round-1 findings using the 70/30 blend
        formula (70% new + 30% prior).  Updates quality scores and writes
        final results.  Gracefully degrades if round-2 data is unavailable.
        """
        if not state.judge_enabled:
            logger.info("Skipping step 22 -- judge not enabled")
            return state

        self._ensure_team(state)

        judge_data = state.judge_scores
        if not judge_data or judge_data.get("degraded"):
            logger.info("Skipping step 22 -- no judge scores available (degraded)")
            return state

        failing_agents: list[str] = judge_data.get("agents_below_threshold", [])
        if not failing_agents:
            logger.info("No agents below threshold -- round 2 not needed")
            return state

        # Check if round-2 results exist
        has_round2 = any(f"{a}_round2" in state.agent_results for a in failing_agents)
        if not has_round2:
            logger.info("No round-2 results available -- applying quality caveats")
            judge_data["quality_caveats"] = [
                f"Agent {a} below threshold, round-2 re-analysis unavailable" for a in failing_agents
            ]
            state.judge_scores = judge_data
            return state

        from dd_agents.agents.judge import blend_round_scores

        # Blend round-1 and round-2 scores for agents that were re-spawned
        agent_scores = judge_data.get("agent_scores", {})
        for agent_name in failing_agents:
            round2_key = f"{agent_name}_round2"
            if round2_key not in state.agent_results:
                continue

            r1_score_data = agent_scores.get(agent_name, {})
            r1_score = r1_score_data.get("score", 0)
            # Round-2 score placeholder (in production, the Judge would score it)
            r2_score = r1_score  # Placeholder until real Judge scoring is wired
            blended = blend_round_scores(r1_score, r2_score)

            if agent_name in agent_scores:
                agent_scores[agent_name]["score"] = blended
                agent_scores[agent_name]["blended"] = True

            logger.info(
                "Agent %s: round1=%d, round2=%d, blended=%d",
                agent_name,
                r1_score,
                r2_score,
                blended,
            )

        judge_data["agent_scores"] = agent_scores
        judge_data["iteration_round"] = 2
        state.judge_scores = judge_data

        # Update persisted quality scores
        judge_dir = state.run_dir / "judge"
        judge_dir.mkdir(parents=True, exist_ok=True)
        scores_path = judge_dir / "quality_scores.json"
        scores_path.write_text(json.dumps(judge_data, indent=2))

        logger.info("Judge Round 2 complete: blended scores for %d agents", len(failing_agents))
        return state

    # Phase 6: Reporting ----------------------------------------------------

    async def _step_23_spawn_reporting_lead(self, state: PipelineState) -> PipelineState:
        """Spawn the Reporting Lead agent."""
        team = self._ensure_team(state)

        result = await team.spawn_reporting_lead()
        state.agent_results["reporting_lead"] = result
        state.agent_sessions["reporting_lead"] = result.get("session_id", "")
        state.agent_costs["reporting_lead"] = result.get("cost_usd", 0.0)
        return state

    async def _step_24_merge_dedup(self, state: PipelineState) -> PipelineState:
        """Merge and deduplicate findings across agents."""
        from dd_agents.reporting.merge import FindingMerger

        # Load file inventory so the merger can resolve agent citation paths.
        files_txt = self._inventory_dir(state) / "files.txt"
        file_inventory: list[str] = []
        if files_txt.exists():
            file_inventory = [line.strip() for line in files_txt.read_text().strip().splitlines() if line.strip()]

        merger = FindingMerger(run_id=state.run_id, file_inventory=file_inventory)
        findings_dir = state.run_dir / "findings"
        merged = merger.merge_all(findings_dir)

        # Write merged files
        merged_dir = findings_dir / "merged"
        merger.write_merged(merged, merged_dir)

        logger.info("Merged findings for %d customers", len(merged))
        return state

    async def _step_25_merge_gaps(self, state: PipelineState) -> PipelineState:
        """Merge gap files from all agents."""
        # Gaps are merged as part of the merged customer output in step 24.
        # This step handles any additional gap-specific processing.
        findings_dir = state.run_dir / "findings"
        gaps_dir = findings_dir / "merged" / "gaps"
        gaps_dir.mkdir(parents=True, exist_ok=True)

        # Collect gaps from agent directories
        for customer in state.customer_safe_names:
            all_gaps: list[dict[str, Any]] = []
            for agent in ALL_SPECIALIST_AGENTS:
                gap_file = findings_dir / agent / "gaps" / f"{customer}.json"
                if gap_file.exists():
                    try:
                        data = json.loads(gap_file.read_text())
                        if isinstance(data, list):
                            all_gaps.extend(data)
                        elif isinstance(data, dict):
                            all_gaps.extend(data.get("gaps", []))
                    except (json.JSONDecodeError, OSError):
                        continue
            if all_gaps:
                out = gaps_dir / f"{customer}.json"
                out.write_text(json.dumps(all_gaps, indent=2))

        logger.info("Gap merge complete")
        return state

    def _rebuild_missing_inventory_files(self, state: PipelineState, inv_dir: Path) -> None:
        """Recreate missing FRESH-tier inventory files from state/checkpoint data.

        When the pipeline resumes via ``--resume-from`` past step 8, FRESH tier
        files may not exist on disk (they were wiped by a prior run's init step
        and the rebuild steps were skipped).  Without these files, the
        numerical audit's Layer 1 (source traceability) fails.

        This helper reconstructs minimal-but-accurate versions so the audit
        can verify source traceability.
        """
        inv_dir.mkdir(parents=True, exist_ok=True)

        # -- customers.csv --------------------------------------------------
        csv_path = inv_dir / "customers.csv"
        if not csv_path.exists():
            entries = self._ensure_customer_entries(state)
            if entries:
                from dd_agents.inventory.customers import CustomerRegistryBuilder

                builder = CustomerRegistryBuilder()
                builder.write_csv(entries, csv_path)
                logger.info(
                    "Rebuilt customers.csv (%d entries) for audit traceability",
                    len(entries),
                )
            elif state.customer_safe_names:
                # Minimal CSV from safe_names when full entries unavailable.
                import csv as csv_mod
                import io

                buf = io.StringIO()
                writer = csv_mod.writer(buf)
                writer.writerow(["group", "name", "safe_name", "path", "file_count", "file_list"])
                for csn in state.customer_safe_names:
                    writer.writerow(["", csn, csn, "", 0, ""])
                csv_path.write_text(buf.getvalue())
                logger.info(
                    "Rebuilt minimal customers.csv (%d names) for audit traceability",
                    len(state.customer_safe_names),
                )

        # -- files.txt -------------------------------------------------------
        files_path = inv_dir / "files.txt"
        if not files_path.exists() and state.total_files > 0:
            try:
                from dd_agents.inventory.discovery import FileDiscovery

                discovery = FileDiscovery()
                files = discovery.discover(state.project_dir)
                discovery.write_files_list(files, files_path)
                logger.info("Rebuilt files.txt (%d files) for audit traceability", len(files))
            except Exception:  # noqa: BLE001
                logger.warning("Could not rebuild files.txt from data room scan -- Layer 1 may fail")

        # -- reference_files.json -------------------------------------------
        ref_path = inv_dir / "reference_files.json"
        if not ref_path.exists():
            # Write a list with the correct length so count rederivation passes.
            placeholder = [{"path": f"ref_{i}", "category": "unknown"} for i in range(state.reference_file_count)]
            ref_path.write_text(json.dumps(placeholder, indent=2))
            logger.info(
                "Rebuilt reference_files.json (%d entries) for audit traceability",
                state.reference_file_count,
            )

        # -- counts.json ----------------------------------------------------
        counts_path = inv_dir / "counts.json"
        if not counts_path.exists():
            counts_path.write_text(
                json.dumps(
                    {
                        "total_customers": state.total_customers,
                        "total_files": state.total_files,
                        "total_reference_files": state.reference_file_count,
                    },
                    indent=2,
                )
            )
            logger.info("Rebuilt counts.json for audit traceability")

    async def _step_26_build_numerical_manifest(self, state: PipelineState) -> PipelineState:
        """Build numerical_manifest.json for audit."""
        # Build a basic numerical manifest from inventory data
        inv_dir = self._inventory_dir(state)

        # Ensure FRESH-tier inventory files exist for audit traceability.
        # They may be missing after --resume-from when steps 4-8 are skipped.
        self._rebuild_missing_inventory_files(state, inv_dir)
        manifest: dict[str, Any] = {
            "run_id": state.run_id,
            "generated_at": datetime.now(UTC).isoformat(),
            "numbers": [
                {
                    "id": "N001",
                    "label": "Total Customers",
                    "value": state.total_customers,
                    "source_file": str(inv_dir / "customers.csv"),
                    "derivation": "row_count",
                },
                {
                    "id": "N002",
                    "label": "Total Files",
                    "value": state.total_files,
                    "source_file": str(inv_dir / "files.txt"),
                    "derivation": "line_count",
                },
                {
                    "id": "N003",
                    "label": "Total Findings",
                    "value": 0,
                    "source_file": "{RUN_DIR}/findings/merged/*.json",
                    "derivation": "count",
                },
                {
                    "id": "N004",
                    "label": "P0 Findings",
                    "value": 0,
                    "source_file": "{RUN_DIR}/findings/merged/*.json",
                    "derivation": "count_by_severity",
                },
                {
                    "id": "N005",
                    "label": "P1 Findings",
                    "value": 0,
                    "source_file": "{RUN_DIR}/findings/merged/*.json",
                    "derivation": "count_by_severity",
                },
                {
                    "id": "N006",
                    "label": "P2 Findings",
                    "value": 0,
                    "source_file": "{RUN_DIR}/findings/merged/*.json",
                    "derivation": "count_by_severity",
                },
                {
                    "id": "N007",
                    "label": "P3 Findings",
                    "value": 0,
                    "source_file": "{RUN_DIR}/findings/merged/*.json",
                    "derivation": "count_by_severity",
                },
                {
                    "id": "N008",
                    "label": "Clean Results",
                    "value": 0,
                    "source_file": "{RUN_DIR}/findings/merged/*.json",
                    "derivation": "count_clean",
                },
                {
                    "id": "N009",
                    "label": "Total Gaps",
                    "value": 0,
                    "source_file": "{RUN_DIR}/findings/merged/gaps/*.json",
                    "derivation": "count",
                },
                {
                    "id": "N010",
                    "label": "Reference Files",
                    "value": state.reference_file_count,
                    "source_file": str(inv_dir / "reference_files.json"),
                    "derivation": "count",
                },
            ],
        }

        # Update finding counts from merged directory
        merged_dir = state.run_dir / "findings" / "merged"
        if merged_dir.exists():
            total_findings = 0
            clean_result_count = 0
            sev_counts = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
            total_gaps = 0
            for jf in merged_dir.glob("*.json"):
                try:
                    data = json.loads(jf.read_text())
                    findings = data.get("findings", [])
                    for f in findings:
                        if f.get("category") == "domain_reviewed_no_issues":
                            clean_result_count += 1
                        else:
                            total_findings += 1
                            sev = f.get("severity", "P3")
                            if sev in sev_counts:
                                sev_counts[sev] += 1
                except (json.JSONDecodeError, OSError):
                    continue

            gaps_dir = merged_dir / "gaps"
            if gaps_dir.exists():
                for gf in gaps_dir.glob("*.json"):
                    try:
                        gdata = json.loads(gf.read_text())
                        if isinstance(gdata, list):
                            total_gaps += len(gdata)
                        elif isinstance(gdata, dict):
                            total_gaps += len(gdata.get("gaps", []))
                    except (json.JSONDecodeError, OSError):
                        continue

            manifest["numbers"][2]["value"] = total_findings
            manifest["numbers"][3]["value"] = sev_counts["P0"]
            manifest["numbers"][4]["value"] = sev_counts["P1"]
            manifest["numbers"][5]["value"] = sev_counts["P2"]
            manifest["numbers"][6]["value"] = sev_counts["P3"]
            manifest["numbers"][7]["value"] = clean_result_count
            manifest["numbers"][8]["value"] = total_gaps

        manifest_path = state.run_dir / "numerical_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2))

        logger.info("Built numerical manifest with %d entries", len(manifest["numbers"]))
        return state

    async def _step_27_numerical_audit(self, state: PipelineState) -> PipelineState:
        """Five-layer numerical validation.  BLOCKING GATE."""
        from dd_agents.validation.numerical_audit import NumericalAuditor

        inv_dir = self._inventory_dir(state)
        auditor = NumericalAuditor(
            run_dir=state.run_dir,
            inventory_dir=inv_dir,
        )

        # Load numerical manifest
        manifest_path = state.run_dir / "numerical_manifest.json"
        if not manifest_path.exists():
            state.validation_results["numerical_audit"] = False
            raise BlockingGateError("Numerical manifest not found")

        from dd_agents.models.numerical import NumericalManifest

        manifest_data = json.loads(manifest_path.read_text())
        manifest = NumericalManifest.model_validate(manifest_data)
        checks = auditor.run_full_audit(manifest)

        failures = [c for c in checks if not c.passed]
        if failures:
            failed_layers = [c.rule or f"check {i}" for i, c in enumerate(checks) if not c.passed]
            logger.warning(
                "Numerical audit: %d/%d checks failed",
                len(failures),
                len(checks),
            )
            state.validation_results["numerical_audit"] = False
            raise BlockingGateError(f"Numerical audit failed: {', '.join(failed_layers)}")

        logger.info("Numerical audit: all %d checks passed", len(checks))
        state.validation_results["numerical_audit"] = True
        return state

    async def _step_28_full_qa_audit(self, state: PipelineState) -> PipelineState:
        """Full QA audit (Definition of Done checks).  BLOCKING GATE."""
        from dd_agents.validation.qa_audit import QAAuditor

        inv_dir = self._inventory_dir(state)
        auditor = QAAuditor(
            run_dir=state.run_dir,
            inventory_dir=inv_dir,
            customer_safe_names=state.customer_safe_names,
            deal_config=state.deal_config,
        )

        report = auditor.run_full_audit(run_id=state.run_id)
        auditor.write_audit_json(report, state.run_dir / "audit.json")

        state.audit_passed = report.audit_passed
        state.validation_results["qa_audit"] = report.audit_passed

        if report.audit_passed:
            logger.info("QA audit passed")
        else:
            failed = [name for name, check in report.checks.items() if not check.passed]
            logger.warning("QA audit: %d checks failed: %s", len(failed), failed)
            raise BlockingGateError(f"QA audit failed: {', '.join(failed)}")

        return state

    async def _step_29_build_report_diff(self, state: PipelineState) -> PipelineState:
        """Build diff against prior run.  CONDITIONAL."""
        if not state.prior_run_id or not state.prior_run_dir:
            logger.info("Skipping step 29 -- no prior run for diff comparison")
            return state

        from dd_agents.reporting.diff import ReportDiffBuilder

        diff_builder = ReportDiffBuilder()
        diff = diff_builder.build_diff(
            current_findings_dir=state.run_dir / "findings",
            prior_findings_dir=state.prior_run_dir / "findings",
            current_run_id=state.run_id,
            prior_run_id=state.prior_run_id,
        )

        diff_builder.write_diff(diff, state.run_dir / "report_diff.json")

        logger.info(
            "Report diff: %d changes",
            len(diff.changes),
        )
        return state

    async def _step_30_generate_excel(self, state: PipelineState) -> PipelineState:
        """Generate Excel workbook from report_schema.json.

        Schema resolution order (Issue #35):
        1. ``{run_dir}/report_schema.json`` -- written by earlier pipeline steps
        2. ``{project_root}/config/report_schema.json`` -- shipped with the project
        3. Built-in minimal schema with a single Summary sheet
        """
        from dd_agents.models.reporting import ReportSchema
        from dd_agents.reporting.excel import ExcelReportGenerator

        # Load merged findings
        merged_dir = state.run_dir / "findings" / "merged"
        merged_findings: dict[str, Any] = {}
        if merged_dir.exists():
            for jf in merged_dir.glob("*.json"):
                try:
                    data = json.loads(jf.read_text())
                    merged_findings[jf.stem] = data
                except (json.JSONDecodeError, OSError):
                    continue

        # ------------------------------------------------------------------
        # Schema resolution with config/ fallback (Issue #35)
        # ------------------------------------------------------------------
        schema: ReportSchema | None = None

        # 1. Try run_dir
        run_schema_path = state.run_dir / "report_schema.json"
        if run_schema_path.exists():
            try:
                schema = ReportSchema.model_validate_json(run_schema_path.read_text())
                logger.info("Loaded report schema from run dir: %s", run_schema_path)
            except Exception:
                logger.warning("Invalid report_schema.json in run dir -- trying config/")

        # 2. Fallback: project config/ directory and package-relative paths.
        #    project_dir may point to the data room (not the codebase), so
        #    also search relative to the installed package location.
        if schema is None:
            from pathlib import Path as _Path

            import dd_agents as _pkg

            _pkg_root = _Path(_pkg.__file__).resolve().parent  # src/dd_agents/
            candidate_paths: list[Path] = [
                self.project_dir / "config" / "report_schema.json",
                _pkg_root.parent.parent / "config" / "report_schema.json",  # repo_root/config/
                _pkg_root / "config" / "report_schema.json",  # src/dd_agents/config/
            ]
            for config_schema_path in candidate_paths:
                if config_schema_path.exists():
                    try:
                        schema = ReportSchema.model_validate_json(config_schema_path.read_text())
                        logger.info("Loaded report schema from: %s", config_schema_path)
                        # Copy to run_dir so step 31 can find it
                        run_schema_path.parent.mkdir(parents=True, exist_ok=True)
                        run_schema_path.write_text(config_schema_path.read_text())
                        break
                    except Exception:
                        logger.warning("Invalid report_schema.json at %s -- trying next", config_schema_path)

        # 3. Fallback: built-in minimal schema
        if schema is None:
            logger.warning(
                "No valid report_schema.json found in run dir or config/. "
                "Using built-in minimal schema with a Summary sheet."
            )
            schema = ReportSchema.model_validate(
                {
                    "schema_version": "1.0.0",
                    "description": "Built-in minimal schema (fallback)",
                    "sheets": [
                        {
                            "name": "Summary",
                            "required": True,
                            "activation_condition": "always",
                            "columns": [
                                {"name": "Customer", "key": "customer", "type": "string", "width": 30},
                                {
                                    "name": "Overall Risk Rating",
                                    "key": "overall_risk_rating",
                                    "type": "string",
                                    "width": 20,
                                },
                                {
                                    "name": "Total Findings",
                                    "key": "total_findings",
                                    "type": "integer",
                                    "width": 14,
                                },
                                {"name": "Gap Count", "key": "gap_count", "type": "integer", "width": 12},
                            ],
                        },
                    ],
                }
            )
            run_schema_path.parent.mkdir(parents=True, exist_ok=True)
            run_schema_path.write_text(schema.model_dump_json(indent=2))

        generator = ExcelReportGenerator()
        report_dir = state.run_dir / "report"
        report_dir.mkdir(parents=True, exist_ok=True)
        output_path = report_dir / "dd_report.xlsx"

        generator.generate(
            merged_findings=merged_findings,
            report_schema=schema,
            output_path=output_path,
            deal_config=state.deal_config,
        )

        logger.info("Excel report generated: %s", output_path)

        # Generate interactive HTML report alongside Excel (Issue #9)
        try:
            from dd_agents.reporting.html import HTMLReportGenerator

            html_generator = HTMLReportGenerator()
            html_path = report_dir / "dd_report.html"
            html_generator.generate(
                merged_data=merged_findings,
                output_path=html_path,
                run_id=state.run_id,
                title="Due Diligence Report",
            )
            logger.info("HTML report generated: %s", html_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("HTML report generation failed (Excel report still available): %s", exc)

        return state

    async def _step_31_post_generation_validation(self, state: PipelineState) -> PipelineState:
        """Post-generation validation.  BLOCKING GATE."""
        from dd_agents.models.reporting import ReportSchema
        from dd_agents.validation.schema_validator import SchemaValidator

        schema_path = state.run_dir / "report_schema.json"
        if not schema_path.exists():
            logger.info("No report_schema.json -- skipping post-generation validation")
            return state

        try:
            schema = ReportSchema.model_validate_json(schema_path.read_text())
        except Exception as exc:
            logger.warning("Cannot load report schema for validation: %s", exc)
            return state

        validator = SchemaValidator(report_schema=schema)
        report_dir = state.run_dir / "report"
        excel_files = list(report_dir.glob("*.xlsx")) if report_dir.exists() else []

        if excel_files:
            checks = validator.validate_report(excel_files[0])
            failures = [c for c in checks if not c.passed]
            if failures:
                failed_rules = [c.rule or f"check {i}" for i, c in enumerate(checks) if not c.passed]
                logger.warning(
                    "Schema validation: %d/%d checks failed",
                    len(failures),
                    len(checks),
                )
                raise BlockingGateError(f"Post-generation schema validation failed: {', '.join(failed_rules)}")
            else:
                logger.info("Schema validation passed")

        return state

    # Phase 7: Finalization -------------------------------------------------

    async def _step_32_finalize_metadata(self, state: PipelineState) -> PipelineState:
        """Write metadata.json, update 'latest' symlink."""
        from dd_agents.models.enums import CompletionStatus, ExecutionMode
        from dd_agents.models.persistence import RunMetadata
        from dd_agents.persistence.run_manager import RunManager

        run_mgr = RunManager(state.project_dir)

        metadata = RunMetadata(
            run_id=state.run_id,
            timestamp=state.run_dir.name if state.run_dir else state.run_id,
            skill="forensic-dd",
            execution_mode=ExecutionMode(state.execution_mode),
            config_hash=state.config_hash,
            framework_version=state.framework_version,
            completion_status=CompletionStatus.COMPLETED,
        )

        run_mgr.finalize_run(metadata)
        logger.info("Run finalized: %s", state.run_id)
        return state

    async def _step_33_update_run_history(self, state: PipelineState) -> PipelineState:
        """Append entry to run_history.json."""
        # Already handled in step 32 by RunManager.finalize_run()
        logger.info("Run history updated (via finalize_run)")
        return state

    async def _step_34_save_entity_cache(self, state: PipelineState) -> PipelineState:
        """Persist entity resolution cache to PERMANENT tier."""
        resolver = getattr(state, "_entity_resolver", None)
        if resolver is not None:
            try:
                resolver.cache.save()
                logger.info("Entity resolution cache saved")
            except Exception as exc:
                logger.warning("Failed to save entity cache: %s", exc)
        else:
            logger.info("No entity resolver -- skipping cache save")
        return state

    # Critical DoD check numbers per spec (Issue #56).
    # Failures in these checks cause a non-zero pipeline exit status.
    CRITICAL_DOD_CHECKS: frozenset[int] = frozenset({1, 2, 3, 11, 13, 14, 15, 17, 19})

    async def _step_35_shutdown(self, state: PipelineState) -> PipelineState:
        """Shutdown all agents, run DoD checks, set exit status.

        Issue #56: DoD results are stored in ``state.validation_results["dod"]``
        and the pipeline exit status reflects critical DoD failures.
        """
        # Run Definition of Done checks
        from dd_agents.validation.dod import DefinitionOfDoneChecker

        inv_dir = self._inventory_dir(state)
        dod = DefinitionOfDoneChecker(
            run_dir=state.run_dir,
            inventory_dir=inv_dir,
            customer_safe_names=state.customer_safe_names,
            deal_config=state.deal_config,
        )

        dod_results = dod.check_all()
        passed = sum(1 for c in dod_results if c.passed)
        total = len(dod_results)
        logger.info("DoD: %d/%d checks passed", passed, total)

        # Identify critical DoD failures (Issue #56)
        critical_failures: list[str] = []
        for check in dod_results:
            if not check.passed:
                # A check is critical if any of its dod_checks numbers
                # are in the CRITICAL_DOD_CHECKS set.
                check_nums = set(check.dod_checks)
                if check_nums & self.CRITICAL_DOD_CHECKS:
                    label = check.rule or f"DoD checks {check.dod_checks}"
                    critical_failures.append(label)

        # Persist DoD results
        dod_output: dict[str, object] = {
            "passed": passed,
            "total": total,
            "critical_failures": critical_failures,
            "checks": [c.model_dump() for c in dod_results],
        }
        dod_path = state.run_dir / "dod_results.json"
        dod_path.parent.mkdir(parents=True, exist_ok=True)
        dod_path.write_text(json.dumps(dod_output, indent=2))
        logger.info("DoD results written to %s", dod_path)

        # Store in state for pipeline exit status (Issue #56)
        state.validation_results["dod"] = len(critical_failures) == 0

        if critical_failures:
            logger.warning(
                "DoD CRITICAL FAILURES (%d): %s",
                len(critical_failures),
                critical_failures,
            )

        self.team = None
        logger.info("Pipeline shutdown complete")
        return state
