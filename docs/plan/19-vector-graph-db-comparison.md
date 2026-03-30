# 19 -- Vector and Graph Database Comparison

A comprehensive evaluation of vector database, graph database, and hybrid solutions for the Due Diligence Agent SDK. This document supports ADR-03 (ChromaDB optional) and ADR-04 (NetworkX for governance graphs) with detailed technical analysis, code examples, and maturity assessments.

Cross-references: `01-architecture-decisions.md` (ADR-03, ADR-04), `14-vector-store.md` (ChromaDB integration), `04-data-models.md` (GovernanceEdge schema).

---

**Summary**: ChromaDB (optional vector search) + NetworkX (governance graph) is the recommended architecture. ruvector was evaluated and rejected due to insufficient maturity. See detailed evaluation below.

## 1. Executive Summary

The Due Diligence Agent SDK performs forensic M&A analysis on contract data rooms. Two categories of data infrastructure are relevant:

1. **Graph operations** (required): Governance hierarchy modeling. MSAs govern Order Forms, Amendments modify MSAs, SOWs reference MSAs. Typical scale is 200 customers with 3-5 governance edges each, totaling 600-1,000 edges. Required operations: cycle detection, topological sort, ancestor/descendant queries, isolate detection, multi-parent conflict identification.

2. **Vector search** (optional): Cross-document semantic similarity for clause matching, pattern detection, and semantic gap discovery. Typical scale: 400 documents chunked into approximately 20,000 text segments.

This document evaluates nine solutions across both categories and one claimed hybrid. All solutions must be freely open-source under permissive licenses (Apache 2.0, MIT, BSD, PostgreSQL License). Commercial, closed-source, and subscription-gated tools are excluded; the only exception is LLM API access (AWS Bedrock), which is already configured.

### Quick Recommendation

| Need | Selected | Rationale |
|------|----------|-----------|
| Graph operations | **NetworkX** (BSD 3-Clause) | 15+ years mature, pure Python, rich algorithm library, ideal for sub-1,000-edge in-memory graphs |
| Vector search | **ChromaDB** (Apache 2.0) | Embedded mode, `pip install` simple, right scale for 20K chunks, optional dependency |

---

## 2. Our Requirements

### 2.1 Graph Requirements

The governance graph is a directed acyclic graph (DAG) built per customer from explicit text linkages found by the Legal agent.

| Requirement | Detail |
|-------------|--------|
| Scale | ~600-1,000 edges across all customers; ~3-5 edges per customer |
| Storage | In-memory during pipeline execution; serialized to JSON for persistence |
| Algorithms | Cycle detection, topological sort, ancestor/descendant queries, isolate detection, multi-parent detection |
| Deployment | Zero external services; must run in a single Python process |
| License | Permissive OSI-approved open-source |

### 2.2 Vector Requirements (Optional)

Semantic search is supplementary to file-based keyword search (Grep). The system functions fully without it. When enabled, it adds cross-document clause similarity discovery.

| Requirement | Detail |
|-------------|--------|
| Scale | ~400 documents, ~20,000 text chunks, ~384-768 dimensional embeddings |
| Operations | k-NN similarity search with optional metadata filtering (by customer, file type, section) |
| Deployment | Preferably embedded (no server process); `pip install` only |
| Persistence | Per-deal collection stored alongside deal artifacts |
| License | Permissive OSI-approved open-source |

### 2.3 Non-Negotiable Constraints

- **Python 3.12+**: All solutions must have a Python client or native Python API.
- **Open-source only**: Permissive licenses (Apache 2.0, MIT, BSD, PostgreSQL License). No AGPL, SSPL, BSL, or commercial-only components.
- **Minimal deployment**: No JVM, no Docker requirement, no external services (etcd, MinIO, Zookeeper).
- **Deterministic reproducibility**: Graph operations must produce identical results given identical inputs (no probabilistic graph algorithms for governance validation).

---

## 3. Comparison Matrix

