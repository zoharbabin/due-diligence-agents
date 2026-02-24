# Document Extraction for LLM Analysis: Knowledge Base

> Lessons learned, requirements, edge cases, and best practices from building
> and operating the `dd-agents` forensic due-diligence pipeline against
> real-world M&A data rooms (Data Room A: 431 files / 183 customers;
> Data Room B: 995 files / 37 customers).

---

## Table of Contents

1. [Core Requirements](#1-core-requirements)
2. [The Extraction Fallback Chain](#2-the-extraction-fallback-chain)
3. [Page Markers and Structural Preservation](#3-page-markers-and-structural-preservation)
4. [Scanned PDF Detection](#4-scanned-pdf-detection)
5. [Chunking for LLM Context Windows](#5-chunking-for-llm-context-windows)
6. [Citation Accuracy](#6-citation-accuracy)
7. [Completeness Enforcement](#7-completeness-enforcement)
8. [LLM Output Normalization](#8-llm-output-normalization)
9. [Caching and Incremental Re-extraction](#9-caching-and-incremental-re-extraction)
10. [Quality Tracking and Observability](#10-quality-tracking-and-observability)
11. [Bugs Found in Production](#11-bugs-found-in-production)
12. [Edge Cases Catalog](#12-edge-cases-catalog)
13. [Prompt Engineering for Contract Analysis](#13-prompt-engineering-for-contract-analysis)
14. [Constants and Thresholds Reference](#14-constants-and-thresholds-reference)
15. [Architecture Decisions](#15-architecture-decisions)
16. [Alternative Extraction Libraries Evaluation](#16-alternative-extraction-libraries-evaluation)
17. [Visual Grounding and Source Attribution](#17-visual-grounding-and-source-attribution)
18. [Structured LLM Output Techniques](#18-structured-llm-output-techniques)
19. [Pipeline Improvement Roadmap](#19-pipeline-improvement-roadmap)
20. [Future Research Areas](#20-future-research-areas)

---

## 1. Core Requirements

### 1.1 Non-Negotiable Principles

These were established early and validated by production failures:

1. **100% document coverage** — Every file in the data room must be
   extracted. No file is silently skipped due to format, size, or
   extraction difficulty. Failures are recorded, never hidden.

2. **Structural fidelity** — Page boundaries, section numbers, paragraph
   breaks, and document hierarchy must survive extraction. LLMs need this
   structure for accurate citations and precedence reasoning.

3. **Citation-grade output** — Extracted text must support exact page
   number, section reference, and verbatim quote citations. This means
   page markers must be injected during extraction, not inferred later.

4. **Deterministic reproducibility** — Same input files must produce
   identical extractions. SHA-256 content hashing drives the cache, not
   timestamps or file metadata.

5. **Graceful degradation** — When a primary extraction method fails, the
   system falls through to lower-fidelity methods rather than producing
   nothing. A 0.5-confidence OCR extraction is infinitely more useful
   than a 0.0-confidence blank.

6. **Completeness over perfection** — Every customer in the input must
   appear in the output. Every question must get an answer. Missing data
   is flagged visually (orange/red in Excel), never silently dropped.

### 1.2 What "100% Coverage" Actually Means

In practice, 100% coverage requires:

- A fallback chain deep enough to handle every file format encountered
- Cache quality gates that reject near-empty cached output
- Text density checks that catch scanned PDFs masquerading as text PDFs
- Per-page density thresholds, not just total character counts
- Explicit tracking of skipped files so reviewers know what was missed

---

## 2. The Extraction Fallback Chain

### 2.1 Design Principle

Each file type has an ordered sequence of extraction methods. The first
method to produce output above the quality threshold wins. Every method
attempted is recorded in the `fallback_chain` array for auditability.

### 2.2 PDF Fallback Chain (Most Complex)

```
Step 1: pymupdf (page-aware, injects --- Page N --- markers)
  ↓ fails density check? (<500 chars total, or <50 chars/page)
Step 2: pdftotext (poppler CLI, converts \f to page markers)
  ↓ fails density check? (<500 chars total, or <50 chars/page)
Step 3: markitdown (handles edge-case PDFs, no page markers)
  ↓ fails threshold? (<100 chars) OR fails readability gate? (<85% printable)
Step 4: pytesseract OCR (page-by-page image OCR, injects markers)
  ↓ fails threshold? (<20 chars)
Step 5: Direct text read (UTF-8 → latin-1, last resort)
  ↓ fails threshold? (<20 chars)
FAILED — confidence 0.0
```

**Confidence scores per method:**

| Method | Confidence | Page Markers | Notes |
|--------|-----------|--------------|-------|
| pymupdf | 0.9 | Yes | Best quality, preserves layout |
| pdftotext | 0.7 | Yes (from \f) | Good for form-heavy PDFs |
| markitdown | 0.5 | No | Catches edge cases pymupdf misses |
| pytesseract | 0.6 | Yes | Slow but handles scanned docs |
| Direct read | 0.5 | No | PDF binary → mostly garbage |
| Failed | 0.0 | N/A | All methods exhausted |

### 2.3 Office Document Chain

```
Step 1: markitdown (handles .docx, .doc, .xlsx, .xls, .pptx, .rtf)
  ↓ fails? (<20 chars)
Step 2: macOS textutil (Darwin only, .doc/.docx/.rtf/.html/.odt)
  ↓ fails or not macOS?
Step 3: Direct text read (UTF-8 → latin-1)
  ↓ fails? (<20 chars)
FAILED
```

### 2.4 Image Chain

```
Step 1: markitdown (OCR mode)
  ↓ fails? (<20 chars)
Step 2: pytesseract
  ↓ fails? (<20 chars)
Step 3: Diagram placeholder (records that image exists but is unreadable)
  → confidence 0.3
```

### 2.5 Plain Text (No Chain Needed)

Direct read with UTF-8, fallback to latin-1 with error replacement.
Confidence: 0.5.

### 2.6 Key Lesson: Every Step Needs the Same Quality Gate

The initial implementation used different thresholds at different steps
(20 chars for pdftotext, 100 chars for pymupdf). This caused scanned PDFs
to "pass" pdftotext with 20-150 chars of signature fragments and never
reach OCR. **All steps in the PDF chain now use the same density check.**

---

## 3. Page Markers and Structural Preservation

### 3.1 The Page Marker Format

```
\n--- Page N ---\n
```

Where N is the 1-indexed page number. This format was chosen because:

- It is unambiguous (unlikely to appear in contract text)
- It is human-readable in the extracted `.md` files
- It is machine-parseable via regex: `\n--- Page (\d+) ---\n`
- It works as a chunking boundary for large documents
- It enables exact page citations by the LLM

### 3.2 Where Page Markers Are Injected

| Extraction Method | Marker Source |
|-------------------|---------------|
| pymupdf | `page.get_text()` per page, marker injected between pages |
| pdftotext | Form-feed characters (`\f`) converted to markers |
| pytesseract OCR | Each page image gets a marker before its OCR text |
| markitdown | **No markers** — this is a known limitation |
| Direct read | **No markers** |

### 3.3 Why This Matters for LLMs

Without page markers, the LLM cannot:
- Cite specific page numbers (essential for legal review)
- Reason about document sections that span pages
- Be verified by a human reviewer looking at the original PDF

The prompt explicitly instructs the LLM:
> "Page numbers: PDF documents contain '--- Page N ---' markers. Use these
> to determine the exact page number for each citation."

### 3.4 Counting Pages Without Re-Opening the PDF

Rather than opening the PDF twice (once for extraction, once for page
count), we count page markers in the extracted text:

```python
import re
markers = re.findall(r"\n--- Page \d+ ---\n", text)
page_count = len(markers) if markers else 1
```

This is used for the density check (chars/page) without additional I/O.

### 3.5 Document Hierarchy Preservation

Beyond page markers, the system preserves:

- **Section numbers** — appear naturally in extracted text (e.g., "12.3")
- **Paragraph breaks** — double newlines preserved by all extraction methods
- **Document headers** — each file gets a `## Document: {path}` header
- **File path context** — enables LLM to reason about document type (MSA vs
  amendment vs PO) from filename keywords

---

## 4. Scanned PDF Detection

### 4.1 The Problem

Scanned PDFs are the single largest source of extraction failures.
They look like PDFs but contain images of text, not selectable text.
Text extractors (pymupdf, pdftotext) return near-empty output.

**Real-world examples from production:**

| Customer | File | Source Size | pymupdf Chars | Root Cause |
|----------|------|-------------|---------------|------------|
| Customer G | PO | 567 KB | 0 | Pure image scan |
| Customer N | PO | 1.2 MB | 0 | Pure image scan |
| Customer E | MSA + 3 POs | 0.9–18.7 MB | 0 | Pure image scan |
| Customer D1 | 2 MSSAs | 1.5 MB ea | 401 | Sparse headers across 32 pages |
| Customer D2 | Signed PO | 240 KB | 68 | Signature fragment only |
| Customer B | Asset Purchase | 357 KB | 42 | Signature fragment only |
| Customer NF | NDA | 1.9 MB | 49 | Signature fragment only |

### 4.2 Detection Strategy: Two-Level Check

**Level 1 — Absolute threshold:**
```python
_SCANNED_PDF_THRESHOLD = 100  # chars
```
Any extraction returning < 100 characters is rejected immediately.

**Level 2 — Per-page density:**
```python
_MIN_CHARS_PER_PAGE = 50  # chars per page
```
A multi-page PDF might extract > 100 chars total but still be scanned.
Example: Customer D1 extracted 401 chars across 32 pages = 12.5
chars/page (scattered headers/footers). The density check catches this:

```python
is_dense_enough = (
    text_len >= _MIN_EXTRACTION_CHARS  # 500 chars (Bug H fix)
    and (page_count <= 1 or text_len / page_count >= _MIN_CHARS_PER_PAGE)
)
```

### 4.3 Why Both Checks Are Needed at Every Step

Initially, the density check was only applied to pymupdf output. But
pdftotext can also return sparse text from scanned PDFs (signature
fragments, header/footer text). Customer D2's Signed PO returned 151 chars via
pdftotext — above the 100-char threshold but clearly not a real
extraction. **Both pymupdf and pdftotext now apply the density check.**

### 4.4 The Signature Fragment Problem

Many scanned PDFs contain a small amount of real text: the signature
block at the end. This produces 20-150 chars of "John Smith, VP Sales,
Date: 2024-01-15" which passes naive character count thresholds but
represents < 1% of the document's actual content.

**Solution:** The density check (50 chars/page) rejects these because
a 10-page signed PO with 150 chars of signature text = 15 chars/page,
well below the 50 char/page threshold.

### 4.5 OCR Configuration

When OCR is triggered:

- **DPI:** 300 (balances quality vs speed)
- **Language:** English (`eng`) — hardcoded, limitation for non-English docs
- **Page cap:** 50 pages maximum for OCR (prevents runaway processing)
- **Per-page timeout:** 30 seconds
- **Format:** PDF → PNG images → pytesseract → text with page markers

---

## 5. Chunking for LLM Context Windows

### 5.1 Why Chunking Is Necessary

A single customer may have an 18.7 MB MSA or 38 files totaling
millions of characters (38 chunks). LLM context windows
(~200K tokens for Claude) cannot fit everything at once.

### 5.2 Constants

```python
TARGET_CHUNK_CHARS = 150_000   # ~50K tokens, safe within 200K window
MAX_CHUNK_CHARS = 400_000      # Hard ceiling
OVERLAP_RATIO = 0.15           # 15% overlap between chunks
MAX_OVERLAP_CHARS = 60_000     # Cap on overlap size
```

The 15% overlap ratio comes from the Addleshaw Goddard RAG Report (2024),
which found this optimal for preserving cross-boundary context in legal
document analysis.

### 5.3 Splitting Strategy

**For documents with page markers (PDFs):**
1. Parse `--- Page N ---` markers into page groups
2. Fill chunks up to `TARGET_CHUNK_CHARS`
3. Add 15% overlap from trailing pages of the previous chunk
4. Track `start_page`, `end_page`, `total_pages` per segment
5. Mark segments as `is_partial=True` with `part_number` / `total_parts`

**For documents without page markers (Office docs, text files):**
1. Split at `\n\n` (paragraph breaks) — preferred
2. Fallback: split at `\n` (line breaks)
3. Fallback: split at `". "` (sentence boundaries)
4. Last resort: hard character break at `TARGET_CHUNK_CHARS`

### 5.4 Bin-Packing Multiple Files

Small files from the same customer are packed into a single chunk:

```
Chunk 1: [msa.pdf (80K chars)] + [amendment.docx (30K chars)] + [nda.pdf (20K chars)]
Chunk 2: [sow_v1.pdf (full, 150K chars)]
Chunk 3: [large_exhibit.pdf part 1 (pages 1-50, 140K chars)]
Chunk 4: [large_exhibit.pdf part 2 (pages 45-100, 145K chars, 15% overlap)]
```

### 5.5 What the LLM Sees

Each chunk prompt includes metadata so the LLM knows it is seeing a subset:

```
# Customer: Acme Corp (Group: Above 200K)

**Analysis Part 2 of 4**
You are reviewing a SUBSET of this customer's documents.
If a question cannot be answered from the documents below,
answer "NOT_ADDRESSED" — another chunk may contain the answer.

---
## Document: Above 200K/Acme Corp/msa.pdf (Pages 45-90 of 200, Part 2 of 4)
---
[extracted text]
```

### 5.6 Multi-Chunk Analysis Flow (4 Phases)

```
Phase 1 — MAP:    Analyze each chunk independently → N partial results
Phase 2 — MERGE:  Mechanically combine results (priority: YES > NO > NOT_ADDRESSED)
Phase 3 — SYNTH:  If chunks DISAGREE (YES vs NO), ask LLM to resolve with all evidence
Phase 4 — VALID:  If any NOT_ADDRESSED remains, re-query with targeted follow-up
```

**Phase 2 merge rules:**
- Answer priority: YES (3) > substantive free-text (2) = NO (2) > NOT_ADDRESSED (1)
- When tied at same priority: prefer the longer, more substantive answer
- Conflict detection: if both YES and NO present → trigger Phase 3
- Citation deduplication: key = `(file_path, page, section_ref, exact_quote)`

---

## 6. Citation Accuracy

### 6.1 Citation Structure

Every answer must include zero or more citations with these fields:

```json
{
  "file_path": "Above 200K/Acme Corp/msa.pdf",
  "page": "15",
  "section_ref": "Section 12.3",
  "exact_quote": "The Supplier shall not assign this Agreement..."
}
```

### 6.2 How Page Numbers Work End-to-End

```
1. pymupdf extracts text per page, injects "--- Page N ---" markers
2. Chunker splits at page boundaries, tracks start_page/end_page
3. Chunk prompt tells LLM: "Pages 15-30 of 80, Part 2 of 4"
4. System prompt instructs: "Use --- Page N --- markers for page numbers"
5. LLM returns citations with page numbers from markers
6. Excel writer places page in "Page" column of Details sheet
```

### 6.3 Section Reference Extraction

The LLM extracts section references naturally from contract text:
- "Section 12.3", "Article IV", "Clause 8(a)", "Schedule B"
- The system prompt instructs: cite with `section_ref` (e.g., "Section 12.3")

### 6.4 Exact Quote Verification

The `exact_quote` field contains verbatim text from the document. This
enables human reviewers to:
- Verify the LLM's interpretation
- Find the clause in the original document
- Assess quote accuracy (hallucination detection)

### 6.5 Citation Deduplication

Citations are deduplicated at two levels using a 4-tuple key:

```python
key = (citation.file_path, citation.page, citation.section_ref, citation.exact_quote)
```

This preserves distinct quotes from the same page/section (e.g., two
different clauses on the same page) while eliminating true duplicates.

Dedup is applied via the shared `dedup_citations()` function at:

1. **Parse time** — inside `parse_column_result()`, so every LLM
   response (map, synthesis, validation) gets deduped immediately
2. **Merge time** — in `_merge_chunk_results()`, deduping citations
   collected across multiple chunks

This two-level approach ensures consistent dedup for both single-chunk
customers (parse-time only) and multi-chunk customers (parse + merge).

### 6.6 Known Citation Limitations

1. **markitdown extractions lack page markers** — citations from markitdown-
   extracted files cannot include page numbers
2. **OCR text quality** — exact quotes from OCR may contain character
   recognition errors
3. **Synthesis truncation** — the synthesis pass truncates `exact_quote` to
   200 chars for compactness in the conflict resolution prompt

### 6.7 Citation Verification (Issue #5)

After analysis, all citations are verified against extracted source text
using `rapidfuzz.fuzz.partial_ratio`. This runs locally — no API calls.

**Core configuration:**
- **80% threshold** — quotes scoring >= 80 are marked as verified.
  This tolerates OCR character-level errors while catching fabricated text.
- **Whitespace normalization** — all whitespace (newlines, tabs, multiple
  spaces) is collapsed to single spaces before comparison, handling line
  breaks from PDF column layout, OCR, and markitdown reformatting.
- **Section verification** — substring check for `section_ref` in the
  full document text (any file in the customer's set).
- **Non-blocking** — verification failures populate metadata fields but
  never block the pipeline.

**Progressive search scope (Issue #24):**

Quote verification uses a 4-level progressive search to maximize recall
while keeping attribution accurate:

1. **Page-scoped** — search within the cited page only (fastest, most
   precise attribution).
2. **Adjacent pages (+-1)** — expand to neighboring pages. Catches
   cross-page quotes and off-by-one page citations from the LLM.
3. **Full document** — search the entire source file. Catches quotes
   where the page number is wrong but the file is correct.
4. **Cross-file** — search ALL files in the customer's text set. Catches
   file misattributions from the LLM merge phase. When found, the
   citation's `file_path` and `page` are automatically corrected.

**Production results (Data Room B, 37 customers):**
- 244 citations verified (99.6%)
- 1 citation unverified (OCR artifact, score 71)
- 136 citations unverifiable (no exact_quote provided — expected)

Fields on `SearchCitation`:
- `quote_verified: bool | None` — True if found, False if not, None if
  nothing to verify (empty quote)
- `quote_match_score: float` — fuzzy match score (0-100)
- `section_verified: bool | None` — True if section_ref found in source

---

## 7. Completeness Enforcement

### 7.1 Customer Completeness

**Guarantee:** Every customer in the input list appears in the output,
even if analysis completely fails.

Implementation:
```python
# Safety net: exceptions wrapped, never raised
try:
    result = await self._analyze_customer(customer)
except Exception as exc:
    result = SearchCustomerResult(
        customer_name=customer.name,
        error=f"Unexpected error: {exc}",
    )

# Post-analysis assertion
if len(final) != len(customers):
    logger.error("COMPLETENESS VIOLATION: %d in, %d out", ...)
```

### 7.2 Question Completeness

**Guarantee:** Every question gets an answer for every customer.

The system prompt demands:
> "Your JSON response MUST contain exactly these keys: {column_names}.
> If a question is not addressed in any document, you MUST still include
> the key with answer 'NOT_ADDRESSED' — do NOT omit it."

If the LLM omits a column anyway, it is tracked:
```python
incomplete_columns.append(col.name)
columns[col.name] = SearchColumnResult(
    answer="INCOMPLETE — not returned by model",
)
```

### 7.3 File Completeness

**Guarantee:** Every file is accounted for in the report.

- `files_analyzed` / `total_files` shown as "X/Y" in Excel
- `skipped_files` listed by name in the Excel report
- Empty/missing extractions logged and counted

### 7.4 The Systemic Failure Gate

If > 50% of non-plaintext files fail extraction:

```python
if failure_rate > 0.50:
    raise ExtractionPipelineError(
        f"Systemic extraction failure: {primary_failures}/{total_non_plaintext} "
        f"files ({failure_rate:.0%}) failed."
    )
```

This is a hard stop — something is fundamentally wrong (missing
dependencies, corrupted data room, permission issues).

### 7.5 External Reference Completeness (Issue #15)

Contracts that incorporate external T&Cs by URL are a known accuracy gap.
The pipeline now includes a post-extraction step that:

1. Scans all `.md` files in `text_dir` for URL patterns
2. Filters to T&C-like URLs using path keyword heuristics
   (terms, conditions, policy, SLA, EULA, privacy, legal, etc.)
3. Downloads via `urllib.request` (stdlib, no new deps)
4. Extracts text via `markitdown` (existing dep)
5. Caches to `text_dir` with `__external__<slug>.md` naming

This step is **non-blocking**: download failures are logged as warnings
but never halt the pipeline. On re-runs, cached files are skipped.

---

## 8. LLM Output Normalization

### 8.1 The Confidence Casing Bug

The system prompt instructs: `"confidence": "<HIGH|MEDIUM|LOW>"`. But LLMs
return "High", "high", "HIGH", "Medium", etc. unpredictably.

**Lesson learned:** Normalize at EVERY point where LLM output is consumed,
not just at the initial parse. We initially added `.upper()` at parse time
(Phase 1) and merge time (Phase 2), but missed the synthesis pass (Phase 3)
and validation pass (Phase 4). This caused 53% of confidence values in the
a production retest to remain mixed-case.

**Fix (final):** Confidence normalization is now centralized in the Pydantic
`field_validator` on `SearchColumnResult.confidence`. All four phases (map,
merge, synthesis, validation) route through `parse_column_result()` which
triggers the validator automatically. No manual `.upper()` needed.

### 8.2 Answer Normalization (Issue #24)

LLMs sometimes return free-text answers instead of the requested
YES/NO/NOT_ADDRESSED format. The `_normalize_answer()` function in
`models/search.py` detects 10 non-standard prefixes and maps them to
NOT_ADDRESSED:

```python
_NOT_ADDRESSED_PREFIXES = (
    "UNABLE TO DETERMINE",
    "CANNOT DETERMINE",
    "CANNOT BE DETERMINED",
    "UNABLE TO ASSESS",
    "INSUFFICIENT INFORMATION",
    "NOT ENOUGH INFORMATION",
    "COULD NOT DETERMINE",
    "COULD NOT BE DETERMINED",
    "NOT DETERMINABLE",
    "INDETERMINATE",
)
```

**Normalization rules:**
- Standard answers (YES, NO, NOT_ADDRESSED) are returned as-is
  (preserving original casing for free-text that starts with YES/NO)
- Any answer starting with a recognized prefix is replaced with
  NOT_ADDRESSED
- All other answers are whitespace-stripped but otherwise preserved

**Applied at every entry point:** Normalization runs inside
`parse_column_result()` which is called by all four pipeline phases.
This was critical — the initial implementation only normalized in the
map phase, but the validation phase re-queries Claude which returns
the same non-standard text again, bypassing the normalization.

### 8.3 Verbose NOT_ADDRESSED Detection

The LLM sometimes returns:
> "NOT_ADDRESSED. The portions of the agreement reviewed (Part 1 of 4)
> do not contain an explicit obligation..."

This must be treated as NOT_ADDRESSED (priority 1), not as substantive
free-text (priority 2). Detection in the merge phase:

```python
if answer_upper.startswith("NOT_ADDRESSED") or answer_upper.startswith("NOT ADDRESSED"):
    priority = 1  # Not substantive
```

This is separate from the `_normalize_answer()` normalization above —
the merge phase needs to detect verbose NOT_ADDRESSED for priority
ranking, while `_normalize_answer()` handles non-standard phrasings
that don't start with "NOT_ADDRESSED" at all.

### 8.4 JSON Extraction from LLM Output

LLMs wrap JSON in markdown fences, add preamble text, or sometimes return
two JSON objects (a draft then a revision). The parser handles all cases:

1. Strip `` ```json ... ``` `` wrappers
2. Find first `{` in text
3. Use `json.JSONDecoder().raw_decode()` to extract the first complete JSON
4. Fallback: find last `}` if raw_decode fails

### 8.5 Empty JSON Rejection

An empty `{}` response means the LLM hit a context limit or failed
silently. This is rejected immediately and retried:

```python
if not data:
    return SearchCustomerResult(error="Claude returned empty JSON {}")
```

---

## 9. Caching and Incremental Re-extraction

### 9.1 Cache Design

SHA-256 content hashes stored in `sha256sum`-compatible format:

```
a1b2c3d4e5...  ./Above 200K/Acme/MSA.pdf
f7e8d9c0b1...  ./Reference Data/Customers.xlsx
```

### 9.2 Cache Hit Criteria

A file is skipped (cache hit) only if ALL of:
1. File path exists in cache
2. Current SHA-256 hash matches cached hash
3. Output `.md` file exists
4. Output file size >= 100 bytes (`_SCANNED_PDF_THRESHOLD`)
5. Output content is readable text (>= 85% printable characters)

### 9.3 The Near-Empty Output Bug (Bug A)

**What happened:** A 1-byte newline (`\n`) in the output file passed the
original cache gate (`st_size > 0`). Subsequent runs skipped re-extraction,
perpetuating the empty output forever.

**Fix:** Cache gate now requires `st_size >= 100`:

```python
# Before (Bug A):
if cache.is_cached(...) and out_file.exists() and out_file.stat().st_size > 0:

# After:
if cache.is_cached(...) and out_file.exists() and out_file.stat().st_size >= _SCANNED_PDF_THRESHOLD:
```

### 9.4 Stale Cache Cleanup

When files are removed from the data room between runs:

```python
cache.remove_stale(current_file_list)
```

Entries for deleted files are purged so the cache doesn't grow unbounded.

---

## 10. Quality Tracking and Observability

### 10.1 Per-File Quality Record

Every extraction produces a quality entry:

```json
{
  "./path/to/file.pdf": {
    "method": "primary",
    "bytes_extracted": 24500,
    "confidence": 0.9,
    "fallback_chain": ["pymupdf"],
    "timestamp": "2026-02-23T16:50:14.164489+00:00"
  }
}
```

### 10.2 What to Monitor

| Metric | Healthy | Warning | Critical |
|--------|---------|---------|----------|
| Avg confidence | > 0.85 | 0.7–0.85 | < 0.7 |
| Failed files | 0 | 1–5% | > 5% |
| OCR fallbacks | < 5% | 5–20% | > 20% |
| Bytes = 0 | 0 | Any | — |
| Chars/page < 50 | 0 | Any | — |

### 10.3 Aggregate Statistics

```python
tracker.get_stats() → {
    "total": 995,
    "by_method": {"primary": 990, "fallback_ocr": 2, ...},
    "avg_confidence": 0.89,
    "total_bytes": 45_000_000,
    "failed": 0,
}
```

### 10.4 Real-World Extraction Profile (Data Room B, 995 files)

```
primary (pymupdf/markitdown):  990 files (99.5%)  conf 0.9
fallback_pdftotext:              1 file  (0.1%)   conf 0.7
fallback_markitdown:             3 files (0.3%)   conf 0.5
fallback_ocr:                    1 file  (0.1%)   conf 0.6
failed:                          0 files (0.0%)
```

Extraction time: ~33 seconds for 995 files (33 ms/file average).

---

## 11. Bugs Found in Production

### Bug A: Cache Accepts Near-Empty Output

| | |
|---|---|
| **Symptom** | 21 files in Data Room A with 0-89 bytes extracted across runs |
| **Root cause** | Cache gate `st_size > 0` accepts 1-byte newline |
| **Fix** | `st_size >= _SCANNED_PDF_THRESHOLD` (100 bytes) |
| **Lesson** | Cache quality gates must match extraction quality thresholds |

### Bug B: pdftotext Threshold Too Low

| | |
|---|---|
| **Symptom** | Scanned PDFs with 20-149 chars of signature text accepted |
| **Root cause** | pdftotext used `_MIN_TEXT_LEN = 20` as threshold |
| **Fix** | Raised to `_SCANNED_PDF_THRESHOLD = 100` + density check |
| **Lesson** | All steps in the fallback chain need consistent thresholds |

### Bug C: Missing Per-Page Density Check

| | |
|---|---|
| **Symptom** | Customer D1: 401 chars across 32 pages (12.5 chars/page) accepted as valid |
| **Root cause** | Only total char count checked, not per-page density |
| **Fix** | Added `_MIN_CHARS_PER_PAGE = 50` density check |
| **Lesson** | Multi-page scanned PDFs can have > 100 total chars from headers/footers |

### Bug D: Confidence Not Normalized in All Phases

| | |
|---|---|
| **Symptom** | 53% of confidence values mixed-case in Data Room B Details sheet |
| **Root cause** | `.upper()` added at Phase 1 (parse) and Phase 2 (merge) but missed Phase 3 (synthesis) and Phase 4 (validation) |
| **Fix** | Added `.upper()` to all 4 code paths that read `confidence` from LLM JSON |
| **Lesson** | Normalize external data at EVERY ingestion point, not just the "main" one |

### Bug E: pdftotext Missing Density Check

| | |
|---|---|
| **Symptom** | Customer D2 Signed PO: 151 chars via pdftotext accepted (signature fragment) |
| **Root cause** | Density check applied to pymupdf but not pdftotext |
| **Fix** | Same density check (chars/page >= 50) applied to pdftotext output |
| **Lesson** | Every extraction method that returns text needs the same quality gate |

### Bug F: Verbose NOT_ADDRESSED Beats Substantive Answers

| | |
|---|---|
| **Symptom** | "NOT_ADDRESSED. The portions of the agreement..." ranked higher than real summaries during merge |
| **Root cause** | Verbose NOT_ADDRESSED treated as free-text (priority 2) instead of NOT_ADDRESSED (priority 1) |
| **Fix** | `startswith("NOT_ADDRESSED")` detection before priority assignment |
| **Lesson** | LLMs add explanatory text to structured answers; detect the intent, not just the format |

### Bug G: Markitdown Dumps Raw PDF Binary for Scanned PDFs

| | |
|---|---|
| **Symptom** | 3 files in Data Room B (Customer B1 OEM 5.4 MB, Customer C1 1.6 MB, Customer NF SOW 8.0 MB) contained raw PDF binary (`%PDF-1.3`, stream objects, binary image data) as "extracted text" |
| **Root cause** | Markitdown on image-only scanned PDFs dumps the raw PDF binary as text. The binary passes `len(text.strip()) >= 100` because binary bytes count as characters |
| **Fix** | Added `_is_readable_text()` that checks >= 85% printable character ratio. Applied at markitdown step in PDF chain and in cache gate (`_is_cached_output_readable`) |
| **Lesson** | Length thresholds alone cannot distinguish binary from text. A printable-character ratio check is essential for any extraction method that might return raw file content |

### Bug H: Stale Cache Persists Bad Extractions After Code Fixes

| | |
|---|---|
| **Symptom** | Customer D2 Signed PO (151 bytes) persisted through cache despite new pdftotext density check being deployed |
| **Root cause** | Cache gate only checked `st_size >= 100` and hash match — 151 bytes passes. New extraction logic never ran because cache hit returned first |
| **Fix** | Added `_is_cached_output_readable()` to cache gate; also deleted stale `.md` output files to force immediate re-extraction |
| **Lesson** | Cache gates must be upgraded alongside extraction logic. When deploying new quality checks, delete stale outputs for affected files |

---

## 12. Edge Cases Catalog

### 12.1 File Format Edge Cases

| Edge Case | Handling |
|-----------|----------|
| Empty PDF (0 bytes) | All methods fail → confidence 0.0, recorded as failed |
| Encrypted PDF | pymupdf/pdftotext fail → markitdown may succeed → OCR as last resort |
| PDF with only images | pymupdf returns ~0 chars → density check fails → OCR triggered |
| Scanned PDF → markitdown binary dump | markitdown returns raw PDF binary → `_is_readable_text()` rejects (< 85% printable) → OCR triggered |
| Multi-page scanned PDF with headers | Total chars > 100 but chars/page < 50 → density check catches it |
| Signed PDF (signature fragment only) | 20-150 chars extracted → density check rejects → OCR |
| .doc (legacy Word) | markitdown → macOS textutil → direct read |
| .xlsx with merged cells | markitdown handles; future: openpyxl smart extraction |
| Corrupt/truncated file | All methods fail gracefully → confidence 0.0 |
| Non-UTF-8 encoding | UTF-8 with error replacement → latin-1 fallback |
| Filename with Unicode/spaces | Safe name conversion: `/` → `__`, length cap with hash |
| Filename > 200 chars | Truncated with SHA-256 suffix for uniqueness (macOS 255-byte limit) |
| macOS resource forks (`__MACOSX`) | Excluded from file discovery |

### 12.2 LLM Response Edge Cases

| Edge Case | Handling |
|-----------|----------|
| Empty response `{}` | Rejected, retried up to 3 times |
| Markdown-fenced JSON | Fences stripped before parsing |
| Preamble text before JSON | First `{` found and parsed |
| Two JSON objects concatenated | `raw_decode()` extracts only the first |
| Missing columns in response | Tracked as `incomplete_columns`, flagged in Excel |
| Non-transient API error | "Prompt is too long", "context length" → no retry |
| Transient API error | Exponential backoff: 2, 4, 8 seconds |
| Cancel-scope RuntimeError | SDK bug suppressed, partial results used if available |
| Mixed-case confidence | `.upper()` normalization at all 4 phases |
| Verbose NOT_ADDRESSED | `startswith()` detection, downgraded to priority 1 |

### 12.3 Chunking Edge Cases

| Edge Case | Handling |
|-----------|----------|
| Single file fits in one chunk | No chunking, skip Phases 2-4 |
| File larger than MAX_CHUNK_CHARS | Split at page boundaries with overlap |
| No page markers in text | Paragraph-based splitting (`\n\n` → `\n` → `". "` → hard break) |
| Continuous text with no breaks | Hard character break at TARGET_CHUNK_CHARS |
| Single page exceeds target | Included as-is (no sub-page splitting) |
| 38+ chunks for one customer | All chunks analyzed sequentially, merged, synthesized |
| Overlap larger than MAX_OVERLAP | Capped at 60K chars |
| Empty file list | Returns empty chunk list |

### 12.4 Cache Edge Cases

| Edge Case | Handling |
|-----------|----------|
| First run (no cache) | All files extracted |
| File modified between runs | SHA-256 mismatch → re-extracted |
| File deleted between runs | Stale entry removed from cache |
| Output file deleted but cache exists | `out_file.exists()` check → re-extracted |
| Output file near-empty but cached | `st_size >= 100` check → re-extracted |
| Cache file corrupt/missing | Loaded as empty, all files re-extracted |

---

## 13. Prompt Engineering for Contract Analysis

### 13.1 System Prompt Design Principles

Based on the Addleshaw Goddard RAG Report (2024):

1. **Provision-specific prompts** — Each question targets exactly one
   contractual concept (consent, notice period, termination rights)

2. **Explicit completeness mandate** — "You MUST answer EVERY question"
   and "MUST contain exactly these keys" prevents omissions

3. **Follow-up validation language** — "Pay special attention to
   schedules, exhibits, and annexes" catches provisions buried in
   appendices

4. **Double-check instruction** — "Re-read the questions and verify you
   have not missed any relevant clause" reduces false NOT_ADDRESSED

5. **Document hierarchy reasoning** — The prompt instructs the LLM to read
   precedence/supremacy clauses within the contracts themselves, not
   assume a fixed hierarchy (MSA > SOW > PO). This is critical because
   some order forms explicitly supersede the MSA.

### 13.2 Prompt Anti-Patterns

| Anti-Pattern | Problem | Better Approach |
|-------------|---------|-----------------|
| "What are the key terms?" | Too vague, inconsistent answers | "Does this require consent? YES/NO/NOT_ADDRESSED" |
| 15 sub-questions in one prompt | LLM loses focus, omits answers | Split into separate columns |
| "List all important clauses" | Unbounded output, hallucination risk | "Does clause X exist? Cite it." |
| Assuming MSA > SOW hierarchy | Wrong for ~30% of contracts | "Read precedence clauses in the documents" |
| No answer format specification | Free-form answers, hard to aggregate | "Answer YES, NO, or NOT_ADDRESSED" |

### 13.3 Document Type Inference

The system infers document type from filename keywords to help the LLM
reason about precedence during the synthesis pass:

```python
"msa"/"master" → "MSA"
"amendment"     → "Amendment"
"sow"           → "SOW"
"order"         → "Order Form"
"nda"           → "NDA"
"exhibit"       → "Exhibit"
"addendum"      → "Addendum"
"renewal"       → "Renewal"
"side letter"   → "Side Letter"
default         → "Contract"
```

### 13.4 Multi-Chunk Prompt Adaptation

Single-chunk customers get a standard prompt. Multi-chunk customers get:

- **Phase 1 (Map):** "You are reviewing a SUBSET... answer NOT_ADDRESSED
  if the relevant information is not in this part"
- **Phase 3 (Synthesis):** "Amendments and addenda override base agreements
  they modify... look at doc_type and citation evidence"
- **Phase 4 (Validation):** "Previous analysis could NOT find answers...
  pay special attention to schedules, exhibits, annexes"

---

## 14. Constants and Thresholds Reference

### 14.1 Extraction Thresholds

| Constant | Value | Purpose |
|----------|-------|---------|
| `_MIN_TEXT_LEN` | 20 chars | Minimum for any extraction to be "non-empty" |
| `_SCANNED_PDF_THRESHOLD` | 100 chars | Cache gate minimum; markitdown fallback threshold |
| `_MIN_EXTRACTION_CHARS` | 500 chars | Density check hard minimum for pymupdf/pdftotext (Bug H fix) |
| `_MIN_CHARS_PER_PAGE` | 50 chars/page | Density check for scanned PDF detection |
| `_MIN_PRINTABLE_RATIO` | 0.85 (85%) | Readability gate — rejects binary garbage from markitdown |
| `QUOTE_MATCH_THRESHOLD` | 80 (0-100) | Citation verification fuzzy match minimum |
| `OCR_PAGE_TIMEOUT` | 30 seconds | Per-page timeout for pytesseract |
| `OCR_LAST_PAGE_CAP` | 50 pages | Maximum pages for OCR processing |
| Systemic failure gate | 50% | Pipeline halts if > 50% non-plaintext files fail |

### 14.2 Chunking Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `TARGET_CHUNK_CHARS` | 150,000 | Target chars per chunk (~50K tokens) |
| `MAX_CHUNK_CHARS` | 400,000 | Hard ceiling per chunk |
| `OVERLAP_RATIO` | 0.15 | 15% overlap between chunks |
| `MAX_OVERLAP_CHARS` | 60,000 | Cap on overlap size |

### 14.3 Analysis Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `_CHARS_PER_TOKEN` | 4 | Approximate chars per token for cost estimation |
| `_INPUT_COST_PER_MTOK` | $3.00 | Claude Sonnet 4 input pricing |
| `_OUTPUT_COST_PER_MTOK` | $15.00 | Claude Sonnet 4 output pricing |
| Max retries | 3 | API call retries per chunk |
| Default concurrency | 5 | Parallel API calls |

### 14.4 Confidence Score Scale

| Score | Meaning | Extraction Method |
|-------|---------|-------------------|
| 0.9 | Primary method succeeded | pymupdf, markitdown (Office) |
| 0.7 | First fallback | pdftotext (poppler) |
| 0.6 | OCR fallback | pytesseract |
| 0.5 | Direct text read / textutil | UTF-8 or macOS textutil |
| 0.3 | Diagram placeholder | Image that couldn't be OCR'd |
| 0.0 | Failed | All methods exhausted |

---

## 15. Architecture Decisions

### 15.1 Why Multiple Extraction Methods Instead of One

No single extraction method handles all document formats and conditions:

- **pymupdf** is fast and preserves page structure but returns nothing for
  scanned PDFs
- **pdftotext** handles form-heavy PDFs that pymupdf struggles with but
  also returns nothing for scans
- **markitdown** handles Office formats and some edge-case PDFs but
  produces no page markers
- **pytesseract** handles scanned documents but is slow and error-prone
- **Direct read** catches plain text in unexpected containers

### 15.2 Why Page Markers Instead of Metadata

Page numbers could be stored as metadata (JSON sidecar, database). But:

1. LLMs need page context inline with the text to cite accurately
2. Metadata would require a separate lookup during LLM prompting
3. Inline markers are self-contained — the `.md` file is the single
   source of truth
4. Human reviewers can read the `.md` file directly

### 15.3 Why 4-Phase Analysis Instead of Single Pass

A single pass with all documents would:
- Exceed context windows for large customers
- Produce lower-quality answers (attention dilution)
- Provide no mechanism for conflict resolution

The 4-phase approach:
- Phase 1 (Map): Each chunk gets full attention
- Phase 2 (Merge): Mechanical, deterministic, no API cost
- Phase 3 (Synth): Targeted, only for actual conflicts
- Phase 4 (Valid): Safety net for missed clauses

### 15.4 Why SHA-256 Content Hashing

- Deterministic: same content → same hash regardless of timestamp
- Collision-resistant: probability of false cache hit negligible
- Standard format: `sha256sum`-compatible file for debugging
- Fast: chunked reading (8 KB blocks) handles large files efficiently

### 15.5 Why Safe Filenames Instead of a Database

Extracted text is stored as flat `.md` files with deterministic names
derived from the source path. This means:

- No database dependency
- Files are human-readable and debuggable
- `git diff` works on the extraction output
- Any tool can read the output (not locked to our pipeline)

---

## 16. Alternative Extraction Libraries Evaluation

> Research conducted February 2026. Evaluated against our non-negotiable
> requirements: 100% coverage, structural fidelity, citation-grade page
> references, and deterministic reproducibility.

### 16.1 Current Stack Weaknesses

Our current PDF chain (pymupdf → pdftotext → markitdown → pytesseract)
has proven reliable for text-native PDFs but has structural weaknesses:

| Weakness | Impact | Root Cause |
|----------|--------|------------|
| No table structure preservation | LLM sees flattened text, loses row/column context | pymupdf `get_text()` returns plain text |
| No formula extraction | Mathematical formulas in contracts rendered as garbled text | No LaTeX/MathML support |
| markitdown binary dumps on scans | Required Bug G fix (readability gate) | markitdown not designed for scanned PDFs |
| No reading order detection | Multi-column layouts extracted column-interleaved | pymupdf follows PDF object order, not visual flow |
| Single-language OCR | Korean, Japanese, Chinese contracts → garbled | pytesseract hardcoded to `lang="eng"` |
| No layout analysis | Cannot distinguish headers, footers, sidebars from body | Extraction is purely text-based |

### 16.2 Library Comparison Matrix

Eight libraries evaluated as potential replacements or supplements to
markitdown in our fallback chain:

| Criteria | markitdown (current) | Docling (IBM) | MinerU (OpenDataLab) | PP-StructureV3 (PaddlePaddle) | LangExtract (Google) | Unstructured | AWS Textract | **GLM-OCR (Zhipu AI)** |
|----------|---------------------|---------------|---------------------|-------------------------------|---------------------|--------------|-----------------|----------------------|
| **PDF text extraction** | Basic | Layout-aware | Layout-aware | Layout-aware | LLM-driven | Layout-aware | Layout-aware (managed) | Vision-LM (image-based) |
| **Table → structured** | No | HTML/CSV | HTML/Markdown | HTML | JSON | HTML | HTML (rows/cols/merged cells) | Markdown tables |
| **Formula → LaTeX** | No | Yes | Yes | Yes | No | No | No | Yes |
| **Reading order** | No | Yes | Yes | Yes | N/A | Yes | Yes (LAYOUT API) | Yes (PP-DocLayout-V3) |
| **OCR languages** | English only | Multi-language | 109 languages | Multi-language | N/A (LLM) | Multi-language | 6 Latin (EN/FR/DE/IT/PT/ES) | 100+ languages |
| **Page markers** | No | Yes (page-level) | Yes (page-level) | Yes | N/A | Yes (element-level) | Yes (page-level) | Yes (page-level) |
| **Scanned PDF** | Binary dump (Bug G) | DocTR/EasyOCR | PaddleOCR/Tesseract | PaddleOCR | Vision LLM | Tesseract/paddle | Native OCR (managed) | Vision-LM OCR (renders to images) |
| **Formats beyond PDF** | DOCX, XLSX, PPTX, RTF | DOCX, PPTX, XLSX, HTML, images, AsciiDoc | PDF only | PDF/images only | Any (LLM) | All major formats | PDF, TIFF, PNG, JPEG only | PDF, PNG, JPG only |
| **Lossless output** | Markdown only | JSON (DoclingDocument) | Markdown + JSON | Markdown | JSON | JSON elements | JSON (blocks/tables/forms) | Markdown + JSON |
| **License** | MIT | MIT | AGPL-3.0 | Apache 2.0 | Apache 2.0 | Apache 2.0 | Proprietary (pay-per-page) | MIT (model) + Apache 2.0 (code) |
| **Python install** | `pip install` | `pip install docling` | `pip install magic-pdf` | `pip install paddlepaddle paddleocr` | `pip install langextract` | `pip install unstructured` | `pip install boto3` | `ollama pull glm-ocr` |
| **GPU required** | No | Optional (faster) | Optional | Optional | No (API-based) | Optional | No (cloud-managed) | No (0.9B runs on CPU; GPU faster) |
| **Benchmark (OmniDocBench)** | N/A | 0.589 EN edit distance | 0.238 EN edit distance | **0.145 EN edit distance** | N/A | N/A | N/A (proprietary) | **94.62 OmniDocBench V1.5** (#1) |

### 16.3 Docling (IBM, Open Source)

**Repository:** github.com/docling-project/docling (MIT license)

**Architecture:** PDF → layout analysis (DocLayNet) → cell detection →
table structure recognition → OCR (DocTR or EasyOCR) → DoclingDocument
JSON → export to Markdown/HTML/DOCX.

**Strengths:**
- Lossless `DoclingDocument` JSON preserves full document structure
  (headings, paragraphs, tables, figures, code blocks, formulas)
- Built-in table structure recognition with HTML output
- Formula recognition (experimental)
- Native integration with LangChain (`DoclingLoader`) and LlamaIndex
  (`DoclingReader`)
- Multi-format support: PDF, DOCX, PPTX, XLSX, HTML, images, AsciiDoc,
  Markdown
- Page-level metadata on every element (enables exact page citations)
- Chunking built-in: `HybridChunker` with configurable token limits and
  overlap — could replace our custom chunking logic
- Active IBM Research maintenance

**Weaknesses:**
- Worst OmniDocBench score among layout-aware libraries (0.589 EN edit
  distance vs PP-StructureV3's 0.145 — 4x worse accuracy)
- Slower than MinerU on large documents (layout model overhead)
- Formula recognition still experimental
- Custom model requires fine-tuning for specialized document layouts

**Relevance to dd-agents:**
- Could replace markitdown as the Office document extractor (DOCX, PPTX,
  XLSX) while preserving table structure
- Built-in chunker could simplify our chunking pipeline
- But PDF extraction accuracy inferior to MinerU and PP-StructureV3

### 16.4 MinerU (OpenDataLab)

**Repository:** github.com/opendatalab/MinerU (AGPL-3.0 license)

**Architecture:** Three backends:
1. **Pipeline** (traditional): Layout detection → OCR → reading order →
   formula recognition → table recognition → Markdown/JSON output.
   Accuracy: 82+ on OmniDocBench.
2. **Hybrid** (PDF.js + model): Faster, text-layer aware. 85+ accuracy.
3. **VLM** (vision language model): Uses Qwen2.5-VL or similar for
   end-to-end understanding. 90+ accuracy on complex documents.

**Strengths:**
- 109-language OCR via PaddleOCR — solves our Korean/Japanese limitation
- Reading order detection — solves multi-column layout issues
- Formula → LaTeX conversion
- Table → HTML/Markdown with cell-level structure
- Page-level output with coordinates (bounding boxes)
- Three accuracy tiers: pipeline (fast), hybrid (balanced), VLM (best)
- 0.238 EN edit distance on OmniDocBench (2.5x better than Docling)
- Active development with frequent releases

**Weaknesses:**
- AGPL-3.0 license — requires open-sourcing derivative works or
  purchasing commercial license. This is a **blocker for proprietary
  deployment** unless used as a standalone service
- PDF-only — does not handle DOCX, XLSX, PPTX (we still need
  markitdown or Docling for Office formats)
- Heavier dependencies (PaddleOCR, PyTorch models)
- VLM backend requires GPU for reasonable speed

**Relevance to dd-agents:**
- Best candidate for replacing pymupdf + pytesseract in the PDF chain
- 109-language OCR directly solves the Korean MSA problem
- Reading order detection eliminates multi-column interleaving
- AGPL license needs legal review before adoption

### 16.5 PP-StructureV3 / PaddleOCR (PaddlePaddle)

**Repository:** github.com/PaddlePaddle/PaddleOCR (Apache 2.0 license)

**Architecture:** Layout detection (RT-DETR) → region classification →
per-region processing: text OCR, table recognition (SLANeXt), formula
recognition (UniMERNet), chart understanding → Markdown output.

**Benchmark results (OmniDocBench, February 2025):**

| Library | EN Edit Distance ↓ | EN BLEU ↑ | EN Meteor ↑ |
|---------|-------------------|-----------|-------------|
| **PP-StructureV3** | **0.145** | **0.694** | **0.781** |
| MinerU (pipeline) | 0.238 | 0.574 | 0.685 |
| Docling | 0.589 | 0.318 | 0.445 |
| MinerU + VLM | — | — | — (90+ composite) |

PP-StructureV3 achieves **4x lower edit distance** than Docling and 1.6x
lower than MinerU's pipeline backend.

**Strengths:**
- Best-in-class accuracy on OmniDocBench across all document types
- Apache 2.0 license — no commercial restrictions
- Layout detection, table recognition, formula recognition, chart
  understanding in one integrated pipeline
- Markdown output with preserved structure
- Multi-language OCR built in
- Chart → structured data extraction (unique capability)
- Active development, backed by Baidu

**Weaknesses:**
- PaddlePaddle framework dependency (not PyTorch) — separate ecosystem
- PDF and image only — no DOCX/XLSX support
- Larger model downloads (~1-2 GB)
- Less mature Python API compared to Docling
- Documentation primarily in Chinese (English docs improving)

**Relevance to dd-agents:**
- Strongest candidate purely on extraction accuracy
- Apache 2.0 license is ideal
- Table recognition would preserve pricing tables, payment schedules
- Chart understanding could extract data from embedded diagrams
- Requires PaddlePaddle, which adds a non-trivial dependency

### 16.6 AWS Textract (Amazon)

**Service:** Managed OCR/document analysis API (proprietary, pay-per-page)

**Architecture:** Documents uploaded to S3 (async) or sent inline (sync,
single page only) → AWS-managed OCR and layout analysis → JSON response
with blocks (pages, lines, words), tables (rows, columns, merged cells),
forms (key-value pairs), signatures, and layout elements.

**Five API types:**

| API | Purpose | Price/page |
|-----|---------|------------|
| `DetectDocumentText` | Basic OCR (lines + words) | $0.0015 |
| `AnalyzeDocument` — Tables | Table extraction with cell structure | $0.015 |
| `AnalyzeDocument` — Forms | Key-value pair extraction | $0.050 |
| `AnalyzeDocument` — Layout | Reading order, headers, footers, sections | $0.015 |
| `AnalyzeDocument` — Queries | Natural language questions about the document | $0.015 + query fee |

Additional APIs: `AnalyzeExpense` (invoices/receipts, $0.01/page),
`AnalyzeID` (identity documents, $0.01/page), `AnalyzeLending`
(mortgage documents, $0.003/page).

**Strengths:**
- Table extraction with HTML-level structure (rows, columns, merged
  cells, column headers) — strongest table capability among evaluated
  options alongside PP-StructureV3
- Layout analysis API returns reading order, section headers, page
  headers/footers, titles — solves multi-column interleaving
- Form extraction (key-value pairs) useful for insurance forms,
  compliance questionnaires
- Signature detection — useful for identifying signed vs unsigned docs
- Confidence scores per word/line/cell — enables quality-aware fallback
  decisions (low-confidence blocks could trigger re-extraction)
- Bounding box coordinates for every element — enables visual grounding
- Zero infrastructure: no GPU, no model downloads, no dependency
  management
- Async API handles up to 3,000 pages / 500 MB per document

**Weaknesses:**
- Only 6 Latin languages (EN, FR, DE, IT, PT, ES) — **no CJK support**
  (Korean, Japanese, Chinese). Does not solve our Korean MSA problem
- S3 dependency for async (multi-page) processing — adds AWS credential
  management and S3 bucket provisioning to deployment
- Sync API limited to single page — impractical for multi-page contracts
- Cost at scale: a 200-customer deal with ~50 pages each = 10,000 pages.
  At $0.015/page (tables) = $150/deal; at $0.065/page (tables+forms) =
  $650/deal. Adds up for repeated runs
- Proprietary: no local/offline mode, no self-hosting, subject to AWS
  pricing changes and rate limits
- No formula/LaTeX extraction
- No DOCX/XLSX support (PDF and image formats only)
- Async workflow adds polling/callback complexity compared to
  synchronous local libraries

**Cost comparison for typical M&A deal (10,000 pages):**

| Method | Cost | Notes |
|--------|------|-------|
| pytesseract (current) | $0 | Local, free |
| Textract DetectDocumentText | $15 | Basic OCR only |
| Textract AnalyzeDocument (tables) | $150 | Tables + OCR |
| Textract AnalyzeDocument (tables + forms) | $650 | Full extraction |
| PP-StructureV3 / PaddleOCR | $0 | Local, free (GPU optional) |

**Relevance to dd-agents:**
- Best positioned as a **pytesseract replacement** (Step 4 in our PDF
  fallback chain) for scanned PDFs where local OCR produces poor results
- Table extraction valuable for pricing schedules, payment tables, and
  financial exhibits that our current chain flattens to plain text
- Confidence scores could feed into our quality gates (reject
  low-confidence extractions and trigger re-extraction with a different
  method)
- **Not recommended as default** due to cost, AWS dependency, and
  limited language support
- **Add when these triggers occur:**
  1. Table extraction accuracy matters for the analysis (pricing
     schedules, financial exhibits with complex table layouts)
  2. The deployment already runs on AWS (S3 and credentials available)
  3. Volume justifies the cost vs. manual review savings
  4. English/Western European documents dominate the deal (CJK excluded)
- **Integration point:** Add as Step 4b in the PDF chain, between
  pytesseract (Step 4) and direct-read fallback (Step 5). Gate on:
  file is scanned PDF + pytesseract confidence < threshold + AWS
  credentials available

### 16.7 GLM-OCR (Zhipu AI)

**Repository:** github.com/zai-org/GLM-OCR (MIT model + Apache 2.0 code)
**Ollama:** `ollama pull glm-ocr` (2.2 GB default, 1.6 GB q8_0)
**Hugging Face:** zai-org/GLM-OCR

**Architecture:** A 0.9B-parameter multimodal vision-language model with
a two-stage pipeline:
1. **Layout analysis** (PP-DocLayout-V3): Detects text regions, tables,
   formulas, figures, seals, code blocks on the page image.
2. **Parallel recognition** (CogViT encoder + GLM-0.5B decoder): Each
   detected region is recognized in parallel and assembled into
   structured output.

Uses Multi-Token Prediction (MTP) loss for contextual error correction
and Stable Full-Task Reinforcement Learning for layout generalization.
128K context window.

**Key difference from other OCR tools:** GLM-OCR is not a traditional
OCR engine — it is a vision-language model. It processes pages as images,
not as PDF text streams. This means it re-OCRs digitally-born PDFs
rather than extracting embedded text, which is slower but handles
scanned/degraded documents better than text-layer extraction.

**Capabilities:**
- Text recognition (print and handwriting)
- Table recognition (complex, nested, cross-page → Markdown tables)
- Formula recognition (→ LaTeX)
- Figure/chart description
- Seal/stamp recognition (circular, elliptical, irregular)
- Code block recognition with syntax awareness
- Information extraction with JSON Schema output
- 100+ languages including CJK (English, Chinese, Japanese, Korean,
  European languages)

**Benchmark results:**

| Benchmark | GLM-OCR (0.9B) | PP-StructureV3 | MinerU | Docling |
|-----------|---------------|----------------|--------|---------|
| OmniDocBench V1.5 | **94.62** (#1) | — | — | — |
| OmniDocBench V1 edit dist. | — | **0.145** | 0.238 | 0.589 |

Note: OmniDocBench V1 and V1.5 use different scoring (edit distance vs
composite score), so direct comparison is not possible. GLM-OCR ranks #1
on the V1.5 leaderboard. Independent head-to-head benchmarks against
PP-StructureV3 on identical test sets are not yet available (model
released February 2026).

**System requirements:**

| Variant | Download size | Min RAM | GPU |
|---------|--------------|---------|-----|
| `glm-ocr:latest` (bf16) | 2.2 GB | ~4 GB | Optional |
| `glm-ocr:q8_0` (quantized) | 1.6 GB | ~3 GB | Optional |

Throughput: ~1.86 pages/sec (PDF), ~0.67 images/sec (single instance).
Runs on CPU (including Apple Silicon via MLX-VLM). GPU accelerates but
is not required.

**Strengths:**
- #1 on OmniDocBench V1.5 with only 0.9B parameters — remarkable
  efficiency vs competitors at 3B–72B+
- Structured Markdown/JSON/LaTeX output (not raw text) — directly
  compatible with our page-aware chunking pipeline
- 100+ language OCR including CJK — directly solves our Korean MSA
  and Japanese contract limitations
- Table extraction to Markdown — preserves structure for pricing
  schedules and payment tables
- Formula → LaTeX — handles mathematical terms in financial exhibits
- Fully local, air-gapped capable — ideal for confidential M&A data
  rooms where data cannot leave the network
- MIT + Apache 2.0 license — no commercial restrictions
- Tiny footprint (2.2 GB) — can run alongside the rest of the pipeline
  on a standard laptop
- Ollama integration — simple localhost API, same pattern as our
  existing claude-agent-sdk calls
- Fine-tunable via LLaMA-Factory for domain-specific document layouts

**Weaknesses:**
- **Image-based processing only** — PDFs are rendered to images before
  OCR. For digitally-born PDFs with selectable text, pymupdf/pdftotext
  remain faster and more accurate. GLM-OCR should not replace text-layer
  extraction; it should replace pytesseract for scanned/degraded docs
- **100-page PDF limit** — long documents must be chunked before
  processing (our pipeline already handles this via page-level splitting)
- **No technical report yet** — training data, failure modes, and
  ablation studies are unavailable. "Coming soon" per authors
- **Young ecosystem** — released February 2026, ~40K downloads, 27
  commits, 31 open issues. Limited independent validation
- **Layout detection dependency** — pipeline relies on PP-DocLayout-V3
  as a separate stage; layout errors propagate to OCR quality
- **No embedded text extraction** — cannot use PDF text layer, always
  does visual recognition. Slower than `pdftotext` for text-native PDFs
- **Throughput** — 1.86 pages/sec is adequate for our deal sizes
  (~10,000 pages) but would need ~90 minutes for a full deal on a single
  instance (pytesseract is comparable)
- **Precision claims unverified** — "99.9% precision" in PRECISION_MODE
  lacks metric definitions or public test results

**Cost comparison (10,000-page deal):**

| Method | Cost | Hardware | Speed |
|--------|------|----------|-------|
| pytesseract (current) | $0 | CPU | ~1-2 pages/sec |
| GLM-OCR via Ollama | $0 | CPU (GPU optional) | ~1.86 pages/sec |
| AWS Textract (tables) | $150 | Cloud | ~5-10 pages/sec |
| PP-StructureV3 | $0 | CPU (GPU optional) | Varies |

**Relevance to dd-agents:**
- **Strongest candidate for replacing pytesseract** as Step 4 in the
  PDF fallback chain. Same role (scanned PDF OCR) but with structured
  output, table extraction, formula recognition, and 100+ languages
- Unlike AWS Textract: free, local, air-gapped, no cloud dependency
- Unlike PP-StructureV3: simpler deployment via Ollama (no PaddlePaddle
  framework), smaller model, MIT-licensed
- Unlike MinerU: no AGPL license concerns
- **Integration point:** Replace pytesseract as Step 4, or add as
  Step 3b (between markitdown and pytesseract). The Ollama API makes
  integration straightforward:
  ```python
  # Conceptual integration
  import ollama
  response = ollama.chat(
      model="glm-ocr",
      messages=[{
          "role": "user",
          "content": [
              {"type": "image", "url": page_image_path},
              {"type": "text", "text": "Text Recognition:"},
          ],
      }],
  )
  text = response.message.content  # Structured Markdown
  ```
- **Add when these triggers occur:**
  1. Scanned PDFs are a significant portion of the data room (>20%)
  2. Table structure matters for analysis accuracy (pricing schedules,
     financial exhibits)
  3. Non-English documents appear (Korean, Japanese, Chinese contracts)
  4. pytesseract output quality is insufficient (low density, garbled
     text from complex layouts)
- **Wait for:** Independent benchmarks confirming OmniDocBench V1.5
  results, technical report publication, and ecosystem maturation
  (currently <30 commits). Run a pilot on one deal's scanned PDFs
  before committing to pipeline integration

### 16.8 Head-to-Head Recommendation

For the dd-agents pipeline, the evaluation suggests a **hybrid approach**
rather than a single library replacement:

| Role | Current | Recommended | Rationale |
|------|---------|-------------|-----------|
| PDF text extraction (primary) | pymupdf | **MinerU hybrid** or **PP-StructureV3** | Layout-aware, reading order, 2-4x better accuracy |
| PDF OCR (scanned docs) | pytesseract | **GLM-OCR** or **MinerU** (109-lang OCR) | GLM-OCR: #1 benchmark, 100+ langs, local, MIT, simple Ollama deploy; MinerU: proven, but AGPL |
| PDF OCR (scanned, AWS deploy) | pytesseract | **AWS Textract** | Managed service, confidence scores, zero infra; only when on AWS and CJK not needed |
| PDF tables | None (flattened) | **PP-StructureV3** (SLANeXt) or **GLM-OCR** | PP-StructureV3: HTML tables, best edit distance; GLM-OCR: Markdown tables, simpler deploy |
| Office documents (DOCX/XLSX/PPTX) | markitdown | **Docling** | Table structure, multi-format, LangChain integration |
| Formulas | None | **GLM-OCR**, **MinerU**, or **PP-StructureV3** | All produce LaTeX; GLM-OCR simplest to deploy |
| Citation grounding | Page markers | **LangExtract** pattern (see §17) | Bounding-box-level source attribution |

**License consideration:** MinerU's AGPL-3.0 may require running it as
an isolated microservice to avoid copyleft obligations. PP-StructureV3
(Apache 2.0) and Docling (MIT) have no such constraints.

**Migration path:** The safest approach is to add new libraries as
additional steps in the fallback chain rather than replacing existing
ones immediately. This preserves backward compatibility while gaining
accuracy on previously-failing documents.

---

## 17. Visual Grounding and Source Attribution

### 17.1 The Citation Accuracy Gap

Our current citation model (`file_path`, `page`, `section_ref`,
`exact_quote`) relies on text matching — the LLM reads `--- Page N ---`
markers and reports the page number. This has known failure modes:

1. **markitdown extractions lack page markers** — no page numbers possible
2. **OCR text errors** — `exact_quote` may not match the original document
3. **No sub-page precision** — we know the page but not the position on
   the page (paragraph, table cell, footnote)
4. **No verification** — we cannot programmatically confirm the cited text
   actually exists at the cited location

### 17.2 Visual Grounding (LandingAI Concept)

LandingAI's "Agentic Document Extraction" introduces **visual grounding**:
every extracted data point is linked to a bounding box in the original
document (x, y, width, height coordinates on a specific page).

**How it works:**
1. Document → page images (high-DPI render)
2. Vision LLM or layout model identifies text regions with coordinates
3. Extraction output includes `bounding_box` per datum
4. Verification: overlay bounding boxes on original pages to visually
   confirm extraction accuracy

**What this would enable for dd-agents:**
- **Pixel-precise citations** — "Section 12.3, Page 15, top-right
  quadrant" instead of just "Page 15"
- **Automated citation verification** — crop bounding box, OCR it,
  compare to `exact_quote`
- **Visual diff for amendments** — overlay bounding boxes from MSA and
  amendment to show what changed
- **Reviewer confidence** — human reviewers see exactly where the LLM
  found each answer

### 17.3 LangExtract Source Grounding Pattern

**Repository:** github.com/google/langextract (Apache 2.0, 33.6K stars)

LangExtract (Google) implements a different but complementary approach:
**source grounding via text spans**. Every extracted field includes a
reference to the exact source text that produced it.

**Key design patterns applicable to dd-agents:**

1. **Multi-pass extraction for recall:** First pass extracts obvious
   answers, second pass specifically targets fields that came back empty.
   This mirrors our Phase 4 (validation) but is more targeted — the
   second pass gets explicit hints about what to look for based on what
   was found in the first pass.

2. **Parallel chunk processing:** For documents exceeding context limits,
   LangExtract chunks the document and processes chunks in parallel,
   then merges results with conflict resolution. Similar to our Phase 1-2
   but with parallelism (we process chunks sequentially).

3. **Interactive HTML visualization:** Extracted data rendered as an
   interactive HTML report where clicking any field highlights the source
   text in the original document. This is the text-based equivalent of
   visual grounding — achievable without bounding boxes.

4. **Source span tracking:** Each extracted value carries a pointer to the
   exact character range in the source document. This enables automated
   verification: compare `exact_quote` to `source_text[start:end]`.

### 17.4 Applicability to dd-agents

**Short-term (no architecture change):**
- Add source span tracking to citations: store `char_start` and `char_end`
  offsets into the extracted `.md` file alongside `page` and `section_ref`
- ~~Implement citation verification~~ — **DONE** (Issue #5, Issue #24):
  `CitationVerifier` with progressive 4-scope search, whitespace
  normalization, and cross-file correction. 99.6% verification rate
  in production (Data Room B).
- Generate interactive HTML review pages where clicking a finding
  highlights the source passage

**Medium-term (with library upgrade):**
- If adopting MinerU or PP-StructureV3, their bounding box output enables
  visual grounding without additional work
- Docling's `DoclingDocument` JSON includes element-level page and
  coordinate metadata
- Could generate "evidence pages" — original PDF pages with highlighted
  regions for each finding

**Long-term (visual LLM approach):**
- Feed page images directly to a vision LLM (Claude, Qwen2.5-VL) for
  extraction, getting both text and coordinates
- This eliminates the text extraction step entirely for some use cases
- Trade-off: higher API cost, non-deterministic, but potentially higher
  accuracy for complex layouts

---

## 18. Structured LLM Output Techniques

### 18.1 Current Approach and Its Limitations

Our pipeline instructs the LLM to return JSON via prompt engineering:

```
Return a JSON object with exactly these keys: {column_names}
Each value must have: answer, confidence, citations, ...
```

The LLM usually complies, but failure modes exist:
- Malformed JSON (missing closing braces, trailing commas)
- Extra keys or missing keys
- Wrong types (string instead of array for citations)
- Markdown fence wrapping requiring strip logic
- Empty `{}` responses requiring retry

### 18.2 Approaches Evaluated

Based on the structured output landscape (2024-2025):

| Approach | Library | How It Works | Guarantees |
|----------|---------|-------------|------------|
| **Prompting** | None | System prompt instructs JSON format | None — LLM may not comply |
| **Function calling** | `instructor` | Pydantic model → tool schema → validated response | Schema-valid, retries on failure |
| **Constrained generation** | `outlines` | Token-level masking forces valid JSON | Guaranteed valid output |
| **Grammar-guided** | `guidance` | Handlebars-style template with type constraints | Guaranteed valid output |
| **API-native** | Anthropic `tool_use` | First-class structured output in API | Schema-valid per provider |

### 18.3 Recommended Approach: `instructor` with Pydantic

**Why `instructor`:**
- Works with Claude's `tool_use` API natively
- Pydantic models define the exact schema — type checking, required
  fields, enum constraints (e.g., confidence must be HIGH/MEDIUM/LOW)
- Automatic retry with validation error feedback to the LLM
- No change to model weights or sampling — works with any API provider
- Active maintenance, large community (6K+ GitHub stars)

**What this would replace:**
```python
# Current: manual JSON parsing with fallbacks
text = response.content[0].text
text = strip_markdown_fences(text)
data = json.JSONDecoder().raw_decode(text)
# ... manual field extraction with get() defaults

# With instructor:
class ColumnResult(BaseModel):
    answer: str
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    citations: list[Citation]
    explanation: str = ""

class AnalysisResponse(BaseModel):
    columns: dict[str, ColumnResult]

result = client.chat.completions.create(
    response_model=AnalysisResponse,
    ...
)
# result is guaranteed to be a valid AnalysisResponse
```

**Benefits for dd-agents:**
- Eliminates all JSON parsing bugs (Bug D confidence casing solved at
  schema level: `Literal["HIGH", "MEDIUM", "LOW"]`)
- Eliminates empty `{}` responses (Pydantic rejects them)
- Eliminates missing column detection (schema requires all columns)
- Eliminates verbose NOT_ADDRESSED parsing (could use enum or validator)
- Automatic retries with the validation error as context for the LLM

### 18.4 Constrained Generation: `outlines`

**For local model scenarios (not our current use case but worth noting):**

`outlines` constrains the token sampling process itself, guaranteeing
that every generated token is part of a valid JSON structure. This is
impossible with API-based models (we don't control token sampling) but
is relevant if we ever switch to local models for cost optimization.

### 18.5 Integration Complexity

| Approach | Lines of Code Change | Risk | Benefit |
|----------|---------------------|------|---------|
| `instructor` + Pydantic | ~200 LOC across analyzer.py | Medium (changes core analysis loop) | Eliminates entire class of parsing bugs |
| Anthropic `tool_use` native | ~150 LOC | Low (already using Anthropic SDK) | Schema validation without new dependency |
| Keep current + add validation | ~50 LOC | Lowest | Catches errors but doesn't prevent them |

The pragmatic path: first add Pydantic validation as a post-parse check
(50 LOC, catches errors), then migrate to `instructor` for guaranteed
output (200 LOC, prevents errors).

---

## 19. Pipeline Improvement Roadmap

### 19.1 Priority Matrix

Ranked by impact on the three 100% goals (completeness, accuracy,
citation fidelity):

| Priority | Improvement | Effort | Impact on Completeness | Impact on Accuracy | Impact on Citations |
|----------|-------------|--------|----------------------|-------------------|-------------------|
| **P0** | Replace pytesseract with PaddleOCR (109 languages) | Medium | High — solves Korean/Japanese/Chinese | Medium | None |
| **P0** | Add layout-aware PDF extraction (MinerU or PP-StructureV3) | High | Low (most PDFs already work) | **High** — tables, reading order, formulas | Medium — page coordinates |
| **P1** | Adopt `instructor` for structured LLM output | Medium | Medium — eliminates empty/malformed responses | Medium — schema-enforced confidence | Low |
| ~~P1~~ | ~~Add citation verification~~ | ~~Medium~~ | — | — | **DONE** — Issue #5, progressive 4-scope search, 99.6% verification rate |
| **P1** | Replace markitdown for Office docs with Docling | Medium | Low | **High** — preserves table structure in XLSX/DOCX | Medium — element-level page refs |
| **P2** | Add visual grounding (bounding boxes) | High | None | Low | **High** — pixel-precise citations |
| ~~P2~~ | ~~Parallel chunk analysis~~ | ~~Low~~ | — | — | **DONE** — Issue #21, `asyncio.gather` concurrent chunks |
| **P2** | Interactive HTML review pages | Medium | None | None | **High** — reviewer experience |
| **P3** | VLM-based extraction (vision LLM) | High | Medium — handles any visual layout | High — understands context | High — visual coordinates |
| **P3** | Cross-document entity resolution | Medium | None | Medium — consistent naming | Low |

### 19.2 Proposed New Fallback Chain (Post-Upgrade)

```
PDF Extraction Chain v2:
Step 1: MinerU hybrid or PP-StructureV3 (layout-aware, tables, reading order)
  ↓ fails density check?
Step 2: pymupdf (fast fallback, page markers)
  ↓ fails density check?
Step 3: pdftotext (poppler, form-heavy PDFs)
  ↓ fails density + readability check?
Step 4: PaddleOCR (109-language OCR, layout-aware)
  ↓ fails threshold?
Step 5: Direct text read (last resort)
  ↓ fails threshold?
FAILED — confidence 0.0

Office Document Chain v2:
Step 1: Docling (table structure, multi-format)
  ↓ fails threshold?
Step 2: markitdown (current, known fallback)
  ↓ fails threshold?
Step 3: macOS textutil (Darwin only)
  ↓ fails threshold?
Step 4: Direct text read
  ↓ fails threshold?
FAILED
```

**Key changes from current chain:**
1. Layout-aware extraction becomes Step 1 (MinerU/PP-StructureV3)
2. pymupdf demoted to Step 2 (still fast and reliable for simple PDFs)
3. pytesseract replaced by PaddleOCR (multi-language, layout-aware)
4. markitdown demoted from Step 3 to Step 2 in Office chain
5. Docling becomes primary Office extractor

### 19.3 Confidence Score Revision

With layout-aware extractors, the confidence scale should be recalibrated:

| Score | Current Meaning | Proposed Meaning |
|-------|----------------|-----------------|
| 0.95 | — | Layout-aware extraction with table/formula preservation |
| 0.9 | pymupdf primary | pymupdf text extraction (no layout) |
| 0.7 | pdftotext | pdftotext fallback |
| 0.6 | pytesseract OCR | PaddleOCR (layout-aware OCR) |
| 0.5 | markitdown / direct | markitdown / direct read |
| 0.3 | Diagram placeholder | Diagram placeholder |
| 0.0 | Failed | Failed |

### 19.4 Table Extraction Deep Dive

Tables in M&A contracts carry critical structured data:
- Pricing schedules (unit prices, volume tiers, discounts)
- Payment terms (milestones, dates, amounts)
- SLA metrics (uptime %, response times, penalties)
- License counts and entitlements

**Current state:** pymupdf flattens tables to whitespace-separated text.
The LLM must infer row/column relationships from alignment, which fails
for complex tables with merged cells or multi-line cell content.

**With PP-StructureV3 (SLANeXt table recognition):**
```markdown
| Tier | Monthly Volume | Unit Price | Discount |
|------|---------------|------------|----------|
| Standard | 0 - 1,000 | $0.05 | 0% |
| Growth | 1,001 - 10,000 | $0.04 | 20% |
| Enterprise | 10,001+ | $0.03 | 40% |
```

This structured output enables the LLM to reason precisely about pricing
terms rather than guessing from misaligned text.

### 19.5 Reading Order Impact

Multi-column PDFs (common in legal contracts with side-by-side
English/Korean or English/French text) currently extract as interleaved
columns:

```
Current pymupdf output (wrong):
"The Supplier shall     Le Fournisseur doit
 provide services       fournir des services
 as described in        tels que décrits dans"

With MinerU/PP-StructureV3 reading order (correct):
"The Supplier shall provide services as described in..."
[column break]
"Le Fournisseur doit fournir des services tels que décrits dans..."
```

Reading order detection is particularly important for:
- Bilingual contracts (Korean MSAs, French Canadian SOWs)
- Side-by-side comparison sections (original vs amended terms)
- Multi-column SOW appendices
- Legal exhibits with parallel text

### 19.6 Implementation Strategy

**Phase 1 — Add, don't replace (lowest risk):**
1. Install PP-StructureV3 or MinerU as optional dependency
2. Add as Step 0 in the PDF chain (before pymupdf)
3. If Step 0 fails or is unavailable, existing chain is unchanged
4. Measure accuracy improvement on both data rooms
5. Install PaddleOCR alongside pytesseract for multi-language OCR

**Phase 2 — Validate and promote:**
1. Run both old and new chains on all 1,426 files (431 + 995)
2. Compare extraction quality: character count, table preservation,
   page marker accuracy, citation correctness
3. If new chain is equal or better on all files, promote to primary
4. Demote old chain to fallback

**Phase 3 — Structured output migration:**
1. Add Pydantic models for all LLM response schemas
2. Add post-parse validation (catches errors, no behavior change)
3. Migrate to `instructor` (prevents errors, behavior change)
4. Remove manual JSON parsing code

**Phase 4 — Citation enhancement:**
1. Add source span tracking (`char_start`, `char_end` in extracted text)
2. Implement citation verification (quote lookup in source)
3. Add bounding box output from layout-aware extractors
4. Build interactive HTML review pages

### 19.7 Dependencies and License Summary

| Library | License | Commercial Use | Notes |
|---------|---------|---------------|-------|
| PP-StructureV3 | Apache 2.0 | Yes, unrestricted | Recommended for layout + tables |
| PaddleOCR | Apache 2.0 | Yes, unrestricted | 109-language OCR |
| Docling | MIT | Yes, unrestricted | Office document extraction |
| instructor | MIT | Yes, unrestricted | Structured LLM output |
| MinerU | AGPL-3.0 | **Requires open-sourcing or commercial license** | Best accuracy but license risk |
| LangExtract | Apache 2.0 | Yes, unrestricted | Source grounding patterns |
| outlines | Apache 2.0 | Yes, unrestricted | Only for local models |
| AWS Textract | Proprietary (pay-per-page) | Yes, unrestricted | $0.0015–$0.065/page; requires AWS account + S3 for async |
| GLM-OCR | MIT (model) + Apache 2.0 (code) | Yes, unrestricted | 0.9B VLM via Ollama; #1 OmniDocBench V1.5; 100+ langs; new ecosystem (Feb 2026) |

**Recommendation:** Use PP-StructureV3 + PaddleOCR (both Apache 2.0) for
PDF extraction, Docling (MIT) for Office documents, and instructor (MIT)
for structured output. For scanned PDF OCR, **GLM-OCR** (MIT) is the
most promising pytesseract replacement — #1 on OmniDocBench V1.5 with
only 0.9B parameters, 100+ language support, structured Markdown output,
and simple Ollama deployment with no cloud dependency. Pending:
independent benchmark validation and ecosystem maturation. Avoid MinerU's
AGPL unless legal approves or it's deployed as an isolated service. AWS
Textract is a viable managed alternative when deploying on AWS, but adds
cost and does not support CJK languages.

---

## 20. Future Research Areas

### 20.1 Known Limitations to Address

1. **Non-English OCR** — pytesseract is hardcoded to `lang="eng"`. Korean
   MSAs, Japanese contracts need language detection + multi-language OCR.
   → **Addressed in §19.1 (P0):** PaddleOCR supports 109 languages. See
   §16.4 (MinerU) and §16.5 (PP-StructureV3).

2. **markitdown lacks page markers** — When PDFs fall through to
   markitdown, page numbers are lost. → **Partially addressed:** Layout-
   aware extractors (§16) provide page-level metadata. Markitdown remains
   as a fallback in the proposed chain (§19.2) but is no longer primary.

3. **Smart Excel extraction** — Current markitdown extraction of `.xlsx`
   files loses cell structure. → **Addressed in §16.3:** Docling preserves
   table structure for XLSX/DOCX/PPTX with HTML output. See §19.1 (P1).

4. **Diagram/image indexing** — Images in contracts (org charts, network
   diagrams, floor plans) are stored as placeholders. → **Partially
   addressed:** PP-StructureV3 includes chart understanding (§16.5).
   Full VLM-based image analysis remains P3 (§19.1).

5. **LLM response caching** — Each run calls the API fresh. Caching
   responses per (customer, prompt, document_hash) tuple would reduce
   cost for re-runs with unchanged prompts.

6. **Parallel extraction** — Current extraction is serial. PDF extraction
   and OCR are CPU/IO-bound and could benefit from multiprocessing.
   LangExtract demonstrates parallel chunk processing (§17.3).

7. **Synthesis retry** — Phase 3 (synthesis) has no retry logic. If the
   synthesis call fails, merged results are kept as-is. Adding retries
   would improve conflict resolution reliability. → `instructor` (§18.3)
   provides built-in retry with validation error feedback.

### 20.2 Potential Quality Improvements

1. **Cross-document entity resolution** — Detect when "ABC Corp" in one
   document is "ABC Corporation" in another and merge their analysis.

2. **Extraction confidence recalibration** — Current confidence scores are
   static (0.9 for pymupdf, 0.7 for pdftotext). → **Proposed revision
   in §19.3** adds 0.95 tier for layout-aware extraction.

3. **Chunk boundary optimization** — Current chunking splits at page
   boundaries. Semantic chunking (split at section boundaries, not page
   boundaries) could improve answer quality. → Docling's
   `HybridChunker` (§16.3) supports semantic-aware splitting.

4. ~~**Citation verification**~~ — **DONE** (Issue #5, Issue #24).
   `CitationVerifier` with progressive 4-scope search (page → adjacent
   ±1 → full doc → cross-file), whitespace normalization, and automatic
   cross-file correction. See §6.7 for details.

5. **Incremental search** — Re-analyze only customers whose documents
   changed, carrying forward unchanged results. Currently the full
   search is re-run even when only extraction changed.

### 20.3 Research Questions

- What is the optimal chars/page density threshold for scanned PDF
  detection? Current value (50) was set empirically from two data rooms.
  A larger sample could refine this.

- What is the optimal chunk overlap ratio? The AG report suggests 15%
  but this was for general RAG, not legal contract analysis specifically.

- How much does Phase 4 (validation) actually improve coverage? Measure
  the NOT_ADDRESSED → answered conversion rate across data rooms.

- At what chunk count does answer quality degrade? One customer had 38
  chunks. Is there a point where more chunks hurt more than they help?

- **PP-StructureV3 vs MinerU on our data rooms:** Both score well on
  OmniDocBench, but how do they perform specifically on M&A contracts
  (dense legal text, pricing tables, signature pages)? Run both on the
  1,426 files and compare.

- **Docling vs markitdown on Office documents:** Measure table structure
  preservation, page marker accuracy, and extraction completeness for
  DOCX/XLSX files in both data rooms.

- **instructor adoption cost/benefit:** Measure how many of the 8 known
  bugs (A-H) would have been prevented by schema-enforced output. Track
  JSON parse failures and malformed responses in production logs.

- **VLM extraction accuracy vs cost:** Compare Claude vision, Qwen2.5-VL,
  and traditional OCR on the 26 scanned PDFs in our data rooms. What is
  the accuracy uplift per dollar of additional API cost?

---

## Appendix A: File Layout Reference

```
data_room/
  _dd/
    forensic-dd/
      index/
        text/                          # Extracted .md files
          Above_200K__Acme__MSA.pdf.md
          extraction_quality.json      # Per-file quality records
      inventory/
        checksums.sha256               # Content hash cache
        customers.csv                  # Customer registry
        tree.txt                       # Directory tree
        files.txt                      # All discovered files
  GroupA/
    Customer1/
      msa.pdf
      amendment.docx
    Customer2/
      contract.pdf
  GroupB/
    Customer3/
      sow.pdf
```

## Appendix B: Supported File Types

| Category | Extensions | Primary Method |
|----------|-----------|----------------|
| PDF | `.pdf` | pymupdf (page-aware) |
| Word | `.docx`, `.doc` | markitdown |
| Excel | `.xlsx`, `.xls` | markitdown |
| PowerPoint | `.pptx`, `.ppt` | markitdown |
| Rich Text | `.rtf` | markitdown |
| Web | `.html`, `.htm` | markitdown |
| Images | `.png`, `.jpg`, `.jpeg`, `.tiff`, `.tif`, `.bmp`, `.gif` | markitdown + OCR |
| Plain Text | `.txt`, `.csv`, `.md`, `.json`, `.yaml`, `.yml`, `.xml`, `.log`, `.tsv`, `.ini`, `.cfg`, `.conf` | Direct read |

## Appendix C: Excluded Patterns

These are automatically excluded from file discovery:

```
__MACOSX, .DS_Store, Thumbs.db, desktop.ini,
.git, .svn, ~$* (Office temp files), ~lock.*
```

## Appendix D: Research Sources (February 2026)

| # | Source | Key Contribution |
|---|--------|-----------------|
| 1 | [LLM Document Extraction Overview](https://substack.com/@danielvanstrien) | Survey of traditional vs LLM extraction approaches; visual grounding concept |
| 2 | [LandingAI Agentic Document Extraction](https://landing.ai) | Visual grounding with bounding boxes; spatial context preservation |
| 3 | [Docling Documentation](https://docling-project.github.io/docling/) | Layout analysis, lossless DoclingDocument JSON, multi-format, LangChain/LlamaIndex integration |
| 4 | [MinerU GitHub](https://github.com/opendatalab/MinerU) | 109-language OCR, reading order detection, pipeline/hybrid/VLM backends |
| 5 | [PP-StructureV3 / PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) | Best OmniDocBench scores (0.145 EN edit distance), layout+table+formula+chart |
| 6 | [LangExtract (Google)](https://github.com/google/langextract) | Multi-pass extraction, source grounding, parallel processing, interactive HTML visualization |
| 7 | [Structured Output Comparison](https://simmering.dev/blog/structured_output/) | 10 libraries compared; instructor for function calling, outlines for constrained generation |
| 8 | [HuggingFace Document Processing Discussion](https://huggingface.co/blog) | LayoutLM, BERT, VLMs (Qwen, GraniteDocling) for document classification and understanding |
