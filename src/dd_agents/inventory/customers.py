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

log = logging.getLogger("dd_agents.inventory.customers")


class CustomerRegistryBuilder:
    """Parses the data room directory hierarchy to identify customer folders.

    Assumes the convention ``data_room/group/customer/files``:
      - Top-level directories are *groups* (business units, portfolios, etc.).
      - Second-level directories are *customer folders*.
      - Files directly in the root or in a group dir are reference files.
    """

    def build(
        self,
        data_room_path: Path,
        files: list[FileEntry],
    ) -> tuple[list[CustomerEntry], CountsJson]:
        """Build the customer registry and aggregate counts.

        Parameters
        ----------
        data_room_path:
            Root of the data room.
        files:
            Discovered file entries from :class:`FileDiscovery`.

        Returns
        -------
        tuple[list[CustomerEntry], CountsJson]
            The customer list and the aggregate counts structure.
        """
        Path(data_room_path)

        # Bucket files by group/customer
        customer_files: dict[tuple[str, str], list[str]] = defaultdict(list)
        reference_file_paths: list[str] = []
        ext_counts: dict[str, int] = defaultdict(int)
        group_file_counts: dict[str, int] = defaultdict(int)
        group_customer_names: dict[str, set[str]] = defaultdict(set)

        for entry in files:
            parts = PurePosixPath(entry.path).parts

            # Track extension counts
            suffix = PurePosixPath(entry.path).suffix.lower()
            if suffix:
                ext_counts[suffix] = ext_counts.get(suffix, 0) + 1

            if len(parts) >= 3:
                # group/customer/... pattern
                group = parts[0]
                customer = parts[1]
                customer_files[(group, customer)].append(entry.path)
                group_file_counts[group] += 1
                group_customer_names[group].add(customer)
            else:
                # Root-level or group-level file => reference
                reference_file_paths.append(entry.path)
                if len(parts) >= 2:
                    group_file_counts[parts[0]] += 1

        # Build CustomerEntry list
        customers: list[CustomerEntry] = []
        for (group, customer_name), file_paths in sorted(customer_files.items()):
            try:
                safe_name = customer_safe_name(customer_name)
            except ValueError:
                log.warning("Could not compute safe_name for %r -- skipping", customer_name)
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

        log.info(
            "Registry: %d customers in %d groups, %d reference files, %d total files",
            counts.total_customers,
            len(customers_by_group),
            counts.total_reference_files,
            counts.total_files,
        )
        return customers, counts

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

        output_path.write_text(buf.getvalue())
        log.debug("Wrote customers.csv with %d rows", len(customers))

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
        output_path.write_text(json.dumps(counts.model_dump(), indent=2))
        log.debug("Wrote counts.json")
