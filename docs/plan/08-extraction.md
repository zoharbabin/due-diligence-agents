# 08 — Document Extraction Pipeline

> **Historical design spec** — written during the build phase. The code in `src/dd_agents/extraction/` is the authoritative implementation; retained for design rationale only. See `CLAUDE.md` for current state.

## Overview

Before any agent touches a document, every non-plaintext file in the data room is pre-extracted to markdown. This happens at pipeline step 5 (SKILL.md section 1b) and is a BLOCKING GATE -- agents cannot start until extraction completes. Pre-extraction ensures:

1. Agents read from cached text (fast, deterministic) instead of parsing PDFs/images on the fly
2. Every document has a single canonical text representation used for citation verification
3. Extraction quality is logged and auditable
4. Re-runs skip unchanged files via SHA-256 checksum cache

---

## 1. Extraction Fallback Chain

Each file type has a primary extraction method and fallback chain. The pipeline tries each method in order, stopping at the first that produces non-empty output.

| File Type | Detection | Primary | Fallback Chain |
|-----------|-----------|---------|----------------|
| PDF (normal) | `_inspect_pdf()` → `"normal"` | pymupdf (page markers) | pdftotext → markitdown → GLM-OCR → pytesseract → Claude vision → direct read |
| PDF (scanned) | `_inspect_pdf()` → `"scanned"` | GLM-OCR | pytesseract → Claude vision → direct read |
| PDF (missing ToUnicode) | `_inspect_pdf()` → `"missing_tounicode"` | GLM-OCR | pytesseract → Claude vision → direct read |
| Word (.docx) | Extension match | `markitdown` | macOS textutil → direct read |
| Excel (.xlsx) | Extension match | `markitdown` | `openpyxl` (smart extraction — see §1.1) → direct read |
| PowerPoint (.pptx) | Extension match | `markitdown` | direct read |
| Images (text) | Extension match | markitdown (OCR) | GLM-OCR → pytesseract → Claude vision → diagram placeholder |
| Images (diagrams) | OCR yields <20 chars | Claude vision | Diagram placeholder |
| Plain text (.txt, .csv, .json, .md) | Extension match | Direct read | -- |

> **Note:** PDF pre-inspection (`_inspect_pdf()`) classifies PDFs at ~8ms/file before extraction.
> Scanned and missing-ToUnicode PDFs skip pymupdf/pdftotext/markitdown entirely, routing
> directly to GLM-OCR. This saves ~700ms of futile extraction attempts per scanned file.

### 1.1 Smart Excel Extraction (openpyxl fallback)

> Research context: `22-llm-robustness.md` §7 (findings E-1 through E-4)

When `markitdown` fails on Excel files, the `openpyxl` fallback uses structure-preserving extraction instead of a naive cell dump.

Smart Excel extraction preserves sheet names, handles merged cells by unmerging and filling values, detects header rows, and converts formulas to their computed values. Implementation uses `openpyxl` with `data_only=True` for formula resolution. See also `22-llm-robustness.md` section 7 for additional Excel handling details.

Specific behaviors:
1. **Date conversion**: Excel date serial numbers (e.g., 44621) are pre-converted to ISO-8601 strings (`2022-03-01`). This prevents LLMs from misinterpreting dates as meaningless integers.
2. **Header preservation**: Column headers are formatted as markdown table headers above each data section. Header rows are auto-detected by inspecting the first non-empty row.
3. **Sheet separation**: Each sheet is output with a `## Sheet: {name}` markdown heading.
4. **Merged cells**: Merged cells are unmerged and the merged value is filled into all constituent cells.
5. **Formula resolution**: Formulas are converted to their computed values via `data_only=True`.
6. **Currency/percentage formatting**: Values with currency or percentage number formats are output with `$` or `%` symbols.
7. **Sub-table detection**: Blank rows are treated as sub-table separators. Each sub-table gets its own header row.
8. **Wide table handling**: For sheets with >15 columns, output the first 15 columns with a note listing remaining column names.

Implementation: `src/dd_agents/extraction/tabular.py` (~150 lines). See `22-llm-robustness.md` §7.2 for code outline.

### 1.2 Clause-Aware Chunking for Vector Store (Optional)

> Research context: `22-llm-robustness.md` §2 (AG report finding: 3,500-char clause-aware chunks with 700-char overlap are optimal)

When ChromaDB is enabled, extracted documents are additionally chunked for vector indexing. Chunking happens AFTER extraction completes (not instead of it). Agents still receive full extracted documents via tools.

