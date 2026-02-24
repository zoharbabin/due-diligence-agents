# Changelog

All notable changes to this project will be documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/).

## [0.2.0] - 2026-02-24

### Added

- PDF pre-inspection (`_inspect_pdf`) classifies PDFs before extraction — routes scanned and garbled PDFs directly to OCR, saving ~700ms per file.
- GLM-OCR vision-language model as preferred OCR method (mlx-vlm on Apple Silicon, Ollama cross-platform). Higher accuracy than pytesseract with structured Markdown output.
- Claude vision as last-resort fallback for images and PDFs that all OCR methods fail on — uses Claude Agent SDK to visually examine files.
- Control-character corruption detection (`_has_control_char_corruption`) catches garbled text from PDFs with missing /ToUnicode CMap entries.
- Watermark detection (`_is_watermark_only`) catches DocuSign overlay-only PDFs where >50% of lines are identical repeated strings.
- Binary image detection in readability gates — PNG/JPEG magic bytes, U+FFFD replacement character ratio, improved printable character counting.
- Confidence scaling (`_scale_confidence`) — base scores now scale by actual-vs-expected text extraction ratio, calibrated from production medians.
- Shared extraction constants (`_constants.py`) and helpers (`_helpers.py`) — eliminates 5 duplicate definitions across extraction modules.
- Unified `_try_method()` helper consolidates duplicated try/check/write/return patterns across PDF, image, and Office extraction chains.
- `_check_text_quality()` extracts shared U+FFFD and printable-ratio checks used by both `_is_cached_output_readable` and `_is_readable_text`.
- Reference URL downloads parallelized with `ThreadPoolExecutor` (5 concurrent).
- Citation verifier optimized with per-file page split caching and exact substring matching before fuzzy matching.

### Fixed

- Confidence scores calibrated to real-world medians — PDF ratio lowered from 0.5 to 0.09 (was producing 0.01-0.05 scores for well-extracted files).
- Binary PNG/JPEG data no longer passes readability gates (U+FFFD counted as non-printable).
- Identity-H PDF over-classification fixed — 25/26 Identity-H PDFs now extract normally with page markers (was skipping 91% of PDFs to markitdown, losing page markers).
- MuPDF C-level stderr noise suppressed and routed through Python logging.

### Changed

- PDF extraction chain expanded: pymupdf → pdftotext → markitdown → GLM-OCR → pytesseract → Claude vision → direct read.
- Image extraction chain expanded: markitdown → GLM-OCR → pytesseract → Claude vision → diagram placeholder.
- Scanned PDF chain: GLM-OCR → pytesseract → Claude vision → direct read (skips text extractors entirely).

## [0.1.0] - 2026-02-22

### Added

- 102 Pydantic v2 data models covering findings, gaps, manifests, config, inventory, quality scores, and all intermediate pipeline schemas.
- 6-pass cascading entity resolution with rapidfuzz token-sort-ratio matching, abbreviation expansion, cache learning, and configurable thresholds.
- Document extraction pipeline with markitdown, pdftotext fallback chain, checksum-based caching, and optional Tesseract OCR for scanned PDFs.
- 35-step deterministic orchestrator with 5 blocking quality gates, step dependencies, state machine, and checkpoint/resume support.
- 4 specialist agents (Contract, Financial, Operational, Compliance) plus optional Judge agent and Reporting Lead, all driven by claude-agent-sdk v0.1.39+.
- Schema-driven 14-sheet Excel report generation via openpyxl, with configurable report_schema.json governing sheet layout, column definitions, and formatting.
- 5-layer numerical audit system: extraction-time validation, cross-document reconciliation, agent-output verification, report-level totals check, and final sign-off gate.
- 30 Definition of Done (DoD) checks enforced as fail-closed quality gates across the pipeline.
- CLI with `run`, `validate`, and `version` commands via Click, with `--dry-run`, `--mode incremental`, and `--verbose` flags.
- Optional ChromaDB vector store integration for cross-document semantic search and retrieval-augmented analysis.
- Incremental execution mode that skips unchanged documents based on file checksums, reducing re-processing time for iterative runs.
- Three-tier persistence layer: run-scoped file storage, cross-run project registry, and optional database-backed metadata store.
- NetworkX-based governance graph construction for entity relationship mapping and contract hierarchy analysis.
- Hook-enforced quality gates via claude-agent-sdk PreToolUse, PostToolUse, and Stop hooks.
- Custom MCP tools (validate_finding, lookup_entity, query_vector_store) for agent-accessible validation and search.
- Deal configuration system with JSON schema validation, template configs, and entity alias management.
- Quickstart example with sample data room, pre-filled deal config, and step-by-step guide.
- Dockerfile with multi-stage build for containerized deployment.
- Comprehensive test infrastructure with pytest, fixtures, and markers for unit, integration, and e2e test tiers.
