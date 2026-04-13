# 22 — LLM Robustness: Research-Informed Mitigations

> **Purpose**: Cross-cutting reference for every design decision aimed at overcoming inherent LLM limitations when analyzing contracts, financial data, and technical documents. Consolidates findings from peer-reviewed research and maps each finding to a concrete mitigation in the plan.
> **Cross-references**: `06-agents.md` (prompting), `08-extraction.md` (pipeline), `11-qa-validation.md` (audit), `14-vector-store.md` (retrieval), `21-ontology-and-reasoning.md` (reasoning)

---

## 1. Research Foundation

This section catalogues the empirical findings that inform the plan. Every claim is sourced; every mitigation is traceable to a finding.

### 1.1 Addleshaw Goddard RAG Report (2024)

**Study**: 510 CUAD contracts, 9 provision types, systematic evaluation of retrieval and generation strategies using GPT-4 and GPT-3.5. Most rigorous publicly available evaluation of LLM contract analysis.

Key findings (with section references to the AG report):

| # | Finding | AG Section | Implication for Plan |
|---|---------|-----------|---------------------|
| AG-1 | RAG 10 (10 retrieved chunks) **outperforms** full in-context analysis. Smaller, targeted context produces higher F1 than dumping the entire document. | Retrieval §3.1 | Do NOT paste full documents into agent prompts. Use targeted extraction per provision. |
| AG-2 | Clause-aware chunking (splitting at section/clause boundaries) outperforms fixed-size chunking. Optimal chunk: ~3,500 chars with ~700-char overlap. | Retrieval §2.2 | Implement clause-boundary detection in extraction pipeline. |
| AG-3 | **Chunk ordering matters**: feeding chunks in original document order (not by relevance score) preserves structural context and improves extraction accuracy. | Retrieval §3.2 | When presenting retrieved chunks to agents, sort by document position, not similarity score. |
| AG-4 | Provision-specific prompts outperform generic "find all clauses" prompts. Each provision type needs: legal definition, targeted request, relevant keywords, and general extraction instructions. | Generation §4.1 | Build per-provision prompt templates for each specialist agent. |
| AG-5 | Simple system prompts outperform complex ones. Overly detailed instructions degrade accuracy. A persona + task description is sufficient. | Generation §4.2 | Keep system prompts short. Move detail to user prompt sections. |
| AG-6 | **Follow-up prompts improve accuracy by 9.2% on average**. Accusatory/emotive follow-ups ("you may have missed critical information") work best. | Generation §5 | Implement a mandatory follow-up pass for high-value provisions (P0/P1 findings). |
| AG-7 | Cap on Liability provisions are the hardest to extract (0.67 F1 vs 0.99 for Governing Law). Provisions with high formulation variability are systematically harder. | Provision Analysis §6 | Allocate more verification effort to variable-formulation provisions (liability caps, indemnification, exclusivity). |
| AG-8 | Giving the model a "Not found" option reduces hallucination. Without it, models fabricate clauses rather than admitting absence. | Generation §4.3 | Every agent prompt must include explicit "If you cannot find [X], write gap_type: Not_Found with explanation." |
| AG-9 | Temperature 0 with constant seed produces reproducible results. Higher temperatures increase hallucination risk. | Parameters §7 | Enforce temperature 0 for all agent invocations. |
| AG-10 | Baseline RAG accuracy for contract analysis: 74%. Optimized (improved retrieval + improved prompts + follow-up): 95%. The 21-point gap is entirely in engineering, not model capability. | Summary Table 3 | The plan's hook-enforced architecture + these mitigations should close the accuracy gap. |

### 1.2 Stanford Legal AI Hallucination Study (Magesh et al., 2025)

**Study**: Systematic evaluation of legal AI tools including LexisNexis AI, Westlaw AI, GPT-4.

| # | Finding | Implication |
|---|---------|------------|
| S-1 | LexisNexis AI: 17% hallucination rate. Westlaw AI: 33%. GPT-4 (direct): 58-80% on legal tasks. | Even purpose-built legal AI hallucinates. Citation verification is mandatory, not optional. |
| S-2 | Longer answers correlate with more hallucinations. | Constrain agent output length. Short, cited findings > verbose narrative. |
| S-3 | Systems struggle with "elementary legal comprehension" — misidentifying parties, confusing defined terms, reversing obligations. | Enforce structured output (Pydantic models) for parties, terms, and obligations. Validate against document metadata. |
| S-4 | RAG reduces but does not eliminate hallucination. | RAG is necessary but insufficient. Layer additional verification (Judge, citation hooks, numerical audit). |

### 1.3 Anthropic Contextual Retrieval (2024)

| # | Finding | Implication |
|---|---------|------------|
| A-1 | Prepending 50-100 tokens of document-level context to each chunk reduces retrieval failures by 49%. | When chunking for vector store, prepend document metadata (title, parties, date, document type). |
| A-2 | Combining contextual retrieval with reranking reduces failures by 67%. | If ChromaDB is enabled, implement reranking of results before feeding to agents. |
| A-3 | Prompt caching makes contextual chunk generation cost-effective at scale. | Cache document-level summaries in PERMANENT tier for reuse across runs. |

### 1.4 Document-Level Retrieval Mismatch (Reuter et al., 2025)

| # | Finding | Implication |
|---|---------|------------|
| D-1 | Legal boilerplate causes lexical redundancy — retrievers select chunks from the WRONG source document because boilerplate text matches across documents. | Each chunk must carry explicit source document metadata. Retrieval must filter by document before ranking by similarity. |
| D-2 | Summary-Augmented Chunking (SAC): injecting document-level summaries into chunks prevents retrieval from wrong documents. | Implement SAC for all chunks in optional vector store integration. |
| D-3 | Generic document summaries outperform expert-guided summaries for retrieval. | Use LLM-generated summaries (not manually crafted) for chunk context. |

