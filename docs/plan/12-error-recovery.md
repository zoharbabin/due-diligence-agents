# 12 — Error Recovery

> **Historical note**: This document references the ReportingLead agent which was removed in v0.4.0. Step 23 is now deterministic pre-merge validation (`validation/pre_merge.py`). See `06-agents.md` §11.

## Overview

The forensic DD pipeline runs 13 agents (9 specialists + 4 synthesis/validation) across 35 steps. Failures are inevitable: agents exhaust context, extraction tools hang, shared files corrupt, configs change between runs. This document defines all 15 error scenarios, their detection methods, automatic recovery actions, fallbacks, and Python implementation patterns.

Design principle: **fail forward**. A single agent failure should not abort the entire pipeline. The orchestrator degrades gracefully — continuing with partial results, logging P1 gaps for missing coverage, and notifying the user of degraded output.

Cross-reference: `05-orchestrator.md` (pipeline state machine), `13-multi-project.md` (shared resource concurrency), `04-data-models.md` (Pydantic models for error tracking), SKILL.md section 7.

---

## 1. Error Taxonomy

### 1.1 Base Exception Hierarchy

```python
# src/dd_agents/errors.py

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ErrorSeverity(str, Enum):
    """How severely the error impacts the pipeline."""
    FATAL = "fatal"          # Pipeline must stop (config invalid, systemic extraction failure)
    DEGRADED = "degraded"    # Pipeline continues with reduced quality (agent failed after retry)
    RECOVERED = "recovered"  # Automatic recovery succeeded (agent re-spawned successfully)
    WARNING = "warning"      # Noted but no action needed (stale lock cleaned up)


class ErrorCategory(str, Enum):
    """Classification for error tracking and metrics."""
    AGENT_FAILURE = "agent_failure"
    AGENT_PARTIAL = "agent_partial"
    AGENT_TIMEOUT = "agent_timeout"
    AGENT_CONTEXT = "agent_context"
    EXTRACTION = "extraction"
    ENTITY_RESOLUTION = "entity_resolution"
    CONFIG = "config"
    CONCURRENCY = "concurrency"
    VALIDATION = "validation"


@dataclass
class AgentError(Exception):
    """Raised when an agent fails or produces incomplete output."""
    agent: str                              # e.g., "legal", "judge", "reporting_lead"
    error_type: ErrorCategory
    details: str
    subjects_affected: list[str] = field(default_factory=list)
    retry_count: int = 0
    recoverable: bool = True

    def __str__(self):
        return f"AgentError({self.agent}, {self.error_type.value}): {self.details}"


@dataclass
class PipelineError(Exception):
    """Raised when the pipeline encounters a blocking error."""
    step: int
    error_type: ErrorCategory
    details: str
    fatal: bool = False

    def __str__(self):
        return f"PipelineError(step {self.step}, {self.error_type.value}): {self.details}"


@dataclass
class ErrorRecord:
    """Immutable record of an error for the run log."""
    timestamp: str                          # ISO-8601
    step: int
    category: ErrorCategory
    severity: ErrorSeverity
    agent: Optional[str]
    message: str
    recovery_action: str                    # What the system did
    outcome: str                            # "recovered", "degraded", "fatal"
    subjects_affected: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)
```

### 1.2 Error Registry in Pipeline State

```python
# Added to PipelineState (see 05-orchestrator.md)

@dataclass
class PipelineState:
    # ... existing fields ...

    # Error tracking
    errors: list[ErrorRecord] = field(default_factory=list)
    gap_findings_from_errors: list[dict] = field(default_factory=list)
    degraded_agents: list[str] = field(default_factory=list)
    quality_caveats: list[str] = field(default_factory=list)
```

---

## 2. Core Recovery Engine

### 2.1 spawn_with_retry

The fundamental building block. Every agent invocation goes through this function.

```python
# src/dd_agents/orchestrator/recovery.py

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from claude_agent_sdk import query, ClaudeAgentOptions, AgentDefinition

logger = logging.getLogger(__name__)


async def spawn_with_retry(
    agent_name: str,
    prompt: str,
    options: ClaudeAgentOptions,
    definition: Optional[AgentDefinition] = None,
    max_retries: int = 1,
    timeout_minutes: int = 30,
    status_check_interval_minutes: int = 5,
) -> dict:
    """Spawn an agent with automatic retry on failure.

    Returns the final agent result dict. Raises AgentError if all retries exhausted.

    Args:
        agent_name: Identifier for logging (e.g., "legal", "judge").
        prompt: Full prompt text for the agent.
        options: ClaudeAgentOptions (cwd, hooks, tools, budget, etc.).
        definition: Optional AgentDefinition for structured output.
        max_retries: Number of retry attempts after initial failure.
        timeout_minutes: Wall-clock timeout per attempt.
        status_check_interval_minutes: Interval to check for stalled agents.
    """
    last_error = None

    for attempt in range(max_retries + 1):
        attempt_label = f"attempt {attempt + 1}/{max_retries + 1}"
        logger.info(f"Spawning agent {agent_name} ({attempt_label})")

        try:
            result = await asyncio.wait_for(
                _run_agent(agent_name, prompt, options, definition),
                timeout=timeout_minutes * 60,
            )
            logger.info(f"Agent {agent_name} completed ({attempt_label})")
            return result

        except asyncio.TimeoutError:
            last_error = AgentError(
                agent=agent_name,
                error_type=ErrorCategory.AGENT_TIMEOUT,
                details=f"No output after {timeout_minutes} minutes",
                retry_count=attempt,
            )
            logger.warning(f"Agent {agent_name} timed out ({attempt_label})")

        except Exception as e:
            last_error = AgentError(
                agent=agent_name,
                error_type=ErrorCategory.AGENT_FAILURE,
                details=str(e),
                retry_count=attempt,
            )
            logger.warning(f"Agent {agent_name} failed ({attempt_label}): {e}")

        if attempt < max_retries:
            logger.info(f"Retrying agent {agent_name}...")
            await asyncio.sleep(2)  # Brief pause before retry
            continue

    # All retries exhausted
    raise last_error


async def _run_agent(
    agent_name: str,
    prompt: str,
    options: ClaudeAgentOptions,
    definition: Optional[AgentDefinition],
) -> dict:
    """Execute a single agent invocation, collecting all messages."""
    result = {}
    async for message in query(
        prompt=prompt,
        options=options,
        agent_definition=definition,
    ):
        # Collect final result
        if hasattr(message, "type"):
            result["last_message"] = message
    return result
```

