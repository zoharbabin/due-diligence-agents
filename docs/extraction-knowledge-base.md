# Document Extraction for LLM Analysis: Knowledge Base

> Lessons learned, requirements, edge cases, and best practices from building
> and operating the `dd-agents` forensic due-diligence pipeline against
> real-world M&A data rooms (PathFactory: 431 files / 183 customers;
> BlueRush: 995 files / 37 customers).

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
16. [Future Research Areas](#16-future-research-areas)

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
  ↓ fails density check? (<100 chars total, or <50 chars/page)
Step 2: pdftotext (poppler CLI, converts \f to page markers)
  ↓ fails density check? (<100 chars total, or <50 chars/page)
Step 3: markitdown (handles edge-case PDFs, no page markers)
  ↓ fails threshold? (<100 chars)
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
| GE Grid | PO | 567 KB | 0 | Pure image scan |
| NOKIA | PO | 1.2 MB | 0 | Pure image scan |
| Ericsson | MSA + 3 POs | 0.9–18.7 MB | 0 | Pure image scan |
| DFS Financial | 2 MSSAs | 1.5 MB ea | 401 | Sparse headers across 32 pages |
| DCX | Signed PO | 240 KB | 68 | Signature fragment only |
| Broadridge | Asset Purchase | 357 KB | 42 | Signature fragment only |
| Navy Federal | NDA | 1.9 MB | 49 | Signature fragment only |

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
Example: DFS Financial extracted 401 chars across 32 pages = 12.5
chars/page (scattered headers/footers). The density check catches this:

```python
is_dense_enough = (
    text_len >= _SCANNED_PDF_THRESHOLD
    and (page_count <= 1 or text_len / page_count >= _MIN_CHARS_PER_PAGE)
)
```

### 4.3 Why Both Checks Are Needed at Every Step

Initially, the density check was only applied to pymupdf output. But
pdftotext can also return sparse text from scanned PDFs (signature
fragments, header/footer text). The DCX Signed PO returned 151 chars via
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

A single customer may have an 18.7 MB MSA (Ericsson) or 38 files totaling
millions of characters (Navy Federal with 38 chunks). LLM context windows
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
- Citation deduplication: key = `(file_path, page, section_ref)`

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

When merging multi-chunk results, identical citations are deduplicated:

```python
key = (citation.file_path, citation.page, citation.section_ref)
```

This prevents the same clause from appearing multiple times when
overlapping chunks both cite it.

### 6.6 Known Citation Limitations

1. **markitdown extractions lack page markers** — citations from markitdown-
   extracted files cannot include page numbers
2. **OCR text quality** — exact quotes from OCR may contain character
   recognition errors
3. **Synthesis truncation** — the synthesis pass truncates `exact_quote` to
   200 chars for compactness in the conflict resolution prompt

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

---

## 8. LLM Output Normalization

### 8.1 The Confidence Casing Bug

The system prompt instructs: `"confidence": "<HIGH|MEDIUM|LOW>"`. But LLMs
return "High", "high", "HIGH", "Medium", etc. unpredictably.

**Lesson learned:** Normalize at EVERY point where LLM output is consumed,
not just at the initial parse. We initially added `.upper()` at parse time
(Phase 1) and merge time (Phase 2), but missed the synthesis pass (Phase 3)
and validation pass (Phase 4). This caused 53% of confidence values in the
BlueRush retest to remain mixed-case.

**Rule:** Every `col_data.get("confidence", "")` must end with `.upper()`.

### 8.2 Answer Normalization

Answers are compared case-insensitively:
```python
answer_upper = col_result.answer.upper().strip()
```

But the original casing is preserved for display (free-text summaries
should not be uppercased).

### 8.3 Verbose NOT_ADDRESSED Detection

The LLM sometimes returns:
> "NOT_ADDRESSED. The portions of the agreement reviewed (Part 1 of 4)
> do not contain an explicit obligation..."

This must be treated as NOT_ADDRESSED (priority 1), not as substantive
free-text (priority 2). Detection:

```python
if answer_upper.startswith("NOT_ADDRESSED") or answer_upper.startswith("NOT ADDRESSED"):
    priority = 1  # Not substantive
```

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

### 10.4 Real-World Extraction Profile (BlueRush, 995 files)

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
| **Symptom** | 21 PathFactory files with 0-89 bytes extracted across runs |
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
| **Symptom** | DFS Financial: 401 chars across 32 pages (12.5 chars/page) accepted as valid |
| **Root cause** | Only total char count checked, not per-page density |
| **Fix** | Added `_MIN_CHARS_PER_PAGE = 50` density check |
| **Lesson** | Multi-page scanned PDFs can have > 100 total chars from headers/footers |

### Bug D: Confidence Not Normalized in All Phases

| | |
|---|---|
| **Symptom** | 53% of confidence values mixed-case in BlueRush Details sheet |
| **Root cause** | `.upper()` added at Phase 1 (parse) and Phase 2 (merge) but missed Phase 3 (synthesis) and Phase 4 (validation) |
| **Fix** | Added `.upper()` to all 4 code paths that read `confidence` from LLM JSON |
| **Lesson** | Normalize external data at EVERY ingestion point, not just the "main" one |

### Bug E: pdftotext Missing Density Check

| | |
|---|---|
| **Symptom** | DCX Signed PO: 151 chars via pdftotext accepted (signature fragment) |
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
| **Symptom** | 3 BlueRush files (Broadridge OEM 5.4 MB, Cooperators CFSL-001 1.6 MB, Navy Federal SOW 8.0 MB) contained raw PDF binary (`%PDF-1.3`, stream objects, binary image data) as "extracted text" |
| **Root cause** | Markitdown on image-only scanned PDFs dumps the raw PDF binary as text. The binary passes `len(text.strip()) >= 100` because binary bytes count as characters |
| **Fix** | Added `_is_readable_text()` that checks >= 85% printable character ratio. Applied at markitdown step in PDF chain and in cache gate (`_is_cached_output_readable`) |
| **Lesson** | Length thresholds alone cannot distinguish binary from text. A printable-character ratio check is essential for any extraction method that might return raw file content |

### Bug H: Stale Cache Persists Bad Extractions After Code Fixes

| | |
|---|---|
| **Symptom** | DCX Signed PO (151 bytes) persisted through cache despite new pdftotext density check being deployed |
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
| `_SCANNED_PDF_THRESHOLD` | 100 chars | Minimum for PDF extraction to be accepted |
| `_MIN_CHARS_PER_PAGE` | 50 chars/page | Density check for scanned PDF detection |
| `_MIN_PRINTABLE_RATIO` | 0.85 (85%) | Readability gate — rejects binary garbage from markitdown |
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

## 16. Future Research Areas

### 16.1 Known Limitations to Address

1. **Non-English OCR** — pytesseract is hardcoded to `lang="eng"`. Korean
   MSAs (e.g., LG), Japanese contracts need language detection + multi-
   language OCR.

2. **markitdown lacks page markers** — When PDFs fall through to
   markitdown, page numbers are lost. Investigate hybrid approach:
   use pymupdf for page structure + markitdown for text content.

3. **Smart Excel extraction** — Current markitdown extraction of `.xlsx`
   files loses cell structure. The spec includes an openpyxl-based
   approach that preserves sheet names, handles merged cells, converts
   formulas, and formats dates/currency.

4. **Diagram/image indexing** — Images in contracts (org charts, network
   diagrams, floor plans) are stored as placeholders. Multimodal LLM
   analysis could extract structured data from these.

5. **LLM response caching** — Each run calls the API fresh. Caching
   responses per (customer, prompt, document_hash) tuple would reduce
   cost for re-runs with unchanged prompts.

6. **Parallel extraction** — Current extraction is serial. PDF extraction
   and OCR are CPU/IO-bound and could benefit from multiprocessing.

7. **Synthesis retry** — Phase 3 (synthesis) has no retry logic. If the
   synthesis call fails, merged results are kept as-is. Adding retries
   would improve conflict resolution reliability.

### 16.2 Potential Quality Improvements

1. **Cross-document entity resolution** — Detect when "ABC Corp" in one
   document is "ABC Corporation" in another and merge their analysis.

2. **Extraction confidence recalibration** — Current confidence scores are
   static (0.9 for pymupdf, 0.7 for pdftotext). Calibrate against
   actual extraction quality (compare to OCR ground truth).

3. **Chunk boundary optimization** — Current chunking splits at page
   boundaries. Semantic chunking (split at section boundaries, not page
   boundaries) could improve answer quality.

4. **Citation verification** — Post-hoc check that `exact_quote` actually
   appears in the cited `file_path` at the cited `page`. Flag
   hallucinated citations.

5. **Incremental search** — Re-analyze only customers whose documents
   changed, carrying forward unchanged results. Currently the full
   search is re-run even when only extraction changed.

### 16.3 Research Questions

- What is the optimal chars/page density threshold for scanned PDF
  detection? Current value (50) was set empirically from two data rooms.
  A larger sample could refine this.

- What is the optimal chunk overlap ratio? The AG report suggests 15%
  but this was for general RAG, not legal contract analysis specifically.

- How much does Phase 4 (validation) actually improve coverage? Measure
  the NOT_ADDRESSED → answered conversion rate across data rooms.

- At what chunk count does answer quality degrade? Navy Federal had 38
  chunks. Is there a point where more chunks hurt more than they help?

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