### 1.5 Excel and Tabular Data Challenges (LangChain/eparse, 2024)

| # | Finding | Implication |
|---|---------|------------|
| E-1 | LLMs misinterpret Excel date serial numbers (e.g., 44621 → "2022-03-01"). | Pre-convert all Excel dates to ISO-8601 strings during extraction. |
| E-2 | Financial amounts can be off by 10x due to unit/scale ambiguity. | Extract units alongside values. Include column headers in every data chunk. |
| E-3 | Sub-table extraction dramatically outperforms whole-sheet extraction. | Detect logical sub-tables within sheets. Extract each with its own header row. |
| E-4 | Map-reduce chains outperform "stuff" (single-prompt) for spreadsheet analysis. | For spreadsheets with >100 rows, use chunked analysis with per-chunk summaries merged at end. |

### 1.6 Context Window Degradation

| # | Finding | Source | Implication |
|---|---------|--------|------------|
| C-1 | "Lost-in-the-middle" — information in the middle 40% of long contexts is recalled at lower rates than information at the beginning or end. | Liu et al. (2023), Pinecone research | Place critical instructions at prompt start and end. Place subject data in the middle (it's verified by coverage gate anyway). |
| C-2 | Even 200K-token context models degrade for facts beyond ~80K tokens. | Anthropic internal benchmarks | Cap agent prompts at 80K tokens (40% of 200K). Already specified in doc 06 as the safety margin. |
| C-3 | Attention degrades proportionally to prompt length. Short prompts with precise context outperform long prompts with full context. | AG Report §3.1 (AG-1 above) | Reinforces: targeted extraction > full document dumps. |

---

## 2. Chunking and Segmentation Strategy

### 2.1 When Chunking Applies

Chunking is relevant at two points in the pipeline:

| Pipeline Point | Purpose | Strategy |
|---------------|---------|----------|
| **Pre-extraction** (step 5) | Convert documents to text for agent consumption | Document-level extraction (no chunking). Output: one `.md` file per source document. |
| **Vector indexing** (optional, step 5.5) | Index chunks for semantic search via ChromaDB | Clause-aware chunking with overlap. |

Agents do NOT receive chunked text. They receive full extracted documents and use Read/Grep tools to navigate them. Chunking is only for the optional vector store.

**Rationale** (from AG-1): RAG 10 outperforms full in-context because the retriever selects only relevant chunks. But our agents are specialists — they read entire subject files through their domain lens. The agent IS the retriever. Chunking the agent's input would fragment the structural context agents need for governance graph construction, override detection, and cross-reference reconciliation. Instead, we control context size at the subject-batch level (doc 06 §6).

### 2.2 Clause-Aware Chunking for Vector Store

Clause-aware chunking integrates with the extraction pipeline defined in `08-extraction.md`. After text extraction (step 4 in the pipeline), documents are chunked for vector store insertion. Chunking parameters: 3,500 characters per chunk, 700-character overlap, clause-boundary-aware splitting.

When ChromaDB is enabled, chunks must respect document structure:

```python
# src/dd_agents/extraction/chunking.py

import re
from dataclasses import dataclass

@dataclass
class Chunk:
    text: str
    source_file: str
    text_path: str
    chunk_index: int
    start_char: int
    end_char: int
    section_heading: str | None
    document_context: str  # 50-100 token summary of source document

# Clause boundary patterns (legal document structure)
CLAUSE_PATTERNS = [
    r'(?m)^#{1,3}\s+',                           # Markdown headings
    r'(?m)^(?:ARTICLE|SECTION|CLAUSE)\s+\d+',    # Formal clause headers
    r'(?m)^\d+\.\d+[\.\s]',                       # Numbered subsections
    r'(?m)^(?:WHEREAS|NOW,?\s+THEREFORE)',         # Recitals
    r'(?m)^(?:SCHEDULE|EXHIBIT|ANNEX)\s+[A-Z\d]', # Attachments
]

TARGET_CHUNK_SIZE = 3500    # chars (per AG report optimal)
OVERLAP_SIZE = 700          # chars (per AG report optimal)
MIN_CHUNK_SIZE = 200        # Merge short sections with neighbors

def chunk_document(
    text: str,
    source_file: str,
    text_path: str,
    document_context: str,
) -> list[Chunk]:
    """Split document into clause-aware chunks.

    Strategy:
    1. Detect clause/section boundaries via regex patterns
    2. Split at boundaries, targeting ~3500 chars per chunk
    3. If a section exceeds target, split at sentence boundaries
    4. Merge sections shorter than MIN_CHUNK_SIZE with neighbors
    5. Add OVERLAP_SIZE chars of overlap between consecutive chunks
    6. Prepend document_context to each chunk (per Anthropic A-1)
    """
    ...
```

### 2.3 Tabular Data Chunking

Excel and CSV data require different chunking:

```python
def chunk_tabular(
    text: str,
    source_file: str,
    text_path: str,
    document_context: str,
) -> list[Chunk]:
    """Chunk tabular data preserving header context.

    Strategy:
    1. Detect header row (first row or row after blank line)
    2. Split into sub-tables of 50 data rows each
    3. Prepend header row to each chunk
    4. For wide tables (>15 columns): split vertically, keeping key columns
    5. Prepend document_context to each chunk
    """
    ...
```

### 2.4 Cross-Reference to Implementation

| Doc | Section | What to Implement |
|-----|---------|------------------|
| `08-extraction.md` | Section 2 (DocumentExtractor) | After extraction, optionally invoke chunking for vector store indexing |
| `14-vector-store.md` | Section 3 (Ingestion) | Use clause-aware chunks from `extraction/chunking.py`, not naive fixed-size splits |
| `05-orchestrator.md` | Step 5 | Add optional step 5.5: chunk and index if ChromaDB enabled |
| `17-file-manifest.md` | File list | Add `src/dd_agents/extraction/chunking.py` (~200 lines) |

### 2.5 Search Analyzer Chunking

The `dd-agents search` command uses a distinct chunking strategy optimized for comprehensive contract analysis rather than vector retrieval. While §2.2 describes chunking for the optional vector store (~3.5K chars), search chunking operates at a much larger scale (~150K chars) because search requires full-document analysis, not similarity-based retrieval.

**Research mapping:**

| Finding | Application to Search Chunking |
|---------|-------------------------------|
| AG-1 | Target 150K chars per chunk (~50K tokens) — well within 200K context, leaving room for system prompt and output. Smaller focused context outperforms full document dumps. |
| AG-2 | Split at page boundaries (`--- Page N ---` markers) rather than fixed character counts. Page boundaries are natural structural breaks in legal documents. |
| AG-3 | Chunks preserve original document order. File segments within each chunk maintain their position in the source document. |
| AG-6 | Phase 4 (validation) implements follow-up prompting for NOT_ADDRESSED answers: "Pay special attention to schedules, exhibits, annexes, and definitions sections." |
| AG-8 | Each chunk prompt includes explicit NOT_ADDRESSED option. Phase 2 merge treats NOT_ADDRESSED as lowest priority (YES > NO > NOT_ADDRESSED). |

**Architecture:**

```
Phase 1 — MAP:    Each chunk analyzed independently (stateless SDK calls)
Phase 2 — MERGE:  Mechanical combination (YES > NO > NOT_ADDRESSED, dedup citations)
Phase 3 — SYNTH:  Lightweight LLM call with all findings as JSON (~5-20KB) for conflicts only
Phase 4 — VALID:  Follow-up for remaining NOT_ADDRESSED answers
```

**Implementation:** `src/dd_agents/search/chunker.py` (pure logic), `src/dd_agents/search/analyzer.py` (4-phase orchestration).

---

## 3. Context Window Management

### 3.1 Token Budget Architecture

The system manages context at three levels:

| Level | Mechanism | Limit | Enforcement |
|-------|-----------|-------|-------------|
| **Prompt construction** | `PromptSizeEstimator` in `prompt_builder.py` | 80K tokens (40% of 200K context) | Python code splits subjects into groups if exceeded |
| **Agent runtime** | Agent processes subjects sequentially; each subject's files are read on-demand via tools | No single subject file should exceed ~30K tokens | Extraction logs file sizes; orchestrator flags files >120KB of text |
| **Output accumulation** | Agent writes one JSON per subject, keeping output incremental | No output accumulates in context | PostToolUse hooks prevent aggregate files |

### 3.2 Prompt Token Budget Breakdown

Per specialist agent, with 200K context window and 80% safety margin (160K usable):

| Component | Tokens | Notes |
|-----------|--------|-------|
| System prompt | ~200 | Short persona + task (per AG-5) |
| Deal context | ~500 | Buyer, target, subsidiaries |
| Subject list | 50 × N | N = subjects in this group |
| Reference file texts | Variable | Measured per file; cap at 40K total |
| Domain rules | ~3,000 | Extraction + governance + gap detection |
| Output schema | ~600 | JSON schema for structured output |
| Instructions | ~1,000 | File processing, manifest, output rules |
| **Reserved for agent work** | **~115K** | Tool calls, file reads, reasoning, output |

**Maximum subjects per group**: If reference files consume 40K tokens, remaining prompt budget is ~35K tokens. At 50 tokens/subject, that's ~700 subjects per group. In practice, groups are limited by agent processing capacity (agent must Read each subject's files), not prompt size.

