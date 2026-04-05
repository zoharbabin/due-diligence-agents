"""Tests for dd_agents.vector_store -- VectorStore and DocumentChunker."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from dd_agents.vector_store.embeddings import DocumentChunker

# ===========================================================================
# DocumentChunker
# ===========================================================================


class TestDocumentChunker:
    """Tests for DocumentChunker."""

    def test_default_params(self) -> None:
        c = DocumentChunker()
        assert c.chunk_size == 1000
        assert c.overlap == 200

    def test_custom_params(self) -> None:
        c = DocumentChunker(chunk_size=500, overlap=50)
        assert c.chunk_size == 500
        assert c.overlap == 50

    def test_invalid_chunk_size(self) -> None:
        with pytest.raises(ValueError, match="chunk_size must be positive"):
            DocumentChunker(chunk_size=0)

    def test_negative_overlap(self) -> None:
        with pytest.raises(ValueError, match="overlap must be non-negative"):
            DocumentChunker(overlap=-1)

    def test_overlap_ge_chunk_size(self) -> None:
        with pytest.raises(ValueError, match="overlap must be less than chunk_size"):
            DocumentChunker(chunk_size=100, overlap=100)

    def test_empty_text(self) -> None:
        c = DocumentChunker()
        assert c.chunk_document("") == []

    def test_short_text_single_chunk(self) -> None:
        c = DocumentChunker(chunk_size=100, overlap=10)
        chunks = c.chunk_document("hello world")
        assert len(chunks) == 1
        assert chunks[0]["text"] == "hello world"
        assert chunks[0]["start_char"] == 0
        assert chunks[0]["chunk_index"] == 0

    def test_longer_text_multiple_chunks(self) -> None:
        c = DocumentChunker(chunk_size=10, overlap=2)
        text = "a" * 25
        chunks = c.chunk_document(text)
        assert len(chunks) >= 3
        # All text is covered
        assert chunks[-1]["end_char"] == 25

    def test_metadata_propagated(self) -> None:
        c = DocumentChunker(chunk_size=100, overlap=10)
        chunks = c.chunk_document("test", metadata={"file": "a.pdf"})
        assert chunks[0]["file"] == "a.pdf"

    def test_chunk_documents_batch(self) -> None:
        c = DocumentChunker(chunk_size=100, overlap=10)
        docs = [
            {"text": "short doc one"},
            {"text": "short doc two"},
            {"text": ""},  # empty — should be skipped
        ]
        chunks = c.chunk_documents(docs)
        assert len(chunks) == 2
        assert chunks[0]["source_doc_index"] == 0
        assert chunks[1]["source_doc_index"] == 1

    def test_override_params_in_call(self) -> None:
        c = DocumentChunker(chunk_size=100, overlap=10)
        text = "a" * 50
        chunks = c.chunk_document(text, chunk_size=20, overlap=5)
        assert len(chunks) >= 3


# ===========================================================================
# VectorStore (with ChromaDB mocked)
# ===========================================================================


class TestVectorStoreNoChromaDB:
    """Tests when ChromaDB is NOT installed."""

    def test_noop_when_unavailable(self) -> None:
        with patch("dd_agents.vector_store.store.CHROMADB_AVAILABLE", False):
            from dd_agents.vector_store.store import VectorStore

            vs = VectorStore.__new__(VectorStore)
            vs.collection_name = "test"
            vs.persist_dir = None
            vs._client = None
            vs._collection = None

            assert vs.add_documents([{"text": "hello"}]) == 0
            assert vs.search("hello") == []
            assert vs.delete_collection() is True


class TestVectorStoreWithMock:
    """Tests with a mock ChromaDB collection."""

    def _make_store(self) -> Any:
        """Create a VectorStore with mocked internals."""
        from dd_agents.vector_store.store import VectorStore

        vs = VectorStore.__new__(VectorStore)
        vs.collection_name = "test"
        vs.persist_dir = None
        vs._client = MagicMock()
        vs._collection = MagicMock()
        return vs

    def test_add_documents_calls_collection(self) -> None:
        vs = self._make_store()
        count = vs.add_documents(
            [
                {"text": "hello", "id": "1", "metadata": {"file": "a.pdf"}},
                {"text": "world", "id": "2"},
            ]
        )
        assert count == 2
        vs._collection.add.assert_called_once()
        call_args = vs._collection.add.call_args
        assert len(call_args.kwargs["ids"]) == 2

    def test_add_empty_text_skipped(self) -> None:
        vs = self._make_store()
        count = vs.add_documents([{"text": ""}])
        assert count == 0

    def test_add_no_collection(self) -> None:
        vs = self._make_store()
        vs._collection = None
        assert vs.add_documents([{"text": "hello"}]) == 0

    def test_search_returns_results(self) -> None:
        vs = self._make_store()
        vs._collection.query.return_value = {
            "documents": [["doc1", "doc2"]],
            "metadatas": [[{"file": "a.pdf"}, {}]],
            "distances": [[0.1, 0.5]],
            "ids": [["id1", "id2"]],
        }
        results = vs.search("query", top_k=2)
        assert len(results) == 2
        assert results[0]["text"] == "doc1"
        assert results[0]["distance"] == 0.1
        assert results[1]["metadata"] == {}

    def test_search_distance_threshold(self) -> None:
        vs = self._make_store()
        vs._collection.query.return_value = {
            "documents": [["doc1", "doc2"]],
            "metadatas": [[{}, {}]],
            "distances": [[0.1, 0.9]],
            "ids": [["id1", "id2"]],
        }
        results = vs.search("query", distance_threshold=0.5)
        assert len(results) == 1

    def test_search_no_collection(self) -> None:
        vs = self._make_store()
        vs._collection = None
        assert vs.search("hello") == []

    def test_search_empty_results(self) -> None:
        vs = self._make_store()
        vs._collection.query.return_value = {}
        assert vs.search("hello") == []

    def test_delete_collection(self) -> None:
        vs = self._make_store()
        assert vs.delete_collection() is True
        vs._client.delete_collection.assert_called_once_with(name="test")
        assert vs._collection is None

    def test_delete_no_client(self) -> None:
        vs = self._make_store()
        vs._client = None
        assert vs.delete_collection() is True

    def test_metadata_coercion(self) -> None:
        """Non-scalar metadata values should be coerced to strings."""
        vs = self._make_store()
        vs.add_documents(
            [
                {
                    "text": "hello",
                    "metadata": {"list_val": [1, 2], "str_val": "ok", "int_val": 42},
                }
            ]
        )
        call_args = vs._collection.add.call_args
        meta = call_args.kwargs["metadatas"][0]
        assert meta["list_val"] == "[1, 2]"
        assert meta["str_val"] == "ok"
        assert meta["int_val"] == 42