### 2.2 ErrorRecoveryManager

Central coordinator for all error handling decisions.

```python
# src/dd_agents/orchestrator/recovery.py (continued)

from pathlib import Path


class ErrorRecoveryManager:
    """Manages error detection, recovery, and gap generation for the pipeline."""

    def __init__(self, state: "PipelineState", logger: logging.Logger):
        self.state = state
        self.logger = logger

    def record_error(
        self,
        step: int,
        category: ErrorCategory,
        severity: ErrorSeverity,
        message: str,
        recovery_action: str,
        outcome: str,
        agent: Optional[str] = None,
        subjects_affected: Optional[list[str]] = None,
        details: Optional[dict] = None,
    ) -> ErrorRecord:
        """Record an error and return the record."""
        record = ErrorRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            step=step,
            category=category,
            severity=severity,
            agent=agent,
            message=message,
            recovery_action=recovery_action,
            outcome=outcome,
            subjects_affected=subjects_affected or [],
            details=details or {},
        )
        self.state.errors.append(record)
        self.logger.log(
            logging.ERROR if severity == ErrorSeverity.FATAL else logging.WARNING,
            f"[{severity.value}] Step {step}: {message} -> {recovery_action} -> {outcome}",
        )
        return record

    def generate_gap_finding(
        self,
        agent: str,
        subject: str,
        gap_type: str,
        priority: str,
        description: str,
    ) -> dict:
        """Create a gap finding for missing coverage due to an error."""
        gap = {
            "id": f"forensic-dd_{agent}_gap_{self.state.subject_safe_name(subject)}_error",
            "skill": "forensic-dd",
            "agent": agent,
            "subject": subject,
            "category": agent.capitalize() if agent != "producttech" else "ProductTech",
            "severity": priority,
            "title": f"Agent {agent} failed - {gap_type}",
            "description": description,
            "gap_type": gap_type,
            "source": "error_recovery",
            "citation": {
                "source_path": "N/A - agent failure",
                "exact_quote": "",
            },
        }
        self.state.gap_findings_from_errors.append(gap)
        return gap

    def should_stop_pipeline(self) -> bool:
        """Check if accumulated errors warrant stopping the pipeline."""
        fatal_errors = [
            e for e in self.state.errors if e.severity == ErrorSeverity.FATAL
        ]
        return len(fatal_errors) > 0
```

---

## 3. The 15 Error Scenarios

### Scenario 1: Specialist Agent Fails (1 of 4)

**When**: A specialist agent (Legal, Finance, Commercial, or ProductTech) crashes, returns an error, or produces no output at all.

**Detection**: `spawn_with_retry` catches the exception. After all agents complete at step 17, the orchestrator checks that each agent's output directory exists and contains files.

**Recovery**:
1. Re-spawn the agent once with the identical prompt.
2. If the retry succeeds, proceed normally.
3. If the retry also fails, continue with 3 agents.
4. Generate a P1 gap finding for every subject: "Agent {name} failed -- {domain} coverage missing for all subjects."
5. Add the agent to `state.degraded_agents`.

**Fallback**: Remaining 3 agents' findings are still valid. The Excel report is generated with a quality caveat noting missing domain coverage.

**User notification**: Console warning + quality caveat in `metadata.json`.

```python
# src/dd_agents/orchestrator/agents.py

async def run_specialists(state: PipelineState, recovery: ErrorRecoveryManager):
    """Step 16: Spawn all 4 specialists in parallel."""
    agents = ["legal", "finance", "commercial", "producttech"]
    tasks = {}

    for agent_name in agents:
        prompt = state.agent_prompts[agent_name]
        options = build_specialist_options(state, agent_name)
        tasks[agent_name] = asyncio.create_task(
            spawn_with_retry(agent_name, prompt, options, max_retries=1)
        )

    results = {}
    for agent_name, task in tasks.items():
        try:
            results[agent_name] = await task
        except AgentError as e:
            recovery.record_error(
                step=16,
                category=ErrorCategory.AGENT_FAILURE,
                severity=ErrorSeverity.DEGRADED,
                message=f"Specialist {agent_name} failed after retry: {e.details}",
                recovery_action=f"Continuing with {len(agents) - 1 - len(state.degraded_agents)} agents",
                outcome="degraded",
                agent=agent_name,
                subjects_affected=state.subject_safe_names,
            )
            state.degraded_agents.append(agent_name)

            # Generate P1 gap for every subject
            for subject in state.all_subjects:
                recovery.generate_gap_finding(
                    agent=agent_name,
                    subject=subject,
                    gap_type="Agent_Failure",
                    priority="P1",
                    description=(
                        f"Agent {agent_name} failed -- {agent_name} domain coverage "
                        f"missing for {subject}."
                    ),
                )

    return results
```

---

### Scenario 2: Specialist Agent Partial Failure

**When**: An agent completes but produces output for fewer than 90% of assigned subjects.

**Detection**: Step 17 coverage gate. The orchestrator counts `{subject_safe_name}.json` files in `{RUN_DIR}/findings/{agent}/` and compares against the expected subject count from `subjects.csv`.

**Recovery**:
1. Identify which subjects are missing by comparing filenames against `state.subject_safe_names`.
2. Build a reduced prompt containing only the missing subjects (same rules, references, and instructions).
3. Re-spawn the agent for the missing subjects only.
4. If the re-spawn fills the gaps, merge outputs.
5. If still incomplete after one retry, log P1 gaps for each uncovered subject.

**Fallback**: Partial output is retained. Only uncovered subjects get gap findings.

**User notification**: Console warning listing missing subject count per agent.