### 3.3 Large File Handling

Files that extract to >120KB of text (approximately >30K tokens) require special handling:

```python
# In extraction pipeline, after extraction completes:

LARGE_FILE_THRESHOLD = 120_000  # bytes of extracted text

def flag_large_files(extraction_results: list[ExtractionResult]) -> list[str]:
    """Identify files that may challenge agent context when read."""
    return [
        r.text_path for r in extraction_results
        if r.bytes_extracted > LARGE_FILE_THRESHOLD
    ]
```

For flagged files, agents are instructed to use Grep for targeted search rather than Read for full content:

```
LARGE FILES: The following files are large (>120KB extracted text).
For these files, use Grep to search for specific terms rather than
reading the entire file. This prevents context exhaustion.
  - _dd/forensic-dd/index/text/Master_Agreement_v3.pdf.md (245KB)
```

### 3.4 Lost-in-the-Middle Mitigation (C-1)

Agent prompt structure places critical content at the beginning and end:

```
[START — high attention zone]
  1. Role and deal context
  2. Specialist focus areas
  3. Strict output rules ("MUST" instructions)

[MIDDLE — lower attention zone]
  4. Subject list with file paths
  5. Subject-mention index
  6. Reference file texts

[END — high attention zone]
  7. Domain rules (extraction, governance, gap detection)
  8. Output format (JSON schema)
  9. Manifest requirement
  10. Repetition of key rules ("EVERY subject, EVERY file")
```

This reorders the existing prompt sections (doc 06 §5.1) to place volatile data in the middle and invariant rules at the edges.