Chunking strategy:
- Split at clause/section boundaries (regex patterns for legal headings, numbered subsections, recitals, schedules)
- Target ~3,500 chars per chunk with ~700-char overlap
- Merge sections shorter than 200 chars with neighbors
- Prepend 50-100 token document context to each chunk (document title, type, parties, date)
- For tabular data: chunk by 50 data rows, repeating header row in each chunk

Implementation: `src/dd_agents/extraction/chunking.py` (~200 lines). See `22-llm-robustness.md` §2.2 for code outline.

### PDF Pre-Inspection (`_inspect_pdf`)

Before attempting extraction, `_inspect_pdf()` classifies each PDF by examining
its fonts and first-page text content. This costs ~8ms per file and routes
known-bad PDFs directly to OCR, avoiding wasted extraction attempts.

| Classification | Condition | Routing |
|---------------|-----------|---------|
| `"normal"` | Text-based with valid fonts | Full chain (pymupdf → pdftotext → ...) |
| `"scanned"` | First page has < 100 text characters | Skip to GLM-OCR |
| `"missing_tounicode"` | Identity-H fonts AND >1% control-char corruption | Skip to GLM-OCR |
| `"encrypted"` | Password-protected | Skip to GLM-OCR (some allow text copy) |

> **Identity-H handling note:** Identity-H is a standard CIDFont encoding used by most
> modern PDF generators. Only 1 in 26 Identity-H PDFs actually produces garbled output
> (the one missing a /ToUnicode CMap). The classifier requires BOTH Identity-H encoding
> AND detected control-char corruption before flagging — avoiding false positives on the
> other 25.

### OCR Workflows

**GLM-OCR** (preferred OCR method, higher accuracy than pytesseract):
1. Render PDF pages to PNG images using pypdfium2 (200 DPI, max 1024px)
2. Run GLM-OCR vision-language model per page (mlx-vlm on Apple Silicon, or Ollama cross-platform)
3. Assemble results with `--- Page N ---` markers
4. Model cached for extractor lifetime (~1.5 GB for 8-bit model)

**pytesseract** (fallback when GLM-OCR unavailable):
1. Convert PDF pages to PNG images using pdf2image (poppler, 300 DPI)
2. Run `pytesseract.image_to_string()` per page (30s timeout each)
3. Concatenate results with page separators
4. Temporary files cleaned up after extraction

**Claude vision** (last resort for unreadable images/PDFs):
1. Uses `claude_agent_sdk.query()` with Read-only tool access
2. Claude visually examines the file and produces a textual description
3. Includes transcribed text, table data, diagram layouts, signatures
4. Runs in a separate thread (120s timeout) since the pipeline is synchronous

---

## 2. Extraction Module (where the code actually lives)

> The ~600 lines of `extractor.py` / `methods.py` listings that were here described
> a `DocumentExtractor` class that was never built. The real implementation is
> **`ExtractionPipeline` in `src/dd_agents/extraction/pipeline.py`**, which orchestrates
> a pre-inspection step plus per-format fallback chains across `markitdown.py`,
> `ocr.py`, `glm_ocr.py`, `layout_pdf.py`, and `_helpers.py`. Backend selection lives in
> `backend.py`; the checksum cache in `cache.py`; quality tracking in `quality.py`. Read
> those modules for the authoritative behavior. The durable design content — the fallback
> chain (§1), PDF pre-inspection, OCR workflows, checksum cache (§4), quality log (§5), the
> step-5 blocking gate (§6), image/diagram handling (§7), and file layout (§10) — is below.

## 4. Checksum Cache (PERMANENT Tier)

The checksum file lives at `_dd/forensic-dd/index/text/checksums.sha256`. It persists across runs and is the primary mechanism for avoiding redundant re-extraction.

**Format** (standard sha256sum format):
```
a1b2c3d4e5f6...  ./Above 200K USD/Acme Corp/MSA.pdf
f7e8d9c0b1a2...  ./Above 200K USD/Acme Corp/Order Form 2023.docx
9a8b7c6d5e4f...  ./Reference Data/Subjects Cube Q4 2024.xlsx
```

**Cache behavior on re-runs**:
1. Load existing checksums from `checksums.sha256`
2. For each file in `files.txt`:
   a. Compute current SHA-256 hash
   b. If hash matches cached value AND extracted text file exists: **skip** (cache hit)
   c. If hash differs OR no cached value OR text file missing: **re-extract**
