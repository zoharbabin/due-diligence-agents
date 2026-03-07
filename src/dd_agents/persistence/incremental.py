"""Incremental mode: customer classification and finding carry-forward.

Classification categories:
  NEW           -- customer folder not present in prior run.
  CHANGED       -- customer files differ from prior run (checksum mismatch).
  STALE_REFRESH -- files unchanged for >= staleness_threshold consecutive runs.
  UNCHANGED     -- files identical to prior run; carry forward findings.
  DELETED       -- customer present in prior run but absent from current.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from dd_agents.models.enums import CustomerClassificationStatus, ExecutionMode
from dd_agents.models.persistence import (
    Classification,
    ClassificationSummary,
    CustomerClassEntry,
)

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class IncrementalClassifier:
    """Classifies customers for incremental pipeline runs."""

    def classify_customers(
        self,
        current_files: dict[str, list[str]],
        prior_files: dict[str, list[str]],
        staleness_threshold: int,
        prior_classifications: dict[str, CustomerClassEntry] | None = None,
    ) -> Classification:
        """Compare current vs prior customer file sets and classify each.

        Parameters
        ----------
        current_files:
            Mapping of ``customer_safe_name`` to list of file checksums
            (sorted) representing the current data room state.
        prior_files:
            Same structure from the prior run.
        staleness_threshold:
            Number of consecutive unchanged runs before a customer is
            classified as ``STALE_REFRESH``.
        prior_classifications:
            Prior ``CustomerClassEntry`` objects keyed by ``customer_safe_name``.
            Used to track ``consecutive_unchanged_runs``.

        Returns
        -------
        Classification
            Full classification document with per-customer entries.
        """
        prior_classifications = prior_classifications or {}
        entries: list[CustomerClassEntry] = []

        all_customers = set(current_files) | set(prior_files)

        summary = ClassificationSummary()

        for customer in sorted(all_customers):
            current = current_files.get(customer)
            prior = prior_files.get(customer)

            if current is None and prior is not None:
                # DELETED: was in prior, not in current
                entry = CustomerClassEntry(
                    customer=customer,
                    customer_safe_name=customer,
                    classification=CustomerClassificationStatus.DELETED,
                    reason="Customer folder absent in current data room",
                    prior_checksum=_joined_checksum(prior),
                )
                summary.deleted += 1

            elif prior is None and current is not None:
                # NEW: not in prior, exists in current
                entry = CustomerClassEntry(
                    customer=customer,
                    customer_safe_name=customer,
                    classification=CustomerClassificationStatus.NEW,
                    reason="Customer folder not present in prior run",
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

                    entry = CustomerClassEntry(
                        customer=customer,
                        customer_safe_name=customer,
                        classification=CustomerClassificationStatus.CHANGED,
                        reason="Customer files differ from prior run",
                        files_added=files_added,
                        files_removed=files_removed,
                        files_modified=files_modified,
                        prior_checksum=prior_cksum,
                        current_checksum=current_cksum,
                    )
                    summary.changed += 1
                else:
                    # Unchanged -- check staleness
                    prior_entry = prior_classifications.get(customer)
                    consecutive = 1  # at least this run is unchanged
                    if prior_entry is not None:
                        consecutive = prior_entry.consecutive_unchanged_runs + 1

                    if consecutive >= staleness_threshold:
                        entry = CustomerClassEntry(
                            customer=customer,
                            customer_safe_name=customer,
                            classification=CustomerClassificationStatus.STALE_REFRESH,
                            reason=(f"Unchanged for {consecutive} consecutive runs (threshold: {staleness_threshold})"),
                            prior_checksum=prior_cksum,
                            current_checksum=current_cksum,
                            consecutive_unchanged_runs=consecutive,
                        )
                        summary.stale_refresh += 1
                    else:
                        entry = CustomerClassEntry(
                            customer=customer,
                            customer_safe_name=customer,
                            classification=CustomerClassificationStatus.UNCHANGED,
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
            customers=entries,
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
        unchanged_customers: list[str],
        prior_findings_dir: Path,
        current_findings_dir: Path,
    ) -> int:
        """Copy findings for UNCHANGED customers from prior run with carry-forward metadata.

        Parameters
        ----------
        unchanged_customers:
            List of ``customer_safe_name`` values to carry forward.
        prior_findings_dir:
            Path to the prior run's ``findings/`` directory.
        current_findings_dir:
            Path to the current run's ``findings/`` directory.

        Returns
        -------
        int
            Number of customer findings files carried forward.
        """
        carried = 0

        for customer in unchanged_customers:
            for agent_dir in prior_findings_dir.iterdir():
                if not agent_dir.is_dir():
                    continue

                source_file = agent_dir / f"{customer}.json"
                if not source_file.exists():
                    continue

                target_agent_dir = current_findings_dir / agent_dir.name
                target_agent_dir.mkdir(parents=True, exist_ok=True)
                target_file = target_agent_dir / f"{customer}.json"

                # Copy and annotate with _carried_forward metadata
                try:
                    data = json.loads(source_file.read_text())
                    data["_carried_forward"] = True
                    data["_carried_from_run"] = prior_findings_dir.parent.name
                    target_file.write_text(json.dumps(data, indent=2))
                    carried += 1
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning(
                        "Failed to carry forward %s/%s: %s",
                        agent_dir.name,
                        customer,
                        exc,
                    )

                # Also carry forward gaps
                source_gap = agent_dir / "gaps" / f"{customer}.json"
                if source_gap.exists():
                    target_gap_dir = target_agent_dir / "gaps"
                    target_gap_dir.mkdir(parents=True, exist_ok=True)
                    target_gap = target_gap_dir / f"{customer}.json"
                    try:
                        gap_data = json.loads(source_gap.read_text())
                        if isinstance(gap_data, list):
                            for g in gap_data:
                                g["_carried_forward"] = True
                        elif isinstance(gap_data, dict):
                            gap_data["_carried_forward"] = True
                        target_gap.write_text(json.dumps(gap_data, indent=2))
                    except (json.JSONDecodeError, OSError) as exc:
                        logger.warning(
                            "Failed to carry forward gap %s/%s: %s",
                            agent_dir.name,
                            customer,
                            exc,
                        )

        logger.info("Carried forward %d finding files for %d customers", carried, len(unchanged_customers))
        return carried


def _joined_checksum(file_checksums: list[str]) -> str:
    """Create a deterministic combined checksum string from a sorted list."""
    return "|".join(sorted(file_checksums))