```python
# src/dd_agents/orchestrator/coverage.py

async def validate_specialist_coverage(
    state: PipelineState,
    recovery: ErrorRecoveryManager,
) -> dict[str, list[str]]:
    """Step 17: Coverage gate. Returns dict of agent -> missing subjects."""
    missing_by_agent: dict[str, list[str]] = {}

    for agent_name in ["legal", "finance", "commercial", "producttech"]:
        if agent_name in state.degraded_agents:
            continue  # Already handled as full failure

        findings_dir = state.run_dir / "findings" / agent_name
        produced_files = {
            p.stem for p in findings_dir.glob("*.json")
            if p.stem != "coverage_manifest"
        }

        expected = set(state.subject_safe_names)
        missing = expected - produced_files

        # Also check for aggregate files (bad agent behavior)
        aggregate_patterns = {"_global", "batch_summary", "other_subjects", "all_subjects"}
        bad_files = produced_files & aggregate_patterns
        if bad_files:
            recovery.record_error(
                step=17,
                category=ErrorCategory.AGENT_PARTIAL,
                severity=ErrorSeverity.WARNING,
                message=f"Agent {agent_name} produced aggregate files: {bad_files}",
                recovery_action="Will re-spawn with explicit per-subject instruction",
                outcome="retrying",
                agent=agent_name,
            )
            # Remove aggregate files
            for bad_file in bad_files:
                (findings_dir / f"{bad_file}.json").unlink(missing_ok=True)

        if len(missing) > 0:
            coverage_pct = 1 - (len(missing) / len(expected))
            missing_by_agent[agent_name] = sorted(missing)

            if coverage_pct < 0.90:
                logger.warning(
                    f"Agent {agent_name} produced {len(produced_files)}/{len(expected)} "
                    f"subject files ({coverage_pct:.0%}) - below 90% threshold"
                )

    return missing_by_agent


async def respawn_for_missing_subjects(
    agent_name: str,
    missing_subjects: list[str],
    state: PipelineState,
    recovery: ErrorRecoveryManager,
):
    """Re-spawn a specialist for only the missing subjects."""
    prompt = build_partial_prompt(state, agent_name, missing_subjects)
    options = build_specialist_options(state, agent_name)

    try:
        await spawn_with_retry(
            f"{agent_name}-respawn",
            prompt,
            options,
            max_retries=0,  # One attempt only (this is already the retry)
        )

        # Verify re-spawn filled the gaps
        findings_dir = state.run_dir / "findings" / agent_name
        still_missing = [
            c for c in missing_subjects
            if not (findings_dir / f"{c}.json").exists()
        ]

        if still_missing:
            for subject_safe in still_missing:
                subject = state.safe_name_to_subject[subject_safe]
                recovery.generate_gap_finding(
                    agent=agent_name,
                    subject=subject,
                    gap_type="Partial_Failure",
                    priority="P1",
                    description=(
                        f"Agent {agent_name} did not produce output for {subject} "
                        f"-- {agent_name} coverage missing."
                    ),
                )
            recovery.record_error(
                step=17,
                category=ErrorCategory.AGENT_PARTIAL,
                severity=ErrorSeverity.DEGRADED,
                message=f"Re-spawn for {agent_name} still missing {len(still_missing)} subjects",
                recovery_action="Logged P1 gaps for uncovered subjects",
                outcome="degraded",
                agent=agent_name,
                subjects_affected=still_missing,
            )

    except AgentError:
        # Re-spawn itself failed - log gaps for all missing
        for subject_safe in missing_subjects:
            subject = state.safe_name_to_subject[subject_safe]
            recovery.generate_gap_finding(
                agent=agent_name,
                subject=subject,
                gap_type="Partial_Failure",
                priority="P1",
                description=(
                    f"Agent {agent_name} did not produce output for {subject} "
                    f"after re-spawn -- {agent_name} coverage missing."
                ),
            )
```

---

### Scenario 3: Judge Agent Fails

**When**: The Judge agent crashes or produces no quality_scores.json.

**Detection**: After Judge spawn at step 19-22, check for `{RUN_DIR}/judge/quality_scores.json`.

**Recovery**:
1. Re-spawn once with the same prompt.
2. If retry fails, set `judge_enabled: false` in `metadata.json`.
3. Add quality caveat to all findings: "Judge unavailable -- findings not quality-verified."

**Fallback**: Pipeline proceeds without quality review. Report includes a caveat in the Summary sheet.

**User notification**: Console warning. Caveat embedded in final report metadata.

```python
async def run_judge(state: PipelineState, recovery: ErrorRecoveryManager):
    """Steps 19-22: Spawn Judge agent with retry."""
    if not state.judge_enabled:
        return

    prompt = state.agent_prompts["judge"]
    options = build_judge_options(state)

    try:
        await spawn_with_retry("judge", prompt, options, max_retries=1)

        # Verify output
        scores_path = state.run_dir / "judge" / "quality_scores.json"
        if not scores_path.exists():
            raise AgentError(
                agent="judge",
                error_type=ErrorCategory.AGENT_FAILURE,
                details="Judge completed but quality_scores.json not found",
            )

    except AgentError as e:
        recovery.record_error(
            step=19,
            category=ErrorCategory.AGENT_FAILURE,
            severity=ErrorSeverity.DEGRADED,
            message=f"Judge failed: {e.details}",
            recovery_action="Proceeding without quality review",
            outcome="degraded",
            agent="judge",
        )
        state.judge_enabled = False
        state.quality_caveats.append(
            "Judge unavailable -- findings not quality-verified."
        )
```

---

### Scenario 4: Reporting Lead Fails

**When**: The Reporting Lead agent crashes or fails to produce the Excel report.

**Detection**: After Reporting Lead spawn at step 23, check for report output files.

**Recovery**:
1. Check `{RUN_DIR}/report/checkpoint.json` for partial progress. If present, the Reporting Lead may resume from the last completed phase rather than restarting.
2. Re-spawn once with all findings, schema path, and checkpoint data.
3. If retry fails, output raw merged findings JSONs.

**Fallback**: Raw JSON findings are available at `{RUN_DIR}/findings/merged/`. User can manually review or re-run reporting phase only.

**User notification**: Console error with path to raw findings.

