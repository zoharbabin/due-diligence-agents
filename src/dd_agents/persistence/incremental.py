"""Incremental mode: subject classification and finding carry-forward.

Classification categories:
  NEW           -- subject folders not present in prior run.
  CHANGED       -- subject files differ from prior run (checksum mismatch).
  STALE_REFRESH -- files unchanged for >= staleness_threshold consecutive runs.
  UNCHANGED     -- files identical to prior run; carry forward findings.
  DELETED       -- subject present in prior run but absent from current.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from dd_agents.models.enums import ExecutionMode, SubjectClassificationStatus
from dd_agents.models.persistence import (
    Classification,
    ClassificationSummary,
    SubjectClassEntry,
)

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class IncrementalClassifier:
    """Classifies subjects for incremental pipeline runs."""

    def classify_subjects(
        self,
        current_files: dict[str, list[str]],
        prior_files: dict[str, list[str]],
        staleness_threshold: int,
        prior_classifications: dict[str, SubjectClassEntry] | None = None,
    ) -> Classification:
        """Compare current vs prior subject file sets and classify each.

        Parameters
        ----------
        current_files:
            Mapping of ``subject_safe_name`` to list of file checksums
            (sorted) representing the current data room state.
        prior_files:
            Same structure from the prior run.
        staleness_threshold:
            Number of consecutive unchanged runs before a subject is
            classified as ``STALE_REFRESH``.
        prior_classifications:
            Prior ``SubjectClassEntry`` objects keyed by ``subject_safe_name``.
            Used to track ``consecutive_unchanged_runs``.

        Returns
        -------
        Classification
            Full classification document with per-subject entries.
        """
        prior_classifications = prior_classifications or {}
        entries: list[SubjectClassEntry] = []

        all_subjects = set(current_files) | set(prior_files)

        summary = ClassificationSummary()

        for subj in sorted(all_subjects):
            current = current_files.get(subj)
            prior = prior_files.get(subj)

            if current is None and prior is not None:
                # DELETED: was in prior, not in current
                entry = SubjectClassEntry(
                    subject=subj,
                    subject_safe_name=subj,
                    classification=SubjectClassificationStatus.DELETED,
                    reason="Subject folder absent in current data room",
                    prior_checksum=_joined_checksum(prior),
                )
                summary.deleted += 1

            elif prior is None and current is not None:
                # NEW: not in prior, exists in current
                entry = SubjectClassEntry(
                    subject=subj,
                    subject_safe_name=subj,
                    classification=SubjectClassificationStatus.NEW,
                    reason="Subject folder not present in prior run",
                    current_checksum=_joined_checksum(current),
                )
                summary.new += 1

            else:
                # Both exist -- compare checksums
                if current is None or prior is None:  # pragma: no cover
                    continue
                current_cksum = _joined_checksum(current)
                prior_cksum = _joined_checksum(prior)

                if current_cksum != prior_cksum:
                    # CHANGED: files differ.
                    # Use set-based comparison instead of index-based.  Issue #66.
                    prior_set = set(prior)
                    current_set = set(current)
                    files_added = [f for f in current if f not in prior_set]
                    files_removed = [f for f in prior if f not in current_set]
                    # Files present in both sets are candidates for modification.
                    # Without per-file checksums we cannot distinguish a rename from
                    # a content change, but we reliably report files that persisted
                    # across runs while the overall checksum shifted.
                    common = current_set & prior_set
                    files_modified = sorted(common - set(files_added) - set(files_removed))

                    entry = SubjectClassEntry(
                        subject=subj,
                        subject_safe_name=subj,
                        classification=SubjectClassificationStatus.CHANGED,
                        reason="Subject files differ from prior run",
                        files_added=files_added,
                        files_removed=files_removed,
                        files_modified=files_modified,
                        prior_checksum=prior_cksum,
                        current_checksum=current_cksum,
                    )
                    summary.changed += 1
                else:
                    # Unchanged -- check staleness
                    prior_entry = prior_classifications.get(subj)
                    consecutive = 1  # at least this run is unchanged
                    if prior_entry is not None:
                        consecutive = prior_entry.consecutive_unchanged_runs + 1

                    if consecutive >= staleness_threshold:
                        entry = SubjectClassEntry(
                            subject=subj,
                            subject_safe_name=subj,
                            classification=SubjectClassificationStatus.STALE_REFRESH,
                            reason=(f"Unchanged for {consecutive} consecutive runs (threshold: {staleness_threshold})"),
                            prior_checksum=prior_cksum,
                            current_checksum=current_cksum,
                            consecutive_unchanged_runs=consecutive,
                        )
                        summary.stale_refresh += 1
                    else:
                        entry = SubjectClassEntry(
                            subject=subj,
                            subject_safe_name=subj,
                            classification=SubjectClassificationStatus.UNCHANGED,
                            reason="Files identical to prior run",
                            prior_checksum=prior_cksum,
                            current_checksum=current_cksum,
                            consecutive_unchanged_runs=consecutive,
                        )
                        summary.unchanged += 1

            entries.append(entry)

        classification = Classification(
            run_id="",  # Populated by caller
            execution_mode=ExecutionMode.INCREMENTAL,
            classification_summary=summary,
            subjects=entries,
        )

        logger.info(
            "Classification: %d NEW, %d CHANGED, %d STALE_REFRESH, %d UNCHANGED, %d DELETED",
            summary.new,
            summary.changed,
            summary.stale_refresh,
            summary.unchanged,
            summary.deleted,
        )
        return classification

    def carry_forward_findings(
        self,
        unchanged_subjects: list[str],
        prior_findings_dir: Path,
        current_findings_dir: Path,
        active_agents: list[str] | None = None,
    ) -> int:
        """Copy findings for UNCHANGED subjects from prior run with carry-forward metadata.

        Parameters
        ----------
        unchanged_subjects:
            List of ``subject_safe_name`` values to carry forward.
        prior_findings_dir:
            Path to the prior run's ``findings/`` directory.
        current_findings_dir:
            Path to the current run's ``findings/`` directory.
        active_agents:
            If provided, only carry forward findings from these agents.
            Findings from agents not in this list (e.g. disabled between
            runs) are skipped.

        Returns
        -------
        int
            Number of subject findings files carried forward.
        """
        carried = 0
        active_set = set(active_agents) if active_agents is not None else None

        for subj in unchanged_subjects:
            for agent_dir in prior_findings_dir.iterdir():
                if not agent_dir.is_dir():
                    continue
                if active_set is not None and agent_dir.name not in active_set:
                    continue

                source_file = agent_dir / f"{subj}.json"
                if not source_file.exists():
                    continue

                target_agent_dir = current_findings_dir / agent_dir.name
                target_agent_dir.mkdir(parents=True, exist_ok=True)
                target_file = target_agent_dir / f"{subj}.json"

                # Copy and annotate with _carried_forward metadata
                try:
                    data = json.loads(source_file.read_text(encoding="utf-8"))
                    data["_carried_forward"] = True
                    data["_carried_from_run"] = prior_findings_dir.parent.name
                    target_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
                    carried += 1
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning(
                        "Failed to carry forward %s/%s: %s",
                        agent_dir.name,
                        subj,
                        exc,
                    )

                # Also carry forward gaps
                source_gap = agent_dir / "gaps" / f"{subj}.json"
                if source_gap.exists():
                    target_gap_dir = target_agent_dir / "gaps"
                    target_gap_dir.mkdir(parents=True, exist_ok=True)
                    target_gap = target_gap_dir / f"{subj}.json"
                    try:
                        gap_data = json.loads(source_gap.read_text(encoding="utf-8"))
                        if isinstance(gap_data, list):
                            for g in gap_data:
                                g["_carried_forward"] = True
                        elif isinstance(gap_data, dict):
                            gap_data["_carried_forward"] = True
                        target_gap.write_text(json.dumps(gap_data, indent=2), encoding="utf-8")
                    except (json.JSONDecodeError, OSError) as exc:
                        logger.warning(
                            "Failed to carry forward gap %s/%s: %s",
                            agent_dir.name,
                            subj,
                            exc,
                        )

        logger.info("Carried forward %d finding files for %d subjects", carried, len(unchanged_subjects))
        return carried


def _joined_checksum(file_checksums: list[str]) -> str:
    """Create a deterministic combined checksum string from a sorted list."""
    return "|".join(sorted(file_checksums))