### 3.5 Runtime Context Monitoring

Agents cannot report their own context usage, but the orchestrator can detect context exhaustion indirectly:

| Signal | Detection | Response |
|--------|-----------|----------|
| Agent stops producing output files | No new file writes for 5+ minutes (monitored via filesystem timestamps) | Status check via error recovery (doc 12 scenario 8) |
| Agent produces empty/truncated JSON | PostToolUse hook detects malformed output | Block write, increment error count; if >3 errors, treat as context exhaustion |
| Agent writes aggregate file | PostToolUse hook blocks `_global.json`, `batch_summary.json` patterns | Block and issue warning; if persists, terminate and re-spawn with smaller subject set |
| Agent exits with incomplete manifest | Stop hook checks subject count in manifest vs assigned | Re-spawn for missing subjects (doc 12 scenario 2) |

---

## 4. Provision-Specific Prompt Engineering

### 4.1 Background (AG-4, AG-5)

The AG report found that provision-specific prompts dramatically outperform generic extraction prompts. Each provision type has different formulation variability and requires different keywords for effective extraction.

### 4.2 Provision Difficulty Spectrum

Based on AG report Table 3, provisions ordered by extraction difficulty:

| Provision | AG F1 Score | Variability | Primary Agent |
|-----------|------------|-------------|---------------|
| Governing Law | 0.99 | Low (always in same section) | Legal |
| Insurance | 0.98 | Low | Finance |
| Non-Compete | 0.96 | Medium | Legal |
| Termination for Convenience | 0.93 | Medium | Legal, Commercial |
| Most Favored Nation | 0.90 | Medium-High | Commercial |
| Anti-Assignment | 0.88 | Medium-High | Legal |
| Exclusivity | 0.86 | High | Legal, Commercial |
| Change of Control | 0.82 | High | Legal |
| Cap on Liability | 0.67 | Very High | Legal, Finance |

### 4.3 Prompt Template Structure (Per Provision)

Each specialist's focus area (doc 06 §5 `SPECIALIST_FOCUS`) should include per-provision guidance for their high-difficulty provisions:

```
## EXTRACTION GUIDANCE: Cap on Liability

DEFINITION: A contractual clause limiting the maximum aggregate liability
of one or both parties under the agreement, typically expressed as a fixed
dollar amount, a multiple of fees paid, or "direct damages only."

WHAT TO EXTRACT:
- The cap amount (absolute $ or formula)
- Which parties are capped
- What is excluded from the cap (typically: IP indemnity, confidentiality breach, willful misconduct)
- Whether the cap is mutual or asymmetric

KEYWORDS TO SEARCH FOR:
liability cap, limitation of liability, aggregate liability, maximum liability,
direct damages, consequential damages, exclusion of liability, cap on damages,
total liability shall not exceed

COMMON FORMULATIONS:
- "In no event shall [Party]'s aggregate liability exceed [amount]"
- "The total liability of either party shall be limited to [formula]"
- "Notwithstanding anything to the contrary, [Party] shall not be liable for [exclusions]"
- Sometimes embedded in indemnification clauses, not a standalone section

IF NOT FOUND: Write a gap finding with gap_type "Not_Found" and explain where
you looked. Do NOT fabricate a liability cap that does not exist in the document.
```

### 4.4 Integration with Current Prompts

The existing `SPECIALIST_FOCUS` dictionary (doc 06 §5) provides high-level focus areas. For high-difficulty provisions (F1 < 0.90 in AG study), add per-provision extraction templates as an appendix to each specialist prompt:

| Agent | Provisions Needing Templates | Approximate Additional Tokens |
|-------|----------------------------|------------------------------|
| Legal | Change of Control, Anti-Assignment, Cap on Liability, Exclusivity | ~1,200 |
| Finance | Cap on Liability, Insurance | ~600 |
| Commercial | Most Favored Nation, Exclusivity, Termination for Convenience | ~900 |
| ProductTech | (None above threshold — tech provisions not in AG study) | 0 |

Total additional prompt overhead: ~2,700 tokens across all specialists, well within budget.

Provision-specific templates are defined for the most common contract provisions: pricing, termination, liability, IP, confidentiality, SLA, data protection, and renewal. Additional templates can be added to `agents/prompt_builder.py` as new provision types are encountered in production.

---

## 5. Follow-Up Verification Protocol

### 5.1 Background (AG-6)

The AG report found that a single follow-up prompt improves accuracy by 9.2% on average. Accusatory/emotive follow-ups ("you may have missed critical information") are most effective. This works because:
- The model has already built internal representations of the document during the first pass
- The follow-up forces reconsideration of low-confidence extractions
- The accusatory framing triggers more thorough re-checking

### 5.2 Implementation: Judge as Follow-Up

The plan already includes a Judge agent (doc 06 §10) that reviews specialist output and triggers re-analysis. This IS the follow-up mechanism, but it needs to be strengthened with AG-informed patterns:

**Current Judge protocol** (doc 06 §10.4): Spot-checks findings along 5 dimensions, scores agents, triggers re-analysis for agents below threshold.

**Enhancement**: Add a mandatory "adversarial follow-up" phase to the Judge's review of P0 and P1 findings:

```
For each P0/P1 finding you review, perform this adversarial check:

1. Read the source document section cited by the agent
2. Ask yourself: "Is there another reasonable interpretation of this clause?"
3. Ask yourself: "Did the agent miss any qualifiers, exceptions, or carve-outs?"
4. Check: Does the severity match the actual contractual language?
   - Is this truly a P0 (deal-stopper) or was the agent overreacting?
   - Could this be a P2 that was escalated due to missing context?

IMPORTANT: You may have missed critical information in your initial review.
Go back and re-examine the surrounding paragraphs of each cited section.
Clauses often have qualifiers in preceding or following subsections that
materially change the finding's severity.
```