```python
async def run_reporting_lead(state: PipelineState, recovery: ErrorRecoveryManager):
    """Steps 23-31: Spawn Reporting Lead with retry."""
    prompt = state.agent_prompts["reporting_lead"]
    options = build_reporting_lead_options(state)

    try:
        await spawn_with_retry("reporting_lead", prompt, options, max_retries=1)

        # Verify outputs
        report_glob = list((state.run_dir / "report").glob("Due_Diligence_Report_*.xlsx"))
        if not report_glob:
            raise AgentError(
                agent="reporting_lead",
                error_type=ErrorCategory.AGENT_FAILURE,
                details="Reporting Lead completed but no Excel report found",
            )

    except AgentError as e:
        recovery.record_error(
            step=23,
            category=ErrorCategory.AGENT_FAILURE,
            severity=ErrorSeverity.DEGRADED,
            message=f"Reporting Lead failed: {e.details}",
            recovery_action="Raw findings available at findings/merged/",
            outcome="degraded",
            agent="reporting_lead",
        )
        state.quality_caveats.append(
            f"Report generation failed -- raw findings available at "
            f"{state.run_dir / 'findings' / 'merged'}/"
        )
        logger.error(
            f"Reporting Lead failed. Raw findings at: "
            f"{state.run_dir / 'findings' / 'merged'}/"
        )
```

---

### Scenario 5: Extraction Failure (File Unreadable)

**When**: A document fails all extraction methods in the fallback chain (markitdown, pdftotext, Read tool, pytesseract).

**Detection**: The extraction pipeline returns zero bytes after exhausting all methods. Tracked in `extraction_quality.json` with `method: "failed"`.

**Recovery**: This is already handled by the fallback chain (SKILL.md section 1b). No agent-level recovery needed.

**Action**: Log a gap finding with `gap_type=Unreadable` for the affected subject. Record the failure in `extraction_quality.json`.

**Fallback**: The file is excluded from agent analysis. The gap finding alerts the user that manual review is needed.

**User notification**: Warning in extraction log. Gap finding appears in the Missing_Docs_Gaps sheet of the final report.

```python
# src/dd_agents/extraction/pipeline.py

async def extract_file(
    file_path: Path,
    output_dir: Path,
    state: PipelineState,
) -> ExtractionResult:
    """Extract text from a file using the fallback chain."""
    methods = [
        ("markitdown", _extract_markitdown),
        ("pdftotext", _extract_pdftotext),
        ("read_tool", _extract_read),
        ("tesseract", _extract_tesseract),
    ]

    for method_name, method_fn in methods:
        try:
            result = await method_fn(file_path, output_dir)
            if result.bytes_extracted > 0:
                return ExtractionResult(
                    file_path=str(file_path),
                    method=method_name,
                    bytes_extracted=result.bytes_extracted,
                    confidence=result.confidence,
                )
        except Exception as e:
            logger.debug(f"Extraction method {method_name} failed for {file_path}: {e}")
            continue

    # All methods failed
    logger.warning(f"All extraction methods failed for {file_path}")
    return ExtractionResult(
        file_path=str(file_path),
        method="failed",
        bytes_extracted=0,
        confidence=0.0,
        gap_type="Unreadable",
    )
```

---

### Scenario 6: Entity Resolution Cache Corrupted

**When**: `_dd/entity_resolution_cache.json` exists but contains invalid JSON, is truncated, or has schema violations.

**Detection**: JSON parse error or Pydantic validation failure when loading the cache at step 7.

**Recovery**:
1. Delete `_dd/entity_resolution_cache.json`.
2. Run the full 6-pass cascading matcher from scratch.
3. Write a fresh cache with the new results.
4. Log: "Entity cache rebuilt from scratch."

**Fallback**: No fallback needed. The 6-pass matcher produces correct results without the cache; the cache only accelerates subsequent runs.

**User notification**: Info-level log message.

```python
# src/dd_agents/entity_resolution/cache.py

import json
from pathlib import Path
from pydantic import ValidationError


def load_entity_cache(cache_path: Path, logger) -> dict:
    """Load entity resolution cache, rebuilding if corrupted."""
    if not cache_path.exists():
        logger.info("No entity resolution cache found, will build from scratch")
        return {}

    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
        # Validate structure
        EntityResolutionCache.model_validate(raw)
        logger.info(f"Loaded entity cache with {len(raw.get('matches', {}))} entries")
        return raw
    except (json.JSONDecodeError, ValidationError, KeyError) as e:
        logger.warning(f"Entity cache corrupted ({e}), deleting and rebuilding")
        cache_path.unlink(missing_ok=True)
        return {}
```

---

### Scenario 7: Out-of-Context Agent (Explicit)

**When**: An agent explicitly signals context exhaustion before processing all assigned subjects. The agent reports something like "I have run out of context and cannot process the remaining subjects."

**Detection**: The agent's output includes a context exhaustion signal in its final message or produces a partial `coverage_manifest.json` with `subjects_processed < subjects_assigned`.

**Recovery**:
1. Identify which subjects remain unprocessed.
2. Build a new prompt containing only the remaining subjects (same rules, references, instructions).
3. Spawn a continuation instance of the same agent type.
4. Merge outputs from both instances into the primary findings directory.

**Fallback**: If the continuation instance also exhausts context, split the remaining subjects further and try again (up to 2 total re-spawns). If still incomplete, treat as partial failure (Scenario 2).

**User notification**: Console info message about context-split.

```python
async def handle_context_exhaustion_explicit(
    agent_name: str,
    manifest: dict,
    state: PipelineState,
    recovery: ErrorRecoveryManager,
):
    """Handle an agent that explicitly reported context exhaustion."""
    processed = set(manifest.get("subjects_processed_safe_names", []))
    expected = set(state.subject_safe_names)
    remaining = sorted(expected - processed)

    if not remaining:
        return  # Actually complete

    logger.info(
        f"Agent {agent_name} exhausted context after {len(processed)}/{len(expected)} "
        f"subjects. Re-spawning for {len(remaining)} remaining."
    )

    recovery.record_error(
        step=17,
        category=ErrorCategory.AGENT_CONTEXT,
        severity=ErrorSeverity.RECOVERED,
        message=f"Agent {agent_name} signaled context exhaustion",
        recovery_action=f"Re-spawning for {len(remaining)} remaining subjects",
        outcome="retrying",
        agent=agent_name,
        subjects_affected=remaining,
    )

    # Split remaining into batches if needed (avoid exhausting context again)
    batch_size = max(len(remaining) // 2, 1) if len(remaining) > 20 else len(remaining)
    batches = [remaining[i:i + batch_size] for i in range(0, len(remaining), batch_size)]

    for batch_idx, batch in enumerate(batches):
        await respawn_for_missing_subjects(
            f"{agent_name}-ctx-{batch_idx}",
            batch,
            state,
            recovery,
        )
```

