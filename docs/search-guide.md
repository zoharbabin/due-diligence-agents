# Search Command Guide

The `dd-agents search` command lets you run targeted questions against every
customer's contracts in a data room and get an Excel report with answers
and precise citations.

## Quick Start

```bash
dd-agents search prompts.json --data-room ./data_room
```

This will:

1. Scan the data room and discover all customer contracts
2. Extract text from documents (if not already done)
3. Show a cost estimate and ask for confirmation
4. Analyze each customer's contracts against your questions
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
      "prompt": "Does this agreement require consent from the customer upon a change of control? Answer YES, NO, or NOT_ADDRESSED."
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

### Tips for Writing Good Prompts

Based on research from the [Addleshaw Goddard RAG Report](https://www.addleshawgoddard.com/globalassets/insights/technology/llm/rag-report.pdf),
these practices improve accuracy:

- **Be specific**: "Does this agreement require consent upon a change of
  control?" is better than "What are the consent requirements?"
- **Specify the answer format**: "Answer YES, NO, or NOT_ADDRESSED" helps
  get consistent results
- **Ask for section references**: "Provide the section reference and page
  number" improves citation quality
- **Don't be too granular**: Asking too many sub-questions in one prompt
  can reduce accuracy. Split into separate columns instead.
- **One concept per question**: Each column should focus on one specific
  provision or clause type

## Data Room Structure

The data room must follow this directory layout:

```
data_room/
  GroupA/
    Customer1/
      msa.pdf
      amendment_2024.docx
      sow_1.pdf
    Customer2/
      master_agreement.pdf
  GroupB/
    Customer3/
      contract.pdf
```

Each customer is a subfolder under a group folder. All files in a
customer's folder are analyzed together.

## Command Options

```
dd-agents search PROMPTS_PATH [OPTIONS]

Arguments:
  PROMPTS_PATH   Path to your prompts JSON file

Options:
  --data-room PATH     Path to the data room folder (required)
  --output PATH        Excel output path (default: auto-named)
  --customers TEXT      Filter to specific customers (comma-separated)
  --concurrency N      Parallel API calls, 1-20 (default: 5)
  --yes / -y           Skip cost confirmation prompt
  --verbose / -v       Show detailed logging
```

### Examples

```bash
# Analyze all customers
dd-agents search prompts.json --data-room ./data_room

# Analyze only specific customers
dd-agents search prompts.json --data-room ./data_room --customers "Acme,Beta Corp"

# Skip confirmation and save to specific file
dd-agents search prompts.json --data-room ./data_room -y --output results.xlsx

# See detailed progress
dd-agents search prompts.json --data-room ./data_room -v
```

## Understanding the Excel Report

The report has two sheets:

### Summary Sheet

One row per customer with:

| Column | Description |
|--------|-------------|
| Customer | Customer name |
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
| Customer | Customer name |
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
customer's combined document text exceeds the model's optimal context size
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
shows how many analysis passes were needed per customer. Single-chunk
customers (the majority) see no change in behavior.

## External Reference Download

Contracts frequently incorporate external Terms & Conditions by URL
reference (e.g. `https://vendor.com/general-terms-and-conditions/`).
After text extraction, the pipeline automatically:

1. **Scans** customer-extracted text for URLs matching T&C-like patterns
   (terms, conditions, policy, SLA, EULA, privacy, agreement, etc.)
2. **Downloads** referenced documents via HTTP (any domain accepted —
   if a URL appears in a contract with a legal keyword in its path, it
   was put there for a reason)
3. **Extracts** text content using markitdown
4. **Caches** results in the text index with an `__external__` prefix

This step is non-blocking: download failures are logged as warnings
but never halt the pipeline.

**Important**: Downloaded external references are cached for future use
but are **not** automatically included in the customer contract analysis.
The search analyzer only reads files listed in each customer's registry
entry — never by scanning the text directory. This prevents external
documents (e.g. a cloud provider's customer agreement) from being
confused with the customer's own contract terms. External references
may be relevant for vendor/infrastructure analysis but must be
explicitly opted-in for that use case.

## Citation Verification

After analysis, all citations are verified against the extracted
source text using fuzzy matching (rapidfuzz). This catches
hallucinated quotes and wrong page references without requiring
additional API calls.

- **80% match threshold** — tolerates OCR character errors while
  flagging fabricated quotes
- **Page-scoped search** — when a page number is cited, verification
  searches within that page's text
- **Section verification** — checks that the cited section reference
  actually appears in the source document
- Results appear in the Excel Details sheet (Quote Verified / Match
  Score columns) and in the CLI summary output

## Data Completeness Guarantees

The search command is designed for legal due diligence where missing data
is unacceptable:

- **Every customer** in the input appears in the output, even if analysis
  failed
- **Every question** gets an answer for every customer — missing answers
  are flagged as "INCOMPLETE" in orange
- **No size limit** — files of any size are analyzed via automatic chunking.
  No documents are ever skipped due to size constraints
- **Skipped files** (missing text extraction) are listed in the report so
  you know what wasn't analyzed
- **Files Analyzed** shows "X/Y" format so you can see at a glance if any
  files were missed
- **Errors** are recorded per customer, never silently dropped

## Troubleshooting

### "No customers found"

Your data room doesn't follow the expected directory structure. It must be:
`data_room/group/customer/files`. See the Data Room Structure section above.

### "No extracted text found for this customer's files"

The text extraction step couldn't read any of this customer's files. Check
that the files are valid PDFs, Word documents, or other supported formats.

### "Incomplete response — missing columns"

The AI didn't answer all questions for this customer. This can happen with
very large document sets. The missing columns are flagged in orange in the
Excel report. Re-running with `--concurrency 1` may help.

### "Failed to parse API response as JSON"

The AI returned a malformed response. This is automatically retried (up to
3 times). If it persists, the error is recorded in the report.

### Cost seems too high

Use `--customers` to test with a small subset first. Use `--verbose` to
see token counts. Reduce the number of questions in your prompts file.