### 5.3 Implementation: Specialist Self-Check

Before each specialist completes its analysis (writes coverage manifest), the prompt includes a self-verification step:

```
BEFORE YOU WRITE YOUR COVERAGE MANIFEST:

Review your findings against this checklist:
1. For each P0 finding: re-read the cited section. Is the quote exact? Is the severity justified?
2. For each subject with zero findings: re-read their files. Did you skip a file?
3. For each subject with only P3 findings: did you overlook higher-severity issues?
4. Check your manifest: does files_assigned match what you were given?
5. Check: did you process ALL reference files listed in your prompt?

YOU MAY HAVE MISSED CRITICAL INFORMATION. Go back and re-examine any
subjects where you produced fewer than expected findings relative to
the number of files they have.
```

This is a zero-cost addition (just prompt text, ~200 tokens) that leverages AG-6 findings.

---

## 6. "Not Found" Protocol

### 6.1 Background (AG-8)

Without an explicit "not found" escape valve, LLMs fabricate content rather than admitting absence. The AG report found that providing a "Not found" option significantly reduces hallucination.

### 6.2 Implementation

Every specialist prompt must include:

```
NOT FOUND PROTOCOL:

If you search for a specific clause or document and it genuinely does not exist
in the subject's files, you MUST record this as a gap, NOT as a finding.

DO NOT:
- Fabricate clauses that you cannot find
- Infer terms from general legal principles
- Assume standard industry terms apply
- Create findings based on what "should" be in the contract

DO:
- Write a gap with gap_type: "Not_Found"
- Explain what you searched for and where you looked
- Note which files you reviewed
- Suggest what the missing clause means for the deal

EXAMPLE:
{
  "gap_type": "Not_Found",
  "missing_item": "Cap on Liability clause",
  "referenced_in": "Expected in MSA but not found",
  "priority": "P1",
  "impact": "Unlimited liability exposure. MSA reviewed: all 24 pages,
            no limitation of liability section found. Amendment #1 also
            reviewed: no liability cap added.",
  "files_searched": ["./subject/MSA.pdf", "./subject/Amendment_1.pdf"]
}
```

This is already partially addressed in the gap detection rules (doc 06 §5 `SPECIALIST_FOCUS`), but must be made more explicit as a first-class protocol.

### 6.3 Validation

The QA audit (doc 11) should verify:
- Every subject has at least one finding OR at least one gap per specialist
- Any subject with zero findings AND zero gaps from a specialist is flagged as "potentially incomplete analysis"
- Gap findings with `gap_type: "Not_Found"` must include `files_searched` array

Compliance with the Not-Found protocol should be validated in the QA audit (`11-qa-validation.md`). The check verifies that for each subject, every required field in the finding schema either has a value or has an explicit `not_found: true` marker with a search description.

---

## 7. Excel and Financial Data Handling

### 7.1 The Problem (E-1 through E-4)

Excel spreadsheets are fundamentally different from text documents:
- **Structure is semantic**: Row/column position carries meaning that flat text loses
- **Date serial numbers**: Excel stores dates as integers (44621 = 2022-03-01); naive text extraction produces meaningless numbers
- **Unit ambiguity**: "$120" could be $120 or $120,000 depending on column header
- **Multi-sheet context**: Data in Sheet 2 may reference formulas in Sheet 1

### 7.2 Extraction Enhancements for Excel

This is the authoritative specification for smart Excel extraction. Doc 08 (`08-extraction.md`) references this section for Excel handling details.

Update the `extract_openpyxl` fallback (doc 08 §1) to handle these issues:

```python
# src/dd_agents/extraction/tabular.py

import openpyxl
from datetime import datetime

def extract_excel_smart(file_path: str) -> str:
    """Extract Excel with structure preservation and date conversion.

    Enhancements over basic openpyxl dump:
    1. Convert date serial numbers to ISO-8601 strings
    2. Preserve column headers above each data section
    3. Detect and label sub-tables within sheets
    4. Include sheet names as section headers
    5. For wide tables (>15 cols), split into logical groups
    6. Preserve number formatting (currency, percentage)
    """
    wb = openpyxl.load_workbook(file_path, data_only=True)
    sections = []

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        sections.append(f"\n## Sheet: {sheet_name}\n")

        header_row = None
        for row in ws.iter_rows(values_only=False):
            cells = [(c.value, c.number_format) for c in row]

            if header_row is None and any(isinstance(v, str) for v, _ in cells):
                header_row = [str(v) if v else "" for v, _ in cells]
                sections.append("| " + " | ".join(header_row) + " |")
                sections.append("| " + " | ".join(["---"] * len(header_row)) + " |")
                continue

            formatted = []
            for value, fmt in cells:
                if isinstance(value, datetime):
                    formatted.append(value.strftime("%Y-%m-%d"))
                elif isinstance(value, (int, float)) and fmt and "$" in str(fmt):
                    formatted.append(f"${value:,.2f}")
                elif isinstance(value, (int, float)) and fmt and "%" in str(fmt):
                    formatted.append(f"{value:.1%}")
                elif value is not None:
                    formatted.append(str(value))
                else:
                    formatted.append("")

            sections.append("| " + " | ".join(formatted) + " |")

    return "\n".join(sections)
```

### 7.3 Financial Cross-Reference Protocol

