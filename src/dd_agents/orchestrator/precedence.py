"""Orchestrator integration for the document precedence engine.

Wires together folder priority classification, version chain detection,
and precedence scoring into a single function the pipeline can call.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from dd_agents.precedence.folder_priority import FolderPriorityClassifier
from dd_agents.precedence.scorer import PrecedenceScorer
from dd_agents.precedence.version_chains import VersionChainBuilder

if TYPE_CHECKING:
    from dd_agents.models.inventory import FileEntry

logger = logging.getLogger(__name__)


def compute_precedence_index(
    files: list[FileEntry],
    folder_overrides: dict[str, int] | None = None,
) -> dict[str, float]:
    """Run the full precedence pipeline and return a path → score index.

    Mutates :class:`FileEntry` objects in-place, enriching them with
    ``folder_tier``, ``version_indicator``, ``version_rank``,
    ``precedence_score``, ``is_latest_version``, and ``superseded_by``.

    Parameters
    ----------
    files:
        All discovered :class:`FileEntry` objects from the data room.
    folder_overrides:
        Optional user-provided folder-name → tier mapping from deal-config.

    Returns
    -------
    dict[str, float]
        Mapping of relative file path → composite precedence score (0–1).
    """
    if not files:
        return {}

    # 1. Classify folder tiers
    classifier = FolderPriorityClassifier(overrides=folder_overrides)
    for entry in files:
        entry.folder_tier = int(classifier.classify_path(entry.path))

    # 2. Detect version chains (sets version_indicator, version_rank,
    #    is_latest_version, superseded_by)
    chain_builder = VersionChainBuilder()
    groups = chain_builder.build_chains(files)

    # 3. Compute composite precedence scores
    scorer = PrecedenceScorer()
    scorer.score_batch(files)

    logger.info(
        "Precedence: scored %d files in %d version groups",
        len(files),
        len(groups),
    )

    return {entry.path: entry.precedence_score for entry in files}
