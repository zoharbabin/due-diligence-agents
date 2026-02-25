"""Run initialization and finalization.

Responsible for:
  - Generating a timestamp-based ``run_id``.
  - Creating the full run directory tree (VERSIONED tier).
  - Archiving prior VERSIONED inventory before wiping FRESH tier.
  - Finalizing runs: updating ``run_history.json`` and writing final metadata.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dd_agents.models.persistence import RunHistoryEntry, RunMetadata
from dd_agents.persistence.tiers import TierManager
from dd_agents.utils.constants import DD_DIR, SKILL_DIR

logger = logging.getLogger(__name__)


class RunManager:
    """Manages the lifecycle of a single pipeline run.

    Parameters
    ----------
    project_dir:
        Root of the data room (contains ``_dd/``).
    """

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = Path(project_dir)
        self.tier_mgr = TierManager(self.project_dir)

    # ------------------------------------------------------------------
    # Run initialization
    # ------------------------------------------------------------------

    def initialize_run(
        self,
        project_dir: Path,
        deal_config: dict[str, Any] | None = None,
    ) -> RunMetadata:
        """Set up a new run: generate run_id, create directory tree, archive prior.

        Parameters
        ----------
        project_dir:
            Root of the data room.
        deal_config:
            Parsed deal configuration dict (used for metadata fields).

        Returns
        -------
        RunMetadata
            Metadata model for the newly created run.
        """
        self.project_dir = Path(project_dir)
        self.tier_mgr = TierManager(self.project_dir)

        # 1. Generate run_id from current UTC time
        run_id = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

        # 2. Ensure PERMANENT dirs exist
        self.tier_mgr.ensure_permanent_dirs()

        # 3. Create VERSIONED run directory tree
        skill_dir = self.project_dir / SKILL_DIR
        run_dir = skill_dir / "runs" / run_id
        self.tier_mgr.ensure_run_dirs(run_dir)

        # 4. Archive prior VERSIONED inventory (before wiping FRESH)
        prior_runs_dir = skill_dir / "runs"
        self.tier_mgr.archive_versioned(run_dir, prior_runs_dir)

        # 5. Wipe FRESH tier
        self.tier_mgr.wipe_fresh()

        # 6. Build RunMetadata
        config_hash = ""
        execution_mode = "full"
        framework_version = "unknown"

        if deal_config:
            import hashlib

            config_hash = hashlib.sha256(json.dumps(deal_config, sort_keys=True).encode()).hexdigest()
            execution = deal_config.get("execution", {})
            execution_mode = execution.get("execution_mode", "full")

        fw_path = self.project_dir / DD_DIR / "framework_version.txt"
        if fw_path.exists():
            framework_version = fw_path.read_text().strip()

        metadata = RunMetadata(
            run_id=run_id,
            timestamp=datetime.now(UTC).isoformat(),
            skill="forensic-dd",
            execution_mode=execution_mode,
            config_hash=config_hash,
            framework_version=framework_version,
            completion_status="in_progress",
        )

        # Write initial metadata.json
        meta_path = run_dir / "metadata.json"
        meta_path.write_text(json.dumps(metadata.model_dump(), indent=2))

        logger.info("Initialized run %s at %s", run_id, run_dir)
        return metadata

    # ------------------------------------------------------------------
    # Run finalization
    # ------------------------------------------------------------------

    def finalize_run(self, run_metadata: RunMetadata) -> RunHistoryEntry:
        """Finalize a completed run: update metadata and append to run_history.json.

        Parameters
        ----------
        run_metadata:
            The run's metadata (will be updated with ``completion_status``).

        Returns
        -------
        RunHistoryEntry
            The entry appended to ``run_history.json``.
        """
        skill_dir = self.project_dir / SKILL_DIR
        run_dir = skill_dir / "runs" / run_metadata.run_id

        # Mark metadata as completed
        run_metadata.completion_status = "completed"
        meta_path = run_dir / "metadata.json"
        meta_path.write_text(json.dumps(run_metadata.model_dump(), indent=2))

        # Build RunHistoryEntry
        history_entry = RunHistoryEntry(
            run_id=run_metadata.run_id,
            skill=run_metadata.skill,
            timestamp=run_metadata.timestamp,
            execution_mode=run_metadata.execution_mode,
            agent_scores=run_metadata.agent_scores,
        )

        # Append to run_history.json (shared across DD skills)
        history_path = self.project_dir / DD_DIR / "run_history.json"
        history: list[dict[str, Any]] = []
        if history_path.exists():
            try:
                history = json.loads(history_path.read_text())
            except (json.JSONDecodeError, ValueError):
                logger.warning("Corrupt run_history.json -- starting fresh")
                history = []

        history.append(history_entry.model_dump())
        history_path.write_text(json.dumps(history, indent=2))

        # Update latest symlink (use missing_ok to avoid TOCTOU race)
        latest_link = skill_dir / "runs" / "latest"
        latest_link.unlink(missing_ok=True)
        latest_link.symlink_to(run_dir.name)

        logger.info(
            "Finalized run %s -- history updated, latest symlink set",
            run_metadata.run_id,
        )
        return history_entry

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def get_prior_run_id(self) -> str | None:
        """Return the run_id of the most recent completed run, or None."""
        latest_link = self.project_dir / SKILL_DIR / "runs" / "latest"
        if latest_link.is_symlink():
            return latest_link.resolve().name
        return None

    def get_run_dir(self, run_id: str) -> Path:
        """Return the absolute path to a run directory."""
        return self.project_dir / SKILL_DIR / "runs" / run_id

    def load_run_history(self) -> list[dict[str, Any]]:
        """Load and return the full run history."""
        history_path = self.project_dir / DD_DIR / "run_history.json"
        if not history_path.exists():
            return []
        try:
            result: list[dict[str, Any]] = json.loads(history_path.read_text())
            return result
        except (json.JSONDecodeError, ValueError):
            return []
