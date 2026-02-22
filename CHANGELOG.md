# Changelog

All notable changes to this project will be documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/).

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
