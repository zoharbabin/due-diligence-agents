"""Checkpoint persistence for the forensic DD pipeline.

Saves ``PipelineState`` to a JSON file after each successful step so the
pipeline can be resumed from the last completed step after a crash.

Checkpoint filename format::

    checkpoint_{step_number:02d}_{step_name}.json

Writes use an atomic pattern (write to ``.tmp``, then rename) to prevent
corruption from partial writes.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from dd_agents.orchestrator.state import PipelineState

if TYPE_CHECKING:
    from pathlib import Path

log = logging.getLogger("dd_agents.checkpoints")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def save_checkpoint(state: PipelineState, checkpoint_dir: Path) -> Path:
    """Serialise *state* to a checkpoint JSON file.

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
    step_num = step.step_number
    step_name = step.value  # e.g. "05_bulk_extraction"
    filename = f"checkpoint_{step_num:02d}_{step_name}.json"
    path = checkpoint_dir / filename
    tmp_path = path.with_suffix(".tmp")

    data = state.to_checkpoint_dict()
    tmp_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp_path.rename(path)

    log.debug("Checkpoint saved: %s", path.name)
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
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    log.info("Loaded checkpoint: %s", latest)
    return PipelineState.from_checkpoint_dict(data)


def load_checkpoint_by_step(checkpoint_dir: Path, step_number: int) -> PipelineState:
    """Load the checkpoint for a specific step number.

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
    data: dict[str, Any] = json.loads(matches[0].read_text(encoding="utf-8"))
    log.info("Loaded checkpoint for step %d: %s", step_number, matches[0].name)
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
    """Remove all checkpoint files (and stale ``.tmp`` files).

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
        if f.name.startswith("checkpoint_") and f.suffix in (".json", ".tmp"):
            f.unlink()
            removed += 1
    if removed:
        log.info("Cleaned %d checkpoint file(s)", removed)
    return removed
