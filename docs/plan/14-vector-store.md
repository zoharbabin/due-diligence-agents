# 14 — Vector Store Integration (Optional)

## Overview

ChromaDB is an OPTIONAL enhancement, licensed under Apache 2.0. The system must function fully without it. File-based search (Grep, keyword matching) is sufficient at the typical forensic DD scale of 400 documents and 20,000 text chunks. ChromaDB adds cross-document semantic discovery for larger data rooms or specialized query patterns.

Cross-reference: `01-architecture-decisions.md` ADR-03 (ChromaDB optional), `03-project-structure.md` (directory layout), `05-orchestrator.md` (pipeline steps).

---

## 1. Decision Criteria

### 1.1 When ChromaDB Is NOT Needed

The default mode. File-based search handles:
- Entity resolution: deterministic 6-pass cascading matcher (no embeddings needed)
- Gap detection: pattern-based and checklist-based methods
- Cross-reference reconciliation: keyword matching + entity resolution
- Reference file lookup: pre-classified in `reference_files.json` with agent routing

At 400 documents / 20,000 chunks, keyword search via Grep completes in milliseconds. No vector DB overhead is justified.

### 1.2 When to Enable ChromaDB

Enable when any of these conditions apply:
- **Scale**: >500 documents in the data room
- **Semantic search**: Cross-document semantic search is needed (e.g., "find all clauses similar to this non-compete clause")
- **Pattern discovery**: Identifying common clause patterns across customers for benchmarking
- **Custom queries**: Users need ad-hoc semantic queries not covered by the standard pipeline

### 1.3 Configuration

ChromaDB is enabled via `deal-config.json`:

```json
{
  "execution": {
    "chromadb_enabled": false
  }
}
```

Or via CLI flag:

```bash
dd-agents run /path/to/data-room/ --chromadb
```

---

## 2. Architecture

### 2.1 Integration Point

ChromaDB is populated AFTER extraction (step 5) and BEFORE agents are spawned (step 16). It does NOT replace file-based extraction -- agents still receive pre-extracted text from `_dd/forensic-dd/index/text/`. ChromaDB adds an additional cross-document discovery channel.

Vector store population runs as a sub-step of step 5 (extraction). After each file is extracted, if ChromaDB is enabled, the extracted text is chunked and inserted. This is not a separate pipeline step -- it piggybacks on extraction to avoid a second pass over all files.

```
Step 5:  Bulk pre-extraction  ──── writes to index/text/
         (ChromaDB indexing)  ──── reads from index/text/, writes to ChromaDB (if enabled)
         ...
Step 16: Spawn specialists    ──── agents use file-based text + optional semantic_search tool
```

### 2.2 Collection Naming

One collection per deal per run, named to prevent collisions:

```
forensic_dd_{deal_slug}_{run_id}
```

Example: `forensic_dd_alpha_acquisition_20260221_093000`

Prior run collections are retained for incremental comparison. Collections are cleaned up when runs are archived.

### 2.3 Storage

ChromaDB runs in persistent mode with storage inside the deal's `_dd/` directory:

```
{data_room}/_dd/forensic-dd/chromadb/
  chroma.sqlite3
  collections/
```

This maintains per-deal isolation (see `13-multi-project.md`).

---

## 3. Chunking Strategy

### 3.1 Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Chunk size | 1000 tokens | Large enough for full clause context, small enough for precise retrieval |
| Overlap | 200 tokens | Ensures clause boundaries are not lost between chunks |
| Separator priority | Section headers > paragraph breaks > sentence breaks | Preserves document structure |

### 3.2 Metadata Per Chunk

Every chunk is stored with rich metadata for filtered retrieval:

