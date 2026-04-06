"""Coordinate index for visual grounding of findings.

Stores block-level coordinate data from pymupdf extraction and
provides reverse lookup from text quotes to page positions.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class TextBlock(BaseModel):
    """A single text block with its page coordinates."""

    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    text: str = ""


class CoordinateIndex:
    """Stores and queries block-level coordinates for extracted documents.

    Supports:
    - Indexing coordinates per file
    - Finding the block that best matches a given quote
    - Persistence to/from JSON
    """

    def __init__(self) -> None:
        self._index: dict[str, list[TextBlock]] = {}

    def add_file(self, file_path: str, blocks: list[TextBlock]) -> None:
        """Add coordinate data for a file."""
        self._index[file_path] = list(blocks)

    def get_blocks(self, file_path: str) -> list[TextBlock]:
        """Return all blocks for a file, or empty list if not indexed."""
        return list(self._index.get(file_path, []))

    @property
    def files(self) -> list[str]:
        """Return all indexed file paths."""
        return sorted(self._index.keys())

    def find_quote(self, file_path: str, quote: str) -> TextBlock | None:
        """Find the block that best matches *quote* in *file_path*.

        Uses substring matching.  Returns the first block whose text
        contains *quote* (case-insensitive), or ``None``.
        """
        blocks = self._index.get(file_path, [])
        if not blocks:
            return None

        quote_lower = quote.strip().lower() if quote else ""
        if not quote_lower:
            return None
        for block in blocks:
            if quote_lower in block.text.lower():
                return block
        return None

    def save(self, path: Path) -> None:
        """Persist the index to a JSON file."""
        data: dict[str, list[dict[str, Any]]] = {}
        for fp, blocks in self._index.items():
            data[fp] = [b.model_dump() for b in blocks]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> CoordinateIndex:
        """Load the index from a JSON file."""
        idx = cls()
        if not path.exists():
            return idx
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            for fp, block_list in raw.items():
                idx._index[fp] = [TextBlock.model_validate(b) for b in block_list]
        except (json.JSONDecodeError, OSError, KeyError) as exc:
            logger.warning("Failed to load coordinate index from %s: %s", path, exc)
        return idx