3. After extraction, write updated checksums
4. Remove stale entries (files deleted from data room)

**Expected performance**: On a data room of 400 files, first run extracts all 400. Second run with no changes extracts 0 (100% cache hit). Adding 5 new files extracts only 5.

---

## 5. Extraction Quality Log (PERMANENT Tier)

The quality log lives at `_dd/forensic-dd/index/extraction_quality.json`. It records how each file was extracted and with what confidence.

```json
{
  "./Above 200K USD/Acme Corp/MSA.pdf": {
    "method": "markitdown",
    "fallback_used": false,
    "bytes_extracted": 24500,
    "confidence": "high",
    "text_path": "_dd/forensic-dd/index/text/Above_200K_USD__Acme_Corp__MSA.pdf.md",
    "timestamp": "2025-02-18T14:30:00Z"
  },
  "./Above 200K USD/Acme Corp/Signature Page.png": {
    "method": "pytesseract",
    "fallback_used": true,
    "bytes_extracted": 1200,
    "confidence": "low",
    "text_path": "_dd/forensic-dd/index/text/Above_200K_USD__Acme_Corp__Signature_Page.png.md",
    "timestamp": "2025-02-18T14:31:00Z"
  },
  "./Reference Data/Org Structure.png": {
    "method": "diagram_placeholder",
    "fallback_used": true,
    "bytes_extracted": 150,
    "confidence": "low",
    "text_path": "_dd/forensic-dd/index/text/Reference_Data__Org_Structure.png.md",
    "timestamp": "2025-02-18T14:32:00Z"
  }
}
```

**Confidence levels**:
- `high` -- Primary method succeeded (markitdown on text PDFs, Office docs)
- `medium` -- First fallback succeeded (pdftotext, openpyxl, read_tool for known formats)
- `low` -- OCR fallback or diagram placeholder
- `failed` -- All methods returned empty (logged as Unreadable gap)

---

## 6. Blocking Gate (Pipeline Step 5)

Extraction is a mandatory gate. The orchestrator checks these conditions before proceeding to step 6:

```python
# Illustrative — the real method is PipelineEngine._step_05_bulk_extraction
# in orchestrator/engine.py, using ExtractionPipeline from extraction/pipeline.py.

async def _step_05_bulk_extraction(self, state: PipelineState) -> PipelineState:
    """Step 5: Bulk pre-extraction with fallback chain."""

    pipeline = ExtractionPipeline(
        project_dir=state.project_dir,
        skill_dir=state.project_dir / state.skill_dir,
    )

    files = _load_files_txt(state)
    file_types = _load_file_types(state)

    try:
        results = await pipeline.extract_all(files, file_types)
    except ExtractionPipelineError as e:
        # >50% failure rate -- STOP pipeline
        raise PipelineBlockingError(
            step=5,
            message=str(e),
            action="Report extraction pipeline issue to user. "
                   "Check markitdown installation: pip install markitdown. "
                   "Check poppler (pdftotext): brew install poppler.",
        )

    # BLOCKING GATE: verify outputs exist
    skill_dir = state.project_dir / state.skill_dir
    checksums_path = skill_dir / "index" / "text" / "checksums.sha256"
    quality_path = skill_dir / "index" / "extraction_quality.json"

    if not checksums_path.exists() or checksums_path.stat().st_size == 0:
        raise PipelineBlockingError(
            step=5,
            message="checksums.sha256 missing or empty after extraction",
            action="Extraction failed to produce checksum cache.",
        )

    if not quality_path.exists() or quality_path.stat().st_size == 0:
        raise PipelineBlockingError(
            step=5,
            message="extraction_quality.json missing or empty after extraction",
            action="Extraction failed to produce quality log.",
        )

    # Log failed extractions as gaps
    # NOTE: extraction_gaps is computed during extraction (step 4/5) and stored
    # in extraction_quality.json in the FRESH tier, not as a PipelineState field.
    # Code references should use load_extraction_quality() to read this data.
    # The state.extraction_gaps attribute below is a transient list used only
    # within this step to collect gaps before writing them to extraction_quality.json.
    failed_results = [r for r in results if r.confidence == "failed"]
    for result in failed_results:
        state.extraction_gaps.append({
            "source_path": result.source_path,
            "error": result.error,
            "gap_type": "Unreadable",
        })

    # Summary statistics
    state.extraction_stats = {
        "total_files": len(files),
        "plaintext_skipped": len(files) - len(results),
        "extracted": len([r for r in results if r.confidence != "failed"]),
        "cache_hits": len([r for r in results if r.method == "cached"]),
        "failed": len(failed_results),
        "by_method": _count_by_method(results),
    }

    return state
```