```python
# src/dd_agents/vector_store/chunker.py

from pydantic import BaseModel
from typing import Optional


class ChunkMetadata(BaseModel):
    """Metadata attached to each text chunk in ChromaDB."""
    source_file: str          # Original file path (relative to data room)
    text_path: str            # Path to extracted text in index/text/
    customer: str             # Customer name (from directory structure)
    customer_safe_name: str   # Safe name for filtering
    page_number: Optional[int] = None  # Page number if available from extraction
    section: Optional[str] = None      # Section heading if detected
    chunk_index: int          # Position within the document (0-based)
    total_chunks: int         # Total chunks from this document
    file_type: str            # pdf, docx, xlsx, etc.
    category: Optional[str] = None     # reference file category if applicable
```

### 3.3 Chunking Implementation

```python
# src/dd_agents/vector_store/chunker.py

import re
from pathlib import Path


def chunk_document(
    text: str,
    metadata_base: ChunkMetadata,
    chunk_size: int = 1000,
    overlap: int = 200,
) -> list[tuple[str, dict]]:
    """Split a document into overlapping chunks with metadata.

    Returns list of (chunk_text, metadata_dict) tuples.
    """
    # Tokenize (approximate: 1 token ~ 4 chars for English)
    char_chunk_size = chunk_size * 4
    char_overlap = overlap * 4

    # Split on section boundaries first
    sections = _split_on_sections(text)

    chunks = []
    for section_title, section_text in sections:
        # Split section into chunks
        start = 0
        chunk_idx = 0
        while start < len(section_text):
            end = min(start + char_chunk_size, len(section_text))

            # Try to end at a sentence boundary
            if end < len(section_text):
                last_period = section_text.rfind('. ', start + char_chunk_size // 2, end)
                if last_period > start:
                    end = last_period + 2

            chunk_text = section_text[start:end].strip()
            if chunk_text:
                meta = metadata_base.model_copy(update={
                    "section": section_title,
                    "chunk_index": len(chunks),
                })
                chunks.append((chunk_text, meta.model_dump()))

            start = end - char_overlap
            chunk_idx += 1

    # Update total_chunks for all chunks
    for _, meta in chunks:
        meta["total_chunks"] = len(chunks)

    return chunks


def _split_on_sections(text: str) -> list[tuple[str, str]]:
    """Split text on markdown-style headers."""
    pattern = re.compile(r'^(#{1,3}\s+.+)$', re.MULTILINE)
    parts = pattern.split(text)

    sections = []
    current_title = None
    for part in parts:
        if pattern.match(part):
            current_title = part.strip('# \n')
        else:
            sections.append((current_title, part))

    if not sections:
        sections = [(None, text)]

    return sections
```

---

## 4. ChromaDB Client

### 4.1 Initialization

