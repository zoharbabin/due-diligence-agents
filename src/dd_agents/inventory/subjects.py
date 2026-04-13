"""Subject registry builder: parse directory structure into subjects.csv and counts.json."""

from __future__ import annotations

import csv
import io
import json
import logging
from collections import defaultdict
from pathlib import Path, PurePosixPath

from dd_agents.models.inventory import CountsJson, FileEntry, SubjectEntry
from dd_agents.utils.naming import subject_safe_name

logger = logging.getLogger(__name__)


class SubjectRegistryBuilder:
    """Parses the data room directory hierarchy to identify subject folders.

    Supports two layouts:

    1. **Three-level** (``data_room/group/subject/files``):
       Top-level dirs are *groups*, second-level dirs are *subject folders*.

    2. **Two-level** (``data_room/subject/files``):
       Top-level dirs are *subjects*.  Files directly under a top-level
       dir are assigned to that dir as both group and subject.

    Files in the data room root are always treated as reference files.
    """

    def build(
        self,
        data_room_path: Path,
        files: list[FileEntry],
        *,
        layout: str = "auto",
        target_name: str = "",
    ) -> tuple[list[SubjectEntry], CountsJson]:
        """Build the subject registry and aggregate counts.

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
            categories, not subjects).
        target_name:
            Display name for the single target entity.  Required when
            *layout* is ``"single_target"``.

        Returns
        -------
        tuple[list[SubjectEntry], CountsJson]
            The subject list and the aggregate counts structure.
        """
        if layout == "single_target":
            return self._build_single_target(files, target_name)
        # Bucket files by group/subject
        subject_files: dict[tuple[str, str], list[str]] = defaultdict(list)
        reference_file_paths: list[str] = []
        ext_counts: dict[str, int] = defaultdict(int)
        group_file_counts: dict[str, int] = defaultdict(int)
        group_subject_names: dict[str, set[str]] = defaultdict(set)

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
                # Two-level layout: the top-level dir IS the subject.
                # All files (direct and in subfolders) belong to it.
                subject_files[(top_dir, top_dir)].append(entry.path)
                group_file_counts[top_dir] += 1
                group_subject_names[top_dir].add(top_dir)
            elif len(parts) >= 3:
                # Pure three-level layout: group/subject/files
                group = parts[0]
                subj = parts[1]
                subject_files[(group, subj)].append(entry.path)
                group_file_counts[group] += 1
                group_subject_names[group].add(subj)
            else:
                # File in a group dir that has no direct files but the
                # path is only 2 parts — treat as reference.
                reference_file_paths.append(entry.path)
                group_file_counts[top_dir] += 1

        # Build SubjectEntry list
        subjects: list[SubjectEntry] = []
        for (group, subject_name), file_paths in sorted(subject_files.items()):
            try:
                safe_name = subject_safe_name(subject_name)
            except ValueError:
                logger.warning("Could not compute safe_name for %r -- skipping", subject_name)
                continue

            subject_entry = SubjectEntry(
                group=group,
                name=subject_name,
                safe_name=safe_name,
                path=f"{group}/{subject_name}",
                file_count=len(file_paths),
                files=sorted(file_paths),
            )
            subjects.append(subject_entry)

        subjects.sort(key=lambda s: (s.group, s.name))

        # Build CountsJson
        subjects_by_group: dict[str, int] = {g: len(names) for g, names in group_subject_names.items()}

        counts = CountsJson(
            total_files=len(files),
            total_subjects=len(subjects),
            total_reference_files=len(reference_file_paths),
            files_by_extension=dict(sorted(ext_counts.items())),
            files_by_group=dict(sorted(group_file_counts.items())),
            subjects_by_group=dict(sorted(subjects_by_group.items())),
        )

        logger.info(
            "Registry: %d subjects in %d groups, %d reference files, %d total files",
            counts.total_subjects,
            len(subjects_by_group),
            counts.total_reference_files,
            counts.total_files,
        )
        return subjects, counts

    def _build_single_target(
        self,
        files: list[FileEntry],
        target_name: str,
    ) -> tuple[list[SubjectEntry], CountsJson]:
        """Build registry for a single-target acquisition data room.

        All files are assigned to one subject entity (the target).
        No reference files are produced — every file belongs to the target.
        """
        if not target_name:
            target_name = "Target"
            logger.warning("single_target layout with empty target_name — using 'Target'")

        try:
            safe_name = subject_safe_name(target_name)
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

        subject_entry = SubjectEntry(
            group=safe_name,
            name=target_name,
            safe_name=safe_name,
            path=".",
            file_count=len(all_paths),
            files=sorted(all_paths),
        )

        counts = CountsJson(
            total_files=len(files),
            total_subjects=1,
            total_reference_files=0,
            files_by_extension=dict(sorted(ext_counts.items())),
            files_by_group={safe_name: len(files)},
            subjects_by_group={safe_name: 1},
        )

        logger.info(
            "Registry (single_target): 1 subject '%s', %d files",
            target_name,
            len(files),
        )
        return [subject_entry], counts

    def write_csv(self, subjects: list[SubjectEntry], output_path: Path) -> None:
        """Write the subject registry to ``subjects.csv``.

        Parameters
        ----------
        subjects:
            Subject entries to write.
        output_path:
            Destination path for the CSV file.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["group", "name", "safe_name", "path", "file_count", "file_list"])
        for c in subjects:
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
        logger.debug("Wrote subjects.csv with %d rows", len(subjects))

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