---

### Scenario 8: Out-of-Context Agent (Silent)

**When**: An agent runs out of context without explicitly signaling. It simply stops producing output. This is the most insidious failure mode because the agent appears to have completed successfully.

**Detection**: **Context exhaustion detection**: Primary signal is the agent stopping mid-task without completing all assigned subjects. Secondary signal is output length dropping below 50% of the average for prior subjects in the same batch. False positive mitigation: the detector requires BOTH signals (premature stop AND quality degradation) before triggering context exhaustion recovery. A single short output is not sufficient to trigger recovery.

Context exhaustion is detected by the orchestrator (not self-reported by the agent). The orchestrator monitors: (1) agent stop events via the Stop hook, (2) completion status by checking output files against the assigned subject list, (3) output quality by comparing file sizes against running averages.

At step 17, the coverage gate counts subject JSON files in `{RUN_DIR}/findings/{agent}/` and compares against the expected count. If an agent has fewer files than expected, it indicates the agent stopped mid-execution.

Additionally, spot-check at least 3 subjects JSONs where `findings[]` is empty or contains only P3 entries. Verify each has a `domain_reviewed_no_issues` entry. A JSON with zero findings AND no clean-result entry indicates the agent skipped the subject rather than reviewing it.

**Recovery**: Identical to Scenario 2 (partial failure). Re-spawn for missing subjects only.

**Fallback**: P1 gaps for every uncovered subject.

**User notification**: Console warning noting the silent context exhaustion pattern.

```python
async def detect_silent_context_exhaustion(
    agent_name: str,
    state: PipelineState,
    recovery: ErrorRecoveryManager,
) -> list[str]:
    """Detect agents that silently stopped producing output.

    Returns list of subject safe names that need re-processing.
    """
    findings_dir = state.run_dir / "findings" / agent_name
    produced = {p.stem for p in findings_dir.glob("*.json") if p.stem != "coverage_manifest"}
    expected = set(state.subject_safe_names)

    missing = sorted(expected - produced)
    if missing:
        logger.warning(
            f"Agent {agent_name}: silent context exhaustion detected. "
            f"Produced {len(produced)}/{len(expected)} subject files. "
            f"Missing: {missing[:5]}{'...' if len(missing) > 5 else ''}"
        )
        recovery.record_error(
            step=17,
            category=ErrorCategory.AGENT_CONTEXT,
            severity=ErrorSeverity.WARNING,
            message=(
                f"Agent {agent_name} appears to have silently exhausted context. "
                f"Missing {len(missing)} of {len(expected)} subject outputs."
            ),
            recovery_action="Will re-spawn for missing subjects",
            outcome="retrying",
            agent=agent_name,
            subjects_affected=missing,
        )

    # Spot-check for "skipped" subjects (empty files without clean-result)
    skipped = []
    sample_size = min(3, len(produced))
    empty_files = []

    for safe_name in produced:
        file_path = findings_dir / f"{safe_name}.json"
        data = json.loads(file_path.read_text())
        findings = data.get("findings", [])
        clean_results = [
            f for f in findings if f.get("id", "").endswith("_clean_" + safe_name + "_0000")
        ]
        if not findings and not clean_results:
            empty_files.append(safe_name)

    if empty_files:
        logger.warning(
            f"Agent {agent_name}: {len(empty_files)} subject files have zero findings "
            f"AND no clean-result entry. Treating as skipped: {empty_files[:5]}"
        )
        skipped.extend(empty_files)

    return missing + skipped
```

---

### Scenario 9: Agent Timeout

**When**: An agent has not produced any new output for 30 minutes of wall-clock time (no new files written to its output directory). For extraction, individual file extraction hangs beyond 2 minutes.

**Detection**: File watcher on the agent's output directory. If no new files appear within the timeout window, trigger a status check. If no response within 5 more minutes, declare failure.

**Recovery**:
1. Send a status check message (if the SDK supports inter-agent messaging).
2. Wait 5 minutes for a response.
3. If no response, treat as agent failure and apply the appropriate re-spawn protocol (Scenario 1 for total failure, Scenario 2 for partial).
4. For extraction timeouts: kill the hung subprocess and proceed to the next method in the fallback chain.

**Fallback**: Same as the failure scenario for the relevant agent type.

**User notification**: Console warning with elapsed time.

```python
# src/dd_agents/orchestrator/timeout.py

import asyncio
import time
from pathlib import Path


class AgentTimeoutMonitor:
    """Monitors an agent's output directory for activity."""

    def __init__(
        self,
        output_dir: Path,
        timeout_minutes: int = 30,
        status_check_minutes: int = 5,
    ):
        self.output_dir = output_dir
        self.timeout_seconds = timeout_minutes * 60
        self.status_check_seconds = status_check_minutes * 60
        self.last_activity = time.monotonic()

    def check_activity(self) -> bool:
        """Check if new files have been written since last check."""
        current_files = set(self.output_dir.rglob("*.json"))
        # Compare against last known state
        if self._has_new_files(current_files):
            self.last_activity = time.monotonic()
            return True
        return False

    def is_timed_out(self) -> bool:
        """Check if timeout threshold has been exceeded."""
        elapsed = time.monotonic() - self.last_activity
        return elapsed > self.timeout_seconds

    def is_status_check_due(self) -> bool:
        """Check if we should send a status check."""
        elapsed = time.monotonic() - self.last_activity
        return elapsed > self.timeout_seconds and elapsed < (
            self.timeout_seconds + self.status_check_seconds
        )


EXTRACTION_TIMEOUT_SECONDS = 120  # 2 minutes per file

async def extract_with_timeout(file_path: Path, method_fn, output_dir: Path):
    """Run an extraction method with a 2-minute timeout."""
    try:
        return await asyncio.wait_for(
            method_fn(file_path, output_dir),
            timeout=EXTRACTION_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning(
            f"Extraction timed out after {EXTRACTION_TIMEOUT_SECONDS}s for {file_path}"
        )
        raise
```

---

### Scenario 10: Shared Resource Contention

