# Synthetic extraction corpus

Invented files to test and benchmark text extraction. No real company, person or amount appears in any file. Names such as "Subject A Ltd" are placeholders.

Used by `tests/unit/test_extraction_corpus.py` and `scripts/bench_extraction.py`.

## Use

```python
from extraction_corpus import load_ground_truth, path_for, phrase_in

for name, entry in load_ground_truth().items():
    text = my_extractor(path_for(name))
    missing = [p for p in entry.key_phrases if not phrase_in(text, p)]
```

The directory has no installable package. Load `__init__.py` by path (see `load_corpus()` in `scripts/bench_extraction.py`). `phrase_in` ignores whitespace, so line wraps do not matter.

## Regenerate

The generated files are committed. Normal test runs never run the builder. Re-run it only to change the corpus, then commit the new files and `ground_truth.json`.

The builder needs libraries that are not in `pyproject.toml`. Install them in a throwaway venv as the header of `build.py` shows, then run that venv's Python.

```bash
python tests/fixtures/extraction_corpus/build.py                # writes into this directory
python tests/fixtures/extraction_corpus/build.py --out /tmp/x   # write elsewhere, to compare
```

Output is byte-identical between runs. The script prints a SHA-256 per file, so you can compare two runs. Fonts are SIL OFL 1.1 (Noto). They are downloaded once, checked against a pinned SHA-256, and embedded as subsets.

The whole corpus stays under 5 MB. A unit test enforces the size and a file count between 30 and 50.

## Files

| Group | Files | What it checks |
|---|---|---|
| `contract_{en,de,fr,es,ja,zh,ko}_text.pdf` | 7 | Text layer per language |
| `contract_{lang}_scanned.pdf` | 7 | Same page as an image (200 dpi, no text layer). Needs OCR |
| `layout_table_heavy_en.pdf`, `layout_table_heavy_en_scanned.pdf` | 2 | Exact amounts and dates in a ruled table |
| `layout_two_column_en.pdf` | 1 | Column A is read fully before column B |
| `layout_watermarked_en.pdf` | 1 | Diagonal watermark does not hide body text |
| `layout_signature_stamp_en.pdf` | 1 | Signature stamp box and a blank signature line |
| `layout_mixed_en.pdf` | 1 | Pages are text, scan, text, scan. Per-page classification |
| `layout_long_en.pdf` | 1 | Six pages. Page order and clause numbers |
| `damaged_truncated_en.pdf` | 1 | Tail cut off. PDFium fails, qpdf repair recovers pages 1 to 5 |
| `damaged_truncated_unrecoverable_en.pdf` | 1 | Trailer lost. Nothing can read it (`expected_failure: unreadable`) |
| `damaged_owner_password_en.pdf` | 1 | Owner password only. Must open and extract |
| `damaged_user_password_en.pdf` | 1 | User password. Must report encrypted (`expected_failure: encrypted`) |
| `office_contract_en.docx`, `office_contract_ja.docx` | 2 | Headings and a table. CJK in Office |
| `office_tracked_changes_en.docx` | 1 | Real `w:ins` and `w:del` revision marks |
| `office_arr_schedule_en.xlsx` | 1 | Two sheets, merged cell, numeric cells checked by value |
| `office_board_deck_en.pptx` | 1 | Slides, speaker notes and a table |
| `office_terms_en.html` | 1 | `<script>`, `<style>`, `<nav>` noise around a table |
| `people_officers_en.{pdf,docx}` | 2 | Fictional officers with roles and birth dates, for screening tests |

`ground_truth.json` has the exact purpose of every file.

## `ground_truth.json`

Top level: `schema_version`, `note`, `files` (keyed by file name). The loader returns a frozen `CorpusEntry` per file.

| Field | Meaning |
|---|---|
| `kind` | `pdf`, `docx`, `xlsx`, `pptx` or `html` |
| `category` | Group of the file, for example `table_heavy` or `contract_text` |
| `language` | `en`, `de`, `fr`, `es`, `ja`, `zh` or `ko` |
| `has_text_layer` | True when at least one PDF page has text. True for all Office files |
| `page_kinds` | PDF only. `text` or `scanned` for each page |
| `key_phrases` | Phrases a good extractor recovers |
| `page_key_phrases` | PDF only. Phrases per page, same length as `page_kinds`. Empty for pages that cannot be read |
| `table_cells` | Table rows, header first |
| `numeric_cells` | Numbers stored as numbers (XLSX) |
| `reading_order` | Phrases that must appear in this order |
| `persons` | Name, role, `date_of_birth`, `appointed` |
| `tracked_changes` | `inserted` and `deleted` text of a tracked-changes DOCX |
| `watermark_text` | Watermark text, when the page has one |
| `expected_failure` | `encrypted` or `unreadable` when no extractor should succeed, else `null` |
| `damage` | `truncated`, `owner_password` or `user_password`, else `null` |
| `password` | Password that opens the file, when there is one |
| `pair` | Same content: the text copy of a scan (and back), or the source file of a damaged copy |
| `purpose` | One sentence on why the file exists |