The Finance agent's specialist focus (doc 06 §5) requires cross-referencing contract values against reference data (Revenue Cube, pricing). This is the highest-hallucination-risk task because:
- Numbers may appear in different units ($K vs $)
- Date ranges may not align (calendar year vs fiscal year vs contract year)
- Subject names in spreadsheet may not match contract parties

Mitigations:
1. **Pre-convert units**: Extraction pipeline normalizes all currency values to full units (not thousands)
2. **Date alignment**: Finance agent prompt includes explicit guidance on date range matching
3. **Entity resolution**: Subject names in spreadsheets run through the 6-pass entity matcher (doc 09) before cross-referencing
4. **Dual-source requirement**: Any financial discrepancy must cite BOTH the contract clause AND the spreadsheet cell reference

### 7.4 Cross-Reference to Implementation

| Doc | Section | Change |
|-----|---------|--------|
| `08-extraction.md` | §1 Fallback Chain | Add `extract_excel_smart` as improved openpyxl fallback with date conversion and structure preservation |
| `06-agents.md` | §5 SPECIALIST_FOCUS (Finance) | Add explicit guidance on unit normalization, date alignment, and dual-source citation |
| `17-file-manifest.md` | File list | Add `src/dd_agents/extraction/tabular.py` (~150 lines) |

---

## 8. Hallucination Prevention Architecture

### 8.1 Six-Layer Defense

The plan implements six complementary layers against hallucination. No single layer is sufficient (per S-4); the combination provides defense-in-depth:

| Layer | Mechanism | Where Implemented | Catches |
|-------|-----------|------------------|---------|
| **L1: Structured Output** | Pydantic models enforce required fields, valid enums, non-empty citations | `04-data-models.md`, PostToolUse hooks | Missing citations, invalid severities, malformed output |
| **L2: Citation Verification** | `verify_citation` MCP tool performs exact and fuzzy matching of quotes against extracted text | `07-tools-and-hooks.md` | Fabricated quotes, misattributed sources, wrong sections cited |
| **L3: Not-Found Protocol** | Explicit escape valve for missing information (§6 above) | Agent prompts, gap validation | Fabricated clauses, hallucinated terms |
| **L4: Judge Spot-Check** | Adversarial review of sampled findings (§5 above) | `06-agents.md` §10 | Contextual misinterpretation, severity inflation, missed qualifiers |
| **L5: Numerical Audit** | 6-layer deterministic validation of all numbers | `11-qa-validation.md` | Wrong amounts, arithmetic errors, unit mismatches |

### 8.2 Citation Verification Details

The `verify_citation` tool (doc 07) performs:

1. **Exact match**: Substring search of `exact_quote` in extracted text at `text_path`
2. **Fuzzy match**: If exact match fails, use rapidfuzz token_sort_ratio with threshold 85%
3. **OCR tolerance**: If source file had OCR extraction (confidence: "medium" or "low"), lower fuzzy threshold to 75%
4. **Result**: Returns `PASS` (exact match), `PARTIAL` (fuzzy match), or `FAIL` (no match)

**Enhancement from AG research**: Add location verification. Not only must the quote exist in the document, but it should appear in the section cited (e.g., "Section 12.3"). If the quote exists but in a different section, return `PARTIAL` with a note about location mismatch.

### 8.3 Severity-Based Verification Intensity

Based on AG-7 (harder provisions need more verification) and S-2 (longer answers hallucinate more):

| Severity | Citation Check | Judge Review | Follow-Up Required |
|----------|---------------|-------------|-------------------|
| **P0** (deal-stopper) | 100% verified via tool | 100% reviewed | Yes — adversarial re-check |
| **P1** (material risk) | 100% verified via tool | 20% sampled | Yes — self-check in prompt |
| **P2** (moderate risk) | Tool available, not mandatory | 10% sampled | No |
| **P3** (informational) | Tool available, not mandatory | 0% (unless agent score low) | No |

### 8.4 Cross-Reference to Implementation

| Doc | Section | Change |
|-----|---------|--------|
| `07-tools-and-hooks.md` | verify_citation tool | Add location verification (section matching) |
| `06-agents.md` | §10.4 Spot-Check Protocol | Add adversarial follow-up for P0/P1 findings |
| `06-agents.md` | §5 Prompt Construction | Add self-check step before manifest |
| `11-qa-validation.md` | DoD checks | Add check: "every P0/P1 has verify_citation result of PASS or PARTIAL" |

---

## 9. Retrieval Optimization

### 9.1 Hybrid Search (When ChromaDB Enabled)

The AG report found that improved retrieval keywords + vector search together produce the best results. When ChromaDB is enabled:

1. **Vector search**: `semantic_search` MCP tool queries ChromaDB for relevant chunks
2. **Keyword search**: Agent uses Grep tool for exact terms (contract-specific keywords from §4.3)
3. **Result ordering**: Chunks are presented in **original document order** (per AG-3), not by similarity score

### 9.2 Contextual Chunk Metadata (A-1, D-2)

Every chunk stored in ChromaDB includes a `document_context` field (50-100 tokens) summarizing the source document:

```
Document: Master Service Agreement between Apex Digital Inc and Acme Corp
Type: MSA | Effective: 2023-01-15 | Parties: Apex Digital Inc, Acme Corp
Subject: acme_corp | Files: 3 total | This is the governing agreement.
```

This prevents Document-Level Retrieval Mismatch (D-1) by ensuring the retriever can distinguish boilerplate chunks from different documents.

### 9.3 Cross-Reference to Implementation