**When**: Multiple concurrent runs (or concurrent skill invocations on the same data room) attempt to write to shared PERMANENT-tier files: `_dd/entity_resolution_cache.json` and `_dd/run_history.json`.

**Detection**: Read-validate-write pattern detects when a file changed between read and write (another process modified it concurrently).

**Recovery**:
1. Read the file.
2. Apply changes in memory.
3. Write the file.
4. Re-read and validate the write succeeded (check that applied changes are present).
5. If the file changed (concurrent write detected), re-read the latest version, re-apply changes, and retry once.

**Fallback**: If the retry also fails, log a warning. The current run's changes to the shared file are lost, but the pipeline continues. The data will be regenerated on the next run.

**User notification**: Warning-level log message.

```python
# src/dd_agents/persistence/shared_files.py

import json
import hashlib
from pathlib import Path
from typing import Callable


def read_validate_write(
    file_path: Path,
    transform: Callable[[dict], dict],
    logger,
    max_retries: int = 1,
) -> bool:
    """Safely update a shared JSON file with concurrency protection.

    Args:
        file_path: Path to the shared JSON file.
        transform: Function that takes current data and returns updated data.
        max_retries: Number of retry attempts on concurrent modification.

    Returns:
        True if write succeeded, False if all retries failed.
    """
    for attempt in range(max_retries + 1):
        # Read current state
        if file_path.exists():
            content = file_path.read_text(encoding="utf-8")
            pre_hash = hashlib.sha256(content.encode()).hexdigest()
            data = json.loads(content)
        else:
            pre_hash = None
            data = {}

        # Apply transformation
        updated = transform(data)

        # Write
        file_path.write_text(
            json.dumps(updated, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # Validate: re-read and check
        written_content = file_path.read_text(encoding="utf-8")
        written_data = json.loads(written_content)

        # Check that our changes are present (simple verification)
        if _changes_present(updated, written_data):
            return True

        # Concurrent modification detected
        if attempt < max_retries:
            logger.warning(
                f"Concurrent modification detected on {file_path}, retrying "
                f"(attempt {attempt + 1}/{max_retries})"
            )
            continue

    logger.warning(f"Failed to write {file_path} after {max_retries + 1} attempts")
    return False


def _changes_present(expected: dict, actual: dict) -> bool:
    """Verify that the expected changes are present in the actual file.

    JSON comparison: uses json.dumps(obj, sort_keys=True) for deterministic
    serialization before comparison. This ensures that semantically identical
    JSON objects with different key ordering are correctly identified as equal.
    """
    return json.dumps(expected, sort_keys=True) == json.dumps(actual, sort_keys=True)
```

---

### Scenario 11: Config Validation Failure

**When**: `deal-config.json` is missing, unparseable, or fails schema validation against `deal-config.schema.json`.

**Detection**: Step 1 of the pipeline. Pydantic model validation against the config schema.

**Recovery**: **NONE. STOP the pipeline immediately.** This is a FATAL error. The user must fix the config before re-running.

**Fallback**: None. Config validation is a hard gate.

**User notification**: Console error with specific validation failures (missing fields, type errors, version incompatibility).

```python
# src/dd_agents/orchestrator/engine.py

async def step_01_validate_config(state: PipelineState, recovery: ErrorRecoveryManager):
    """Step 1: Validate deal-config.json. FATAL on failure."""
    config_path = state.project_dir / "deal-config.json"

    if not config_path.exists():
        raise PipelineError(
            step=1,
            error_type=ErrorCategory.CONFIG,
            details=f"deal-config.json not found at {config_path}",
            fatal=True,
        )

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise PipelineError(
            step=1,
            error_type=ErrorCategory.CONFIG,
            details=f"deal-config.json is not valid JSON: {e}",
            fatal=True,
        )

    try:
        config = DealConfig.model_validate(raw)
    except ValidationError as e:
        errors = "; ".join(
            f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}"
            for err in e.errors()
        )
        raise PipelineError(
            step=1,
            error_type=ErrorCategory.CONFIG,
            details=f"Config validation failed: {errors}",
            fatal=True,
        )

    # Version check
    if not _version_compatible(config.config_version, "1.0.0"):
        raise PipelineError(
            step=1,
            error_type=ErrorCategory.CONFIG,
            details=(
                f"Config version {config.config_version} is not compatible "
                f"with minimum required version 1.0.0"
            ),
            fatal=True,
        )

    state.deal_config = config
    state.config_hash = hashlib.sha256(
        config_path.read_bytes()
    ).hexdigest()
```

---

### Scenario 12: Extraction Systemic Failure

**When**: More than 50% of files fail the primary extraction method (markitdown). This indicates a systemic issue (broken installation, incompatible file formats, corrupted data room).

**Detection**: After bulk pre-extraction at step 5, check the ratio of failed extractions to total non-plaintext files.

**Recovery**: **NONE. STOP the pipeline at step 5.** Report the extraction pipeline issue to the user.

**Rationale**: Agents depend on pre-extracted text. Proceeding with >50% extraction failures would produce unreliable, unauditable results.

**User notification**: Console error with failure count, list of failing file types, and suggestion to check markitdown installation.

```python
async def step_05_bulk_extraction(state: PipelineState, recovery: ErrorRecoveryManager):
    """Step 5: Bulk pre-extraction. FATAL if >50% fail primary method."""
    results = await extract_all_files(state)

    total_non_plaintext = sum(1 for r in results if not r.is_plaintext)
    primary_failures = sum(
        1 for r in results
        if not r.is_plaintext and r.method != "markitdown"
    )

    if total_non_plaintext > 0:
        failure_rate = primary_failures / total_non_plaintext
        if failure_rate > 0.50:
            # Categorize failures by file type for diagnostics
            failure_types = {}
            for r in results:
                if r.method == "failed":
                    ext = Path(r.file_path).suffix.lower()
                    failure_types[ext] = failure_types.get(ext, 0) + 1

            raise PipelineError(
                step=5,
                error_type=ErrorCategory.EXTRACTION,
                details=(
                    f"Systemic extraction failure: {primary_failures}/{total_non_plaintext} "
                    f"files ({failure_rate:.0%}) failed primary method. "
                    f"Failure breakdown by type: {failure_types}. "
                    f"Check markitdown installation and data room file integrity."
                ),
                fatal=True,
            )

    # Write extraction_quality.json and checksums.sha256
    write_extraction_quality(state, results)
    write_checksums(state, results)

    # Verify blocking gate files exist
    checksums_path = state.skill_dir / "index" / "text" / "checksums.sha256"
    quality_path = state.skill_dir / "index" / "extraction_quality.json"
    if not checksums_path.exists() or not quality_path.exists():
        raise PipelineError(
            step=5,
            error_type=ErrorCategory.EXTRACTION,
            details="Extraction completed but blocking gate files not written",
            fatal=True,
        )
```