```python
# src/dd_agents/vector_store/client.py

from pathlib import Path
from typing import Optional

try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False


class VectorStore:
    """Optional ChromaDB integration for cross-document semantic search.

    This class is a no-op if ChromaDB is not installed or not enabled.
    """

    def __init__(
        self,
        project_dir: Path,
        deal_slug: str,
        run_id: str,
        enabled: bool = False,
    ):
        self.enabled = enabled and CHROMADB_AVAILABLE
        self.project_dir = project_dir
        self.collection_name = f"forensic_dd_{deal_slug}_{run_id}"
        self._client = None
        self._collection = None

        if self.enabled and not CHROMADB_AVAILABLE:
            import logging
            logging.getLogger(__name__).warning(
                "ChromaDB enabled in config but not installed. "
                "Install with: pip install dd-agents[vector]"
            )
            self.enabled = False

    def initialize(self):
        """Create ChromaDB client and collection."""
        if not self.enabled:
            return

        persist_dir = self.project_dir / "_dd" / "forensic-dd" / "chromadb"
        persist_dir.mkdir(parents=True, exist_ok=True)

        self._client = chromadb.Client(Settings(
            chroma_db_impl="duckdb+parquet",
            persist_directory=str(persist_dir),
            anonymized_telemetry=False,
        ))

        # Default embedding model: ChromaDB's built-in all-MiniLM-L6-v2
        # (384-dimensional, ~80MB). This is sufficient for contract document
        # similarity. Override via vector_store.embedding_model in
        # deal-config.json.
        self._collection = self._client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def add_chunks(self, chunks: list[tuple[str, dict]]):
        """Add document chunks to the collection.

        Args:
            chunks: List of (text, metadata) tuples from chunk_document().
        """
        if not self.enabled or not self._collection:
            return

        ids = []
        documents = []
        metadatas = []

        for i, (text, meta) in enumerate(chunks):
            chunk_id = (
                f"{meta['customer_safe_name']}_"
                f"{Path(meta['source_file']).stem}_"
                f"{meta['chunk_index']:04d}"
            )
            ids.append(chunk_id)
            documents.append(text)
            metadatas.append(meta)

        # Batch insertion uses try/except per batch (default batch size: 100
        # documents). If a batch fails, individual documents from the failed
        # batch are retried one at a time. Documents that fail individual
        # insertion are logged to extraction_quality.json with
        # vector_store_error: true but do not block the pipeline.
        batch_size = 100
        for start in range(0, len(ids), batch_size):
            end = start + batch_size
            try:
                self._collection.add(
                    ids=ids[start:end],
                    documents=documents[start:end],
                    metadatas=metadatas[start:end],
                )
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    f"Batch insert failed ({start}-{end}), retrying individually: {e}"
                )
                for j in range(start, min(end, len(ids))):
                    try:
                        self._collection.add(
                            ids=[ids[j]],
                            documents=[documents[j]],
                            metadatas=[metadatas[j]],
                        )
                    except Exception as e2:
                        logging.getLogger(__name__).error(
                            f"Individual insert failed for {ids[j]}: {e2}"
                        )

    def search(
        self,
        query: str,
        customer: Optional[str] = None,
        top_k: int = 5,
    ) -> list[dict]:
        """Semantic search across indexed documents.

        Args:
            query: Natural language search query.
            customer: Optional customer_safe_name to filter results.
            top_k: Number of results to return.

        Returns:
            List of dicts with keys: text, metadata, distance.
        """
        if not self.enabled or not self._collection:
            return []

        where_filter = None
        if customer:
            where_filter = {"customer_safe_name": customer}

        results = self._collection.query(
            query_texts=[query],
            n_results=top_k,
            where=where_filter,
        )

        formatted = []
        for i in range(len(results["ids"][0])):
            formatted.append({
                "text": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "distance": results["distances"][0][i] if results.get("distances") else None,
            })

        return formatted

    def cleanup_old_collections(self, keep_latest: int = 2):
        """Remove old collections to save disk space."""
        if not self.enabled or not self._client:
            return

        all_collections = self._client.list_collections()
        prefix = f"forensic_dd_{self.project_dir.name}_"
        matching = sorted(
            [c for c in all_collections if c.name.startswith(prefix)],
            key=lambda c: c.name,
            reverse=True,
        )

        for old_collection in matching[keep_latest:]:
            self._client.delete_collection(old_collection.name)
```

---

## 5. MCP Tool for Agents

When ChromaDB is enabled, agents receive a custom MCP tool to query the vector store.

### 5.1 Tool Definition

```python
# src/dd_agents/tools/semantic_search.py

import json

from claude_agent_sdk import tool
from typing import Optional


def create_semantic_search_tool(vector_store: "VectorStore"):
    """Create the semantic_search MCP tool backed by ChromaDB."""

    @tool(
        name="semantic_search",
        description=(
            "Search across all extracted documents using natural language. "
            "Returns the most semantically similar passages. "
            "Use this to find clauses, terms, or patterns across customers. "
            "Optional: filter by customer name."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query",
                },
                "customer": {
                    "type": "string",
                    "description": "Optional customer_safe_name to filter results",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return (default: 5, max: 20)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    )
    async def semantic_search(args: dict) -> str:
        """The semantic_search MCP tool returns structured JSON:
        {"results": [{"document_id": str, "chunk_id": str, "score": float,
        "text": str, "metadata": {...}}]}. The agent receives this as a
        tool result and can parse it directly.
        """
        query_text = args["query"]
        customer = args.get("customer")
        top_k = min(args.get("top_k", 5), 20)

        results = vector_store.search(
            query=query_text,
            customer=customer,
            top_k=top_k,
        )

        if not results:
            return json.dumps({"results": []})

        structured_results = []
        for r in results:
            meta = r["metadata"]
            structured_results.append({
                "document_id": meta.get("source_file", ""),
                "chunk_id": f"{meta.get('customer_safe_name', '')}_{meta.get('chunk_index', 0):04d}",
                "score": round(1 - r["distance"], 4) if r.get("distance") is not None else None,
                "text": r["text"],
                "metadata": meta,
            })

        return json.dumps({"results": structured_results})

    return semantic_search
```

