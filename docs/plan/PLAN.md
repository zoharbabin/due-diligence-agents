# Due Diligence Agent SDK -- Executive Plan

> Status: Implemented — pipeline and search command operational
> Package: `dd_agents` under `src/dd_agents/`
> SDK: `claude-agent-sdk` v0.1.39+ (Python 3.12+)

---

## What We Are Building

A Python application that performs forensic M&A due diligence on contract data rooms. It spawns 8 AI agents (Legal, Finance, Commercial, ProductTech, optional Judge, Executive Synthesis, Red Flag Scanner, Acquirer Intelligence), enforces a 35-step pipeline with 5 blocking gates (step 1 config validation is a precondition, not counted as a gate), validates outputs against Pydantic schemas, and produces a detailed cross-domain HTML report + 14-sheet Excel report with structured findings, citations, and audit trail. The reports provide granular analysis that deal teams can use as a basis for their own deliverables — board presentations, advisor memos, negotiation checklists, or integration plans. The orchestrator is Python code. Agents are workers, not decision-makers.

## Core Principles

- **Open-source only**: All tools and dependencies must be freely available under OSI-approved permissive licenses (Apache 2.0, MIT, BSD, PostgreSQL License). No commercial, closed-source, or subscription tools. The only exception is LLM API access via AWS Bedrock, which is pre-configured in Claude Code.

## Why: The Industry Problem

