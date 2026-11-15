# Extraction coverage

What the extraction pipeline can read, and how to check your own documents.

## Text by file type

| Type | Path |
|------|------|
| PDF with a text layer | PDFium, then `pdftotext`, then markitdown |
| Scanned PDF, images | OCR (GLM-OCR if available, else Tesseract) |
| Office files | markitdown |
| Plain text, CSV | Read directly |

Source of truth: `src/dd_agents/extraction/pipeline.py`.

## Mixed PDFs (text pages plus scanned pages)

PDFium reads the pages that have a text layer. Pages without one are rendered and sent to OCR on their own (`extraction/pdf_pages.py`). The page text is joined in page order.

| Situation | Result |
|-----------|--------|
| Every page has text | No OCR runs |
| Some pages scanned, OCR works | Full text, chain shows `ocr_pages(...)` |
| Some pages scanned, OCR unavailable or empty | Text from the readable pages, and the failure reason `pages N, M have no text layer and OCR could not read them: extracted text is incomplete` |

Small OCR models can get stuck and repeat the same lines. When a page repeats a long line four or more times, the repeats are dropped and the entry gets the reason `page N OCR output repeated itself and was trimmed`. Ollama GLM-OCR calls are capped at 4096 output tokens and 180 seconds per page.

Scanned pages are never dropped silently. Treat an "incomplete" entry as a coverage gap.

Page detection uses `pdf-inspector` when installed (`pip install "dd-agents[pdf-fast]"`). Otherwise a page with fewer than 20 characters counts as scanned. At most 50 pages per file go to OCR.

## OCR and languages

| Backend | Languages |
|---------|-----------|
| Tesseract (`pytesseract`) | The packs listed in `extraction.ocr_languages`. Default `["eng"]` |
| GLM-OCR | Not configured. Accuracy per language is not measured here |

Text-layer PDFs and Office files are not affected by `ocr_languages`. They carry Unicode text.

## Set up a language

```bash
brew install tesseract-lang                       # or your package manager's language packs
dd-agents extraction check --languages deu,eng    # confirm the packs exist
```

Then set it in the deal config:

```json
{ "extraction": { "ocr_backend": "pytesseract", "ocr_languages": ["deu", "eng"] } }
```

Codes are Tesseract codes (`deu`, `fra`, `chi_sim`, `jpn`, `script/Cyrillic`). List them separately. Do not write `deu+eng`.

## Test your own documents

```bash
dd-agents extraction check --config deal-config.json path/to/scan.pdf
```

The command extracts the file and prints how many letters it found per script. It warns when a script is present that no configured language reads. For example, Cyrillic text with `ocr_languages: ["eng"]` gives a warning that lists `rus`, `ukr` and others.

What the check does not do: it does not guess the document's language or score accuracy. A clean result means the right packs are configured, not that the text is correct. Read the extracted text for a few pages.

## Known limits

- Right-to-left and vertical scripts depend on the OCR backend. Check a real page before relying on it.
- Handwriting and low-quality scans lower accuracy in any language.