---

### Scenario 13: Incremental Mode Forced to Full

**When**: `deal-config.json` has `execution.execution_mode = "incremental"` but the config has changed since the prior run, and `execution.force_full_on_config_change` is true (default).

**Detection**: Step 1. Compare the SHA-256 hash of the current `deal-config.json` against the prior run's `metadata.json -> config_hash`.

**Recovery**: Silently override `execution_mode` to `"full"`. This is not an error — it is expected behavior to ensure consistency when the config changes.

**User notification**: Console info message explaining the override.

```python
def check_incremental_to_full_override(state: PipelineState, logger) -> bool:
    """Check if incremental mode should be forced to full.

    Returns True if mode was overridden.
    """
    if state.execution_mode != "incremental":
        return False

    config = state.deal_config
    if not config.execution.force_full_on_config_change:
        return False

    # Check prior run's config hash
    prior_metadata = _load_prior_metadata(state)
    if prior_metadata is None:
        logger.info("No prior run found, running in full mode")
        state.execution_mode = "full"
        return True

    prior_hash = prior_metadata.get("config_hash", "")
    if prior_hash != state.config_hash:
        logger.info(
            f"deal-config.json changed since prior run "
            f"(hash {state.config_hash[:8]}... != {prior_hash[:8]}...). "
            f"Forcing full mode."
        )
        state.execution_mode = "full"
        return True

    return False
```

---

### Scenario 14: Framework Version Mismatch

**When**: The `dd-framework` version has changed since the prior run. Detected via `_dd/framework_version.txt` vs the prior run's `metadata.json -> framework_version`.

**Detection**: Step 1. If the framework version changed or is absent from prior metadata, force `execution_mode` to `"full"`.

**Recovery**: Override to full mode. Not an error, but a safety measure to ensure new framework rules are applied to all subjects.

**User notification**: Console info message.

```python
def check_framework_version_mismatch(state: PipelineState, logger) -> bool:
    """Check if framework version changed, forcing full mode.

    Returns True if mode was overridden.
    """
    framework_version_path = state.project_dir / "_dd" / "framework_version.txt"
    current_version = "unknown"
    if framework_version_path.exists():
        current_version = framework_version_path.read_text().strip()

    state.framework_version = current_version

    if state.execution_mode != "incremental":
        return False

    prior_metadata = _load_prior_metadata(state)
    if prior_metadata is None:
        state.execution_mode = "full"
        return True

    prior_version = prior_metadata.get("framework_version", "")
    if not prior_version or prior_version != current_version:
        logger.info(
            f"Framework version changed ({prior_version!r} -> {current_version!r}). "
            f"Forcing full mode."
        )
        state.execution_mode = "full"
        return True

    return False
```

---

### Scenario 15: Aggregate File Detection

**When**: An agent produces files like `_global.json`, `batch_summary.json`, or `other_subjects.json` instead of per-subject JSON files. This violates the per-subject output format and indicates the agent bundled multiple subjects into a single file.

**Detection**: Step 17 coverage gate. Check for known aggregate filename patterns in the agent's output directory.

**Recovery**:
1. Delete the aggregate files.
2. Re-spawn the agent with an explicit instruction appended to the prompt: "You MUST produce exactly one JSON file per subject named {subject_safe_name}.json. Do NOT create aggregate files."
3. If the re-spawn still produces aggregates, treat as full agent failure (Scenario 1).

**Fallback**: If recovery fails, extract what data is available from the aggregate files (best-effort parsing), then log P1 gaps for any subjects whose data could not be separated.

**User notification**: Console warning about the non-conforming output.

```python
# Aggregate file detection uses a blocklist of exact filenames. The check uses
# exact basename matching (os.path.basename(path) in BLOCKLIST), not substring
# matching, to avoid false positives on subject names that happen to contain
# words like "summary" or "global".
AGGREGATE_FILE_BLOCKLIST = {
    "_global", "batch_summary", "other_subjects", "all_subjects",
    "remaining", "summary", "combined", "misc",
    "all_findings", "master_report",
}


def detect_aggregate_files(findings_dir: Path) -> list[Path]:
    """Detect aggregate output files that violate per-subject format."""
    aggregates = []
    for json_file in findings_dir.glob("*.json"):
        if json_file.stem == "coverage_manifest":
            continue
        if json_file.stem.lower() in AGGREGATE_FILE_BLOCKLIST:
            aggregates.append(json_file)
    return aggregates


async def handle_aggregate_files(
    agent_name: str,
    aggregates: list[Path],
    state: PipelineState,
    recovery: ErrorRecoveryManager,
):
    """Handle aggregate files by re-spawning with explicit instructions."""
    recovery.record_error(
        step=17,
        category=ErrorCategory.AGENT_PARTIAL,
        severity=ErrorSeverity.WARNING,
        message=(
            f"Agent {agent_name} produced {len(aggregates)} aggregate files: "
            f"{[a.name for a in aggregates]}"
        ),
        recovery_action="Deleting aggregates and re-spawning with explicit instruction",
        outcome="retrying",
        agent=agent_name,
    )

    # Delete aggregates
    for agg in aggregates:
        agg.unlink()

    # Build augmented prompt
    base_prompt = state.agent_prompts[agent_name]
    augmented_prompt = (
        base_prompt + "\n\n"
        "CRITICAL INSTRUCTION: You MUST produce exactly one JSON file per subject "
        "named {subject_safe_name}.json. Do NOT create aggregate files like "
        "_global.json, batch_summary.json, or other_subjects.json. "
        "Every subject must have its own separate output file."
    )

    options = build_specialist_options(state, agent_name)
    try:
        await spawn_with_retry(agent_name, augmented_prompt, options, max_retries=0)
    except AgentError:
        # Re-spawn also failed or produced aggregates again
        recovery.record_error(
            step=17,
            category=ErrorCategory.AGENT_FAILURE,
            severity=ErrorSeverity.DEGRADED,
            message=f"Agent {agent_name} still producing aggregate files after re-spawn",
            recovery_action="Treating as full agent failure",
            outcome="degraded",
            agent=agent_name,
        )
        state.degraded_agents.append(agent_name)
```