| Doc | Section | Change |
|-----|---------|--------|
| `14-vector-store.md` | §3 Ingestion | Add document_context field to chunk metadata; implement SAC |
| `14-vector-store.md` | §4 Search | Sort results by document position, not similarity score |
| `07-tools-and-hooks.md` | semantic_search tool | Add document_context to returned results |

---

## 10. Map-Reduce for Oversized Documents

### 10.1 When Map-Reduce Is Needed

Map-reduce is a fallback for documents too large for single-pass agent analysis. This is rare in M&A data rooms (most contracts are <100 pages), but occurs with:
- Consolidated financial statements (100+ pages)
- Master agreement compilations (multiple agreements in one PDF)
- Large customer databases in Excel (1000+ rows)

### 10.2 Document-Level Splitting

For text documents exceeding the large file threshold (120KB extracted text):

```python
# Orchestrator marks large files in the agent prompt
# Agent is instructed to use Grep for targeted search

# If an agent needs to analyze a large file comprehensively:
# 1. Read first 2000 lines (document structure, table of contents)
# 2. Grep for provision-specific keywords
# 3. Read surrounding context for each match
# 4. This is effectively a manual map-reduce within a single agent
```

### 10.3 Tabular Map-Reduce (E-4)

For Excel files with >100 data rows assigned to the Finance agent:

```
For large spreadsheets (>100 data rows):
1. Read the header row and first 10 data rows to understand structure
2. Process data in chunks of 50 rows at a time
3. For each chunk: extract relevant financial terms, flag discrepancies
4. After all chunks: summarize findings, reconcile any chunk-boundary issues
5. Write consolidated findings for the subject

Do NOT attempt to read all rows at once — this will exhaust your context.
```

### 10.4 Cross-Reference to Implementation

| Doc | Section | Change |
|-----|---------|--------|
| `06-agents.md` | §5.4 Reference File Section | Add large-file handling instructions |
| `12-error-recovery.md` | Scenario 7 (context exhaustion) | Add guidance on batch size for re-spawned agents |

---

## 11. Temperature and Reproducibility (AG-9)

### 11.1 LLM Parameters

All agent invocations use:
- **Temperature**: 0 (deterministic output)
- **Max output tokens**: Uncapped (agent writes to files, not stdout)
- **Model**: `claude-sonnet-4-20250514` (configurable via deal-config.json)

### 11.2 Seed Consistency