---

## 7. Image and Diagram Handling

Images require special handling because they may contain either text (signature pages, scanned letters) or diagrams (org charts, architecture diagrams, network maps).

### Text Images
Processed through the OCR fallback chain (markitdown OCR -> pytesseract). The extracted text is written to the text index like any other document.

### Diagram Images
When OCR yields fewer than 50 characters, the image is classified as a diagram. A placeholder is written to the text index directing agents to use the Read tool for visual examination:

```
[DIAGRAM/IMAGE: ./Reference Data/Org Structure.png]
This image could not be OCR-extracted. Use the Read tool to visually examine this file.
```

When agents encounter this placeholder, they use the SDK's built-in Read tool (which supports image viewing since Claude is multimodal) to examine the diagram visually. Diagram descriptions are recorded in the subject JSON under `diagrams[]`:

```json
{
  "diagrams": [
    {
      "file_path": "./Reference Data/Org Structure.png",
      "description": "Corporate org chart showing Acme Holdings Inc. as parent with two subsidiaries: Acme Corp (US) and Acme Solutions ULC (Canada). All subject contracts appear to be signed by Acme Holdings Inc.",
      "relevance": "Entity validation for contract signing authority"
    }
  ]
}
```

---

## 8. Text Path Convention

The mapping from source file path to extracted text path follows a deterministic convention:

```
Source:    ./Above 200K USD/Acme Corp/MSA.pdf
Text:      _dd/forensic-dd/index/text/Above_200K_USD__Acme_Corp__MSA.pdf.md

Source:    ./Reference Data/Subjects Cube.xlsx
Text:      _dd/forensic-dd/index/text/Reference_Data__Customers_Cube.xlsx.md
```

**Transformation rules**:
1. Strip leading `./`
2. Replace `/` with `__` (double underscore for directory separators)
3. Preserve the original file extension in the name
4. Append `.md` (extracted text is always markdown)

This convention is used by:
- The `verify_citation` MCP tool to find extracted text for a source file
- Agent prompts that tell agents where to find pre-extracted content
- The extraction quality log to record text file paths

---

## 9. Dependencies

Required Python packages for the extraction pipeline:

```
# pyproject.toml [project.optional-dependencies]
extraction = [
    "markitdown>=0.1.0",         # Primary extraction for all formats
    "openpyxl>=3.1.0",           # Excel fallback
    "pytesseract>=0.3.10",       # OCR fallback
    "pdf2image>=1.16.0",         # PDF-to-image for OCR (pytesseract)
    "Pillow>=10.0.0",            # Image handling
    "pypdfium2>=4.0.0",          # PDF-to-image for GLM-OCR
]
```

Optional Python packages:
```
    "mlx-vlm>=0.1.0",           # Apple Silicon GLM-OCR backend
    "ollama>=0.1.0",             # Cross-platform GLM-OCR backend
```

Required system dependencies:
- `poppler-utils` (provides `pdftotext` and `pdftoppm`): `brew install poppler` (macOS), `apt install poppler-utils` (Debian/Ubuntu)
- `tesseract-ocr`: `brew install tesseract` (macOS), `apt install tesseract-ocr` (Debian/Ubuntu)
- `pymupdf` (fitz): PDF pre-inspection and primary extraction (pip install)

---

## 10. File Layout

```
src/dd_agents/
  extraction/
    __init__.py
    _constants.py            # Shared constants (extension sets, confidence values)
    _helpers.py              # Shared helpers (read_text)
    pipeline.py              # ExtractionPipeline orchestrator with fallback chains
    markitdown.py            # markitdown wrapper (Office + PDF)
    ocr.py                   # OCR fallback (pytesseract)
    glm_ocr.py               # GLM-OCR vision-language model (mlx-vlm / Ollama)
    cache.py                 # SHA-256 checksum cache
    quality.py               # ExtractionQualityTracker
    reference_downloader.py  # External T&C URL download + extraction
```

Extraction artifacts in the data room:
```
_dd/forensic-dd/
  index/
    text/
      checksums.sha256                              # PERMANENT
      Above_200K_USD__Acme_Corp__MSA.pdf.md         # Extracted text
      Above_200K_USD__Acme_Corp__DPA.pdf.md
      Reference_Data__Customers_Cube.xlsx.md
      ...
    extraction_quality.json                         # PERMANENT
```
