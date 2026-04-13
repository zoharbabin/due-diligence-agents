# Knowledge Architecture & Design Decisions

A technical guide to how Due Diligence Agents analyzes, connects, and compounds knowledge across hundreds of unstructured documents — and why it works this way.

---

## Table of Contents

1. [The Problem](#1-the-problem)
2. [Why Not Vector RAG](#2-why-not-vector-rag)
3. [The Five-Stage Pipeline](#3-the-five-stage-pipeline)
4. [Extraction: Getting Clean Text Out of Messy Files](#4-extraction-getting-clean-text-out-of-messy-files)
5. [The Two-Level Graph Architecture](#5-the-two-level-graph-architecture)
6. [Map-Merge-Resolve: Analysis Without Losing Context](#6-map-merge-resolve-analysis-without-losing-context)
7. [Multi-Agent Cross-Domain Analysis](#7-multi-agent-cross-domain-analysis)
8. [The Verification Stack](#8-the-verification-stack)
9. [Knowledge Compounding](#9-knowledge-compounding)
10. [Key Design Tradeoffs](#10-key-design-tradeoffs)
11. [Research Foundations](#11-research-foundations)

---

## 1. The Problem

M&A due diligence requires multiple workstreams — legal, financial, commercial, product/technical — each analyzing the same data room from different perspectives. Each workstream produces independent findings. But the real risks live at the intersections: a customer that represents 5% of revenue AND has a change-of-control termination right AND is on an expiring contract with below-market pricing. Surfacing that requires connecting findings across all four domains.

Traditional tools are single-domain (one workstream at a time) or single-function (document storage, not analysis). No existing solution performs multi-domain forensic analysis with adversarial cross-validation across Legal, Finance, Commercial, and Product/Tech.

This system runs all four workstreams in parallel, cross-references findings automatically, and traces every claim to an exact page, section, and quote. The architecture below explains how.

---

## 2. Why Not Vector RAG

The dominant approach for AI document analysis is Retrieval-Augmented Generation (RAG): chunk documents, embed them as vectors, retrieve by similarity, feed to an LLM. We evaluated this approach extensively and chose a different path. Here's why.

### The core assumption fails on professional documents

Vector RAG assumes that semantically similar text is relevant text. That assumption breaks on contracts, financial reports, and legal agreements:

- **Cross-references defeat similarity.** An MSA's Section 4.2 says "Subject to the terms of Amendment #2, either party may terminate with 30 days notice." The amendment that modifies this clause has zero semantic overlap with a question about termination rights — but it's the controlling document.
- **Boilerplate drowns signal.** Legal documents share extensive boilerplate. Vector search retrieves chunks from the wrong document because the boilerplate matches (Reuter et al., 2025).
- **Structure matters more than content.** Whether a clause is in an MSA vs. an Order Form vs. an Amendment determines its legal effect. Vector similarity ignores document hierarchy entirely.

### What the research shows

The Addleshaw Goddard study (2024, 510 CUAD contracts) found that focused analysis of targeted document sections outperforms full-context analysis by 21 percentage points (74% → 95% F1). The improvement came entirely from better engineering — same model, same documents, better retrieval and prompting.

The Stanford Legal AI Hallucination Study (Magesh et al., 2025) found hallucination rates of 17-33% in production legal AI tools (LexisNexis, Westlaw), and 58-80% for GPT-4 on direct legal tasks. RAG reduces but does not eliminate hallucination.

### Our approach instead

Rather than retrieve-then-generate, we use a pipeline where:

1. **Agents read documents directly** using tools (Read, Grep, glob). No intermediate retrieval step.
2. **Document relationships are modeled as graphs** (NetworkX), not vector distances.
3. **Analysis uses map-merge-resolve** — chunk for accuracy, merge with priority logic, resolve conflicts via targeted LLM arbitration.
4. **Vector search is optional** — available as a supplementary tool (ChromaDB) when keyword search is insufficient, but never the primary analysis path.

This means every finding traces to a specific file, page, and quote — not to a similarity score.

---

## 3. The Five-Stage Pipeline

The system runs as a 35-step async state machine organized into five stages. Each step receives pipeline state, performs work, checkpoints, and continues. Five steps are **blocking gates** that halt the pipeline on failure — the system produces nothing rather than something unreliable.

```
┌─────────────────────────────────────────────────────────┐
│  Stage 1: Setup & Extraction (Steps 1-5)                │
│  Config validation, persistence init, file discovery,   │
│  bulk text extraction with 7-method fallback chain      │
│  🚫 GATE: Extraction quality (step 5)                   │
├─────────────────────────────────────────────────────────┤
│  Stage 2: Discovery & Inventory (Steps 6-12)            │
│  Subject registry, entity resolution, document          │
│  precedence scoring, reference file routing              │
├─────────────────────────────────────────────────────────┤
│  Stage 3: Agent Execution (Steps 13-17)                 │
│  Prompt building, 4 specialist agents in parallel,      │
│  coverage verification with respawn for gaps            │
│  🚫 GATE: Subject coverage (step 17)                    │
├─────────────────────────────────────────────────────────┤
│  Stage 4: Quality Review (Steps 18-28)                  │
│  Judge adversarial review, merge & dedup, numerical     │
│  audit (6-layer), 31 Definition of Done checks          │
│  🚫 GATE: Numerical audit (step 27)                     │
│  🚫 GATE: Full QA audit (step 28)                       │
├─────────────────────────────────────────────────────────┤
│  Stage 5: Reporting & Knowledge (Steps 29-35)           │
│  Report generation, post-gen validation, knowledge      │
│  compilation, entity cache persistence                  │
│  🚫 GATE: Post-generation validation (step 31)          │
└─────────────────────────────────────────────────────────┘
```

### Checkpoint and resume

After every step, state is serialized to a checkpoint file. If the pipeline crashes at step 30, it resumes from step 30 — not from scratch. For the most expensive step (step 16: spawning specialist agents), sub-checkpoints track individual agent completion. If 2 of 4 agents finish before a crash, only the remaining 2 are re-spawned.

### Three-tier persistence

All artifacts are organized into three lifecycle tiers:

| Tier | Lifecycle | Examples |
|------|-----------|---------|
| **PERMANENT** | Never wiped across runs | Extracted text, checksums, entity resolution cache, knowledge base |
| **VERSIONED** | Archived per run | Findings, gaps, audit logs, reports, judge reviews |
| **FRESH** | Rebuilt every run | File inventory, subject registry, reference routing |

This means extracted text (expensive to produce) survives across runs, while findings (which should reflect current analysis) are always fresh.

---

## 4. Extraction: Getting Clean Text Out of Messy Files

80% of the engineering is extraction, not analysis. Real data rooms contain text-based PDFs, scanned images, watermark overlays, encrypted files, Excel spreadsheets with date serial numbers, and Word documents with tracked changes. No single extraction method handles all of them.

### The 7-method fallback chain

Each file is routed through a fallback chain based on pre-inspection (~8ms per file):

```
Normal PDF:   pymupdf → pdftotext → markitdown → GLM-OCR → Tesseract → Claude vision
Scanned PDF:  GLM-OCR → Tesseract → Claude vision (skips text extractors)
Office docs:  markitdown (handles DOCX, PPTX, XLSX natively)
Images:       markitdown → GLM-OCR → Tesseract → Claude vision → placeholder
```

### Quality gates per method

Every extraction method passes through 6 quality gates before its output is accepted:

1. **Minimum character count** — Reject suspiciously short extractions
2. **Printable character ratio** — Detect binary garbage
3. **Text density** — Flag sparse extractions (file size vs. text size)
4. **Readability score** — Detect garbled OCR output
5. **Watermark detection** — Flag watermark-heavy text
6. **Corruption detection** — Catch control characters and encoding issues

### Confidence scaling

Extraction confidence is not binary. Each method gets a base confidence score (pymupdf: 0.9, pdftotext: 0.7, OCR: 0.65, Claude vision: 0.65), then scaled further by text-to-file-size ratio. A 5MB PDF that yields only 200 characters of text gets a low confidence score regardless of method.

### Structure preservation

- **Page boundaries**: Embedded as `--- Page N ---` markers. These persist through the entire pipeline and enable page-level citation.
- **Section headers**: Preserved as plain text but not hierarchically indexed. Agents navigate documents directly rather than through a pre-computed tree.
- **Tables**: Optional layout-aware extraction detects table regions via block coordinates and renders as Markdown.
- **Checksums**: SHA-256 checksums per file enable extraction caching across runs. A file extracted in run 1 is not re-extracted in run 2 unless the source file changes.

### Spreadsheet handling: two-path architecture

Excel and CSV files get special treatment because financial data has different failure modes than prose. A misread clause is wrong; a misread revenue figure can be wrong by 10x.

**Path 1 — Bulk extraction (pipeline start).** CSV files are classified as plaintext and read directly. Excel files (.xlsx, .xls) route through markitdown for conversion to text. Confidence is scaled against a lower expected text ratio (0.05 vs 0.09 for PDFs) — spreadsheets are binary formats that yield less text per byte of file size.

**Path 2 — Agent-facing `read_office` MCP tool (runtime).** Specialist agents can re-read specific sheets on demand during analysis, not just rely on pre-extracted text. This is the critical path for financial accuracy. Note: only `.xlsx` files get the smart extraction below — legacy `.xls` routes through markitdown, which does not apply date/currency/sub-table processing.

- `.xlsx` files use **openpyxl** with `read_only=True` and `data_only=True` — agents see computed values, not raw formulas like `=SUM(B2:B10)`, with minimal memory overhead
- **E-1 Date conversion**: `datetime` cells render as ISO-8601 (`2024-03-15`) instead of Python's verbose `2024-03-15 00:00:00`. Cells with a non-zero time component render as `2024-06-01 14:30`
- **E-2 Currency/percentage**: Cells with currency format strings (`$`, `€`, `£`, `¥`) render as `$1,234,567.89`. Percentage-formatted cells render as `45.2%` (value × 100, since Excel stores percentages as decimals). NaN/Inf values bypass formatting and fall through to `str()`
- **E-3 Sub-table detection**: Blank rows are detected as logical table boundaries. Each sub-table is rendered as a separate markdown table with its own column-letter headers (A, B, C), matching how analysts structure multi-region financial spreadsheets
- Output renders as **markdown tables with Excel-style column letters** as headers instead of using data from row 1. This prevents a common LLM failure where the first data row gets interpreted as column names
- Cell sanitization preserves table structure: newlines replaced with spaces (would break table rows), pipe characters escaped (would break column boundaries)
- Output capped at 150K characters with explicit truncation notice — agents know when they're seeing partial data
- Falls back to pre-extracted text from `index/text/` if the primary read fails — but only when the `text_dir` parameter is provided (configured at MCP server startup)

**Path 3 — Search chunker (E-4 table-aware splitting).** When Excel-extracted markdown passes through the search analysis pipeline, `is_tabular()` detects predominantly tabular content and routes it through `split_by_table_rows()` instead of paragraph-based splitting. This splits at row boundaries and repeats the full header block (sheet heading + column letters + separator) in every segment — so the LLM never sees data rows without column context.

The multi-path design means the extraction pipeline handles the bulk work once, agents retain the ability to go back to the source spreadsheet for precise reads, and the search pipeline handles large tables without losing header context at chunk boundaries.

---

## 5. The Two-Level Graph Architecture

Documents in a data room are not independent. An MSA governs every Order Form beneath it. An Amendment supersedes specific MSA clauses. A Side Letter waives particular obligations. Understanding these relationships is essential for correct analysis — and it's something vector similarity fundamentally cannot represent.

We model document relationships at two levels using NetworkX directed graphs.

### Level 1: Contract Ontology (inter-document)

The contract knowledge graph tracks how documents relate to each other:

- **13 document types**: MSA, Order Form, Amendment, Side Letter, SOW, NDA, DPA, SLA, PO, Renewal Agreement, Assignment Agreement, Termination Notice, Unknown
- **8 relationship types**: GOVERNS, AMENDS, SUPERSEDES, REFERENCES, INCORPORATES, CONFLICTS_WITH, DEFINES, WAIVES
- **Operations**: Amendment chain detection (topological sort), cascade impact queries (if this MSA changes, which Order Forms are affected?), cycle detection (governance must be a DAG), conflict detection (two documents claiming different governing law)

A cascade impact query across 200 contracts completes in ~50ms — this is deterministic graph traversal, not LLM inference.

### Level 2: Knowledge Graph (cross-run)

The deal knowledge graph tracks relationships across all entities, documents, findings, and knowledge articles:

- **7 node types**: Entity, Document, Clause, Finding, Gap, Article, Obligation
- **16 edge types**: GOVERNS, AMENDS, SUPERSEDES, REFERENCES, INCORPORATES, CONFLICTS_WITH, PARTY_TO, ANALYZED_IN, FOUND_IN, AFFECTS, CONTRADICTS, CORROBORATES, DERIVED_FROM, RELATED_TO, CONTAINS, OVERRIDES

This graph persists across runs and grows over time. When the knowledge compiler detects a contradiction between agents (Legal says P0, Finance says P2 for the same clause), it creates a CONTRADICTS edge that surfaces in subsequent run prompts.

### Why NetworkX (and not Neo4j, or a vector-graph hybrid)

At the scale of a typical data room (200 customers, 600-1,000 governance edges), NetworkX handles all operations in under 1 second with zero deployment dependencies. Neo4j would add a JVM dependency and server management for a graph that fits entirely in memory. We evaluated ruvector (a Rust-based vector+graph hybrid) but found it too immature (16 months old, 4 contributors, open graph operation bugs). The decision was explicit: separate tools for separate jobs — NetworkX for graphs, ChromaDB (optional) for vectors.

At 100,000+ edges, this decision would be worth revisiting. At our current scale, simplicity wins.

---

## 6. Map-Merge-Resolve: Analysis Without Losing Context

When a 200-page master agreement might contain the deal-killer on page 147, you can't skip large files. But dumping an entire document into one LLM context degrades accuracy — the Addleshaw Goddard study measured a drop from 95% to 74%.

Our search module implements a 4-phase structured analysis pipeline:

### Phase 1: Map — Analyze each chunk independently

Documents are split at page boundaries with 15% overlap (capped at 60K characters). Each chunk is analyzed independently against the same question. Target chunk size is 150K characters (~37K tokens), leaving room for agent reasoning.

The overlap is critical: a clause that spans pages 12-13 must not be lost at a chunk boundary. 15% overlap ensures at least partial coverage of boundary-crossing content.

### Phase 2: Merge — Combine answers with priority logic

Chunk results are merged using deterministic rules:
- **YES beats NO**: If any chunk found the clause, it exists — even if other chunks didn't find it.
- **Specific beats generic**: "Termination right in Section 4.2 with 30-day notice" survives over "no termination provisions found."
- **Citations deduplicated** by (file_path, page, section_ref, exact_quote).

### Phase 3: Resolve — LLM arbitration only on disagreement

When chunks genuinely disagree (one says YES, another says NO with evidence), a synthesis pass resolves the conflict. This is the only phase that makes an additional LLM call, and it only triggers on disagreement — saving cost on the common case where chunks agree.

### Phase 4: Validate — Second pass on remaining gaps

Any question still marked NOT_ADDRESSED gets a targeted re-query. This catches items that fell exactly on a chunk boundary and were missed by both overlapping chunks.

### Why this is an accuracy pattern, not a scaling pattern

Map-merge-resolve was inspired by MapReduce but serves a fundamentally different purpose. Classical MapReduce parallelizes computation across machines. Our pattern analyzes focused chunks independently to get better answers — then reconciles. The reduce phase is smarter than simple aggregation: it's priority-based merging with conditional LLM arbitration. You get better answers by analyzing focused chunks than by analyzing everything at once.

---

## 7. Multi-Agent Cross-Domain Analysis

Four specialist agents analyze the data room in parallel, each from their domain perspective:

| Agent | Focus Areas | Example Findings |
|-------|-------------|-----------------|
| **Legal** | CoC (5 subtypes), assignment, termination, IP, indemnification, governing law | "Auto-termination on change of control, no cure period, affects 22% of revenue" |
| **Finance** | Revenue recognition, ARR reconciliation, unit economics, pricing compliance, cost structure | "Reported ARR of $4.2M includes $380K in usage-based overages that haven't recurred in 3 quarters — effective recurring base is $3.8M" |
| **Commercial** | Pricing models, MFN clauses, renewal mechanics, competitive positioning, volume commitments | "Customer's MFN clause guarantees pricing parity — any discount given to future customers automatically applies, capping upsell margin across the base" |
| **ProductTech** | Contractual feature commitments, per-SKU pricing, security SLAs, integration complexity, technical debt | "3 enterprise contracts commit to SSO and audit-log features not yet shipped — blocking renewal negotiation and creating implicit delivery obligations post-close" |

### Cross-domain findings emerge from merge

The same document gets analyzed by all four agents. Legal finds a change-of-control termination right. Finance calculates the revenue at risk. Commercial notes the subject is on an expiring contract. ProductTech flags a missing data processing agreement. After merge and dedup (step 24), these findings are linked to the same subject — and the Executive Synthesis agent connects them into a cross-domain risk assessment.

### Domain boundaries are explicit

Each specialist has forbidden areas:
- Commercial: "Do NOT perform independent financial calculations"
- Finance: "Verify currency units — $120 could be $120 or $120K"
- ProductTech: "Do NOT assume security standards — require documentary evidence"

This prevents agents from producing findings outside their expertise, which would create false confidence.

### Deal-type-aware severity calibration

The same finding gets different severity based on deal structure. A shared services agreement between subsidiaries is P3 (informational) in a stock acquisition — the subsidiaries are absorbed, intercompany obligations vanish at closing. The same agreement is P1 (material risk) in a divestiture — the carved-out entity must replicate the service to operate standalone.

This is implemented through three calibration layers:

1. **Prompt-time**: Deal-type-specific severity rubrics injected into agent prompts
2. **Post-hoc**: Deterministic pattern rules downgrade known false positives (e.g., competitor-only CoC → P3, TfC capped at P2)
3. **Executive synthesis**: Professional judgment overrides with full audit trail

Every severity change records `_recalibrated_from` and `_recalibration_reason` for transparency.

---

## 8. The Verification Stack

Production retrospective on a real deal (~200 subjects) revealed that all 17 quality failures were instruction-following failures — the LLM ignored prose "MUST" constraints. This led to a fundamental architecture decision: **Python controls flow, LLMs are workers.** Enforcement is programmatic, not prose.

### 6-layer hallucination defense

| Layer | Mechanism | What It Catches |
|-------|-----------|-----------------|
| **L1: Structured output** | Pydantic v2 schema validation | Malformed output, missing fields, wrong types |
| **L2: Citation verification** | 4-scope progressive search (exact page → adjacent ±1 → full doc fuzzy → cross-file) | Fabricated quotes, wrong page numbers, file misattribution |
| **L3: NOT_FOUND escape valve** | Explicit protocol: "If you cannot find this clause, write a gap" | Models fabricating clauses rather than admitting ignorance |
| **L4: Adversarial Judge** | Separate agent spot-checks findings (P0: 100%, P1: 20%, P2: 10%) using accusatory framing | Overconfident findings, severity inflation |
| **L5: Numerical audit** | 6-layer deterministic re-derivation of every number | Hallucinated statistics, arithmetic errors |

### Agent guardrails

Agents operate under hard boundaries:
- **Turn limits**: Soft warning at 200 turns, hard kill at 3x (600). Prevents runaway sessions.
- **Path guard**: Agents can only write under `_dd/`. Symlink resolution prevents escape.
- **Bash blocklist**: 24 blocked patterns + 5 regex rules. No `rm -rf`, no `sudo`, no pipe-to-shell.
- **Budget limits**: `max_budget_usd` per agent ($5 default). Pipeline halts if exceeded.

### Three-tier finding classification

Raw agent output produces thousands of findings. Most are noise. A three-tier classification system (applied deterministically in Python, not by LLM) separates signal from noise:

1. **Noise filter** (15 patterns): "Cannot assess: extraction failed", "binary file", "unreadable document" — artifacts of the extraction process.
2. **Data quality filter** (14 patterns): "Data unavailable", "cannot verify financial data" — real gaps, but not material risks. Routed to a separate appendix.
3. **Material findings**: Everything that survives both filters.

Plus 5 severity recalibration rules that auto-adjust based on context (e.g., competitor-only CoC: P0 → P3).

---

## 9. Knowledge Compounding

Inspired by Andrej Karpathy's "LLM Wiki" pattern: instead of starting from scratch each time, compound knowledge across runs so the system develops institutional memory.

### The knowledge layer

```
_dd/forensic-dd/knowledge/          [PERMANENT tier]
├── entities/                        Entity profiles (one per subject)
├── clauses/                         Cross-entity clause summaries
├── contradictions/                  Agent disagreements
├── insights/                        Analyst-added observations
├── annotations/                     Manual annotations
├── index.json                       Auto-rebuilt lookup index
├── graph.json                       NetworkX knowledge graph
├── chronicle.jsonl                  Append-only interaction timeline
└── lineage.json                     Cross-run finding evolution
```

### How it works

**After each run** (step 32), the Knowledge Compiler processes merged findings:

1. **Entity profiles** created or updated — severity distribution, key clauses, cross-run history
2. **Clause summaries** aggregated — which entities are affected by each clause type
3. **Contradictions** detected — where agents disagree on severity for the same clause
4. **Finding lineage** tracked — SHA-256 fingerprints identify findings across runs even when wording changes

**Before the next run** (step 14), the Agent Knowledge Enricher injects prior knowledge into specialist prompts:

| Budget | Content |
|--------|---------|
| 40% | Entity profiles filtered by domain |
| 20% | Persistent findings (appeared in 3+ runs) |
| 15% | Known contradictions |
| 15% | Document relationships from knowledge graph |
| 10% | Prior insights and annotations |

Each specialist only sees knowledge relevant to their domain — Legal gets clause-level findings, Finance gets revenue-related patterns.

### Finding lineage

Every finding gets a stable fingerprint: SHA-256 of (entity, agent, category, primary citation, normalized title). This enables tracking across runs even when the LLM describes the same issue differently:

- **ACTIVE**: Finding present in current run
- **RESOLVED**: Finding absent from current run (was previously active)
- **RECURRED**: Finding reappeared after being resolved

Severity changes are recorded as events with timestamps, enabling trend analysis: "This CoC clause was P0 in run 1, recalibrated to P2 in run 2, and is now P1 in run 3."

### What this enables

- **Run 1** finds the risks
- **Run 2** knows the context, catches what changed, flags new contradictions
- **Run 3+** identifies persistent issues, severity trends, and recurrences
- The system develops institutional memory — like an analyst who remembers every deal they've worked on

---

## 10. Key Design Tradeoffs

Every architecture embodies tradeoffs. These are the ones we made explicitly, with reasoning.

### Python orchestration vs. LLM autonomy

**Chose**: Python controls flow; LLMs are workers.
**Why**: All 17 production failures were instruction-following failures. The LLM ignored prose constraints ("MUST produce per-subject JSON", "MUST verify citations"). Markdown emphasis has zero enforcement power. Python if/else is deterministic.
**Cost**: Added state machine complexity, hook system, checkpoint management.
**Benefit**: Zero enforcement failures since migration.

### File-based storage vs. database

**Chose**: Three-tier file-based JSON/JSONL.
**Why**: At 400 documents / 200 subjects, file-based queries complete in <1 second. Agent outputs are naturally per-subject JSON files. Audit trail is human-readable. No deployment dependency.
**Reconsidering at**: 10,000+ subjects.

### Thoroughness vs. speed

**Chose**: Thoroughness. Agents read full documents. 6-layer verification. 31 DoD checks.
**Why**: In M&A, a missed deal-killer costs more than a slow pipeline. Accuracy is non-negotiable; latency is tolerable.
**Cost**: Pipeline takes hours, not minutes.
**Benefit**: Every finding traces to source. Every number is re-derived.

### Deterministic validation vs. LLM validation

**Chose**: Deterministic Python for validation. LLMs for analysis.
**Why**: We had an LLM agent doing validation and report synthesis. We replaced it with deterministic Python. Quality went up. Cost went down. Every validation failure has a stack trace.
**Rule of thumb**: If you can write the logic as deterministic code, do it. LLMs are for tasks where the rules can't be fully specified.

### Fail-closed vs. fail-open

**Chose**: Fail-closed. Five blocking gates halt the pipeline.
**Why**: Better to produce nothing than unreliable output. An M&A team relying on a report with unverified P0 findings is worse off than having no report at all.
**Cost**: Pipeline failures require investigation.
**Benefit**: If a report is produced, it passed all quality gates.

### Optional vector search vs. mandatory vector search

**Chose**: Optional (ChromaDB). System fully functional without it.
**Why**: Keyword search and agent tool access are sufficient for 400 documents. Vector search adds value for semantic queries ("find clauses similar to this indemnification") but is not necessary for the core analysis pipeline.
**Reconsidering at**: 500+ documents, or when cross-document semantic patterns become a primary analysis mode.

---

## 11. Research Foundations

Every major design decision maps to published research or production retrospective findings.

### Accuracy and retrieval

| Finding | Source | Application |
|---------|--------|------------|
| Focused analysis outperforms full context: 74% → 95% F1 | Addleshaw Goddard, 510 CUAD contracts, 2024 | Agents use targeted tools, not full document dumps. Map-merge-resolve chunks at 150K chars. |
| Clause-aware chunking outperforms fixed-size | Addleshaw Goddard, 2024 | Split at page/paragraph boundaries, not arbitrary character counts. 15% overlap preserves clause context. |
| Document-order chunks preserve structural context | Addleshaw Goddard, 2024 | Retrieved chunks sorted by position, not similarity score. |
| Provision-specific prompts outperform generic | Addleshaw Goddard, 2024 | Each specialist has domain-specific extraction guidance with difficulty ratings per clause type. |
| Accusatory follow-up prompts improve accuracy +9.2% | Addleshaw Goddard, 2024 | Judge uses adversarial framing ("This finding appears fabricated. Prove it.") — polite verification has near-zero effect. |
| "Not found" option reduces hallucination | Addleshaw Goddard, 2024 | Every agent prompt includes explicit NOT_FOUND protocol. Without it, models fabricate clauses. |

### Hallucination and trust

| Finding | Source | Application |
|---------|--------|------------|
| Legal AI hallucination: 17-33% | Stanford, Magesh et al., 2025 | Justification for 6-layer verification stack. Single defense is insufficient. |
| GPT-4 legal hallucination: 58-80% | Stanford, Magesh et al., 2025 | Citation verification is mandatory, not optional. |
| Longer answers correlate with more hallucinations | Stanford, Magesh et al., 2025 | Constrained structured output via Pydantic schemas. |
| RAG reduces but doesn't eliminate hallucination | Stanford, Magesh et al., 2025 | Multiple independent verification layers required. |

### Context and retrieval engineering

| Finding | Source | Application |
|---------|--------|------------|
| Context metadata reduces retrieval failures 49% | Anthropic, Contextual Retrieval, 2024 | Document-level summaries prepended to chunks. |
| Contextual retrieval + reranking reduces failures 67% | Anthropic, 2024 | Reranking of vector results when ChromaDB is enabled. |
| "Lost-in-the-middle": middle content recalled at lower rates | Liu et al., 2023 | Critical instructions at prompt start/end. Subject data in middle. |
| 200K context models degrade beyond ~80K tokens | Anthropic internal benchmarks | 80K token ceiling enforced for reliable instruction-following. |
| Legal boilerplate causes retrieval from wrong document | Reuter et al., 2025 | Source metadata in every chunk. Filter by document before ranking. |

### Domain-specific challenges

| Finding | Source | Application |
|---------|--------|------------|
| Cap on Liability is hardest clause to extract (0.67 F1) | Addleshaw Goddard, 2024 | Higher verification intensity for high-difficulty provisions. |
| Termination for Convenience: 0.93 F1 difficulty | Addleshaw Goddard, 2024 | TfC disaggregated into subtypes with specific severity rules. |
| Excel date serial numbers misinterpreted | LangChain/eparse, 2024 | Pre-convert to ISO-8601 in extraction. |
| Currency unit ambiguity ("$120" could be $120 or $120K) | LangChain/eparse, 2024 | Extract units + column headers. Finance agent verifies units. |
| Map-reduce outperforms "stuff" for >100 row spreadsheets | LangChain/eparse, 2024 | Chunked analysis for large tabular data. |

### Error compounding

| Finding | Source | Application |
|---------|--------|------------|
| 10% per-step error × 10 steps = 34.9% success rate | Production retrospective | 5 blocking gates with deterministic validation at each. Independent verification at every phase boundary. |
| All 17 production failures were instruction-following | Production retrospective, ~200 subjects | Python orchestration replaces LLM-directed flow. Hooks enforce boundaries programmatically. |

---

*This document reflects the architecture as of v0.5.0. For implementation details, see the spec docs in `docs/plan/`. For the 35-step pipeline specification, see `docs/plan/05-orchestrator.md`. For search module details, see `docs/search-guide.md`.*
