# Search Command Guide

The `dd-agents search` command lets you run targeted questions against every
subject's contracts in a data room and get an Excel report with answers
and sourced citations — without running the full pipeline.

## Quick Start

```bash
dd-agents search prompts.json --data-room ./data_room
```

This will:

1. Scan the data room and discover all subject contracts
2. Extract text from documents (if not already done)
3. Show a cost estimate and ask for confirmation
4. Analyze each subject's contracts against your questions
5. Generate an Excel report with answers and citations

## Creating a Prompts File

The prompts file is a simple JSON file that defines the questions you want
answered. Any legal professional can write one — no coding required.

### Format

```json
{
  "name": "Change of Control Analysis",
  "description": "Identify consent requirements triggered by change of control",
  "columns": [
    {
      "name": "Consent Required",
      "prompt": "Does this agreement require consent from the counterparty upon a change of control? Answer YES, NO, or NOT_ADDRESSED."
    },
    {
      "name": "Consent Clause Summary",
      "prompt": "If consent is required upon change of control, summarize the relevant clause and provide the section reference."
    }
  ]
}
```

### Rules

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | A short name for this analysis (1-200 characters) |
| `description` | No | A longer description of what you're looking for |
| `columns` | Yes | Your list of questions (1-20 questions) |
| `columns[].name` | Yes | Display name shown in the Excel report (1-100 characters) |
| `columns[].prompt` | Yes | The actual question sent to the AI (10-2000 characters) |

