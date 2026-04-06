"""Customer registry builder: parse directory structure into customers.csv and counts.json."""

from __future__ import annotations

import csv
import io
import json
import logging
from collections import defaultdict
from pathlib import Path, PurePosixPath

from dd_agents.models.inventory import CountsJson, CustomerEntry, FileEntry
from dd_agents.utils.naming import customer_safe_name

logger = logging.getLogger(__name__)


class CustomerRegistryBuilder:
    """Parses the data room directory hierarchy to identify customer folders.

    Supports two layouts:

    1. **Three-level** (``data_room/group/customer/files``):
       Top-level dirs are *groups*, second-level dirs are *customer folders*.

    2. **Two-level** (``data_room/customer/files``):
       Top-level dirs are *customers*.  Files directly under a top-level
       dir are assigned to that dir as both group and customer.

    Files in the data room root are always treated as reference files.
    """

    def build(
        self,
        data_room_path: Path,
        files: list[FileEntry],
        *,
        layout: str = "auto",
        target_name: str = "",
    ) -> tuple[list[CustomerEntry], CountsJson]:
        """Build the customer registry and aggregate counts.

        Parameters
        ----------
        data_room_path:
            Root of the data room.
        files:
            Discovered file entries from :class:`FileDiscovery`.
        layout:
            ``"auto"`` (default) detects two- or three-level structure.
            ``"single_target"`` treats the entire data room as one entity
            (for single-target acquisition data rooms where folders are
            categories, not customers).
        target_name:
            Display name for the single target entity.  Required when
            *layout* is ``"single_target"``.

        Returns
        -------
        tuple[list[CustomerEntry], CountsJson]
            The customer list and the aggregate counts structure.
        """
        if layout == "single_target":
            return self._build_single_target(files, target_name)
        # Bucket files by group/customer
        customer_files: dict[tuple[str, str], list[str]] = defaultdict(list)
        reference_file_paths: list[str] = []
        ext_counts: dict[str, int] = defaultdict(int)
        group_file_counts: dict[str, int] = defaultdict(int)
        group_customer_names: dict[str, set[str]] = defaultdict(set)

        # First pass: identify which top-level dirs contain files directly
        # (two-level layout) to distinguish from pure three-level dirs.
        dirs_with_direct_files: set[str] = set()
        for entry in files:
            parts = PurePosixPath(entry.path).parts
            if len(parts) == 2:
                dirs_with_direct_files.add(parts[0])

        for entry in files:
            parts = PurePosixPath(entry.path).parts

            # Track extension counts
            suffix = PurePosixPath(entry.path).suffix.lower()
            if suffix:
                ext_counts[suffix] = ext_counts.get(suffix, 0) + 1

            if len(parts) < 2:
                # Root-level file => reference
                reference_file_paths.append(entry.path)
                continue

            top_dir = parts[0]

            if top_dir in dirs_with_direct_files:
                # Two-level layout: the top-level dir IS the customer.
                # All files (direct and in subfolders) belong to it.
                customer_files[(top_dir, top_dir)].append(entry.path)
                group_file_counts[top_dir] += 1
                group_customer_names[top_dir].add(top_dir)
            elif len(parts) >= 3:
                # Pure three-level layout: group/customer/files
                group = parts[0]
                customer = parts[1]
                customer_files[(group, customer)].append(entry.path)
                group_file_counts[group] += 1
                group_customer_names[group].add(customer)
            else:
                # File in a group dir that has no direct files but the
                # path is only 2 parts — treat as reference.
                reference_file_paths.append(entry.path)
                group_file_counts[top_dir] += 1

        # Build CustomerEntry list
        customers: list[CustomerEntry] = []
        for (group, customer_name), file_paths in sorted(customer_files.items()):
            try:
                safe_name = customer_safe_name(customer_name)
            except ValueError:
                logger.warning("Could not compute safe_name for %r -- skipping", customer_name)
                continue

            customer_entry = CustomerEntry(
                group=group,
                name=customer_name,
                safe_name=safe_name,
                path=f"{group}/{customer_name}",
                file_count=len(file_paths),
                files=sorted(file_paths),
            )
            customers.append(customer_entry)

        customers.sort(key=lambda c: (c.group, c.name))

        # Build CountsJson
        customers_by_group: dict[str, int] = {g: len(names) for g, names in group_customer_names.items()}

        counts = CountsJson(
            total_files=len(files),
            total_customers=len(customers),
            total_reference_files=len(reference_file_paths),
            files_by_extension=dict(sorted(ext_counts.items())),
            files_by_group=dict(sorted(group_file_counts.items())),
            customers_by_group=dict(sorted(customers_by_group.items())),
        )

        logger.info(
            "Registry: %d customers in %d groups, %d reference files, %d total files",
            counts.total_customers,
            len(customers_by_group),
            counts.total_reference_files,
            counts.total_files,
        )
        return customers, counts

    def _build_single_target(
        self,
        files: list[FileEntry],
        target_name: str,
    ) -> tuple[list[CustomerEntry], CountsJson]:
        """Build registry for a single-target acquisition data room.

        All files are assigned to one customer entity (the target).
        No reference files are produced — every file belongs to the target.
        """
        if not target_name:
            target_name = "Target"
            logger.warning("single_target layout with empty target_name — using 'Target'")

        try:
            safe_name = customer_safe_name(target_name)
        except ValueError:
            safe_name = "target"
            logger.warning("Could not compute safe_name for %r — using 'target'", target_name)

        ext_counts: dict[str, int] = defaultdict(int)
        all_paths: list[str] = []
        for entry in files:
            all_paths.append(entry.path)
            suffix = PurePosixPath(entry.path).suffix.lower()
            if suffix:
                ext_counts[suffix] = ext_counts.get(suffix, 0) + 1

        customer_entry = CustomerEntry(
            group=safe_name,
            name=target_name,
            safe_name=safe_name,
            path=".",
            file_count=len(all_paths),
            files=sorted(all_paths),
        )

        counts = CountsJson(
            total_files=len(files),
            total_customers=1,
            total_reference_files=0,
            files_by_extension=dict(sorted(ext_counts.items())),
            files_by_group={safe_name: len(files)},
            customers_by_group={safe_name: 1},
        )

        logger.info(
            "Registry (single_target): 1 customer '%s', %d files",
            target_name,
            len(files),
        )
        return [customer_entry], counts

    def write_csv(self, customers: list[CustomerEntry], output_path: Path) -> None:
        """Write the customer registry to ``customers.csv``.

        Parameters
        ----------
        customers:
            Customer entries to write.
        output_path:
            Destination path for the CSV file.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["group", "name", "safe_name", "path", "file_count", "file_list"])
        for c in customers:
            writer.writerow(
                [
                    c.group,
                    c.name,
                    c.safe_name,
                    c.path,
                    c.file_count,
                    ";".join(c.files),
                ]
            )

        output_path.write_text(buf.getvalue(), encoding="utf-8")
        logger.debug("Wrote customers.csv with %d rows", len(customers))

    def write_counts(self, counts: CountsJson, output_path: Path) -> None:
        """Write aggregate counts to ``counts.json``.

        Parameters
        ----------
        counts:
            Aggregate counts structure.
        output_path:
            Destination path for the JSON file.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(counts.model_dump(), indent=2), encoding="utf-8")
        logger.debug("Wrote counts.json")
