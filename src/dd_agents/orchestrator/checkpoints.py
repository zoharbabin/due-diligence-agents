"""Checkpoint persistence for the forensic DD pipeline.

Saves ``PipelineState`` to a JSON file after each successful step so the
pipeline can be resumed from the last completed step after a crash.

Checkpoint filename format::

    checkpoint_{step_value}.json

where ``step_value`` is the ``PipelineStep.value`` string (e.g. ``"06_build_inventory"``).

Writes use an atomic pattern (write to ``.tmp``, then rename) to prevent
corruption from partial writes.

Sub-checkpoints (Issue #51)
---------------------------
Long-running steps (e.g. step 16 agent analysis) can write per-customer
sub-checkpoints so that progress within a step is not lost on crash::

    checkpoints/step_16/customer_<safe_name>.json

Corruption recovery (Issue #51)
-------------------------------
Before writing a new checkpoint, a ``.bak`` copy is created.  If the
primary checkpoint is corrupted on load, the ``.bak`` file is used.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from typing import TYPE_CHECKING, Any

from dd_agents.orchestrator.state import PipelineState

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def save_checkpoint(state: PipelineState, checkpoint_dir: Path) -> Path:
    """Serialise *state* to a checkpoint JSON file.

    Creates a ``.bak`` backup of the previous checkpoint before overwriting
    so that corruption recovery is possible (Issue #51).

    Parameters
    ----------
    state:
        The current pipeline state to persist.
    checkpoint_dir:
        Directory in which to write the checkpoint file.

    Returns
    -------
    Path
        The path to the written checkpoint file.
    """
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    step = state.current_step
    step_name = step.value  # e.g. "05_bulk_extraction"
    filename = f"checkpoint_{step_name}.json"
    path = checkpoint_dir / filename
    bak_path = path.with_suffix(".bak")
    tmp_path = path.with_suffix(".tmp")

    # Create .bak of existing checkpoint before overwriting (Issue #51)
    if path.exists():
        try:
            shutil.copy2(str(path), str(bak_path))
        except OSError:
            logger.debug("Could not create backup of %s", path.name)

    data = state.to_checkpoint_dict()
    try:
        tmp_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        os.replace(str(tmp_path), str(path))
    except Exception:
        # Clean up temp file on serialization or write failure.
        tmp_path.unlink(missing_ok=True)
        raise

    logger.debug("Checkpoint saved: %s", path.name)
    return path


def load_checkpoint(checkpoint_dir: Path) -> PipelineState:
    """Load the most recent checkpoint from *checkpoint_dir*.

    The "most recent" checkpoint is the one with the highest step number
    (determined by sorting the filenames lexicographically).

    Parameters
    ----------
    checkpoint_dir:
        Directory containing checkpoint files.

    Returns
    -------
    PipelineState
        The restored pipeline state.

    Raises
    ------
    FileNotFoundError
        If no checkpoint files exist in the directory.
    """
    checkpoints = list_checkpoints(checkpoint_dir)
    if not checkpoints:
        raise FileNotFoundError(f"No checkpoints found in {checkpoint_dir}")

    latest = checkpoints[-1]  # highest step number (sorted)
    path = checkpoint_dir / latest
    data: dict[str, Any] = _load_json_with_backup(path)
    logger.info("Loaded checkpoint: %s", latest)
    return PipelineState.from_checkpoint_dict(data)


def load_checkpoint_by_step(checkpoint_dir: Path, step_number: int) -> PipelineState:
    """Load the checkpoint for a specific step number.

    If the primary checkpoint is corrupted (JSON parse error), falls back
    to the ``.bak`` backup file (Issue #51).

    Parameters
    ----------
    checkpoint_dir:
        Directory containing checkpoint files.
    step_number:
        The step number whose checkpoint to load.

    Returns
    -------
    PipelineState
        The restored pipeline state.

    Raises
    ------
    FileNotFoundError
        If no checkpoint exists for the given step number.
    """
    prefix = f"checkpoint_{step_number:02d}_"
    matches = sorted(checkpoint_dir.glob(f"{prefix}*.json"))
    if not matches:
        raise FileNotFoundError(f"No checkpoint for step {step_number} in {checkpoint_dir}")
    data: dict[str, Any] = _load_json_with_backup(matches[0])
    logger.info("Loaded checkpoint for step %d: %s", step_number, matches[0].name)
    return PipelineState.from_checkpoint_dict(data)


def list_checkpoints(checkpoint_dir: Path) -> list[str]:
    """Return checkpoint filenames sorted by step number.

    Parameters
    ----------
    checkpoint_dir:
        Directory containing checkpoint files.

    Returns
    -------
    list[str]
        Sorted list of checkpoint filenames (not full paths).
    """
    if not checkpoint_dir.is_dir():
        return []
    return sorted(
        f.name for f in checkpoint_dir.iterdir() if f.name.startswith("checkpoint_") and f.name.endswith(".json")
    )


def clean_checkpoints(checkpoint_dir: Path) -> int:
    """Remove all checkpoint files (and stale ``.tmp`` / ``.bak`` files).

    Called after a successful pipeline completion.

    Returns
    -------
    int
        Number of files removed.
    """
    removed = 0
    if not checkpoint_dir.is_dir():
        return removed
    for f in checkpoint_dir.iterdir():
        if f.name.startswith("checkpoint_") and f.suffix in (".json", ".tmp", ".bak"):
            f.unlink()
            removed += 1
    # Also clean sub-checkpoint directories
    for d in checkpoint_dir.iterdir():
        if d.is_dir() and d.name.startswith("step_"):
            shutil.rmtree(d)
            removed += 1
    if removed:
        logger.info("Cleaned %d checkpoint file(s)/dir(s)", removed)
    return removed


# ---------------------------------------------------------------------------
# Sub-checkpoint API (Issue #51)
# ---------------------------------------------------------------------------


def save_sub_checkpoint(
    checkpoint_dir: Path,
    step: str,
    key: str,
    data: dict[str, Any],
) -> Path:
    """Write a sub-checkpoint for a given step and key.

    Sub-checkpoints allow per-customer progress tracking within long-running
    steps (e.g. step 16 agent analysis).  On resume, previously completed
    customers can be skipped.

    Parameters
    ----------
    checkpoint_dir:
        Root checkpoint directory.
    step:
        Step identifier (e.g. ``"step_16"``).
    key:
        Sub-checkpoint key, typically the customer safe name.
    data:
        Data to persist (must be JSON-serialisable).

    Returns
    -------
    Path
        Path to the written sub-checkpoint file.
    """
    sub_dir = checkpoint_dir / step
    sub_dir.mkdir(parents=True, exist_ok=True)

    filename = f"customer_{key}.json"
    path = sub_dir / filename
    tmp_path = path.with_suffix(".tmp")

    try:
        tmp_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        os.replace(str(tmp_path), str(path))
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    logger.debug("Sub-checkpoint saved: %s/%s", step, filename)
    return path


def load_sub_checkpoints(
    checkpoint_dir: Path,
    step: str,
) -> dict[str, dict[str, Any]]:
    """Load all sub-checkpoints for a given step.

    Returns a dict mapping customer key to its checkpoint data.  Keys are
    extracted from the filename pattern ``customer_<key>.json``.

    Parameters
    ----------
    checkpoint_dir:
        Root checkpoint directory.
    step:
        Step identifier (e.g. ``"step_16"``).

    Returns
    -------
    dict[str, dict[str, Any]]
        Mapping of key -> checkpoint data.  Empty dict if no sub-checkpoints
        exist.
    """
    sub_dir = checkpoint_dir / step
    if not sub_dir.is_dir():
        return {}

    results: dict[str, dict[str, Any]] = {}
    for f in sorted(sub_dir.glob("customer_*.json")):
        key = f.stem.removeprefix("customer_")
        try:
            data: dict[str, Any] = json.loads(f.read_text(encoding="utf-8"))
            results[key] = data
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Corrupt sub-checkpoint %s: %s", f.name, exc)
            continue

    if results:
        logger.info("Loaded %d sub-checkpoint(s) for %s", len(results), step)
    return results


# ---------------------------------------------------------------------------
# Corruption recovery helper (Issue #51)
# ---------------------------------------------------------------------------


def _load_json_with_backup(path: Path) -> dict[str, Any]:
    """Load a JSON file, falling back to ``.bak`` on corruption.

    Parameters
    ----------
    path:
        Primary JSON file path.

    Returns
    -------
    dict[str, Any]
        Parsed JSON data.

    Raises
    ------
    FileNotFoundError
        If neither primary nor backup exist.
    json.JSONDecodeError
        If both primary and backup are corrupted.
    """
    # Try primary file first
    try:
        raw = path.read_text(encoding="utf-8")
        result: dict[str, Any] = json.loads(raw)
        return result
    except (json.JSONDecodeError, OSError) as primary_err:
        bak_path = path.with_suffix(".bak")
        if bak_path.exists():
            logger.warning(
                "Primary checkpoint %s is corrupted (%s), falling back to .bak",
                path.name,
                primary_err,
            )
            try:
                raw = bak_path.read_text(encoding="utf-8")
                result = json.loads(raw)
                return result
            except (json.JSONDecodeError, OSError) as backup_err:
                logger.error(
                    "Backup checkpoint %s is also corrupted: %s",
                    bak_path.name,
                    backup_err,
                )
                raise
        # No backup available -- re-raise original error
        raise