The `query()` SDK function does not expose a `seed` parameter (unlike OpenAI). Reproducibility is achieved through:
- Deterministic prompts (same input → same prompt → near-identical output at temp 0)
- Pydantic validation (output must conform regardless of generation variance)
- Numerical audit (catches any generation-to-generation drift in numbers)
- Run archiving (every run's full output is preserved for comparison)

---

## 12. Error Compounding Prevention

### 12.1 The Risk

In multi-stage pipelines, errors compound:
- Stage 1: Entity resolution maps "Acme" to wrong canonical → all Acme findings are for wrong subject
- Stage 2: Agent cites wrong section number → Judge verifies wrong section → false PASS
- Stage 3: Financial cross-reference uses wrong row from spreadsheet → numerical audit passes (numbers are consistent, just wrong)

### 12.2 Mitigation Layers

| Error Type | Prevention | Detection | Recovery |
|-----------|-----------|-----------|----------|
| Entity resolution error | 6-pass matcher with confidence scores | Manual review queue for low-confidence matches | Re-run entity resolution after config correction |
| Wrong citation | verify_citation tool (L2) | Judge spot-check (L4) | Re-analysis with targeted feedback |
| Wrong financial data | Dual-source citation requirement | Numerical audit layer 3 (cross-source consistency) | Finance agent re-analysis for specific subject |
| Aggregation error | PostToolUse hooks block aggregate files | Coverage gate checks per-subject output | Re-spawn for missing/aggregated subjects |
| Context exhaustion | Prompt size management (§3) | Runtime monitoring (§3.5) | Re-spawn with smaller subject set |

### 12.3 Pipeline Ordering as Error Prevention

The 35-step pipeline (doc 05) is specifically ordered to catch errors early:

| Step Range | Purpose | Error Prevention Function |
|-----------|---------|-------------------------|
| 1-4 | Config validation, file discovery | Catch config errors before any LLM work |
| 5-9 | Extraction, inventory, entity resolution | All deterministic — no LLM involvement. Errors are reproducible and debuggable. |
| 10-12 | Classification, team creation, prompt prep | Deterministic subject routing. Prompt is validated before agent spawn. |
| 13-16 | Agent analysis | First LLM stage. Errors caught by coverage gate (step 17). |
| 17 | **BLOCKING GATE**: Coverage validation | Catches missing subjects, aggregate files, incomplete manifests. Triggers re-spawn. |
| 18-22 | Judge review (optional) | Second LLM stage. Catches hallucinations, severity errors, contradictions. |
| 23-27 | Merge + audit | Third stage. Deterministic pre-merge validation catches financial errors. |
| 28 | **BLOCKING GATE**: Numerical audit | 6-layer deterministic validation. Catches any number that can't be traced to source. |
| 29-31 | Report generation, validation | Deterministic steps from schema. Schema validation catches structural errors. |

---

## 13. Coherence Matrix

This section maps every research finding to its concrete implementation across plan docs:

| Finding | Mitigation | Primary Doc | Supporting Docs |
|---------|-----------|-------------|-----------------|
| AG-1: RAG 10 > full context | Targeted extraction via tools, not full doc in prompt | 06 §3.2 | 08 §2 |
| AG-2: Clause-aware chunking | `extraction/chunking.py` for vector store | This doc §2 | 14 §3 |
| AG-3: Document-order chunks | Sort retrieved chunks by position | This doc §9 | 14 §4 |
| AG-4: Provision-specific prompts | Per-provision templates for hard clauses | This doc §4 | 06 §5 |
| AG-5: Simple system prompts | Short persona in system_prompt | 06 §3.1 | — |
| AG-6: Follow-up prompts | Judge adversarial review + self-check | This doc §5 | 06 §10 |
| AG-7: Hard provisions need more effort | Severity-based verification intensity | This doc §8.3 | 11 §8 |
| AG-8: "Not found" option | Not-Found Protocol in every prompt | This doc §6 | 06 §5, 07 |
| AG-9: Temperature 0 | Enforce in SDK config | This doc §11 | 06 §3 |
| AG-10: 74% → 95% is engineering | This entire document | — | — |
| S-1: 17-33% hallucination rate | 6-layer hallucination prevention | This doc §8 | 07, 11 |
| S-2: Length correlates with hallucination | Constrain output, structured JSON | 04, 06 §7 | — |
| S-3: Elementary comprehension failures | Pydantic validation of parties/terms | 04 | 11 |
| A-1: Contextual chunk metadata | Document context prepended to chunks | This doc §9.2 | 14 §3 |
| D-1: Boilerplate causes retrieval mismatch | Source document metadata in chunks | This doc §9.2 | 14 §3 |
| E-1: Excel date serial numbers | `_format_cell` in `tools/read_office.py` converts to ISO-8601 | This doc §7.2 | 08 §1 |
| E-2: Unit ambiguity | `_format_cell` reads `cell.number_format` for currency/percentage | This doc §7.2 | 08 §1 |
| C-1: Lost-in-the-middle | Prompt structure with edges for key content | This doc §3.4 | 06 §5 |
| C-2: Degradation beyond 80K | 80% safety margin already in place | 06 §6.1 | — |

---

## 14. Implementation Checklist

Discrete changes required to integrate these mitigations into the existing plan:

### 14.1 Implemented Files

E-1 through E-4 mitigations were integrated into existing modules rather than creating separate files:

| Mitigation | Implemented In | Tests In |
|-----------|---------------|----------|
| E-1: Date conversion (ISO-8601) | `src/dd_agents/tools/read_office.py` (`_format_cell`) | `tests/unit/test_read_office.py` (`TestCellFormatting`) |
| E-2: Currency/percentage formatting | `src/dd_agents/tools/read_office.py` (`_format_cell`) | `tests/unit/test_read_office.py` (`TestCellFormatting`, `TestCellEdgeCases`) |
| E-3: Sub-table detection | `src/dd_agents/tools/read_office.py` (`_split_sub_tables`) | `tests/unit/test_read_office.py` (`TestCellFormatting`) |
| E-4: Table-aware chunking | `src/dd_agents/search/chunker.py` (`is_tabular`, `split_by_table_rows`) | `tests/unit/test_search_chunker.py` (`TestIsTabular`, `TestSplitByTableRows`) |

**Design rationale**: E-1/E-2/E-3 belong in `read_office.py` because that's where agents read Excel via the `read_office` tool — avoids maintaining parallel implementations. E-4 belongs in `search/chunker.py` because the search module already handles document chunking and the vector store is optional.

### 14.2 File Modifications

| File | Section | Change |
|------|---------|--------|
| `06-agents.md` §5 | SPECIALIST_FOCUS | Add provision-specific templates for hard clauses |
| `06-agents.md` §5 | Prompt Construction | Reorder sections per §3.4 (lost-in-the-middle) |
| `06-agents.md` §5 | New subsection | Add self-check step before manifest (§5.3) |
| `06-agents.md` §5 | New subsection | Add Not-Found Protocol (§6.2) |
| `06-agents.md` §3.2 | Large files | Add large-file handling instructions (§3.3) |
| `06-agents.md` §10.4 | Judge Protocol | Add adversarial follow-up for P0/P1 (§5.2) |
| `08-extraction.md` §1 | Fallback chain | Add smart Excel extraction fallback |
| `08-extraction.md` §2 | DocumentExtractor | Add optional chunking invocation after extraction |
| `14-vector-store.md` §3 | Ingestion | Use clause-aware chunks; add document_context |
| `14-vector-store.md` §4 | Search | Sort results by document position |
| `07-tools-and-hooks.md` | verify_citation | Add section-location verification |
| `11-qa-validation.md` | DoD checks | Add P0/P1 citation verification check |
| `17-file-manifest.md` | File list | Add 4 new files |
| `18-implementation-order.md` | Phase 1 | Add chunking.py and tabular.py |

### 14.3 No Changes Needed

These docs are complete for their scope and do not require research-informed updates:
- `01-architecture-decisions.md` — ADRs are sound; 80K limit already specified
- `02-system-architecture.md` — Architecture diagram is correct
- `03-project-structure.md` — Layout is correct (new files fit existing modules)
- `04-data-models.md` — Models are comprehensive
- `05-orchestrator.md` — Pipeline steps are correct; gate placement is sound
- `09-entity-resolution.md` — 6-pass matcher is robust
- `10-reporting.md` — Merge/dedup protocol is complete
- `12-error-recovery.md` — 15 scenarios cover the space
- `13-multi-project.md` — Data isolation is correct
- `15-testing-deployment.md` — Test strategy is sound
- `16-migration.md` — Migration plan is phased correctly
- `19-vector-graph-db-comparison.md` — Technology selection is justified
- `20-cross-document-analysis.md` — Cross-doc patterns are comprehensive
- `21-ontology-and-reasoning.md` — Already references AG report findings
