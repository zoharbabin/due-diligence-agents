"""Three-tier persistence lifecycle manager.

Tier definitions:
  PERMANENT  -- never wiped across runs.
  VERSIONED  -- archived per run; each run directory is immutable after completion.
  FRESH      -- rebuilt from scratch at the start of every run.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from dd_agents.utils.constants import (
    AUDIT_DIR,
    DD_DIR,
    FINDINGS_DIR,
    INDEX_DIR,
    INVENTORY_DIR,
    JUDGE_DIR,
    REPORT_DIR,
    SKILL_DIR,
    TEXT_DIR,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PERMANENT tier paths (relative to project_dir)
# ---------------------------------------------------------------------------

PERMANENT_PATHS: list[str] = [
    f"{TEXT_DIR}",  # index/text/*.md
    f"{TEXT_DIR}/checksums.sha256",  # extraction checksums
    f"{INDEX_DIR}/extraction_quality.json",  # per-file extraction quality
    f"{DD_DIR}/entity_resolution_cache.json",  # entity resolution cache
    f"{SKILL_DIR}/runs",  # all prior run directories
    f"{DD_DIR}/run_history.json",  # chronological run log
    f"{SKILL_DIR}/knowledge",  # Deal Knowledge Base (Issue #178)
]

# ---------------------------------------------------------------------------
# VERSIONED tier paths (relative to run directory)
# ---------------------------------------------------------------------------

VERSIONED_SUBDIRS: list[str] = [
    f"{FINDINGS_DIR}/legal/gaps",
    f"{FINDINGS_DIR}/finance/gaps",
    f"{FINDINGS_DIR}/commercial/gaps",
    f"{FINDINGS_DIR}/producttech/gaps",
    f"{FINDINGS_DIR}/merged/gaps",
    JUDGE_DIR,
    REPORT_DIR,
    f"{AUDIT_DIR}/legal",
    f"{AUDIT_DIR}/finance",
    f"{AUDIT_DIR}/commercial",
    f"{AUDIT_DIR}/producttech",
    f"{AUDIT_DIR}/judge",
]

VERSIONED_FILES: list[str] = [
    "audit.json",
    "numerical_manifest.json",
    "file_coverage.json",
    "classification.json",
    "contract_date_reconciliation.json",
    "report_diff.json",
    "metadata.json",
]

# ---------------------------------------------------------------------------
# FRESH tier paths (relative to project_dir)
# ---------------------------------------------------------------------------

FRESH_FILES: list[str] = [
    f"{INVENTORY_DIR}/tree.txt",
    f"{INVENTORY_DIR}/files.txt",
    f"{INVENTORY_DIR}/file_types.txt",
    f"{INVENTORY_DIR}/subjects.csv",
    f"{INVENTORY_DIR}/counts.json",
    f"{INVENTORY_DIR}/reference_files.json",
    f"{INVENTORY_DIR}/subject_mentions.json",
    f"{INVENTORY_DIR}/entity_matches.json",
]


class TierManager:
    """Manages the three-tier persistence lifecycle.

    Parameters
    ----------
    project_dir:
        Root of the data room (contains ``_dd/``).
    """

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = Path(project_dir)
        self.dd_dir = self.project_dir / DD_DIR
        self.skill_dir = self.project_dir / SKILL_DIR
        self.inventory_dir = self.project_dir / INVENTORY_DIR

    # -- directory creation -------------------------------------------------

    def ensure_permanent_dirs(self) -> None:
        """Create all PERMANENT tier directories if they do not already exist."""
        (self.project_dir / TEXT_DIR).mkdir(parents=True, exist_ok=True)
        (self.skill_dir / "runs").mkdir(parents=True, exist_ok=True)
        (self.project_dir / INVENTORY_DIR).mkdir(parents=True, exist_ok=True)
        (self.skill_dir / "knowledge").mkdir(parents=True, exist_ok=True)
        logger.debug("Ensured PERMANENT tier directories exist")

    def ensure_run_dirs(self, run_dir: Path) -> None:
        """Create all VERSIONED sub-directories for a new run.

        Parameters
        ----------
        run_dir:
            Absolute path to the run directory, e.g.
            ``<project>/_dd/forensic-dd/runs/20260215_100000``.
        """
        for subdir in VERSIONED_SUBDIRS:
            (run_dir / subdir).mkdir(parents=True, exist_ok=True)
        # Also create inventory_snapshot placeholder
        (run_dir / "inventory_snapshot").mkdir(parents=True, exist_ok=True)
        logger.debug("Created VERSIONED sub-directories under %s", run_dir)

    def ensure_dirs(self, base_path: Path, run_id: str) -> Path:
        """High-level helper: ensure all PERMANENT dirs plus a new run directory.

        Parameters
        ----------
        base_path:
            Project directory (data room root).
        run_id:
            Timestamp-based run identifier (``YYYYMMDD_HHMMSS``).

        Returns
        -------
        Path
            The newly created run directory.
        """
        self.project_dir = Path(base_path)
        self.dd_dir = self.project_dir / DD_DIR
        self.skill_dir = self.project_dir / SKILL_DIR
        self.inventory_dir = self.project_dir / INVENTORY_DIR

        self.ensure_permanent_dirs()

        run_dir = self.skill_dir / "runs" / run_id
        self.ensure_run_dirs(run_dir)
        return run_dir

    # -- VERSIONED tier archival --------------------------------------------

    def archive_versioned(self, run_dir: Path, prior_runs_dir: Path) -> None:
        """Snapshot the current inventory into the prior run before wiping FRESH.

        If a ``latest`` symlink exists, copies the current inventory into that
        run's ``inventory_snapshot/`` sub-directory so nothing is lost.

        Parameters
        ----------
        run_dir:
            Current (new) run directory -- not modified by this method.
        prior_runs_dir:
            The ``runs/`` directory (``_dd/forensic-dd/runs/``).
        """
        latest_link = prior_runs_dir / "latest"
        if not latest_link.is_symlink():
            logger.debug("No latest symlink -- nothing to archive")
            return

        prior_run_id = latest_link.resolve().name
        prior_run_dir = prior_runs_dir / prior_run_id
        snapshot_dir = prior_run_dir / "inventory_snapshot"

        # Check whether the snapshot directory already has content (not just
        # the empty placeholder created by ensure_run_dirs).  Issue #62.
        snapshot_has_content = snapshot_dir.exists() and any(snapshot_dir.iterdir())

        if self.inventory_dir.exists() and not snapshot_has_content:
            if snapshot_dir.exists():
                # Remove the empty placeholder so copytree can create it.
                shutil.rmtree(snapshot_dir)
            shutil.copytree(self.inventory_dir, snapshot_dir)
            logger.info(
                "Archived VERSIONED inventory to %s",
                snapshot_dir,
            )
        else:
            logger.debug(
                "Skipping archive: inventory=%s exists=%s, snapshot=%s has_content=%s",
                self.inventory_dir,
                self.inventory_dir.exists(),
                snapshot_dir,
                snapshot_has_content,
            )

    # -- FRESH tier wipe ----------------------------------------------------

    def wipe_fresh(self, dirs: list[Path] | None = None) -> None:
        """Delete and recreate FRESH tier directories.

        Parameters
        ----------
        dirs:
            Specific directories to wipe.  Defaults to the inventory directory.
        """
        targets = dirs if dirs is not None else [self.inventory_dir]
        for d in targets:
            if d.exists():
                shutil.rmtree(d)
                logger.info("Wiped FRESH tier directory: %s", d)
            d.mkdir(parents=True, exist_ok=True)

    # -- Query helpers ------------------------------------------------------

    def permanent_paths(self) -> list[Path]:
        """Return resolved paths for all PERMANENT tier entries."""
        return [self.project_dir / p for p in PERMANENT_PATHS]

    def fresh_paths(self) -> list[Path]:
        """Return resolved paths for all FRESH tier files."""
        return [self.project_dir / p for p in FRESH_FILES]