For a complete, production-quality example see
[Ready-to-Use Example: Change of Control Analysis](#ready-to-use-example-change-of-control-analysis)
below, or the file at [`examples/search/change_of_control.json`](../examples/search/change_of_control.json).

### Tips for Writing Good Prompts

Based on research from the [Addleshaw Goddard RAG Report](https://www.addleshawgoddard.com/globalassets/insights/technology/llm/rag-report.pdf)
(510 CUAD contracts, 9 provision types), clause-aware prompting improves
AI contract analysis from 74% baseline accuracy to 95% — a 21-point gain
achieved entirely through prompt engineering and chunking strategy, not
model changes. These practices improve accuracy:

- **Be specific**: "Does this agreement require consent upon a change of
  control?" is better than "What are the consent requirements?"
- **Specify the answer format**: "Answer YES, NO, or NOT_ADDRESSED" helps
  get consistent results
- **Ask for section references**: "Provide the section reference and page
  number" improves citation quality
- **Avoid overly specific questions**: Asking too many sub-questions in
  one prompt can reduce accuracy. Split into separate columns instead.
- **One concept per question**: Each column should focus on one specific
  provision or clause type

## Data Room Structure

The data room must follow this directory layout:

```
data_room/
  GroupA/
    Subject1/
      msa.pdf
      amendment_2024.docx
      sow_1.pdf
    Subject2/
      master_agreement.pdf
  GroupB/
    Subject3/
      contract.pdf
```

Each subject is a subfolder under a group folder. All files in a
subject's folder are analyzed together.

## Command Options

```
dd-agents search PROMPTS_PATH [OPTIONS]

Arguments:
  PROMPTS_PATH   Path to your prompts JSON file

Options:
  --data-room PATH     Path to the data room folder (required)
  --output PATH        Excel output path (default: auto-named)
  --subjects TEXT       Filter to specific subjects (comma-separated)
  --groups TEXT         Filter to specific groups (comma-separated, case-insensitive partial match)
  --concurrency N      Parallel API calls, 1-20 (default: 5)
  --yes / -y           Skip cost confirmation prompt
  --no-file            Skip filing search results back to Knowledge Base
  --verbose / -v       Show detailed logging
```

### Examples

```bash
# Analyze all subjects
dd-agents search prompts.json --data-room ./data_room

# Analyze only specific subjects
dd-agents search prompts.json --data-room ./data_room --subjects "Acme,Beta Corp"

# Skip confirmation and save to specific file
dd-agents search prompts.json --data-room ./data_room -y --output results.xlsx

# Filter by group folder name
dd-agents search prompts.json --data-room ./data_room --groups Commercial

# See detailed progress
dd-agents search prompts.json --data-room ./data_room -v
```

## Understanding the Excel Report

The report has two sheets:

### Summary Sheet

One row per subject with:

| Column | Description |
|--------|-------------|
| Entity | Subject name |
| Group | Group folder name |
| Files Analyzed | How many files were sent to the AI (e.g. "3/5") |
| Chunks | Number of analysis chunks (light-blue highlight when >1) |
| Files Skipped | List of files that couldn't be analyzed |
| *Your questions* | One column per question with the answer |
| Error | Any error that occurred |

**Color coding:**
- Green = YES
- Blue = NO
- Yellow = NOT_ADDRESSED (the contract doesn't cover this)
- Orange = INCOMPLETE (the AI didn't return this answer)
- Red = Error

### Details Sheet

One row per citation with the full evidence trail:

| Column | Description |
|--------|-------------|
| Entity | Subject name |
| Group | Group folder name |
| Question | Which question this citation answers |
| Answer | The answer (YES/NO/NOT_ADDRESSED/summary) |
| Confidence | HIGH, MEDIUM, or LOW |
| File Path | Which document the citation comes from |
| Page | Page number (if identifiable) |
| Section | Section reference (e.g. "Section 12.3") |
| Exact Quote | Verbatim text from the document |
| Quote Verified | YES (green) if quote found in source, NO (orange) if not, blank if not verified |
| Match Score | Fuzzy match percentage (0-100) from citation verification |

## Large File Handling

Files of any size are analyzed — nothing is silently skipped. When a
subject's combined document text exceeds the model's optimal context size
(~150K characters), the system automatically:

1. **Splits** large documents at page boundaries (`--- Page N ---` markers)
   with 15% overlap between chunks to preserve cross-page context
2. **Packs** smaller documents together into analysis chunks
3. **Analyzes** each chunk concurrently (Phase 1: Map)
4. **Merges** results using answer priority YES > NO > NOT_ADDRESSED,
   with semantic conflict detection (free-text answers starting with
   YES/NO are recognized) and best-of confidence selection (Phase 2)
5. **Resolves** conflicts where chunks disagree via a lightweight synthesis
   pass with all findings as structured JSON, using dynamic quote budgeting
   to preserve full citation evidence (Phase 3: Synthesis)
6. **Validates** any remaining NOT_ADDRESSED answers with a targeted
   follow-up query using document-order file selection and page-aware
   splitting (Phase 4: Validation)

This is fully transparent in the Excel report — the `chunks_analyzed` count
shows how many analysis passes were needed per subject. Single-chunk
subjects (the majority) see no change in behavior.

## External Reference Download

Contracts frequently incorporate external Terms & Conditions by URL
reference (e.g. `https://vendor.com/general-terms-and-conditions/`).
After text extraction, the pipeline automatically:

1. **Scans** subject-extracted text for URLs matching T&C-like patterns
   (terms, conditions, policy, SLA, EULA, privacy, agreement, etc.)
2. **Downloads** referenced documents via HTTP (any domain accepted —
   if a URL appears in a contract with a legal keyword in its path, it
   was put there for a reason)
3. **Extracts** text content using markitdown
4. **Caches** results in the text index with an `__external__` prefix

This step is non-blocking: download failures are logged as warnings
but never halt the pipeline.

**Important**: Downloaded external references are cached for future use
but are **not** automatically included in the subject contract analysis.
The search analyzer only reads files listed in each subject's registry
entry — never by scanning the text directory. This prevents external
documents (e.g. a cloud provider's customer agreement) from being
confused with the subject's own contract terms. External references
may be relevant for vendor/infrastructure analysis but must be
explicitly opted-in for that use case.

## Answer Normalization

LLMs sometimes return free-text answers like "Unable to determine..." or
"Cannot be determined from the available documents" instead of the
requested YES/NO/NOT_ADDRESSED format. The analyzer normalizes these
at parse time:

- **10 recognized prefixes**: "Unable to determine", "Cannot determine",
  "Insufficient information", "Indeterminate", etc. are all mapped to
  NOT_ADDRESSED
- **Applied at every entry point**: Map phase, synthesis phase, and
  validation phase all route through `parse_column_result()` which
  normalizes before any downstream logic evaluates the answer
- **Parse-time citation dedup**: Duplicate citations (same file, page,
  section, and quote) are removed at parse time via a 4-tuple key,
  ensuring consistent dedup for both single-chunk and multi-chunk subjects

## Citation Verification

After analysis, all citations are verified against the extracted
source text using fuzzy matching (rapidfuzz). This catches
hallucinated quotes and wrong page references without requiring
additional API calls.

- **80% match threshold** — tolerates OCR character errors while
  flagging fabricated quotes
- **Whitespace normalization** — all whitespace (newlines, tabs, multiple
  spaces) is collapsed to single spaces before comparison, handling
  line breaks from PDF column layout, OCR, and markitdown reformatting
- **Section verification** — checks that the cited section reference
  actually appears in the source document

### Progressive Search Scope

Quote verification uses a 4-level progressive search to maximize
recall while keeping attribution accurate:

1. **Page-scoped** — search within the cited page only
2. **Adjacent pages (+-1)** — expand to neighboring pages (catches
   cross-page quotes and off-by-one page citations)
3. **Full document** — search the entire source file
4. **Cross-file** — search ALL files in the subject's text set
   (catches file misattributions from the LLM merge phase)

When a quote is found in a different file (scope 4), the citation's
`file_path` and `page` are automatically corrected to point to the
actual source document.

Results appear in the Excel Details sheet (Quote Verified / Match
Score columns) and in the CLI summary output.

## Data Completeness Guarantees

The search command is designed for legal due diligence where missing data
is unacceptable:

- **Every subject** in the input appears in the output, even if analysis
  failed
- **Every question** gets an answer for every subject — missing answers
  are flagged as "INCOMPLETE" in orange
- **No size limit** — files of any size are analyzed via automatic chunking.
  No documents are ever skipped due to size constraints
- **Skipped files** (missing text extraction) are listed in the report so
  you know what wasn't analyzed
- **Files Analyzed** shows "X/Y" format so you can see at a glance if any
  files were missed
- **Errors** are recorded per subject, never silently dropped

## Ready-to-Use Example: Change of Control Analysis

A production-quality prompts file is included at
[`examples/search/change_of_control.json`](../examples/search/change_of_control.json).
It covers the most common M&A due-diligence scenario — identifying contracts
that require consent, notice, or that carry termination-for-convenience risk
when ownership of the service provider changes.

```bash
dd-agents search examples/search/change_of_control.json --data-room ./data_room
```

### What it analyzes (6 columns)

| Column | Purpose |
|--------|---------|
| Consent Required (Change of Control) | YES/NO — does the contract require counterparty consent on a change of control? |
| Consent Clause Summary | The relevant clause text, section reference, and page number |
| Notice Required (Change of Control) | YES/NO — does the contract require counterparty notice on a change of control? |
| Notice Clause Summary | The relevant clause text, section reference, and page number |
| Termination for Convenience | YES/NO — can the counterparty terminate without cause (revenue risk even without a CoC trigger)? |
| Termination for Convenience Summary | Who holds the right, notice period, fees/penalties, and section reference |

### Prompt design choices

This example demonstrates several best practices for accurate results:

- **Explicit exclusions** — Each prompt instructs the AI to exclude
  assignment/transfer-only clauses, which is the most common source of
  false positives in change-of-control analysis. A share acquisition does
  not trigger assignment provisions, so conflating the two overstates risk.
- **Paired YES/NO + summary columns** — The first column in each pair
  forces a categorical answer; the second extracts the supporting clause.
  This makes the Summary sheet scannable while preserving full evidence
  in the Details sheet.
- **Termination for convenience** — Often overlooked in CoC analyses.
  A counterparty with a termination-for-convenience right can exit regardless
  of whether a change-of-control clause exists, making it critical for
  acquirer revenue projections.
- **Section and page pinpointing** — Every prompt asks for the section
  reference and page number, enabling quick manual verification.

### Customizing

Copy the file and adapt it to your deal:

```bash
cp examples/search/change_of_control.json my_prompts.json
# Edit my_prompts.json — add/remove columns, adjust prompts
dd-agents search my_prompts.json --data-room ./data_room
```

Common additions for M&A deals:

- **Non-compete / non-solicit** — Do restrictions survive a change of control?
- **IP ownership / license grants** — Are license rights affected by ownership changes?
- **Most Favored Nation (MFN)** — Does the counterparty have MFN pricing protections?
- **Auto-renewal terms** — What is the renewal date and notice period to prevent auto-renewal?

## Troubleshooting

### "No subjects found"

Your data room doesn't follow the expected directory structure. It must be:
`data_room/group/subject/files`. See the Data Room Structure section above.

### "No extracted text found for this subject's files"

The text extraction step couldn't read any of this subject's files. Check
that the files are valid PDFs, Word documents, or other supported formats.

### "Incomplete response — missing columns"

The AI didn't answer all questions for this subject. This can happen with
very large document sets. The missing columns are flagged in orange in the
Excel report. Re-running with `--concurrency 1` may help.

### "Failed to parse API response as JSON"

The AI returned a malformed response. This is automatically retried (up to
3 times). If it persists, the error is recorded in the report.

### Cost seems too high

Use `--subjects` to test with a small subset first. Use `--verbose` to
see token counts. Reduce the number of questions in your prompts file.
