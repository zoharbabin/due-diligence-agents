# Benchmark: Firecrawl's `pdf-inspector` and `anydoc` vs. the dd-agents extraction pipeline

**Question:** should either of Firecrawl's Rust document-conversion libraries —
[`pdf-inspector`](https://github.com/firecrawl/pdf-inspector) (PDF
classification/extraction, PyPI `pdf-inspector` 0.2.6) or
[`anydoc`](https://github.com/firecrawl/anydoc) (Office/PDF-to-Markdown,
PyPI `firecrawl-anydoc` 0.1.6) — replace or augment any stage of
[`src/dd_agents/extraction/pipeline.py`](../src/dd_agents/extraction/pipeline.py)?

**Answer, short version:** neither replaces the pipeline outright. `anydoc`'s
PDF path is a confirmed passthrough to `pdf-inspector` (verified: byte-identical
markdown output on the same file), so this is really one PDF engine plus one
Office-format wrapper around it. On text-based PDFs, `pdf-inspector` is
materially faster with better Markdown table structure but has zero OCR — it
only detects that a page needs it. On the Office formats where `anydoc`
competes with `markitdown` (dd-agents' current backend for
`_extract_generic`/`_extract_spreadsheet`), accuracy is identical on this
corpus and `anydoc` is 3–200x faster at steady state, with materially cleaner
error handling on malformed input — a gap serious enough to fix in dd-agents
regardless of whether either library is adopted (see
[KPI 7](#kpi-7--malformed-office-file-handling)). See
[Recommendation](#recommendation) for the concrete integration proposal and
why full adoption isn't recommended yet.

> **Superseded numbers.** The 2026-08-07 numbers in this file (pdf-inspector 0.2.6,
> anydoc 0.1.6, the 11-file corpus) are superseded by the
> [2026-11-14 re-run](#2026-11-14-re-run-on-the-shared-corpus) below. The old
> sections stay as method history. Read the old Recommendation against the new results.

---

## 2026-11-14 re-run on the shared corpus

Result in one line: on clean synthetic files all PDF arms read text equally well. The
differences are in damaged files, reading order and page classification.

Run it again:

```bash
PYTHONPATH=src python scripts/bench_extraction.py --out-json bench.json --out-md bench.md
```

Each arm is optional. A missing library is skipped and named in the output.

### Versions

| Item | Version |
|---|---|
| pdf-inspector | 1.26.0 |
| firecrawl-anydoc | 0.2.4 |
| pypdfium2 (PDFium, repo engine) | 5.15.2 |
| pikepdf (qpdf repair step of the repo engine) | 10.18.1 |
| markitdown | 0.1.9 |
| mammoth, beautifulsoup4, markdownify, python-pptx, openpyxl (built-in fallback) | 1.13.0, 4.15.0, 1.2.3, 1.0.2, 3.1.5 |
| pdftotext (poppler) | 26.04.0 |
| Python, platform | 3.14.10, macOS arm64 |

### Corpus

33 invented files, under 5 MB, in `tests/fixtures/extraction_corpus/`. Every file has ground
truth in `ground_truth.json`. See `tests/fixtures/extraction_corpus/README.md` for the
file list and schema.

- 7 languages (en, de, fr, es, ja, zh, ko): one text PDF and one scanned PDF each.
- English layouts: table-heavy (also scanned), two columns, watermark, signature stamp, mixed text and scanned pages, six-page contract.
- Damaged PDFs: truncated and repairable, truncated and unreadable, owner password, user password.
- Office and HTML: DOCX (also Japanese, and with tracked changes), XLSX, PPTX, HTML with script and style noise.
- Fictional person fixtures for screening tests (PDF and DOCX).

Scores:

- Phrase recall counts only phrases on pages that have a text layer. Scans score nothing here, because no arm runs OCR.
- Hard failure: an error on a file that should be readable. A `ValueError` from pdf_inspector counts.
- Expected failures: the two files labeled encrypted or unreadable. The arm should raise.
- Seconds per file: median of 3 calls per file, after one warm-up call.
- Files are 1 to 6 pages, so the timings say little about large documents.

### Results: PDF files

26 PDFs: 24 should be readable, 2 should fail (user password, unreadable).

| Arm | Hard failures | Expected failures raised | Phrase recall | Table-cell recall | Reading order | s/file (median) |
|---|---|---|---|---|---|---|
| pdfium | 0/24 | 2/2 | 100.0% | 100.0% | 1/1 | 0.0006 |
| pdf_inspector (extract_text) | 1/24 | 2/2 | 100.0% | 100.0% | 1/1 | 0.0003 |
| pdf_inspector (markdown) | 1/24 | 2/2 | 97.1% | 100.0% | 0/1 | 0.0006 |
| pdftotext | 1/24 | 2/2 | 100.0% | 100.0% | 0/1 | 0.0159 |

Phrase recall on the seven text PDFs of the contract set was 100.0% in every language
(de, en, es, fr, ja, ko, zh) for every arm.

Hard failures:

| Arm | File | Error |
|---|---|---|
| pdf_inspector (extract_text) | damaged_truncated_en.pdf | ValueError: Invalid PDF structure |
| pdf_inspector (markdown) | damaged_truncated_en.pdf | ValueError: Invalid PDF structure |
| pdftotext | damaged_truncated_en.pdf | RuntimeError: Syntax Error: Invalid XRef entry 0 |

### Results: pdf_inspector page classification

Page labels from `classify_pdf` against the ground truth (`text` or `scanned`).

| Set | Pages | Accuracy |
|---|---|---|
| Mixed PDF (text, scan, text, scan) | 4 | 100.0% |
| Text and scanned pairs, 7 languages | 14 | 100.0% |
| All readable PDFs | 30 | 100.0% |

Document type (`text_based`, `scanned`, `mixed`) was correct on 22 of 22 files.
`process_pdf().pages_needing_ocr` scored 100.0% when read as 1-based and 63.3% when read as 0-based.
`classify_pdf().pages_needing_ocr` is 0-based.

### Results: Office and HTML files

7 files.

| Arm | Hard failures | Phrase recall | Table-cell recall | Numeric-cell recall | Tracked: inserted / deleted kept | HTML script and style leaked | s/file (median) |
|---|---|---|---|---|---|---|---|
| markitdown | 0/7 | 100.0% | 100.0% | 100.0% | 2/2 / 0/2 | no | 0.0662 |
| builtin_fallback | 0/7 | 100.0% | 100.0% | 100.0% | 2/2 / 0/2 | no | 0.0596 |
| anydoc | 1/7 | 100.0% | 100.0% | 100.0% | 2/2 / 0/2 | n/a | 0.0035 |

The anydoc failure is `office_terms_en.html`: `UnsupportedError: unsupported input: unrecognized file content and extension`.
anydoc 0.2.4 lists no HTML format.

### What this means

- On clean files, text recall is not a reason to switch PDF engine. All four arms found every phrase in all 7 languages, including ja, zh and ko, and every table cell.
- The repo engine (pdfium with the qpdf repair retry) was the only PDF arm that read all 24 readable files. The repairable truncated file made pdf_inspector and pdftotext fail.
- pdf_inspector `extract_text` and pdfium keep column A before column B. pdf_inspector markdown turns the two columns into one two-column table and splits sentences across rows (2 of 7 phrases found on that page). pdftotext in its default mode interleaves the columns.
- `classify_pdf` labeled every page correctly, including the mixed PDF. `pdf_engine` returns text per page but has no text-or-scanned label. That label is the input a per-page OCR router needs.
- `process_pdf().pages_needing_ocr` is 1-based but `classify_pdf().pages_needing_ocr` is 0-based. An adopter has to handle both.
- Speed is not a deciding factor for PDFs. Every arm is under 20 ms per file here. pdf_inspector `extract_text` took about half the time of pdfium. pdftotext includes process start-up.
- For Office files, all three converters scored the same on phrases, cells and numbers. All keep inserted tracked text and drop deleted text. None of the HTML-capable arms leaks script or style text.
- anydoc is about 17 to 19 times faster than the built-in fallback and markitdown on these files. It cannot read HTML.
- The pdf-inspector 1.26.0 wheel is an `abi3` wheel (`cp38-abi3`). It installed and ran `classify_pdf` and `extract_text` on Python 3.15.2 (macOS arm64 only).
- The 2026-08-07 numbers are not comparable with these. The library versions and the corpus both changed.

Not measured: OCR, files from real data rooms, large documents, other platforms.

---

## Methodology

### Why synthetic files, not real data-room documents

This repo's [Sensitive Data Policy](../CLAUDE.md#sensitive-data-policy)
prohibits real company names, financial data, or PII in source, tests, or
docs, and no data-room files are committed to the repo (`.gitignore` excludes
`*.pdf` except marketing assets). All corpus files were generated with
[`reportlab`](https://pypi.org/project/reportlab/),
[`pypdf`](https://pypi.org/project/pypdf/), [`python-docx`](https://pypi.org/project/python-docx/),
and [`openpyxl`](https://pypi.org/project/openpyxl/) to reproduce the
structural properties that matter for extraction (multi-column layout,
embedded tables, CID/Identity-H fonts, scanned raster pages, encryption,
malformed/truncated files) without using any real contract content. Company
and person names are fabricated placeholders.

**Limitation, stated plainly:** an 11-file synthetic corpus is not a
substitute for running these tools against a real data room. It answers "does
this tool behave correctly on the structural edge cases our pipeline is built
to handle," not "what's the aggregate accuracy across thousands of real
contracts." Firecrawl's own published benchmarks (200-PDF
[opendataloader-bench](https://github.com/opendataloader-project/opendataloader-bench)
for `pdf-inspector`; a per-format docx/xlsx/rtf comparison table in `anydoc`'s
own README) are better estimates of aggregate quality but are self-reported
and not independently reproduced here.

### Corpus

**PDF arm** (`pdf-inspector`, and `anydoc`'s PDF passthrough — not re-run
separately, see below):

| File | Category | What it stresses |
|---|---|---|
| `clean_contract.pdf` | Clean text | Baseline single-column contract text |
| `financial_table.pdf` | Financial table | Exact dollar figures in a rendered table — the sharpest KPI, since [`numerical_audit.py`](../src/dd_agents/validation/numerical_audit.py) and [`severity_thresholds.py`](../src/dd_agents/agents/severity_thresholds.py) key off exact revenue/percentage figures |
| `multi_column.pdf` | Multi-column | Two-column board-deck layout — reading-order correctness |
| `scanned_image.pdf` | Scanned | Raster image with **no embedded text layer** (verified via `fitz`: `page.get_text()` returns `""`) |
| `mixed_doc.pdf` | Mixed | Page 1 real text, page 2 scanned-image-only (verified: page 2 `get_text()` returns `""`) |
| `encrypted.pdf` | Encrypted | Password-protected via `pypdf` (verified: `fitz.open().is_encrypted == True`) |
| `cid_font.pdf` | CID font | Identity-H / Type0 CJK font (`HeiseiMin-W3`, `UniJIS-UCS2-H` encoding, verified via `page.get_fonts()`) — tests ToUnicode CMap decoding |

**Office arm** (`anydoc` vs. dd-agents' `markitdown`-backed generic/spreadsheet
extractors):

| File | Category | What it stresses |
|---|---|---|
| `supply_agreement.docx` | Word, headings + table | Structure fidelity (headings, table cells) and numeric fidelity |
| `arr_schedule.xlsx` | Excel, multi-sheet | Numeric fidelity on real (not text-rendered) numeric cells, multi-sheet handling |
| `subprocessor_list.csv` | CSV | Plain delimited data — baseline for the format neither tool needs a real parser for |
| `nda_excerpt.rtf` | RTF | A format `markitdown` and `anydoc` both claim to support via different code paths |
| `corrupted.docx` | Malformed input | Truncated ZIP container (first third of a valid `.docx` — verified: not a readable zip archive) — fail-closed error-handling test |

Each file has a hand-written ground truth (`must_contain` substrings, exact
expected numbers, sheet names), scored by exact substring/value match — no
fuzzy scoring, no LLM grading. All 12 ground-truth entries and both corpus
generator scripts are scratch tooling (not committed; regenerable from the
tables above).

### What ran

- **dd-agents**: `ExtractionPipeline.extract_single()` from
  `src/dd_agents/extraction/pipeline.py` (unmodified, current `main`),
  exercising the real fallback chains — `pymupdf → pdftotext → markitdown →
  pytesseract OCR` for the PDF arm (GLM-OCR and Claude vision were not reached
  by any file in this corpus), and `openpyxl`/`csv` → `markitdown` → direct
  read for the Office arm.
- **pdf-inspector**: `pdf_inspector.process_pdf()` (the library's "full
  processing" entry point: detect + extract + convert to Markdown) — PDF arm
  only.
- **anydoc**: `anydoc.to_markdown()` — Office arm, plus one PDF spot-check
  (`clean_contract.pdf`) to confirm the passthrough claim. `anydoc`'s PDF
  output was verified byte-identical to `pdf-inspector`'s own output on that
  file, and its README states it delegates PDF conversion to `pdf-inspector`
  internally — so the PDF arm's `pdf-inspector` results stand in for `anydoc`
  on PDFs; re-running the full PDF corpus through `anydoc` would only
  duplicate that result.

### Environment

- macOS Darwin 25.5.0, Apple M3 Pro, Python 3.13.11
- `dd-agents` 1.17.0 (editable install from this repo, unmodified)
- `pdf-inspector` 0.2.6, `firecrawl-anydoc` 0.1.6 (both from PyPI)
- `pymupdf` 1.27.1, `poppler`/`pdftotext` 26.04.0, `tesseract` 5.5.2,
  `markitdown` 0.1.5, `python-docx` 1.2.0, `openpyxl` 3.1.5
- PDF arm: each tool run 3 times per file; see
  [Reproducibility](#reproducibility) for run-to-run variance.
- Office arm: **two separate timing measurements**, because dd-agents'
  `markitdown` and `openpyxl` backends each pay a one-time, per-process
  import/JIT warm-up cost (~250–1050ms on first use, confirmed by isolating
  import time from per-call time) that a naive "one fresh
  `ExtractionPipeline()` per file" harness would misattribute as per-file
  latency. Cold numbers (first call in a fresh process, realistic for a
  single-file CLI invocation) and steady-state numbers (5 reps after warming
  each backend once, realistic for `extract_all()` processing a data room
  with many files per worker) are both reported in
  [KPI 6](#kpi-6--latency).

---

## Results

### KPI 1 — Classification correctness (PDF arm)

Does the tool correctly identify whether a page/document needs OCR?

| File | Ground truth | dd-agents inferred | pdf-inspector `pdf_type` | Both correct? |
|---|---|---|---|---|
| `clean_contract.pdf` | text-based | text-based | `text_based` | ✅ |
| `financial_table.pdf` | text-based | text-based | `text_based` | ✅ |
| `multi_column.pdf` | text-based | text-based | `text_based` | ✅ |
| `scanned_image.pdf` | scanned | scanned | `scanned` | ✅ |
| `mixed_doc.pdf` | mixed (p1 text, p2 scanned) | text-based (no per-page signal) | `mixed`, `pages_needing_ocr: [2]` | ⚠️ pdf-inspector only |
| `encrypted.pdf` | encrypted | encrypted (`Password-protected PDF`, clean fail) | raises `ValueError: PDF is encrypted` | ✅ both, different mechanism |
| `cid_font.pdf` | text-based (has real embedded text, `page.get_text()` len 82) | **scanned** (misclassified) | `text_based`, `has_encoding_issues: True`, `pages_needing_ocr: [1]` | ❌ dd-agents |

**Two concrete findings here:**

1. **dd-agents misclassifies the CID-font PDF as scanned.**
   `ExtractionPipeline._inspect_pdf()`
   ([pipeline.py:505-568](../src/dd_agents/extraction/pipeline.py#L505)) checks
   `len(page_text.strip()) < 100` on page 1 to decide "scanned" — our CID-font
   page has 82 extractable characters (short, but real), so it's routed
   straight to OCR, skipping pymupdf/pdftotext entirely. pdf-inspector's
   classifier correctly called it `text_based` while *also* flagging
   `has_encoding_issues: True` and `pages_needing_ocr: [1]` — a more precise
   signal that separates "this page is scanned" from "this page's font
   encoding is broken but there is real text to try to recover." Our pipeline
   conflates the two failure modes into one "scanned" bucket.

2. **dd-agents has no per-page granularity; pdf-inspector does.** On
   `mixed_doc.pdf`, our `_inspect_pdf()` only samples page 1 (see
   [pipeline.py:537](../src/dd_agents/extraction/pipeline.py#L537),
   `page = doc[0]`) — it has no concept of "page 2 needs OCR, page 1 doesn't."
   In this run dd-agents got lucky: `markitdown` (the fallback after
   pymupdf/pdftotext both failed the 500-char density gate) happened to
   extract page 1's text and produce a placeholder-free result, so the
   `must_contain` check still passed. But there's no mechanism that would
   *route page 2 specifically to OCR* the way pdf-inspector's
   `pages_needing_ocr` list is designed to. On a longer real-world document
   with only one scanned page out of thirty, our current per-file (not
   per-page) classification would either OCR the whole file unnecessarily or
   silently miss the one scanned page's content, depending on which side of
   the density threshold the whole-file text lands on.

### KPI 2 — Text recall, PDF arm (ground-truth substrings found verbatim)

| File | dd-agents | pdf-inspector |
|---|---|---|
| `clean_contract.pdf` | 5/6 (0.83) — missed `"thirty (30) days"` | 6/6 (1.00) |
| `financial_table.pdf` | 2/2 (1.00) | 2/2 (1.00) |
| `multi_column.pdf` | 4/4 (1.00) | 4/4 (1.00) |
| `scanned_image.pdf` | 3/3 (1.00, via OCR) | **0/3 (0.00)** |
| `mixed_doc.pdf` | 2/2 (1.00) | 2/2 (1.00) |
| `cid_font.pdf` | 2/3 (0.67) — missed the CJK line | 2/3 (0.67) — same miss |
| `encrypted.pdf` | n/a (no text expected) | n/a |

**This is the single most important result in the PDF arm: pdf-inspector has
zero OCR capability.** On `scanned_image.pdf` it correctly *classified* the
page as scanned and returned `markdown: null` / empty text rather than
fabricating garbage — that fail-closed behavior is good — but it recovered
none of the three required facts (`SUBPROCESSOR REGISTER`, `CloudHost
Systems`, `DataVault Analytics`). dd-agents' `pytesseract` fallback recovered
all three. This confirms pdf-inspector's own README framing: it's a
classification-and-extraction-for-text-PDFs tool, explicitly *not* an
OCR replacement (["skipping expensive OCR services for the ~54% of PDFs that
don't need them"](https://github.com/firecrawl/pdf-inspector#readme)).

On `clean_contract.pdf`, dd-agents' `pymupdf` output dropped
`"thirty (30) days"` from Section 3 — inspecting the raw extraction, the
phrase is present but wrapped across a line break as `"...upon thirty\n(30)
days written notice."`, and the ground-truth check used an exact substring
match that doesn't tolerate the embedded newline. This is a **scoring-harness
artifact, not a pipeline defect** — the text is fully present and would be
found by any downstream search/citation logic that isn't doing a naive
substring match. Flagging this rather than letting it inflate pdf-inspector's
apparent advantage on this file.

Both tools missed the CJK line on `cid_font.pdf`
(`東京データセンター株式会社`) — dd-agents' OCR pass produced garbled CJK
glyphs (`Rms —-Juevy—hRASstHt`), and pdf-inspector's CID/ToUnicode decoder
produced replacement characters (`�������������`) while correctly setting
`has_encoding_issues: True`. Neither tool solves CJK Identity-H fonts
reliably in this corpus; pdf-inspector at least surfaces the failure as a
flag rather than silent corruption, and does it roughly 120–1600x faster
across the 3 runs (dd-agents: 857–1619ms via its OCR fallback; pdf-inspector:
1.0–7.1ms) before falling through to (in our pipeline's case) an OCR pass
that doesn't help. That wide ratio range is mostly OCR's ms-vs-second cost,
not a precise multiplier — the qualitative point (pdf-inspector fails fast,
dd-agents fails slow) is what matters, not the exact factor.

### KPI 3 — Numeric fidelity, PDF arm (financial_table.pdf)

The KPI that maps most directly to real risk: `numerical_audit.py` and the
severity thresholds in `severity_thresholds.py` (e.g. `COC_REVENUE_PCT`) key
off exact revenue and percentage figures pulled from extracted text. A
transposed digit or reformatted number here is a silent correctness bug.

| Metric | dd-agents | pdf-inspector |
|---|---|---|
| Exact match rate on 6 dollar figures | **6/6 (100%)** | **6/6 (100%)** |
| Table structure | Aligned plain-text columns (no Markdown table syntax) | Proper Markdown `\|---\|` table |

Both tools reproduced every dollar figure byte-exact
(`1,240,500.00`, `486,200.75`, `902,340.10`, `317,890.00`, `58,120.40`,
`3,005,051.25`) — no numeric fidelity gap on this file. The difference is
structure: dd-agents' `pdftotext -layout` output preserves column alignment
with whitespace but produces no machine-parseable table syntax; pdf-inspector
converts to a real Markdown table and additionally reports
`pages_with_tables: [1]`, a structured signal our pipeline doesn't produce.
For an LLM specialist agent reading either format via the `Read` tool
(per design rule 1 — [agents read original files
directly](../CLAUDE.md#design-rules), not extracted text), this difference
matters less; it matters more for the **search/vector index** path
(`extraction/pipeline.py`'s stated purpose, see its module docstring), where
a real Markdown table chunks and embeds more coherently than aligned
whitespace.

### KPI 4 — Reading order, PDF arm (multi_column.pdf)

Both tools preserved correct reading order — column A content
(`"Revenue grew 18%"`) appears before column B content (`"top three customers
represent 41%"`) in both outputs. No difference on this corpus. pymupdf's
default text extraction already handles this layout correctly; pdf-inspector
claims dedicated multi-column detection per its README, but this single
two-column fixture doesn't stress-test the difference (would need nested
columns, sidebars, or footnote interruptions to differentiate).

### KPI 5 — Encrypted PDF handling

| Tool | Behavior |
|---|---|
| dd-agents | `_inspect_pdf()` detects `doc.is_encrypted`, short-circuits before any extractor runs, returns `method="failed"`, `failure_reasons=["Password-protected PDF"]`. No exception escapes. |
| pdf-inspector | `process_pdf()` raises `ValueError: PDF is encrypted`. Caller must catch it — no built-in "return a null/failed result" path in the API surface tested (`detect_pdf` and `classify_pdf` raise the same way). |
| anydoc | `to_markdown()` raises a typed `anydoc.EncryptedError: document is encrypted` — a dedicated exception class distinct from generic `ValueError`, verified on the same encrypted PDF. |

Both fail closed (no fabricated text), which is the property that matters
most. dd-agents' behavior is more convenient to consume (a data object, not
an exception) purely because we wrote the pre-inspection check ourselves; if
we adopted pdf-inspector we'd wrap it the same way we already wrap pymupdf.
anydoc's typed exception hierarchy (`ConvertError` with subclasses
`EncryptedError`, `MalformedError`, `MissingPartError`, `ResourceLimitError`,
`UnsupportedError`) would let a caller distinguish "encrypted" from
"corrupted" from "unsupported format" with a single `except` clause each,
which pdf-inspector's bare `ValueError` and ours does not (see
[KPI 7](#kpi-7--malformed-office-file-handling) for why that distinction
matters in practice).

### KPI 6 — Latency

**PDF arm** (text-based PDFs only — the segment pdf-inspector targets):

| File | dd-agents (pymupdf/pdftotext path) | pdf-inspector | Speedup |
|---|---|---|---|
| `clean_contract.pdf` | ~5 ms | ~0.4–1.5 ms | ~5–10x |
| `financial_table.pdf` | ~22–24 ms (fell through to `pdftotext` — see below) | ~0.7–1.7 ms | ~15–30x |
| `multi_column.pdf` | ~5–7 ms | ~0.4–0.5 ms | ~10–15x |

*(Ranges are min/max across 3 repeated runs — see
[Reproducibility](#reproducibility). dd-agents' timings were stable
run-to-run within ~10%; pdf-inspector's sub-millisecond calls varied by
up to ~3x run-to-run, which is expected noise at that timescale and doesn't
change the order-of-magnitude conclusion.)*

`financial_table.pdf` is the interesting one: dd-agents' `pymupdf` primary
extractor produced only 366 characters and failed the pipeline's
`_MIN_EXTRACTION_CHARS = 500` density gate
([pipeline.py:83](../src/dd_agents/extraction/pipeline.py#L83)) — a threshold
tuned for prose documents, not tables — so it fell through to `pdftotext`,
adding a second subprocess call and ~20ms. This is a **known tuning
sharp edge in the existing pipeline** (a real financial table can legitimately
be short in raw character count while being information-dense), not
something pdf-inspector revealed as new — but it's a good illustration of why
pdf-inspector's page-content-stream sampling approach (no minimum character
heuristic) sidesteps a whole class of threshold-tuning problems.

On files that need OCR (`scanned_image.pdf`, `cid_font.pdf`) dd-agents takes
850–1200ms because `pytesseract` runs; pdf-inspector takes under 10ms because
it only *detects* the need for OCR and stops — it never claims to replace
that stage, so this isn't a fair comparison, just a restatement of KPI 2.

**Office arm** (dd-agents' `markitdown`/`openpyxl` path vs. `anydoc`),
steady-state (5 reps, both backends pre-warmed once — realistic for
`extract_all()` processing many files per worker):

| File | dd-agents steady-state | anydoc | Speedup |
|---|---|---|---|
| `supply_agreement.docx` | 82–148 ms | 3.5–3.7 ms | ~22–42x |
| `arr_schedule.xlsx` | 2.1–2.6 ms | 0.15–0.24 ms | ~9–18x |
| `subprocessor_list.csv` | 0.35–0.60 ms | 0.10–0.12 ms | ~3–6x |
| `nda_excerpt.rtf` | 8.8–11.2 ms | 0.05–0.14 ms | ~62–213x |

Cold-start (first call in a fresh process — realistic for a one-off CLI
extraction, not for the pipeline's batch `extract_all()`):

| File | dd-agents cold | anydoc cold |
|---|---|---|
| `supply_agreement.docx` | ~950–1640 ms (markitdown JIT warm-up dominates) | ~4–7 ms |
| `arr_schedule.xlsx` | ~350–580 ms (openpyxl import dominates) | ~0.6–1.0 ms |
| `subprocessor_list.csv` | ~0.7–4.2 ms | ~0.1–0.5 ms |
| `nda_excerpt.rtf` | ~14–20 ms | ~0.1–0.4 ms |

The cold-vs-steady-state gap is large and worth calling out explicitly:
`markitdown`'s first call in a process costs roughly 250ms–1s (isolated by
timing `MarkitdownExtractor.extract()` in a loop: call 1 took 1051ms, calls
2–5 took 82–134ms each), and `openpyxl`'s first call costs roughly 350–390ms,
both one-time-per-process import/initialization costs, not per-file I/O. A
naive benchmark harness that instantiates a fresh `ExtractionPipeline()` per
file (as this report's own first-draft numbers did, before this was caught)
overstates dd-agents' real-world per-file cost by roughly 10–100x on these
formats, because `extract_all()` in production reuses one pipeline instance
across a whole data room. Both cold and steady-state numbers are reported
here rather than picking the more favorable one for either tool.

Regardless of which number is used, `anydoc` is faster on every Office file
tested, by a wide and consistent margin — the speedup range doesn't collapse
even under the more charitable (to dd-agents) steady-state measurement.

### KPI 7 — Malformed Office file handling

This is the sharpest finding in the Office arm, and it's a real pipeline gap,
not a scoring artifact.

| Tool | Behavior on `corrupted.docx` (truncated ZIP, first third of a valid file) |
|---|---|
| dd-agents | Returns a **"successful" `method="primary"` result** via `markitdown`, containing the raw ZIP binary header as text (`PK  ]\xR\xba...`). No exception, no failure flag. |
| anydoc | Raises `anydoc.MalformedError: malformed document: not a readable zip archive: invalid Zip archive: Could not find EOCD`. Clean, typed, fails closed. |

Verified across all 3 repeated runs, consistent every time. This is not a
hypothetical: dd-agents' own extraction pipeline already has the two checks
that would catch this —
[`_is_readable_text()`](../src/dd_agents/extraction/pipeline.py) and
[`_has_control_char_corruption()`](../src/dd_agents/extraction/pipeline.py) —
and running them directly against the actual bad output confirms both fire
correctly (`is_readable=False`, `has_control_char_corruption=True`). The gap
is that `_extract_generic()`
([pipeline.py:1299](../src/dd_agents/extraction/pipeline.py#L1299)), which
backs `.docx`/`.rtf`/other Office formats, calls `_try_method("markitdown",
...)` **without** `check_readability=True` or `check_control_chars=True` —
unlike the PDF path's markitdown fallback calls
([pipeline.py:1030, 1049, 1069](../src/dd_agents/extraction/pipeline.py#L1030)),
which pass both. So a genuinely garbage extraction on a malformed Office file
sails through the pipeline's own quality gates untouched, gets written to the
findings/search index as if it were real content, and produces no
`failure_reasons` entry a downstream consumer could check.

This is fixable independent of whether `anydoc` is adopted (see
[Recommendation](#recommendation), item 1), but it's also a genuine argument
for `anydoc`, whose fail-closed behavior here required no extra pipeline code
at all.

### Accuracy on well-formed Office files: no differentiation

On the four non-malformed Office files, both tools scored identically: 1.0
text recall and 1.0 numeric exact-match rate on every file, with zero errors,
across all 3 runs. (One ground-truth bug was caught and fixed during this
work: the first draft's expected xlsx numbers used comma-grouped display
strings like `"745,300.50"`, which no cell-value-based extractor — either
tool — can produce from a raw float cell containing `745300.5`; both tools
correctly render the float as `745300.5`, and the ground truth was corrected
to match. This affected both tools identically, so it didn't change the
comparison, only the number that was being checked.) On this corpus, `anydoc`
offers no accuracy advantage on the golden path — its case rests entirely on
speed (KPI 6) and error handling (KPI 7).

---

## Full per-file KPI matrix

### PDF arm

| File | dd-agents method | dd-agents time | dd-agents recall | pdf-inspector `pdf_type` | pdf-inspector time | pdf-inspector recall |
|---|---|---|---|---|---|---|
| `clean_contract.pdf` | `primary` (pymupdf) | ~5ms | 0.83 | `text_based` | ~0.5ms | 1.00 |
| `financial_table.pdf` | `fallback_pdftotext` | ~22ms | 1.00 (numeric 1.00) | `text_based` | ~0.7ms | 1.00 (numeric 1.00) |
| `multi_column.pdf` | `primary` (pymupdf) | ~5ms | 1.00 | `text_based` | ~0.5ms | 1.00 |
| `scanned_image.pdf` | `fallback_ocr` | ~857ms | 1.00 | `scanned` | ~0.2ms | **0.00** |
| `mixed_doc.pdf` | `fallback_markitdown` | ~689ms | 1.00 | `mixed` | ~0.4ms | 1.00 |
| `cid_font.pdf` | `fallback_ocr` | ~1119ms | 0.67 | `text_based` (flags encoding issue) | ~1.0ms | 0.67 |
| `encrypted.pdf` | `failed` (clean) | ~0.5ms | n/a | raises `ValueError` (clean) | ~0.8ms | n/a |

### Office arm

| File | dd-agents method | dd-agents steady-state time | dd-agents recall | anydoc time | anydoc recall |
|---|---|---|---|---|---|
| `supply_agreement.docx` | `primary` (markitdown) | ~82–148ms | 1.00 (numeric 1.00) | ~3.5–3.7ms | 1.00 (numeric 1.00) |
| `arr_schedule.xlsx` | `primary` (openpyxl) | ~2.1–2.6ms | 1.00 (numeric 1.00) | ~0.15–0.24ms | 1.00 (numeric 1.00) |
| `subprocessor_list.csv` | `primary` (csv) | ~0.35–0.60ms | 1.00 | ~0.10–0.12ms | 1.00 |
| `nda_excerpt.rtf` | `primary` (markitdown) | ~8.8–11.2ms | 1.00 | ~0.05–0.14ms | 1.00 |
| `corrupted.docx` | `primary` (markitdown) — **returns garbage, no failure signal** | ~33–43ms | n/a | raises `MalformedError` (clean) | n/a |

---

## Reproducibility

The harness and generator scripts used for this report are not committed
(scratch tooling in `/tmp`) but are fully described above: `reportlab` +
`pypdf` for the PDF corpus, `python-docx` + `openpyxl` + the `csv` module for
the Office corpus, `ExtractionPipeline.extract_single()` vs
`pdf_inspector.process_pdf()` / `anydoc.to_markdown()`, exact-substring/value
scoring against a hand-written ground truth. PDF-arm timing was checked
across 3 repeated runs: dd-agents' millisecond- and hundred-millisecond-scale
operations (pymupdf, pdftotext, OCR) were stable within ~10% run-to-run;
pdf-inspector's sub-to-few-millisecond operations varied by up to ~3x
run-to-run (e.g. `cid_font.pdf`: 7.1ms → 1.5ms → 1.0ms across the 3 runs) —
expected timer noise at that scale on a shared machine, not a sign of
unstable behavior. Office-arm timing was checked across 3 repeated full-harness
runs (all recall/numeric/error results identical across all 3) plus a separate
5-rep steady-state measurement per file after explicitly warming each backend
once, to isolate one-time import/JIT costs from per-file cost (see
[KPI 6](#kpi-6--latency)). No run changed any classification, recall, or
error-handling result on either arm. Anyone wanting to re-run this: the corpus
generation logic is fully specified in the file/category tables above and can
be reconstructed in under two hours.

---

## Recommendation

**Do not replace any pipeline stage wholesale. Consider two narrow, additive
changes, and fix one pipeline gap regardless of either:**

1. **Fix the malformed-Office-file quality gate now, independent of this
   benchmark's outcome.** Add `check_readability=True` and
   `check_control_chars=True` to the `_try_method("markitdown", ...)` call in
   `_extract_generic()` ([pipeline.py:1299](../src/dd_agents/extraction/pipeline.py#L1299)),
   matching what the PDF path's markitdown fallback already does at
   [pipeline.py:1030, 1049, 1069](../src/dd_agents/extraction/pipeline.py#L1030).
   This is a real, verified gap (KPI 7) that exists whether or not `anydoc` is
   ever adopted.
2. **Candidate use, PDF path: pre-classification.** Swap `_inspect_pdf()`'s
   single-page heuristic for pdf-inspector's `detect_pdf()`, which classifies
   per-page (`pages_needing_ocr` list) instead of sampling page 1 only. This
   directly fixes the `mixed_doc.pdf` blind spot in KPI 1 — real value, since
   a data room with a 40-page contract where only the signature page is
   scanned is a realistic case our current per-file check would get wrong.
3. **Candidate use, PDF path: primary text extractor for the `text_based`
   tier**, ahead of `pymupdf`. It's roughly 5–30x faster in this corpus and
   produces genuine Markdown tables (useful for the search/vector-index
   consumer of this pipeline specifically — design rule 1 means specialist
   agents read original files directly regardless). Latency matters here
   because `extract_all()` runs a thread pool capped at 8 workers
   (`_DEFAULT_WORKERS`, [pipeline.py:125](../src/dd_agents/extraction/pipeline.py#L125));
   a 5–30x per-file speedup on the majority-text-based case compounds across
   a large data room.
4. **Candidate use, Office path: replace `markitdown` with `anydoc` as the
   primary backend for `_extract_generic`/`_extract_spreadsheet`.** Steady-state
   latency is 3–200x faster with identical accuracy on well-formed files in
   this corpus, and its typed exception hierarchy
   (`EncryptedError`/`MalformedError`/`UnsupportedError`/etc.) gives cleaner,
   more specific error handling than either `markitdown`'s exceptions or a
   bare `ValueError`. **This is the weaker of the two candidate swaps** —
   `anydoc` is 4 days old as of this writing (repo created 2026-08-03,
   verified via GitHub API), versus `pdf-inspector`'s ~6 months, so the same
   "unproven at this age" caution applies even more strongly here than it did
   to pdf-inspector. Pin the version and re-test before shipping.
5. **Before any code change:** re-run this same harness against a larger,
   still-synthetic corpus (aim for 30–50 files across both arms, covering more
   table shapes, more CJK/RTL variants, nested Office structures like
   embedded objects or tracked changes, and more of the
   `_EXPECTED_TEXT_RATIOS` file types in `_constants.py`) and, if possible,
   get sign-off to test against a handful of anonymized/redacted real
   data-room files under NDA rather than fully synthetic ones — synthetic
   files are clean by construction in ways real scanned contracts,
   watermarked exports, DocuSign envelopes, and Office files saved by a decade
   of different tool versions are not (the pipeline's own
   `_is_watermark_only` check exists precisely because real PDFs have that
   problem; this corpus doesn't exercise it, and the Office corpus doesn't
   exercise the analogous watermark/tracked-changes problem for Office files).

**What would change my mind toward a bigger swap on the PDF side:** if
pdf-inspector's per-page OCR routing plus a larger corpus run showed it
correctly triaging watermarked/DocuSign-style PDFs (a documented failure mode
in our own pipeline — `_is_watermark_only()` exists because of it) at similar
speed, the case for making it the primary pre-classifier for the whole PDF
branch would be much stronger. This benchmark doesn't test that scenario.

**What would change my mind toward a bigger swap on the Office side:** several
more months of `anydoc` releases without quality regressions, plus a larger
corpus confirming the accuracy parity holds on more complex Office documents
(tracked changes, embedded objects, merged cells, multi-level headers) — none
of which this corpus tests.

**What would change my mind against adopting either at all:** any evidence of
released-package quality regressions given their `0.x` versioning — worth
`pip install <package>==<pinned>` and lockfile discipline rather than an
unpinned range if either is adopted, and especially warranted for `anydoc`
given its four-day age.

---

## Sources

- [firecrawl/pdf-inspector README](https://github.com/firecrawl/pdf-inspector) — features, architecture, self-reported benchmark methodology, "Best fit" framing (retrieved 2026-08-05)
- [pdf-inspector on PyPI](https://pypi.org/project/pdf-inspector/) — API reference, install requirements, version 0.2.6 (retrieved 2026-08-05)
- [firecrawl/pdf-inspector GitHub API metadata](https://api.github.com/repos/firecrawl/pdf-inspector) — repo created 2026-02-06, 11,231 stars, 743 forks, 77 open issues, last push 2026-08-05 (retrieved 2026-08-05)
- [firecrawl/anydoc README](https://github.com/firecrawl/anydoc) — features, architecture (unified `Document` model, PDF-via-pdf-inspector delegation), per-format benchmark table vs. markitdown (retrieved 2026-08-07)
- [firecrawl-anydoc on PyPI](https://pypi.org/project/firecrawl-anydoc/) — API reference, version 0.1.6 (retrieved 2026-08-07)
- [firecrawl/anydoc GitHub API metadata](https://api.github.com/repos/firecrawl/anydoc) — repo created 2026-08-03, 9,272 stars, 436 forks, 37 open issues, last push 2026-08-06 (retrieved 2026-08-07)
- `src/dd_agents/extraction/pipeline.py` (this repo, unmodified `main` at benchmark time) — production fallback chains, thresholds, `_inspect_pdf()` and `_extract_generic()` logic
- `src/dd_agents/extraction/_constants.py` — confidence scores, extension routing tables
- `src/dd_agents/agents/severity_thresholds.py` — why numeric fidelity is the highest-stakes KPI
- This benchmark's own harness output (`results.json`, `office_results_run{1,2,3}.json`, `office_steady_state_timing.json`) — raw data behind every table above
