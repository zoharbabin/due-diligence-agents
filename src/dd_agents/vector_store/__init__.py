"""dd_agents.vector_store subpackage.

Provides an optional ChromaDB-backed vector store and a document chunker
for embedding-based search.  If ChromaDB is not installed, no-op stub
classes are exported so that callers never need to guard imports.
"""

from __future__ import annotations

import logging
from typing import Any

from dd_agents.vector_store.embeddings import DocumentChunker

log = logging.getLogger("dd_agents.vector_store")

# Conditional VectorStore export
try:
    from dd_agents.vector_store.store import CHROMADB_AVAILABLE, VectorStore
except Exception:  # pragma: no cover
    CHROMADB_AVAILABLE = False

    class VectorStore:  # type: ignore[no-redef]
        """No-op stub for VectorStore when ChromaDB is unavailable."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            log.warning("VectorStore stub: chromadb is not installed. Install with: pip install chromadb")

        def add_documents(self, documents: list[dict[str, Any]]) -> int:
            return 0

        def search(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
            return []

        def delete_collection(self) -> bool:
            return True

        @property
        def is_available(self) -> bool:
            return False


__all__ = [
    "CHROMADB_AVAILABLE",
    "DocumentChunker",
    "VectorStore",
]
