"""Inventory integrity verifier.

Checks that the data room inventory is internally consistent:
  - total files = customer files + reference files
  - no orphan files (every file is accounted for)
  - all files are classified
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dd_agents.models.inventory import FileEntry, ReferenceFile

log = logging.getLogger("dd_agents.inventory.integrity")


class InventoryIntegrityVerifier:
    """Validates inventory completeness and consistency."""

    def verify(
        self,
        all_files: list[FileEntry],
        customer_files: list[FileEntry],
        reference_files: list[ReferenceFile],
    ) -> list[str]:
        """Run all integrity checks and return a list of issues.

        Parameters
        ----------
        all_files:
            Complete set of discovered files.
        customer_files:
            Files that belong to customer directories.
        reference_files:
            Classified reference files.

        Returns
        -------
        list[str]
            Human-readable issue descriptions.  Empty list means the
            inventory passes all checks.
        """
        issues: list[str] = []

        # 1. Total = customer + reference
        total_expected = len(customer_files) + len(reference_files)
        if len(all_files) != total_expected:
            issues.append(
                f"File count mismatch: total={len(all_files)} "
                f"!= customer({len(customer_files)}) + reference({len(reference_files)}) "
                f"= {total_expected}"
            )

        # 2. No orphan files
        all_paths = {entry.path for entry in all_files}
        customer_paths = {entry.path for entry in customer_files}
        reference_paths = {rf.file_path for rf in reference_files}
        accounted = customer_paths | reference_paths

        orphans = all_paths - accounted
        if orphans:
            sample = sorted(orphans)[:5]
            issues.append(
                f"{len(orphans)} orphan file(s) not classified as customer or reference: "
                f"{sample}{'...' if len(orphans) > 5 else ''}"
            )

        # Files in customer/reference but not in all_files (should not happen)
        extra_customer = customer_paths - all_paths
        if extra_customer:
            issues.append(f"{len(extra_customer)} customer file(s) not in all_files: {sorted(extra_customer)[:3]}")

        extra_reference = reference_paths - all_paths
        if extra_reference:
            issues.append(f"{len(extra_reference)} reference file(s) not in all_files: {sorted(extra_reference)[:3]}")

        # 3. All files are classified (category check for reference files)
        unclassified = [rf.file_path for rf in reference_files if not rf.category]
        if unclassified:
            issues.append(f"{len(unclassified)} reference file(s) with empty category: {unclassified[:3]}")

        if issues:
            for issue in issues:
                log.warning("Integrity issue: %s", issue)
        else:
            log.info("Inventory integrity check passed")

        return issues
