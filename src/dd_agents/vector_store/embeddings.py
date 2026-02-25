"""DocumentChunker -- splits extracted text into overlapping chunks.

Each chunk is annotated with its positional metadata so it can be
stored in a vector store and traced back to the original document.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class DocumentChunker:
    """Split documents into overlapping text chunks for vector embedding.

    Parameters
    ----------
    chunk_size:
        Maximum number of characters per chunk (default 1000).
    overlap:
        Number of overlapping characters between consecutive chunks
        (default 200).
    """

    def __init__(
        self,
        chunk_size: int = 1000,
        overlap: int = 200,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if overlap < 0:
            raise ValueError("overlap must be non-negative")
        if overlap >= chunk_size:
            raise ValueError("overlap must be less than chunk_size")

        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk_document(
        self,
        text: str,
        chunk_size: int | None = None,
        overlap: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Split *text* into overlapping chunks.

        Parameters
        ----------
        text:
            Full document text to split.
        chunk_size:
            Override the instance default chunk size for this call.
        overlap:
            Override the instance default overlap for this call.
        metadata:
            Optional metadata dict to attach to every chunk (merged with
            positional metadata).

        Returns
        -------
        list[dict]
            Each dict has keys: ``text``, ``start_char``, ``end_char``,
            ``chunk_index``, and any extra metadata.
        """
        cs = chunk_size if chunk_size is not None else self.chunk_size
        ov = overlap if overlap is not None else self.overlap
        base_meta = metadata or {}

        if not text:
            return []

        chunks: list[dict[str, Any]] = []
        start = 0
        chunk_index = 0
        text_len = len(text)

        while start < text_len:
            end = min(start + cs, text_len)
            chunk_text = text[start:end]

            # Try to break at a word boundary if we're not at the end
            if end < text_len and not text[end - 1].isspace():
                # Look back for the last space within the chunk
                last_space = chunk_text.rfind(" ")
                if last_space > cs // 2:
                    # Only break at word boundary if we keep at least
                    # half the chunk size
                    end = start + last_space + 1
                    chunk_text = text[start:end]

            chunk_meta = {
                **base_meta,
                "text": chunk_text,
                "start_char": start,
                "end_char": end,
                "chunk_index": chunk_index,
            }
            chunks.append(chunk_meta)

            # If we've reached the end of the text, stop
            if end >= text_len:
                break

            # Advance by (chunk_size - overlap), but at least 1 character
            step = max(cs - ov, 1)
            start += step
            chunk_index += 1

        logger.debug(
            "Chunked document: %d chars -> %d chunks (size=%d, overlap=%d)",
            text_len,
            len(chunks),
            cs,
            ov,
        )
        return chunks

    def chunk_documents(
        self,
        documents: list[dict[str, Any]],
        text_key: str = "text",
        chunk_size: int | None = None,
        overlap: int | None = None,
    ) -> list[dict[str, Any]]:
        """Convenience method to chunk a list of document dicts.

        Each document dict must contain at least a *text_key* field.
        All other fields are preserved as metadata on each chunk.

        Parameters
        ----------
        documents:
            List of dicts, each with at least a ``text`` field.
        text_key:
            The key in each dict that contains the text to chunk.
        chunk_size:
            Override the instance default chunk size.
        overlap:
            Override the instance default overlap.

        Returns
        -------
        list[dict]
            Flat list of all chunks from all documents.
        """
        all_chunks: list[dict[str, Any]] = []
        for doc_idx, doc in enumerate(documents):
            text = doc.get(text_key, "")
            if not text:
                continue

            # Build metadata from all keys except the text key
            meta = {k: v for k, v in doc.items() if k != text_key}
            meta["source_doc_index"] = doc_idx

            chunks = self.chunk_document(
                text=text,
                chunk_size=chunk_size,
                overlap=overlap,
                metadata=meta,
            )
            all_chunks.extend(chunks)

        return all_chunks