| Solution | License | Type | Age (years) | GitHub Stars | Python API | Deployment | Scale Sweet Spot | Our Fit |
|----------|---------|------|-------------|-------------|------------|------------|-----------------|---------|
| **NetworkX** | BSD 3-Clause | Graph library | 15.5 | 17K | Native | `pip install` | <100K nodes | Graph: Excellent |
| **ChromaDB** | Apache 2.0 | Vector DB | 3.4 | 26K | Native | `pip install` (embedded) | <1M vectors | Vector: Excellent |
| **Qdrant** | Apache 2.0 | Vector DB | 5.7 | 29K | Client lib | Embedded or server | 1M-100M vectors | Vector: Good (overspec) |
| **Milvus** | Apache 2.0 | Vector DB | 6.4 | 43K | PyMilvus | Distributed cluster | 100M-1B+ vectors | Vector: Over-engineered |
| **LanceDB** | Apache 2.0 | Vector DB | 3.0 | 9K | Native | Serverless | <100M vectors | Vector: Good (beta risk) |
| **FAISS** | MIT | Vector index | 9.0 | 39K | Python bindings | Library only | Any scale | Vector: Partial (no DB features) |
| **Weaviate** | BSD 3-Clause | Vector DB | 10.0 | 16K | Client lib | Server process | 1M-100M vectors | Vector: Over-engineered |
| **pgvector** | PostgreSQL License | PG extension | 4.8 | 20K | Via psycopg/SQLAlchemy | Requires PostgreSQL | <10M vectors | Vector: Over-engineered (needs PG) |
| **ruvector** | MIT | Claimed hybrid | 1.3 | ~400 | SDK (early) | Server or embedded | Unknown | Not recommended |

**Fit ratings**: "Excellent" = right scale, right deployment model, proven maturity. "Good" = capable but adds unnecessary complexity. "Over-engineered" = designed for much larger scale than needed. "Partial" = missing required features. "Not recommended" = maturity or reliability concerns.

---

## 4. Detailed Assessments

### 4.1 NetworkX

**What it is**: A pure Python library for the creation, manipulation, and study of complex networks. Developed since 2008 by an academic and industry community. It is the standard graph analysis library in the Python ecosystem.

**License and maturity**: BSD 3-Clause. 15.5 years of development. 17,000+ GitHub stars. 760+ contributors. Used in scientific research, industry, and government. Stable API with backward compatibility guarantees.

**Strengths**:
- Comprehensive algorithm library: 500+ graph algorithms including all operations this project needs
- Zero external dependencies beyond NumPy
- Excellent documentation with mathematical references for every algorithm
- Extensive test suite with property-based testing
- Serialization to/from JSON, GraphML, GEXF, and adjacency list formats
- Active maintenance with regular releases

**Limitations**:
- In-memory only; no built-in persistence or query language
- Single-threaded; not suitable for graphs with millions of edges requiring parallel processing
- Pure Python; slower than C/Rust implementations for very large graphs
- No built-in visualization (requires matplotlib or external tools)

**Fit for this project**:
- Graph needs: **Excellent**. The governance graph has ~1,000 edges. NetworkX can handle graphs 100x this size without any performance concern. Every required operation (cycle detection, topological sort, ancestor/descendant queries, isolate detection) is a single function call.
- Vector needs: None. NetworkX is not a vector database.

**Code example**:

```python
import networkx as nx

# Build governance graph from agent output
G = nx.DiGraph()

# Edges from Legal agent findings
edges = [
    ("MSA-2024-001.pdf", "OrderForm-2024-Q1.pdf", {"relation": "governs"}),
    ("MSA-2024-001.pdf", "SOW-2024-A.pdf", {"relation": "governs"}),
    ("Amendment-2024-01.pdf", "MSA-2024-001.pdf", {"relation": "modifies"}),
]
G.add_edges_from(edges)

# Cycle detection (governance must be a DAG)
try:
    cycle = nx.find_cycle(G, orientation="original")
    print(f"ERROR: Circular governance detected: {cycle}")
except nx.NetworkXNoCycle:
    print("OK: No circular governance references")

# Topological sort (document precedence order)
precedence = list(nx.topological_sort(G))
print(f"Document precedence: {precedence}")

# Find all documents governed by an MSA
governed = nx.descendants(G, "MSA-2024-001.pdf")
print(f"MSA governs: {governed}")

# Find isolated nodes (documents with no governance link)
isolates = list(nx.isolates(G))
print(f"Ungoverned documents: {isolates}")

# Governance completeness metric
total_docs = G.number_of_nodes()
governed_docs = total_docs - len(isolates)
completeness = governed_docs / total_docs if total_docs > 0 else 0.0
print(f"Governance resolved: {completeness:.1%}")
```

---

### 4.2 ChromaDB

**What it is**: An open-source embedding database designed for AI applications. Runs in embedded mode (in-process, no server) or client-server mode. Provides automatic embedding generation using sentence-transformers, persistent storage, and metadata filtering.

**License and maturity**: Apache 2.0. 3.4 years of development. 26,000+ GitHub stars. 198 contributors. Backed by a funded company with a clear open-source commitment.

