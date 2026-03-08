"""File discovery: walk the data room, build tree.txt and files.txt."""

from __future__ import annotations

import fnmatch
import logging
import os
from pathlib import Path
from typing import Any

from dd_agents.models.inventory import FileEntry
from dd_agents.utils.constants import DD_DIR, EXCLUDE_PATTERNS

logger = logging.getLogger(__name__)


class FileDiscovery:
    """Walks a data room directory and produces structured file listings."""

    def discover(
        self,
        data_room_path: Path,
        exclude_patterns: list[str] | None = None,
    ) -> list[FileEntry]:
        """Discover all files in the data room, excluding system artefacts.

        Parameters
        ----------
        data_room_path:
            Root of the data room to scan.
        exclude_patterns:
            Glob-style patterns to exclude.  Defaults to
            :data:`dd_agents.utils.constants.EXCLUDE_PATTERNS`.

        Returns
        -------
        list[FileEntry]
            Sorted list of discovered files.
        """
        data_room = Path(data_room_path).resolve()
        patterns = exclude_patterns if exclude_patterns is not None else EXCLUDE_PATTERNS

        entries: list[FileEntry] = []

        for dirpath, dirnames, filenames in os.walk(data_room):
            rel_dir = os.path.relpath(dirpath, data_room)

            # Skip the _dd artifacts directory entirely
            if rel_dir == DD_DIR or rel_dir.startswith(DD_DIR + os.sep):
                dirnames.clear()
                continue

            # Prune excluded directories in-place
            dirnames[:] = [d for d in dirnames if not _matches_any(d, patterns) and d != DD_DIR]

            for fname in sorted(filenames):
                if _matches_any(fname, patterns):
                    continue

                full_path = Path(dirpath) / fname
                rel_path = str(full_path.relative_to(data_room))

                try:
                    st = full_path.stat()
                    size = st.st_size
                    mtime = st.st_mtime
                except OSError:
                    size = 0
                    mtime = 0.0

                mtime_iso = ""
                if mtime > 0:
                    try:
                        import datetime as _dt  # noqa: TC004

                        mtime_iso = _dt.datetime.fromtimestamp(mtime, tz=_dt.UTC).strftime("%Y-%m-%d")
                    except (OSError, ValueError):
                        mtime_iso = ""

                entries.append(
                    FileEntry(
                        path=rel_path,
                        size=size,
                        mtime=mtime,
                        mtime_iso=mtime_iso,
                    )
                )

        entries.sort(key=lambda e: e.path)
        logger.info("Discovered %d files in %s", len(entries), data_room)
        return entries

    def write_tree(self, files: list[FileEntry], output_path: Path) -> None:
        """Write an indented directory tree listing (``tree.txt``).

        Parameters
        ----------
        files:
            Discovered file entries.
        output_path:
            Destination path for the tree file.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Build tree structure
        tree: dict[str, Any] = {}
        for entry in files:
            parts = Path(entry.path).parts
            node = tree
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = None  # leaf file

        lines: list[str] = []
        _render_tree(tree, lines, prefix="")

        output_path.write_text("\n".join(lines) + "\n")
        logger.debug("Wrote tree.txt with %d lines", len(lines))

    def write_files_list(self, files: list[FileEntry], output_path: Path) -> None:
        """Write a flat sorted file list (``files.txt``).

        Parameters
        ----------
        files:
            Discovered file entries.
        output_path:
            Destination path for the file list.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        content = "\n".join(entry.path for entry in files) + "\n"
        output_path.write_text(content)
        logger.debug("Wrote files.txt with %d entries", len(files))


def _matches_any(name: str, patterns: list[str]) -> bool:
    """Check whether *name* matches any of the exclude patterns."""
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def _render_tree(node: dict[str, Any], lines: list[str], prefix: str) -> None:
    """Recursively render a directory tree into a list of indented lines."""
    items = sorted(node.items(), key=lambda kv: (kv[1] is not None, kv[0]))
    for i, (name, children) in enumerate(items):
        is_last = i == len(items) - 1
        connector = "└── " if is_last else "├── "
        lines.append(f"{prefix}{connector}{name}")
        if children is not None:
            extension = "    " if is_last else "│   "
            _render_tree(children, lines, prefix + extension)