---

## 4. Step 17 Coverage Gate (Orchestrated Recovery)

Step 17 is the central error detection point. It combines Scenarios 2, 7, 8, and 15 into a single orchestrated validation pass.

```python
# src/dd_agents/orchestrator/coverage.py

async def step_17_coverage_gate(state: PipelineState, recovery: ErrorRecoveryManager):
    """Step 17: Comprehensive coverage validation with automatic recovery.

    This is the primary detection mechanism for context exhaustion (silent),
    partial failures, and aggregate file production.
    """
    agents = ["legal", "finance", "commercial", "producttech"]

    for agent_name in agents:
        if agent_name in state.degraded_agents:
            continue

        findings_dir = state.run_dir / "findings" / agent_name

        # 1. Check for aggregate files (Scenario 15)
        aggregates = detect_aggregate_files(findings_dir)
        if aggregates:
            await handle_aggregate_files(agent_name, aggregates, state, recovery)

        # 2. Detect silent context exhaustion (Scenario 8)
        missing = await detect_silent_context_exhaustion(agent_name, state, recovery)

        # 3. Check coverage manifest exists
        manifest_path = findings_dir / "coverage_manifest.json"
        if not manifest_path.exists():
            recovery.record_error(
                step=17,
                category=ErrorCategory.AGENT_PARTIAL,
                severity=ErrorSeverity.WARNING,
                message=f"Agent {agent_name} did not produce coverage_manifest.json",
                recovery_action="Will re-spawn to generate manifest",
                outcome="retrying",
                agent=agent_name,
            )
            missing = missing or state.subject_safe_names  # Force re-spawn

        # 4. Check audit log exists
        audit_path = state.run_dir / "audit" / agent_name / "audit_log.jsonl"
        if not audit_path.exists():
            recovery.record_error(
                step=17,
                category=ErrorCategory.AGENT_PARTIAL,
                severity=ErrorSeverity.WARNING,
                message=f"Agent {agent_name} did not produce audit_log.jsonl",
                recovery_action="QA warning (Reporting Lead will flag at section 8b2)",
                outcome="warning",
                agent=agent_name,
            )

        # 5. Re-spawn for missing subjects (Scenario 2)
        if missing:
            await respawn_for_missing_subjects(agent_name, missing, state, recovery)

    # 6. If batched agents were used, merge batch outputs
    for agent_name in agents:
        if agent_name in state.degraded_agents:
            continue
        await merge_batch_outputs(agent_name, state)

    # 7. Final validation pass (no more retries)
    remaining_issues = await validate_specialist_coverage(state, recovery)
    if remaining_issues:
        for agent_name, missing in remaining_issues.items():
            for subject_safe in missing:
                subject = state.safe_name_to_subject.get(subject_safe, subject_safe)
                recovery.generate_gap_finding(
                    agent=agent_name,
                    subject=subject,
                    gap_type="Partial_Failure",
                    priority="P1",
                    description=(
                        f"Agent {agent_name} did not produce output for {subject} "
                        f"after all recovery attempts -- {agent_name} coverage missing."
                    ),
                )
```

---

## 5. Error Metadata in Run Output

All errors are persisted in `{RUN_DIR}/metadata.json` for post-run analysis:

```json
{
  "run_id": "20260221_093000",
  "errors": [
    {
      "timestamp": "2026-02-21T09:45:12Z",
      "step": 17,
      "category": "agent_context",
      "severity": "recovered",
      "agent": "legal",
      "message": "Agent legal: silent context exhaustion detected. Missing 5 of 182 subjects outputs.",
      "recovery_action": "Re-spawning for 5 remaining subjects",
      "outcome": "recovered",
      "subjects_affected": ["acme_corp", "beta_inc", "delta_llc", "epsilon_co", "zeta_group"]
    }
  ],
  "degraded_agents": [],
  "quality_caveats": [],
  "gap_findings_from_errors": 0
}
```

---

## 6. Summary Table

| # | Scenario | Detection Point | Recovery | Fallback | Severity |
|---|----------|----------------|----------|----------|----------|
| 1 | Specialist fails (full) | Step 16 spawn | Re-spawn once | Continue with 3 agents + P1 gaps | DEGRADED |
| 2 | Specialist partial (<90%) | Step 17 coverage gate | Re-spawn for missing only | P1 gaps for uncovered | DEGRADED |
| 3 | Judge fails | Steps 19-22 | Re-spawn once | Proceed without review + caveat | DEGRADED |
| 4 | Reporting Lead fails | Step 23 | Re-spawn once (with checkpoint) | Output raw JSONs | DEGRADED |
| 5 | Extraction failure (file) | Step 5 fallback chain | Fallback chain | gap_type=Unreadable | WARNING |
| 6 | Entity cache corrupted | Step 7 cache load | Delete + full 6-pass | Always succeeds | RECOVERED |
| 7 | Out-of-context (explicit) | Step 17 manifest check | Split remaining + re-spawn | Partial failure path | RECOVERED |
| 8 | Out-of-context (silent) | Step 17 file count | Re-spawn for missing | P1 gaps for uncovered | DEGRADED |
| 9 | Agent timeout | 30min no output | Status check + 5min grace | Treat as failure | DEGRADED |
| 10 | Shared resource contention | read-validate-write check | Re-read + retry once | Data regenerated next run | WARNING |
| 11 | Config validation failure | Step 1 | **STOP** | None (user must fix) | FATAL |
| 12 | Extraction systemic (>50%) | Step 5 | **STOP** | None (user must fix) | FATAL |
| 13 | Incremental forced to full | Step 1 config hash | Override to full mode | Not an error | INFO |
| 14 | Framework version mismatch | Step 1 version check | Override to full mode | Not an error | INFO |
| 15 | Aggregate file detected | Step 17 file scan | Delete + re-spawn with instruction | Full agent failure path | DEGRADED |