**Strengths**:
- Embedded mode: `pip install chromadb` is the entire deployment
- Automatic embedding: pass raw text, ChromaDB handles embedding via built-in sentence-transformers
- Metadata filtering: query with `where={"customer": "acme"}` for scoped results
- Persistent storage: SQLite-backed with on-disk collections
- Python-native API with excellent developer experience
- Active development with regular releases

**Limitations**:
- Single-node only; no horizontal scaling or distributed mode
- Performance degrades above ~1M vectors (adequate for this project's 20K chunks)
- Embedding model choice is limited to what sentence-transformers supports (sufficient for clause matching)
- No built-in graph operations

**Fit for this project**:
- Graph needs: None. ChromaDB is not a graph database.
- Vector needs: **Excellent**. ChromaDB is lightweight in deployment (embedded, no separate server process) but capable of handling the scale needed for DD data rooms (typically 200-500 documents, 5,000-50,000 chunks). For this use case, ChromaDB operates well within its comfortable range. For enterprise deployments exceeding 1M chunks, alternatives like Qdrant should be evaluated. Embedded mode means no server management. Metadata filtering supports per-customer scoping. The optional-dependency pattern (`pip install dd-agents[vector]`) aligns with ChromaDB's deployment model.

**Code example**:

```python
import chromadb

# Embedded mode -- no server needed
client = chromadb.Client()

# Create a collection with cosine similarity
collection = client.get_or_create_collection(
    name="forensic_dd_sample_deal_20260221",
    metadata={"hnsw:space": "cosine"},
)

# Add document chunks (ChromaDB auto-embeds the text)
collection.add(
    ids=["acme_msa_0001", "acme_msa_0002", "beta_orderform_0001"],
    documents=[
        "The Supplier shall indemnify and hold harmless the Customer...",
        "Liability under this Agreement shall not exceed the total fees...",
        "This Order Form is governed by MSA dated January 15, 2024...",
    ],
    metadatas=[
        {"customer": "acme_corp", "file_type": "pdf", "section": "Indemnification"},
        {"customer": "acme_corp", "file_type": "pdf", "section": "Liability"},
        {"customer": "beta_inc", "file_type": "pdf", "section": "Governance"},
    ],
)

# Semantic search: find similar indemnification clauses
results = collection.query(
    query_texts=["indemnification and hold harmless provision"],
    n_results=5,
    where={"section": "Indemnification"},  # Optional metadata filter
)

for doc, meta, dist in zip(
    results["documents"][0],
    results["metadatas"][0],
    results["distances"][0],
):
    print(f"[{1 - dist:.2f} relevance] {meta['customer']}: {doc[:80]}...")
```

---

### 4.3 Qdrant

**What it is**: A high-performance vector similarity search engine written in Rust. Offers both embedded mode (in-process via Python) and client-server mode. Known for rich filtering capabilities and payload indexing.

**License and maturity**: Apache 2.0. 5.7 years of development. 29,000+ GitHub stars. 119 contributors. Production-tested at scale by multiple companies.

**Strengths**:
- Written in Rust: excellent performance and memory efficiency
- Rich filtering: boolean, range, geo, and full-text filters on payload fields
- Embedded mode available via `qdrant-client[fastembed]`
- Payload indexing: fast filtering without scanning all vectors
- Quantization support for memory optimization
- Snapshot and backup capabilities

**Limitations**:
- Embedded mode bundles a Rust binary; larger install footprint than ChromaDB
- Python API is less Pythonic than ChromaDB (more verbose, requires explicit model construction)
- No built-in embedding generation in the core client (requires fastembed add-on or external embeddings)
- Designed for scale beyond this project's needs

**Fit for this project**:
- Graph needs: None.
- Vector needs: **Good but overspecified**. Qdrant's performance advantages emerge at scales above 100K vectors. At 20K chunks, the Rust performance advantage is negligible versus ChromaDB's Python-native approach. The added complexity of Rust binary management is not justified.

**Code example**:

```python
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

# Embedded mode (in-memory)
client = QdrantClient(":memory:")

# Create collection (must specify vector dimensions)
client.create_collection(
    collection_name="forensic_dd",
    vectors_config=VectorParams(size=384, distance=Distance.COSINE),
)

# Add vectors (requires pre-computed embeddings)
# Unlike ChromaDB, Qdrant does not auto-embed text
from sentence_transformers import SentenceTransformer
model = SentenceTransformer("all-MiniLM-L6-v2")

texts = ["The Supplier shall indemnify and hold harmless..."]
embeddings = model.encode(texts).tolist()

client.upsert(
    collection_name="forensic_dd",
    points=[
        PointStruct(
            id=1,
            vector=embeddings[0],
            payload={"customer": "acme_corp", "section": "Indemnification"},
        ),
    ],
)

# Search with filtering
results = client.search(
    collection_name="forensic_dd",
    query_vector=model.encode("indemnification clause").tolist(),
    limit=5,
    query_filter={"must": [{"key": "customer", "match": {"value": "acme_corp"}}]},
)
```

---

### 4.4 Milvus

**What it is**: A cloud-native vector database built for scalable similarity search. A CNCF (Cloud Native Computing Foundation) graduated project. Designed for distributed, multi-billion-vector workloads.

**License and maturity**: Apache 2.0. 6.4 years of development. 43,000+ GitHub stars. 361 contributors. The most mature and widely deployed open-source vector database by contributor count and organizational backing.

**Strengths**:
- Distributed architecture with horizontal scaling
- Supports billions of vectors across multiple nodes
- Multiple index types (IVF, HNSW, DiskANN, GPU indexes)
- Rich SDK (PyMilvus) with ORM-style and raw API modes
- CNCF project with strong governance and long-term sustainability
- Hybrid search (vector + scalar filtering)

**Limitations**:
- Heavy deployment: requires etcd (metadata), MinIO (object storage), and the Milvus server
- Milvus Lite (embedded mode) exists but is less mature than the distributed version
- Significant operational complexity for cluster management
- Overkill for datasets under 1M vectors
- Installation footprint measured in gigabytes

**Fit for this project**:
- Graph needs: None.
- Vector needs: **Over-engineered**. Milvus is designed for billion-vector distributed workloads. Deploying etcd and MinIO for 20,000 text chunks is architecturally inappropriate. Milvus Lite reduces deployment burden but loses the benefits that justify choosing Milvus in the first place.

**Code example**:

```python
from pymilvus import MilvusClient

# Milvus Lite (embedded mode -- simplified but less mature)
client = MilvusClient("forensic_dd.db")

# Create collection with auto-id
client.create_collection(
    collection_name="clauses",
    dimension=384,
    metric_type="COSINE",
)

# Insert data (requires pre-computed embeddings)
data = [
    {
        "vector": [0.1, 0.2, ...],  # 384-dimensional embedding
        "customer": "acme_corp",
        "section": "Indemnification",
        "text": "The Supplier shall indemnify...",
    },
]
client.insert(collection_name="clauses", data=data)

# Search
results = client.search(
    collection_name="clauses",
    data=[[0.1, 0.2, ...]],  # query vector
    limit=5,
    filter='customer == "acme_corp"',
    output_fields=["customer", "section", "text"],
)
```

---

### 4.5 LanceDB

**What it is**: A serverless vector database built on the Lance columnar data format. Designed for multimodal AI applications with zero-copy reads and efficient disk-based storage.

**License and maturity**: Apache 2.0. 3 years of development. 9,000+ GitHub stars. 128 contributors. Backed by LanceDB Inc.

**Strengths**:
- Truly serverless: no server process, direct file access
- Lance columnar format: fast analytical queries alongside vector search
- Zero-copy reads: efficient memory usage for large datasets
- Native Python API with pandas/polars integration
- Multimodal support (images, text, audio in the same table)
- Automatic versioning of data

**Limitations**:
- API is still evolving (beta quality in some areas); breaking changes between versions
- Smaller community than ChromaDB or Qdrant
- Less documentation and fewer tutorials available
- Lance format is proprietary to the project (not a standard like Parquet)
- Fewer embedding model integrations out of the box

**Fit for this project**:
- Graph needs: None.
- Vector needs: **Good but carries beta risk**. LanceDB's serverless model is attractive, and its columnar format could benefit analytical queries over clause metadata. However, the evolving API introduces upgrade risk for a production system. At 20K chunks, LanceDB's performance advantages (designed for larger scale) do not materialize.

**Code example**:

```python
import lancedb

# Open or create a database (directory-based, no server)
db = lancedb.connect("./forensic_dd_lance")

# Create table with data
data = [
    {
        "text": "The Supplier shall indemnify and hold harmless...",
        "customer": "acme_corp",
        "section": "Indemnification",
        "vector": [0.1, 0.2, ...],  # pre-computed embedding
    },
]
table = db.create_table("clauses", data=data, mode="overwrite")

# Search with SQL-like filtering
results = (
    table.search([0.1, 0.2, ...])  # query vector
    .where("customer = 'acme_corp'")
    .limit(5)
    .to_pandas()
)
print(results[["text", "customer", "_distance"]])
```

---

### 4.6 FAISS (Facebook AI Similarity Search)

**What it is**: A library for efficient similarity search and clustering of dense vectors, developed by Facebook AI Research. It is a pure indexing library, not a database -- it provides the mathematical operations for nearest-neighbor search but no persistence, metadata management, or filtering.

**License and maturity**: MIT License. 9 years of development. 39,000+ GitHub stars. Developed and maintained by Meta (Facebook) AI Research. The foundational library that most vector databases build upon or benchmark against.

**Strengths**:
- Extremely fast similarity search (CPU and GPU implementations)
- Multiple index types: flat (exact), IVF, HNSW, PQ (product quantization)
- Battle-tested at Meta's scale (billions of vectors)
- Minimal dependencies
- Well-documented with academic papers backing every algorithm

**Limitations**:
- Not a database: no persistence layer, no metadata storage, no filtering
- No built-in embedding generation
- Requires manual serialization (pickle/numpy save) for persistence
- No update or delete operations on indexed vectors (must rebuild)
- Low-level API requires understanding of index internals

**Fit for this project**:
- Graph needs: None.
- Vector needs: **Partial**. FAISS provides the raw similarity search engine but nothing else. This project needs metadata filtering (by customer, section, file type), persistence, and a high-level query API. Building these on top of FAISS would replicate what ChromaDB already provides. FAISS is the right choice when building a custom vector database; it is not the right choice when using one.

**Code example**:

```python
import faiss
import numpy as np

# Create a flat (exact) index for 384-dimensional vectors
dimension = 384
index = faiss.IndexFlatIP(dimension)  # Inner product (use IndexFlatL2 for L2)

# Add vectors (numpy array)
vectors = np.random.rand(20000, dimension).astype("float32")
faiss.normalize_L2(vectors)  # Normalize for cosine similarity
index.add(vectors)

# Search for 5 nearest neighbors
query = np.random.rand(1, dimension).astype("float32")
faiss.normalize_L2(query)
distances, indices = index.search(query, k=5)

print(f"Nearest neighbors: {indices[0]}")
print(f"Distances: {distances[0]}")

# Persistence: manual save/load
faiss.write_index(index, "forensic_dd.faiss")
loaded_index = faiss.read_index("forensic_dd.faiss")
```

---

### 4.7 Weaviate

**What it is**: A vector database with a GraphQL-like API, built-in vectorization modules, and a module ecosystem for different embedding models. Written in Go.

**License and maturity**: BSD 3-Clause. 10 years of development (as a company, open-sourced later). 16,000+ GitHub stars. Modules for OpenAI, Cohere, Hugging Face, and other embedding providers.

**Strengths**:
- Built-in vectorization: configure a model module and Weaviate handles embedding
- GraphQL-like query language for complex queries
- Multi-tenancy support
- Hybrid search (vector + BM25 keyword search)
- Classification and cross-reference features

**Limitations**:
- Requires running a server process (Go binary or Docker)
- Heavier resource footprint than embedded solutions
- Module system adds configuration complexity
- GraphQL-like API has a learning curve
- Over-featured for simple similarity search use cases

**Fit for this project**:
- Graph needs: Weaviate supports cross-references between objects, but these are not graph algorithms. No cycle detection, topological sort, or standard graph operations.
- Vector needs: **Over-engineered**. Weaviate's server requirement contradicts the project's minimal-deployment constraint. Its strength is in complex knowledge graph + vector hybrid scenarios at scale. For 20K chunks with metadata filtering, ChromaDB's embedded mode is simpler and sufficient.

**Code example**:

```python
import weaviate

# Requires a running Weaviate server
client = weaviate.connect_to_local()  # localhost:8080

# Create a collection
clauses = client.collections.create(
    name="Clause",
    vectorizer_config=weaviate.classes.config.Configure.Vectorizer.text2vec_transformers(),
    properties=[
        weaviate.classes.config.Property(name="text", data_type=weaviate.classes.config.DataType.TEXT),
        weaviate.classes.config.Property(name="customer", data_type=weaviate.classes.config.DataType.TEXT),
        weaviate.classes.config.Property(name="section", data_type=weaviate.classes.config.DataType.TEXT),
    ],
)

# Add object (Weaviate auto-vectorizes the text field)
clauses.data.insert(
    properties={
        "text": "The Supplier shall indemnify and hold harmless...",
        "customer": "acme_corp",
        "section": "Indemnification",
    },
)

# Semantic search
response = clauses.query.near_text(
    query="indemnification provision",
    limit=5,
    filters=weaviate.classes.query.Filter.by_property("customer").equal("acme_corp"),
)

client.close()
```

---

### 4.8 pgvector

**What it is**: A PostgreSQL extension that adds vector similarity search to PostgreSQL. Allows combining traditional SQL queries with vector operations in a single database.

**License and maturity**: PostgreSQL License (permissive, similar to BSD/MIT). 4.8 years of development. 20,000+ GitHub stars. Widely adopted in the PostgreSQL ecosystem.

**Strengths**:
- Combines relational queries and vector search in a single system
- Full SQL expressiveness for filtering and joins
- Leverages PostgreSQL's ACID guarantees, backup, and replication
- HNSW and IVFFlat index types
- Familiar to teams already using PostgreSQL
- No additional service to manage if PostgreSQL is already in the stack

**Limitations**:
- Requires a PostgreSQL server (the extension cannot run standalone)
- Performance is lower than purpose-built vector databases at scale
- Index build times can be slow for large datasets
- No built-in embedding generation

**Fit for this project**:
- Graph needs: PostgreSQL supports recursive CTEs for graph traversal, but this is not a graph library. No built-in cycle detection, topological sort, or graph algorithm library.
- Vector needs: **Over-engineered for this project**. The project does not use PostgreSQL (ADR-02 specifies file-based storage). Adding a PostgreSQL dependency solely for vector search contradicts the minimal-deployment constraint. pgvector is excellent when PostgreSQL is already part of the architecture.

**Code example**:

```python
import psycopg2

# Requires a running PostgreSQL server with pgvector extension
conn = psycopg2.connect("postgresql://localhost/forensic_dd")
cur = conn.cursor()

# Enable pgvector and create table
cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
cur.execute("""
    CREATE TABLE IF NOT EXISTS clauses (
        id SERIAL PRIMARY KEY,
        text TEXT,
        customer TEXT,
        section TEXT,
        embedding vector(384)
    )
""")

# Create HNSW index
cur.execute("""
    CREATE INDEX ON clauses
    USING hnsw (embedding vector_cosine_ops)
""")

# Insert (requires pre-computed embedding)
cur.execute(
    "INSERT INTO clauses (text, customer, section, embedding) VALUES (%s, %s, %s, %s)",
    ("The Supplier shall indemnify...", "acme_corp", "Indemnification", "[0.1,0.2,...]"),
)

# Search with SQL filtering
cur.execute("""
    SELECT text, customer, section, embedding <=> %s::vector AS distance
    FROM clauses
    WHERE customer = 'acme_corp'
    ORDER BY embedding <=> %s::vector
    LIMIT 5
""", (query_embedding, query_embedding))

conn.close()
```

---

### 4.9 ruvector

**What it is**: A project that describes itself as a "unified vector + graph + relational database" with claims of SIMD-accelerated inference, distributed clustering, and graph neural network capabilities.

**License and maturity**: MIT License. Approximately ~16 months old (first commit October 2024). ~422 GitHub stars. 4 contributors.

See Section 5 for a dedicated deep-dive assessment.

---

## 5. ruvector Deep Dive

This section provides an honest, technically grounded assessment of ruvector. The goal is not to dismiss the project but to evaluate whether it meets the reliability and maturity requirements for production use in forensic M&A due diligence.

### 5.1 What ruvector Claims

The project's README and documentation describe:

- Unified vector, graph, and relational database in a single system
- SIMD-accelerated inference engine
- Distributed clustering with automatic rebalancing
- Graph neural network (GNN) integration
- Support for heterogeneous graph schemas
- Real-time vector indexing with HNSW and IVF indexes
- SQL-compatible relational query layer
- Python SDK with async support

If these claims were fully realized and production-tested, ruvector would be a compelling solution. The combination of vector search and graph operations in a single system would eliminate the need for separate NetworkX and ChromaDB dependencies.

### 5.2 Maturity Concerns

The gap between claims and observable evidence raises significant concerns for production use.

**Timeline and resources**:

| Metric | ruvector | ChromaDB (comparison) | NetworkX (comparison) |
|--------|----------|----------------------|----------------------|
| Age | ~16 months | 3.4 years | 15.5 years |
| Contributors | 4 | 198 | 760 |
| GitHub stars | ~422 | 26,000 | 17,000 |
| Production case studies | 0 published | Multiple | Thousands |
| Independent benchmarks | 0 | Multiple | N/A (library) |

**Version numbering**: The project version jumped from 0.1.x to 2.0.4 within approximately one month of initial development. In established open-source conventions, version 2.0 implies a mature project that has gone through at least one major stable release cycle. A jump from 0.1 to 2.0 in one month, with 4 contributors, does not reflect the engineering effort typically associated with a major version milestone.

**Scope versus engineering capacity**: The claimed feature set -- SIMD inference, distributed clustering, graph neural networks, a full relational query layer, heterogeneous graph schemas -- represents person-years of engineering effort at established database companies. For reference:

- Milvus (distributed vector search alone, without graph or relational features) has 361 contributors over 6.4 years.
- Neo4j (graph database alone, without vector features) has been developed since 2007 with hundreds of engineers.
- SQLite (relational database alone, without vector or graph features) has been developed since 2000.

A project with 4 contributors and ~16 months of development claiming to unify all three paradigms warrants skepticism about the depth and correctness of each implementation.

### 5.3 Known Issues

Open GitHub issues at the time of this evaluation include:

- **Graph traversal correctness bugs**: Reported issues with incorrect results in multi-hop graph queries, which directly affects the governance hierarchy operations this project requires (ancestor/descendant queries, cycle detection).
- **SIMD inference issues**: Reports of incorrect results from the SIMD-accelerated inference engine on certain hardware configurations.
- **Python SDK stability**: The Python SDK has limited documentation, and users report breaking changes between minor version releases.

For this project specifically, graph traversal correctness is non-negotiable. The governance graph determines document precedence and conflict detection. An incorrect cycle detection result could cause the system to either miss a governance conflict (false negative) or flag a valid governance chain as circular (false positive). Both outcomes undermine the forensic integrity of the due diligence process.

### 5.4 Why ruvector Is Not Recommended for This Project

The decision is based on five concrete technical criteria, not on dismissiveness toward a new project:

1. **Correctness risk**: Open bugs in graph traversal are disqualifying for governance hierarchy validation. NetworkX's graph algorithms have been tested and used in academic research for 15 years.

2. **No independent validation**: Zero third-party benchmarks, zero production case studies, zero academic citations. For a forensic due diligence tool that produces legal-grade findings, every infrastructure component must have a demonstrable track record.

3. **API instability**: Breaking changes between minor versions create maintenance burden. The project's API surface is still being discovered, not refined.

4. **Unverifiable claims**: The claimed feature set exceeds what 4 contributors can thoroughly implement, test, and maintain in ~16 months. Without independent benchmarks, there is no way to verify that SIMD inference, distributed clustering, or GNN integration work correctly at production quality.

5. **Unnecessary coupling**: Even if ruvector's vector and graph features were both production-ready, combining them in a single dependency creates a coupling risk. If a bug in the vector component requires downgrading, the graph component is also affected. The project's current architecture (NetworkX for graphs, optional ChromaDB for vectors) keeps these concerns cleanly separated.

### 5.5 When ruvector Might Become Viable

ruvector could become a reasonable choice for this project if the following conditions are met:

- **Age**: At least 18-24 months of continuous development with a stable release cadence
- **Contributors**: 20+ active contributors with diverse organizational affiliations
- **Independent benchmarks**: Third-party performance and correctness benchmarks, ideally published by users outside the core team
- **Graph algorithm correctness**: A comprehensive test suite for graph algorithms verified against reference implementations (e.g., NetworkX or igraph output)
- **Stable API**: At least 6 months without breaking changes in the core API surface
- **Production references**: At least 2-3 published case studies from independent organizations using ruvector in production for graph or vector workloads
- **Security audit**: For a tool handling M&A contract data, a third-party security review of the storage and access layer

None of these conditions are unreasonable. They are standard expectations for infrastructure dependencies in systems that produce legal-grade output.

---

## 6. Our Decision

### 6.1 Graph: NetworkX (ADR-04)

**Selected**: NetworkX 3.x, BSD 3-Clause License.

**Why NetworkX over alternatives**:

| Alternative | Why not |
|-------------|---------|
| Neo4j | JVM dependency, server process, Cypher learning curve. Overkill for 1,000 edges. Not permissive license (GPLv3 for Community Edition). |
| Custom adjacency-list JSON | No built-in cycle detection, topological sort, or graph algorithms. Would require reimplementing what NetworkX provides. |
| ruvector | Maturity concerns (Section 5). Graph traversal correctness bugs. |
| igraph | Capable but C-based with complex build dependencies. NetworkX is pure Python and sufficient at this scale. |

**When to reconsider**: If the governance graph grows beyond 100,000 edges (e.g., a data room with 20,000+ customers), consider igraph (C-based, faster for large graphs) or a graph database. This threshold is approximately 100x beyond current maximum expected scale.

### 6.2 Vector: ChromaDB, Optional (ADR-03)

**Selected**: ChromaDB 0.4+, Apache 2.0 License. Optional dependency via `pip install dd-agents[vector]`.

**Why ChromaDB over alternatives**:

| Alternative | Why not |
|-------------|---------|
| Qdrant | Capable but adds Rust binary complexity. Performance advantages do not materialize at 20K chunks. |
| Milvus | Requires etcd + MinIO. Designed for billion-vector scale. Deployment complexity contradicts project constraints. |
| LanceDB | Beta-quality API with breaking changes. Good technology but not yet stable enough for production dependency. |
| FAISS | Library, not a database. Would require building persistence, filtering, and embedding management. |
| Weaviate | Requires server process. Over-engineered for embedded use case. |
| pgvector | Requires PostgreSQL server. Project uses file-based storage (ADR-02). |
| ruvector | Maturity concerns (Section 5). |

**When to reconsider**:
- If vector scale grows beyond 1M chunks: evaluate Qdrant (next step up in scale with embedded mode).
- If the project adopts PostgreSQL for other reasons: pgvector becomes the natural choice (one fewer dependency).
- If LanceDB reaches stable 1.0 with API guarantees: re-evaluate for its serverless model and columnar analytics.

### 6.3 Architecture Summary

```
Due Diligence Agent SDK
|
+-- Graph operations (REQUIRED)
|   +-- NetworkX 3.x (BSD 3-Clause)
|   +-- In-memory, ~1,000 edges
|   +-- Cycle detection, topological sort, ancestor/descendant queries
|   +-- Serialized to JSON in _dd/forensic-dd/runs/{run_id}/
|
+-- Vector search (OPTIONAL)
    +-- ChromaDB 0.4+ (Apache 2.0)
    +-- Embedded mode, ~20,000 chunks
    +-- Semantic clause matching, cross-document discovery
    +-- Stored in _dd/forensic-dd/chromadb/
    +-- Enabled via: chromadb_enabled: true in deal-config.json
```

**Scale sensitivity**: The current architecture handles data rooms up to ~1,000 documents / 100,000 chunks with ChromaDB embedded mode. Beyond this, consider ChromaDB client-server mode or migration to Qdrant. NetworkX handles governance graphs up to ~10,000 edges with sub-second query times. These limits are 10x above current maximum observed data room sizes.

---

## 7. License Compliance Summary

Every dependency must be freely open-source under a permissive OSI-approved license. No AGPL, SSPL, BSL (Business Source License), or commercial-only components are permitted.

| Solution | License | OSI Approved | Permissive | Project Compatible |
|----------|---------|-------------|------------|-------------------|
| NetworkX | BSD 3-Clause | Yes | Yes | Yes (selected) |
| ChromaDB | Apache 2.0 | Yes | Yes | Yes (selected, optional) |
| Qdrant | Apache 2.0 | Yes | Yes | Yes (not selected) |
| Milvus | Apache 2.0 | Yes | Yes | Yes (not selected) |
| LanceDB | Apache 2.0 | Yes | Yes | Yes (not selected) |
| FAISS | MIT | Yes | Yes | Yes (not selected) |
| Weaviate | BSD 3-Clause | Yes | Yes | Yes (not selected) |
| pgvector | PostgreSQL License | Yes | Yes | Yes (not selected) |
| ruvector | MIT | Yes | Yes | Yes (not recommended) |

All nine solutions pass the license compliance check. The selection criteria that differentiate them are maturity, deployment complexity, scale fit, and correctness assurance -- not licensing.

### Transitive Dependency Licenses

The selected tools have the following notable transitive dependencies:

| Tool | Key Dependency | License | Status |
|------|---------------|---------|--------|
| NetworkX | NumPy | BSD 3-Clause | Compliant |
| NetworkX | SciPy (optional) | BSD 3-Clause | Compliant |
| ChromaDB | sentence-transformers | Apache 2.0 | Compliant |
| ChromaDB | SQLite (embedded) | Public Domain | Compliant |
| ChromaDB | hnswlib | Apache 2.0 | Compliant |
| ChromaDB | DuckDB (internal) | MIT | Compliant |

No transitive dependency introduces a copyleft or commercial license obligation.

---

## Appendix: Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-02-21 | Document created | Comprehensive comparison requested; consolidates ADR-03 and ADR-04 rationale |
| 2026-02-21 | ruvector assessed as not recommended | ~16-month maturity, 4 contributors, open graph traversal bugs, unverifiable scope claims |
| 2026-02-21 | NetworkX confirmed for graph operations | 15.5 years mature, BSD 3-Clause, every required algorithm available, sub-1,000-edge scale ideal |
| 2026-02-21 | ChromaDB confirmed for optional vector search | Apache 2.0, embedded mode, 20K-chunk scale comfortable, pip-installable optional dependency |
