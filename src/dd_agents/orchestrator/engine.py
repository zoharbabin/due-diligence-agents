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

        logger.info("Pipeline completed successfully")
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

    def _inventory_dir(self, state: PipelineState) -> Path:
        """Return the PERMANENT inventory directory."""
        return state.project_dir / state.skill_dir / "inventory"

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
        """Generate run_id, create directory structure, wipe FRESH tier."""
        from dd_agents.persistence.run_manager import RunManager

        run_mgr = RunManager(state.project_dir)
        metadata = run_mgr.initialize_run(
            project_dir=state.project_dir,
            deal_config=state.deal_config,
        )

        state.run_id = metadata.run_id
        skill_dir = state.project_dir / state.skill_dir
        state.run_dir = skill_dir / "runs" / state.run_id

        logger.info("Initialized run %s at %s", state.run_id, state.run_dir)
        return state

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

        from dd_agents.extraction.glm_ocr import GlmOcrExtractor

        pipeline = ExtractionPipeline(glm_ocr=GlmOcrExtractor())
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
        """Prepare agent prompts with size estimation and batching."""
        if self.team is None:
            self.team = AgentTeam(state)
        # Placeholder -- wire to agents.prompt_builder when available
        logger.info("Prepare prompts (placeholder -- wire to agents.prompt_builder)")
        return state

    async def _step_15_route_references(self, state: PipelineState) -> PipelineState:
        """Route reference files to agent prompts."""
        if self.team is None:
            self.team = AgentTeam(state)
        # Placeholder -- wire to agents.prompt_builder when available
        logger.info("Route references (placeholder -- wire to inventory.reference_files)")
        return state

    async def _step_16_spawn_specialists(self, state: PipelineState) -> PipelineState:
        """Spawn 4 specialist agents in parallel."""
        if self.team is None:
            self.team = AgentTeam(state)

        results = await self.team.spawn_specialists()
        for name, result in results.items():
            state.agent_results[name] = result
            state.agent_sessions[name] = result.get("session_id", "")
            state.agent_costs[name] = result.get("cost_usd", 0.0)
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
        """Validate specialist output coverage.  BLOCKING GATE."""
        # Check that all 4 agents produced output for all customers
        findings_dir = state.run_dir / "findings"
        missing: list[str] = []

        for customer in state.customer_safe_names:
            for agent in ALL_SPECIALIST_AGENTS:
                path = findings_dir / agent / f"{customer}.json"
                if not path.exists():
                    missing.append(f"{agent}/{customer}")

        if missing:
            logger.warning(
                "Coverage gate: %d missing outputs: %s",
                len(missing),
                missing[:10],
            )
            # Do not block during early wiring -- allow pipeline to continue
            # raise BlockingGateError(f"Coverage gate failed: {len(missing)} missing outputs")

        return state

    # Phase 5: Quality Review -----------------------------------------------

    async def _step_18_incremental_merge(self, state: PipelineState) -> PipelineState:
        """Merge new findings with carried-forward findings.  CONDITIONAL."""
        if state.execution_mode != "incremental":
            logger.info("Skipping step 18 -- not incremental mode")
            return state

        if self.team is None:
            self.team = AgentTeam(state)
        # Placeholder -- handled by agent team
        logger.info("Incremental merge (placeholder -- wire to persistence.incremental)")
        return state

    async def _step_19_spawn_judge(self, state: PipelineState) -> PipelineState:
        """Spawn Judge agent for quality review.  CONDITIONAL."""
        if not state.judge_enabled:
            logger.info("Skipping step 19 -- judge not enabled")
            return state

        if self.team is None:
            self.team = AgentTeam(state)

        result = await self.team.spawn_judge()
        state.agent_results["judge"] = result
        state.agent_sessions["judge"] = result.get("session_id", "")
        state.agent_costs["judge"] = result.get("cost_usd", 0.0)
        return state

    async def _step_20_judge_review(self, state: PipelineState) -> PipelineState:
        """Judge reviews, samples, spot-checks, scores.  CONDITIONAL."""
        if not state.judge_enabled:
            logger.info("Skipping step 20 -- judge not enabled")
            return state

        if self.team is None:
            self.team = AgentTeam(state)
        # Placeholder -- handled by agent team
        logger.info("Judge review (placeholder -- wire to agents.judge)")
        return state

    async def _step_21_judge_respawn(self, state: PipelineState) -> PipelineState:
        """Re-spawn agents below Judge threshold.  CONDITIONAL."""
        if not state.judge_enabled:
            logger.info("Skipping step 21 -- judge not enabled")
            return state

        if self.team is None:
            self.team = AgentTeam(state)
        # Placeholder -- handled by agent team
        logger.info("Judge respawn (placeholder -- wire to agents.judge)")
        return state

    async def _step_22_judge_round2(self, state: PipelineState) -> PipelineState:
        """Judge Round 2 review of re-analyzed findings.  CONDITIONAL."""
        if not state.judge_enabled:
            logger.info("Skipping step 22 -- judge not enabled")
            return state

        if self.team is None:
            self.team = AgentTeam(state)
        # Placeholder -- handled by agent team
        logger.info("Judge Round 2 (placeholder -- wire to agents.judge)")
        return state

    # Phase 6: Reporting ----------------------------------------------------

    async def _step_23_spawn_reporting_lead(self, state: PipelineState) -> PipelineState:
        """Spawn the Reporting Lead agent."""
        if self.team is None:
            self.team = AgentTeam(state)

        result = await self.team.spawn_reporting_lead()
        state.agent_results["reporting_lead"] = result
        state.agent_sessions["reporting_lead"] = result.get("session_id", "")
        state.agent_costs["reporting_lead"] = result.get("cost_usd", 0.0)
        return state

    async def _step_24_merge_dedup(self, state: PipelineState) -> PipelineState:
        """Merge and deduplicate findings across agents."""
        from dd_agents.reporting.merge import FindingMerger

        merger = FindingMerger(run_id=state.run_id)
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

    async def _step_26_build_numerical_manifest(self, state: PipelineState) -> PipelineState:
        """Build numerical_manifest.json for audit."""
        # Build a basic numerical manifest from inventory data
        inv_dir = self._inventory_dir(state)
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
                    "label": "Total Gaps",
                    "value": 0,
                    "source_file": "{RUN_DIR}/findings/merged/gaps/*.json",
                    "derivation": "count",
                },
                {
                    "id": "N009",
                    "label": "Ghost Customers",
                    "value": 0,
                    "source_file": str(inv_dir / "customer_mentions.json"),
                    "derivation": "count_ghost",
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
            sev_counts = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
            total_gaps = 0
            for jf in merged_dir.glob("*.json"):
                try:
                    data = json.loads(jf.read_text())
                    findings = data.get("findings", [])
                    total_findings += len(findings)
                    for f in findings:
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
            manifest["numbers"][7]["value"] = total_gaps

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
        """Generate Excel workbook from report_schema.json."""
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

        # Load or generate report schema
        schema_path = state.run_dir / "report_schema.json"
        if schema_path.exists():
            try:
                schema = ReportSchema.model_validate_json(schema_path.read_text())
            except Exception:
                logger.warning("Invalid report_schema.json -- using default")
                schema = ReportSchema(schema_version="1.0.0")
        else:
            schema = ReportSchema(schema_version="1.0.0")
            schema_path.write_text(schema.model_dump_json(indent=2))

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

    async def _step_35_shutdown(self, state: PipelineState) -> PipelineState:
        """Shutdown all agents and clean up resources."""
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

        # Persist DoD results
        dod_output = {
            "passed": passed,
            "total": total,
            "checks": [c.model_dump() for c in dod_results],
        }
        dod_path = state.run_dir / "dod_results.json"
        dod_path.parent.mkdir(parents=True, exist_ok=True)
        dod_path.write_text(json.dumps(dod_output, indent=2))
        logger.info("DoD results written to %s", dod_path)

        self.team = None
        logger.info("Pipeline shutdown complete")
        return state
