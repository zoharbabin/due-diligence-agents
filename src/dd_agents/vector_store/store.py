"""VectorStore -- optional ChromaDB-backed vector store for document search.

All methods gracefully handle the case where ChromaDB is not installed,
logging a warning and returning empty results or no-op.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

try:
    import chromadb
    from chromadb.config import Settings

    CHROMADB_AVAILABLE = True
except ImportError:  # pragma: no cover
    chromadb = None
    Settings = None
    CHROMADB_AVAILABLE = False


class VectorStore:
    """Thin wrapper around a ChromaDB collection.

    Parameters
    ----------
    collection_name:
        Name of the ChromaDB collection to create or load.
    persist_dir:
        Directory for ChromaDB persistence.  When ``None`` an in-memory
        client is used (useful for tests).
    """

    def __init__(
        self,
        collection_name: str = "dd_documents",
        persist_dir: str | None = None,
    ) -> None:
        self.collection_name = collection_name
        self.persist_dir = persist_dir
        self._client: Any = None
        self._collection: Any = None

        if not CHROMADB_AVAILABLE:
            logger.warning(
                "chromadb is not installed -- VectorStore will operate as a no-op. Install with: pip install chromadb"
            )
            return

        try:
            if persist_dir:
                self._client = chromadb.PersistentClient(path=persist_dir)
            else:
                self._client = chromadb.Client()

            self._collection = self._client.get_or_create_collection(
                name=collection_name,
            )
            logger.info(
                "VectorStore initialized: collection=%s, persist_dir=%s",
                collection_name,
                persist_dir or "<in-memory>",
            )
        except Exception:
            logger.exception("Failed to initialize ChromaDB -- VectorStore disabled")
            self._client = None
            self._collection = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_documents(self, documents: list[dict[str, Any]]) -> int:
        """Add extracted text chunks with metadata to the vector store.

        Parameters
        ----------
        documents:
            List of dicts, each containing at minimum:
            - ``text`` (str): The document text to embed.
            - ``metadata`` (dict, optional): Arbitrary metadata.
            - ``id`` (str, optional): Unique document ID.

        Returns
        -------
        int
            Number of documents successfully added.
        """
        if self._collection is None:
            logger.debug("VectorStore.add_documents: no-op (ChromaDB unavailable)")
            return 0

        try:
            ids: list[str] = []
            texts: list[str] = []
            metadatas: list[dict[str, str | int | float | bool]] = []

            for doc in documents:
                text = doc.get("text", "")
                if not text:
                    continue

                doc_id = doc.get("id", str(uuid.uuid4()))
                metadata = doc.get("metadata", {})

                # ChromaDB requires metadata values to be str/int/float/bool
                clean_meta: dict[str, str | int | float | bool] = {}
                for k, v in metadata.items():
                    if isinstance(v, (str, int, float, bool)):
                        clean_meta[k] = v
                    else:
                        clean_meta[k] = str(v)

                ids.append(doc_id)
                texts.append(text)
                metadatas.append(clean_meta)

            if not ids:
                return 0

            self._collection.add(
                ids=ids,
                documents=texts,
                metadatas=metadatas,
            )
            logger.debug("Added %d documents to collection %s", len(ids), self.collection_name)
            return len(ids)

        except Exception:
            logger.exception("Failed to add documents to VectorStore")
            return 0

    def search(
        self,
        query: str,
        top_k: int = 5,
        distance_threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        """Search the vector store for documents matching *query*.

        Parameters
        ----------
        query:
            Natural-language query string.
        top_k:
            Maximum number of results to return.
        distance_threshold:
            Optional maximum distance for results.  Results farther than
            this threshold are filtered out.

        Returns
        -------
        list[dict]
            Each dict contains ``text``, ``metadata``, ``distance``, and ``id``.
        """
        if self._collection is None:
            logger.debug("VectorStore.search: no-op (ChromaDB unavailable)")
            return []

        try:
            results = self._collection.query(
                query_texts=[query],
                n_results=top_k,
            )

            matches: list[dict[str, Any]] = []
            if not results or not results.get("documents"):
                return matches

            docs = results["documents"][0]
            metadatas = results.get("metadatas", [[]])[0]
            distances = results.get("distances", [[]])[0]
            ids = results.get("ids", [[]])[0]

            for i, text in enumerate(docs):
                distance = distances[i] if i < len(distances) else 0.0
                if distance_threshold is not None and distance > distance_threshold:
                    continue

                matches.append(
                    {
                        "text": text,
                        "metadata": metadatas[i] if i < len(metadatas) else {},
                        "distance": distance,
                        "id": ids[i] if i < len(ids) else "",
                    }
                )

            return matches

        except Exception:
            logger.exception("VectorStore search failed")
            return []

    def delete_collection(self) -> bool:
        """Delete the entire collection from the store.

        Returns
        -------
        bool
            ``True`` if deletion succeeded or no-op, ``False`` on error.
        """
        if self._client is None:
            logger.debug("VectorStore.delete_collection: no-op (ChromaDB unavailable)")
            return True

        try:
            self._client.delete_collection(name=self.collection_name)
            self._collection = None
            logger.info("Deleted collection %s", self.collection_name)
            return True
        except Exception:
            logger.exception("Failed to delete collection %s", self.collection_name)
            return False

    @property
    def is_available(self) -> bool:
        """True if the vector store backend is operational."""
        return self._collection is not None
