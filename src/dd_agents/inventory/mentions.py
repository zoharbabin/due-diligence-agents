"""Subject-mention index builder.

Scans reference file extracted text for subject name mentions using simple
substring matching.  Detects ghost subjects (mentioned in reference files
but no folder) and phantom contracts (folder exists but not in reference files).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from dd_agents.models.inventory import (
    ReferenceFile,
    SubjectMention,
    SubjectMentionIndex,
)

logger = logging.getLogger(__name__)


class SubjectMentionBuilder:
    """Scans reference file text for subject name mentions."""

    def build(
        self,
        reference_files: list[ReferenceFile],
        subject_names: dict[str, str],
        text_dir: Path | None = None,
    ) -> SubjectMentionIndex:
        """Build the subject-mention index.

        Parameters
        ----------
        reference_files:
            Classified reference files (with ``text_path`` where available).
        subject_names:
            Mapping of ``subject_safe_name`` to display name.
        text_dir:
            Optional base directory for resolving ``text_path`` values.

        Returns
        -------
        SubjectMentionIndex
            Index with matches, ghost subjects, and phantom contracts.
        """
        # Track which subjects are mentioned and in which files
        mentions: dict[str, list[str]] = {safe: [] for safe in subject_names}
        # Track names found in references that don't match any subject
        all_found_names: set[str] = set()

        for ref_file in reference_files:
            text = self._load_text(ref_file, text_dir)
            if not text:
                continue

            text_lower = text.lower()

            for safe_name, display_name in subject_names.items():
                # Simple substring matching on the display name
                if display_name.lower() in text_lower:
                    mentions[safe_name].append(ref_file.file_path)
                    all_found_names.add(safe_name)

        # Build SubjectMention entries
        mention_entries: list[SubjectMention] = []
        subjects_with_mentions: set[str] = set()

        for safe_name, ref_paths in sorted(mentions.items()):
            if ref_paths:
                subjects_with_mentions.add(safe_name)
                unique_paths = sorted(set(ref_paths))
                mention_entries.append(
                    SubjectMention(
                        subject_name=subject_names[safe_name],
                        subject_safe_name=safe_name,
                        reference_files=unique_paths,
                        mention_count=len(unique_paths),
                    )
                )

        # Detect ghost subjects: mentioned in ref files but no subject folders
        # (This would require the external caller to pass ref-file-only names.
        #  Here we record subjects_mentioned from ref_file metadata.)
        ghost_subjects: list[str] = []
        for ref_file in reference_files:
            for name in ref_file.subjects_mentioned:
                name_lower = name.lower()
                if not any(name_lower == dn.lower() for dn in subject_names.values()) and name not in ghost_subjects:
                    ghost_subjects.append(name)

        # Detect phantom contracts: folder exists but never mentioned in refs
        phantom_contracts: list[str] = [
            subject_names[safe] for safe in sorted(subject_names) if safe not in subjects_with_mentions
        ]

        index = SubjectMentionIndex(
            matches=mention_entries,
            unmatched_in_reference=sorted(ghost_subjects),
            subjects_without_reference_data=sorted(phantom_contracts),
        )

        logger.info(
            "Mention index: %d subjects mentioned, %d ghosts, %d phantoms",
            len(mention_entries),
            len(ghost_subjects),
            len(phantom_contracts),
        )
        return index

    def write_json(self, index: SubjectMentionIndex, output_path: Path) -> None:
        """Write the subject-mention index to ``subject_mentions.json``.

        Parameters
        ----------
        index:
            Mention index to persist.
        output_path:
            Destination file path.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(index.model_dump(), indent=2), encoding="utf-8")
        logger.debug("Wrote subject_mentions.json")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_text(self, ref_file: ReferenceFile, text_dir: Path | None) -> str:
        """Load the extracted text for a reference file, if available."""
        if ref_file.text_path:
            path = Path(ref_file.text_path)
            if text_dir and not path.is_absolute():
                path = text_dir / path
            if path.exists():
                try:
                    return path.read_text(errors="replace")
                except OSError:
                    return ""
        return ""