### 5.2 Tool Registration

The semantic_search tool is only registered when ChromaDB is enabled:

```python
# src/dd_agents/tools/server.py

def create_dd_tools_server(project_dir: Path, state: PipelineState):
    tools = [
        validate_finding_tool,
        resolve_entity_tool,
        check_governance_tool,
        get_customer_list_tool,
        report_progress_tool,
    ]

    if state.chromadb_enabled and state.vector_store:
        tools.append(create_semantic_search_tool(state.vector_store))

    return create_sdk_mcp_server(
        name="dd", version="1.0.0", tools=tools,
    )
```

---

## 6. Pipeline Integration

### 6.1 ChromaDB Indexing (Sub-step of Step 5)

After extraction (step 5), if ChromaDB is enabled, index all extracted text as part of the same step:

```python
async def step_05b_chromadb_indexing(state: PipelineState):
    """Optional: Index extracted text into ChromaDB."""
    if not state.chromadb_enabled:
        return

    state.vector_store.initialize()

    text_dir = state.skill_dir / "index" / "text"
    total_chunks = 0

    for text_file in sorted(text_dir.glob("*.md")):
        # Determine customer from filename (reverse safe_name mapping)
        customer_info = _resolve_customer_from_text_path(text_file, state)

        text = text_file.read_text(encoding="utf-8")
        metadata_base = ChunkMetadata(
            source_file=customer_info["source_file"],
            text_path=str(text_file),
            customer=customer_info["customer"],
            customer_safe_name=customer_info["customer_safe_name"],
            chunk_index=0,
            total_chunks=0,
            file_type=customer_info["file_type"],
        )

        chunks = chunk_document(text, metadata_base)
        state.vector_store.add_chunks(chunks)
        total_chunks += len(chunks)

    logger.info(f"Indexed {total_chunks} chunks into ChromaDB")
```

### 6.2 What ChromaDB Adds (vs File-Based)

| Capability | File-Based | With ChromaDB |
|------------|-----------|---------------|
| Exact keyword search | Grep (fast) | Also available |
| Entity resolution | 6-pass matcher (deterministic) | Same (not changed) |
| Cross-document clause similarity | Not available | "Find all clauses similar to X" |
| Pattern benchmarking | Not available | "Common pricing patterns across customers" |
| Semantic gap detection | Not available | "Which customers lack renewal clauses?" |
| Scale limit | 400 docs (fine) | 5,000+ docs |

### 6.3 What ChromaDB Does NOT Replace

- **Pre-extracted text**: Agents still receive full extracted text from `index/text/`. ChromaDB is supplementary.
- **Entity resolution**: The 6-pass cascading matcher is deterministic and does not use embeddings.
- **Gap detection**: Pattern-based and checklist-based methods remain primary. ChromaDB can assist with semantic gap discovery but is not authoritative.
- **Governance graphs**: Built from explicit document relationships, not semantic similarity.

---

## 7. Installation

ChromaDB is an optional dependency, installed via extras:

```toml
# pyproject.toml
[project.optional-dependencies]
vector = ["chromadb>=0.4.0"]
```

```bash
# Install without ChromaDB (default)
pip install dd-agents

# Install with ChromaDB
pip install dd-agents[vector]
```

The `VectorStore` class gracefully handles the case where ChromaDB is not installed -- it becomes a no-op.