M&A due diligence runs in silos — legal, financial, and commercial advisors each produce independent reports with no cross-referencing. [31% of M&A failures trace back to DD shortcomings](https://acquisitionstars.com/ma-failure-rate/). [DD timelines keep compressing](https://www.spellbook.legal/briefs/m-a-due-diligence) while scope stays constant. [Corp dev teams screen hundreds of companies per year](https://www.corpdev.ai/wiki/fundamentals/corpdev-metrics) with DD costs sunk on every deal that doesn't close. The [Addleshaw Goddard RAG Report](https://www.addleshawgoddard.com/globalassets/insights/technology/llm/rag-report.pdf) demonstrated that AI contract analysis can reach 95% accuracy with clause-aware prompting (up from 74% baseline) — but no open-source tool applies this at scale across multiple DD workstreams.

## Why: The Enforcement Paradox

In a production retrospective analyzing a real deal, all 17 quality failures were instruction-following failures -- the LLM was told "MUST do X" in prose but skipped it. Examples: skipping customers, fabricating citations, producing aggregate summaries instead of per-customer analysis, missing gap detection, generating incorrect counts. The Skill architecture gives the LLM both orchestration and execution roles; prose constraints ("MUST", "BLOCKING") have no enforcement mechanism. The SDK inverts this: Python code enforces flow control, hooks enforce output format, and validation gates are `if/else` in code, not markdown emphasis.

## What Transfers Directly

All 3,102 lines of domain knowledge -- extraction rules, severity taxonomy (P0-P3), governance graph protocol, gap detection (cross-reference, pattern-based, checklist), cross-reference reconciliation, entity resolution (6-pass cascading matcher), reporting schema (14 sheets), numerical audit (5 layers), 30 Definition of Done checks -- transfer as agent prompts and Pydantic models. The SDK change is architectural. The analytical content is unchanged.

---

## Architecture Decisions (summaries -- full ADRs in [01-architecture-decisions.md](01-architecture-decisions.md))

**ADR-01: SDK over Skills** -- Python orchestrator with hook-enforced gates replaces LLM-directed pipeline. Eliminates the enforcement paradox where all 17 failures were instruction-following failures.

**ADR-02: File-based storage** -- Three-tier persistence (PERMANENT/VERSIONED/FRESH) on the filesystem. At 400 docs / 200 customers, file-based JSON handles all queries; no DB needed.

**ADR-03: ChromaDB optional** -- File-based keyword search (Grep) sufficient for core analysis. ChromaDB adds cross-document semantic search when enabled but is not required.

**ADR-04: NetworkX for governance** -- ~900 edges total across all customers. In-memory directed graph handles cycle detection, topological sort, and path queries. No external graph DB needed.

**ADR-05: Pydantic v2 for all schemas** -- 20+ models covering every JSON artifact. `model_json_schema()` feeds SDK structured outputs. `model_validate()` replaces LLM-based QA checks.

**ADR-06: Programmatic orchestration** -- 35 pipeline steps are Python async functions. Transitions are code, not LLM decisions. State machine supports resume-from-checkpoint.

---

## System Architecture (overview -- full details in [02-system-architecture.md](02-system-architecture.md))

```
                         dd-agents run <config>
                                |
                    +-----------v-----------+
                    |   Python Orchestrator  |
                    |     (35-step pipeline) |
                    +-----------+-----------+
                                |
          +----------+----------+----------+---------+
          |          |          |          |         |
          v          v          v          v         |
      +-------+ +--------+ +---------+ +--------+  |
      | Legal  | |Finance | |Commercl | |ProdTech|  |
      | Agent  | | Agent  | | Agent   | | Agent  |  |
      +---+----+ +---+----+ +----+----+ +---+----+  |
          |          |           |          |        |
          +-----+----+-----+----+-----+----+        |
                |          |          |              |
                v          v          v              |
         findings/    findings/   findings/          |
         {agent}/     merged/    merged/gaps/        |
                |                                    |
          +-----v------+                             |
          | Judge Agent |  (optional)                |
          +-----+------+                             |
                |                                    |
          +-----v-----------+                        |
          | Exec Synthesis  |                        |
          | + Red Flag Scan |                        |
          | + Acquirer Intel |                        |
          | (merge, QA,     |                        |
          |  HTML + Excel)  |                        |
          +-----+-----------+                        |
                |                                    |
                v                                    |
  dd_report.html + dd_report.xlsx                    |
                                                     |
          +-----------------------------------------+
          |  Three-Tier Filesystem
          |  PERMANENT: index/text/, checksums, entity cache
          |  VERSIONED: runs/{id}/findings, audit, judge, report
          |  FRESH: inventory/ (tree, files, customers, counts)
          +------------------------------------------+
```

### Dependencies

All core dependencies are freely available under permissive open-source licenses (Apache 2.0, MIT, BSD). pymupdf (optional `[pdf]` extra) is AGPL-3.0 licensed.

```
claude-agent-sdk >= 0.1.39
pydantic >= 2.0
openpyxl >= 3.1
networkx >= 3.0
rapidfuzz >= 3.0
markitdown >= 0.1
chromadb >= 0.4  (optional)
scikit-learn >= 1.3
click >= 8.0
rich >= 13.0
```

---

## Numbered File Map

Detailed content is distributed across 22 numbered files. Each file is self-contained for its topic and cross-references others by number. See [README.md](../../README.md) for the full table with dependency columns.

| File | Covers |
|------|--------|
| 01 | Architecture Decision Records (6 ADRs) |
| 02 | System architecture, control/data flow, persistence model |
| 03 | Project structure (`src/dd_agents/` package layout) |
| 04 | Pydantic v2 data models (20+ schemas) |
| 05 | 35-step orchestrator, blocking gates, state machine |
| 06 | 8 agent definitions, prompt construction, model selection |
| 07 | Tools and hooks (Stop flat format, PreToolUse guards, custom MCP tools) |
| 08 | Extraction (file discovery, markitdown fallback chain, checksum cache) |
| 09 | Entity resolution (6-pass matcher, cache, rapidfuzz) |
| 10 | Reporting (merge/dedup, 14-sheet Excel, report schema, report diff, date reconciliation) |
| 11 | QA and validation (5-layer numerical audit, 30 DoD checks, audit gates, fail-closed) |
| 12 | Error recovery (15 error scenarios, per-agent retry, partial failure, timeout, context exhaustion) |
| 13 | Multi-project (data isolation between deals, project registry, parallel execution) |
| 14 | Vector store (optional ChromaDB integration, chunking, semantic search) |
| 15 | Testing strategy, CI/CD pipeline, Docker deployment |
| 16 | Migration (5-phase migration from Claude Code Skill to SDK application) |
| 17 | File manifest (complete file inventory: 92 files across 16 categories) |
| 18 | Implementation order (phased build plan with dependency graph, critical path) |
| 19 | Vector and graph DB comparison (ruvector, ChromaDB, Qdrant, etc.) |
| 20 | Cross-document analysis (contract hierarchy, overrides, contradictions, missing docs, renewal chains) |
| 21 | Contract ontology, graph-based reasoning, explainability, hallucination prevention |
| 22 | LLM robustness: research-informed mitigations (AG RAG report, Stanford, Anthropic), chunking, context management, hallucination prevention, Excel handling |

**Reading order for implementers**: Start with PLAN.md (this file) → 01 (ADRs) → 02 (architecture) → 03 (structure) → 04 (models) → 05 (orchestrator) → 06 (agents). Docs 07-14 can be read in any order. Docs 15-18 are build/deployment. Docs 19-22 are supplementary deep-dives. Cross-references between docs use the format `XX-filename.md § Section`.

---

## Key Conventions

**customer_safe_name**: lowercase, strip legal suffixes (Inc., Corp., LLC, Ltd.), replace special chars (`&`, `'`, `/`, `,`, `.`, spaces) with `_`, collapse consecutive underscores, strip leading/trailing underscores. Example: "Smith & Partners, Inc." becomes `smith_partners`.

**Data room layout**: `_dd/forensic-dd/` for skill-specific artifacts, `_dd/` for shared files (entity cache, run history).

**Stop hook format**: Flat `{"decision": "block", "reason": "..."}` -- not nested under `hookSpecificOutput`.

**SDK API surface**:
```python
from claude_agent_sdk import (
    query, ClaudeSDKClient, ClaudeAgentOptions,
    AgentDefinition, HookMatcher,
    tool, create_sdk_mcp_server,
    AssistantMessage, ResultMessage, TextBlock, ToolUseBlock,
)
```
