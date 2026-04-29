# 06 -- Agent Definitions

> **Historical note**: This is a design spec written before implementation. The original design specified 4 specialist agents. The implementation has 9 specialists (Legal, Finance, Commercial, ProductTech, Cybersecurity, HR, Tax, Regulatory, ESG) managed via `AgentRegistry` in `agents/registry.py` with `AgentDescriptor` metadata in `agents/descriptor.py`. The Reporting Lead was removed in v0.4.0. See `CLAUDE.md` and `agents/specialists.py` for the current agent architecture.

> **Source**: `agent-prompts.md` (508 lines), `SKILL.md` sections 3a-3g
> **SDK reference**: `claude-agent-sdk` v0.1.56+ — `query()`, `ClaudeAgentOptions`, `HookMatcher`
> **Cross-references**: `04-data-models.md` (output schemas), `05-orchestrator.md` (pipeline steps 16, 19-22, 23), `07-tools-and-hooks.md` (hooks + MCP tools), `10-reporting.md` (merge protocol), `12-error-recovery.md` (retry)

---

## 1. Architecture Overview

All agents are **workers**, not orchestrators. Python controls flow.

- Each agent is invoked via `query()` — a one-shot call that returns `ResultMessage`
- 4 specialists run **in parallel** (`asyncio.gather`), Judge runs after (if enabled), then deterministic merge + validation
- Agents use Claude Code's full tool ecosystem (Read, Write, Glob, Grep) within their working directory
- Every agent receives a self-contained prompt — agents **cannot** read skill files or other agents' instructions
- Hooks enforce output format and block dangerous operations (see `07-tools-and-hooks.md`)
- Stop hooks use **flat format**: `{"decision": "block", "reason": "..."}` — NOT nested under `hookSpecificOutput`

---

## 2. Agent Registry

Eight agents, four categories:

| Agent | Category | Pipeline Step | Runs After | Conditional |
|-------|----------|--------------|------------|-------------|
| **Legal** | Specialist | 16 | Extraction + inventory | No |
| **Finance** | Specialist | 16 | Extraction + inventory | No |
| **Commercial** | Specialist | 16 | Extraction + inventory | No |
| **ProductTech** | Specialist | 16 | Extraction + inventory | No |
| **Judge** | QA | 19-22 | All 4 specialists | Yes (`judge.enabled`) |
| ~~ReportingLead~~ | ~~Reporting~~ | ~~23~~ | ~~Judge~~ | **Removed in v0.4.0** — replaced by deterministic pre-merge validation (`validation/pre_merge.py`) and deterministic merge (`reporting/merge.py`) |
| **ExecutiveSynthesis** | Synthesis | 30 | Merged findings | No (always runs) |
| **AcquirerIntelligence** | Synthesis | 30 | Merged findings | Yes (`buyer_strategy`) |

---

## 3. SDK Configuration

### 3.1 Base Agent Runner

```python
# src/dd_agents/agents/base.py

from pathlib import Path
from claude_agent_sdk import query, ClaudeAgentOptions, HookMatcher, ResultMessage
from dd_agents.hooks import build_hooks_for_agent
from dd_agents.tools.mcp_server import get_mcp_server_config  # returns {"dd_tools": server}

class BaseAgentRunner:
    """Common spawn logic for all agent types."""

    def __init__(self, project_dir: Path, run_dir: Path, run_id: str):
        self.project_dir = project_dir
        self.run_dir = run_dir
        self.run_id = run_id

    async def spawn(
        self,
        agent_name: str,
        prompt: str,
        *,
        model: str = "claude-sonnet-4-20250514",
        max_turns: int = 200,
        max_budget_usd: float = 5.0,
        tools: list[str] | None = None,
        extra_hooks: list[HookMatcher] | None = None,
    ) -> ResultMessage:
        """Invoke an agent via query(). Returns ResultMessage with cost, session_id."""

        default_tools = ["Read", "Write", "Glob", "Grep"]
        agent_tools = tools or default_tools

        hooks = build_hooks_for_agent(agent_name, self.run_dir)
        if extra_hooks:
            hooks.extend(extra_hooks)

        options = ClaudeAgentOptions(
            model=model,
            max_turns=max_turns,
            max_budget_usd=max_budget_usd,
            system_prompt=f"You are the {agent_name} agent for forensic M&A due diligence.",
            cwd=str(self.project_dir),
            tools=agent_tools,
            allowed_tools=agent_tools,
            hooks=hooks,
            mcp_servers=get_mcp_server_config(agent_name),
        )

        result = await query(options=options, prompt=prompt)
        return result
```

### 3.2 Per-Agent Configuration

| Agent | Model | max_turns | max_budget_usd | Tools | Custom MCP Tools |
|-------|-------|-----------|---------------|-------|------------------|
| Legal | claude-sonnet-4-20250514 | 200 | 5.00 | Read, Write, Glob, Grep | validate_finding, validate_gap, verify_citation, resolve_entity, get_subject_files, report_progress |
| Finance | claude-sonnet-4-20250514 | 200 | 5.00 | Read, Write, Glob, Grep | validate_finding, validate_gap, verify_citation, resolve_entity, get_subject_files, report_progress |
| Commercial | claude-sonnet-4-20250514 | 200 | 5.00 | Read, Write, Glob, Grep | validate_finding, validate_gap, verify_citation, resolve_entity, get_subject_files, report_progress |
| ProductTech | claude-sonnet-4-20250514 | 200 | 5.00 | Read, Write, Glob, Grep | validate_finding, validate_gap, verify_citation, resolve_entity, get_subject_files, report_progress |
| Judge | claude-sonnet-4-20250514 | 150 | 3.00 | Read, Write, Glob, Grep | verify_citation, get_subject_files |

**Notes**:
- Judge gets fewer turns (review only, no analysis)
- ReportingLead was removed in v0.4.0. Merge, audit, and Excel generation are now handled by deterministic Python code (`validation/pre_merge.py`, `reporting/merge.py`) with no LLM calls
- Model selection is configured in `deal-config.json` under `agents.{agent_name}.model`. Default: `claude-sonnet-4-20250514` for specialists, `claude-sonnet-4-20250514` for Judge. Override by setting the model field in the agent config. The orchestrator passes this to `ClaudeAgentOptions(model=...)` at agent spawn time. The global fallback `execution.model` applies to any agent without an explicit per-agent override.
- When web research is enabled, specialists additionally receive: google-researcher-mcp:search_and_scrape, google-researcher-mcp:google_search, google-researcher-mcp:scrape_page

---

## 4. All-Agents-All-Subjects Architecture

**Every specialist agent analyzes ALL subjects.** There is no modulo assignment, no subject splitting by default. Each agent reads every subject's files through their specialist lens.

| Agent | Specialist Lens | What They Prioritize in Every File |
|-------|----------------|-----------------------------------|
| **Legal** | Legal risk and governance | Change of control, assignment, termination, liability caps, indemnification, governing law, IP ownership, non-compete, exclusivity, MFN, entity validation, governance graph construction |
| **Finance** | Financial risk and reconciliation | Pricing, payment terms, discounts, revenue recognition, ARR/MRR cross-reference, minimum commitments, true-ups, one-time vs recurring fees, financial data mismatches, **revenue composition** (recurring vs services vs one-time by product/SKU), **unit economics** (CAC, LTV, NRR/GRR), **financial projections** validation, **cost structure** (COGS, OpEx, R&D, S&M breakdown) |
| **Commercial** | Commercial terms and operations | Term/duration, renewal mechanics, SLA commitments, service credits, expansion rights, usage limits, territory restrictions, customer health/churn risk, pricing compliance, **customer segmentation** (cohort, size tier, geography, vertical), **pricing model** (per-user, tiered, consumption, hybrid), **expansion/contraction** (upsell, NRR decomposition), **competitive positioning** (displacement, exclusivity, benchmarking) |
| **ProductTech** | Technical risk and compliance | Integration requirements, API dependencies, technical SLAs, uptime, security certifications (SOC2/ISO27001), data portability, migration obligations, subprocessor lists, DPA adequacy |

---

## 5. Prompt Construction

### 5.1 Prompt Builder

```python
# src/dd_agents/agents/prompt_builder.py

from enum import Enum
from pathlib import Path
from dd_agents.models.config import DealConfig
from dd_agents.models.inventory import SubjectEntry, ReferenceFile

class AgentType(str, Enum):
    LEGAL = "legal"
    FINANCE = "finance"
    COMMERCIAL = "commercial"
    PRODUCTTECH = "producttech"
    JUDGE = "judge"
    # REPORTING_LEAD was removed in v0.4.0 — merge/reporting is now deterministic Python

# Focus areas per specialist (embedded into prompt)
SPECIALIST_FOCUS = {
    AgentType.LEGAL: (
        "Build the governance graph for each subject. Resolve governed_by for every file. "
        "Flag entity mismatches against the corporate org chart. Flag change of control, "
        "assignment restrictions, and exclusivity clauses. Validate intercompany agreements "
        "cover all signing entities. Gap detection: For each subject, check for missing MSAs, "
        "missing DPAs, missing referenced amendments, missing signature pages. "
        "Write gap files for EVERY missing document detected."
    ),
    AgentType.FINANCE: (
        "Cross-reference every subject's contract values against the Revenue Cube and any "
        "financial reference data. Flag ARR mismatches >5%. Check discount levels against "
        "Pricing Guidelines. Identify one-time fees incorrectly counted as recurring ARR. "
        "Flag minimum commitment shortfalls. IMPORTANT: You MUST analyze ALL subjects, not "
        "just those with dedicated financial documents. For subjects with only contract files, "
        "extract financial terms from their contracts and cross-reference against reference "
        "file data. Gap detection: Check for missing financial verification, missing pricing "
        "documentation, unexplained revenue variances. Write gap files.\n\n"
        "REVENUE DECOMPOSITION: Break down by product/SKU (subscription, professional services, "
        "one-time license, usage-based, support/maintenance). Flag services >10% revenue.\n"
        "UNIT ECONOMICS: Extract CAC, LTV, payback, NRR/GRR. Flag NRR<100% or GRR<85%.\n"
        "FINANCIAL PROJECTIONS: Cross-ref projections vs historical growth. Flag unrealistic assumptions.\n"
        "COST STRUCTURE: COGS, OpEx, R&D, S&M breakdown and margin profiles."
    ),
    AgentType.COMMERCIAL: (
        "Evaluate renewal mechanics (auto vs manual, notice periods, penalties). Cross-reference "
        "contract terms against Customer Health Scores for churn risk. Compare pricing against "
        "rate cards. Flag SLA commitments and service credit exposure. Gap detection: Check for "
        "missing SOWs, missing order forms, missing renewal evidence, unsigned documents. "
        "Write gap files for EVERY missing document detected.\n\n"
        "CUSTOMER SEGMENTATION: Segment by size/geography/vertical/vintage. Flag >30% concentration.\n"
        "PRICING MODEL: Identify type (per-user, consumption, tiered, hybrid). Flag pricing risks.\n"
        "EXPANSION & CONTRACTION: Decompose NRR, identify expansion levers, flag contraction signals.\n"
        "COMPETITIVE POSITIONING: Displacement language, exclusivity, benchmarking/MFN clauses."
    ),
    AgentType.PRODUCTTECH: (
        "Validate DPA adequacy and subprocessor lists. Cross-reference security claims against "
        "SOC2/compliance evidence. Check technical SLA feasibility. Flag data residency "
        "restrictions and migration obligations. IMPORTANT: You MUST analyze ALL subjects, "
        "not just those with dedicated tech/security documents. For every subject's contracts, "
        "extract technology-related clauses. Gap detection: Check for missing DPAs, missing "
        "security addenda, missing SLA documentation, missing architecture/integration specs. "
        "Write gap files.\n\n"
        "CITATION ENFORCEMENT: Every ProductTech finding MUST include a citation with "
        "source_path and exact_quote. For technical documents (SOC2 reports, pentest reports, "
        "architecture docs, SLA addenda, product specs), cite the specific section/page. "
        "If a claim cannot be cited, record it as a gap with gap_type 'Not_Found', not as "
        "an uncited finding. Uncited findings will be DOWNGRADED to P3 during validation."
    ),
}

class PromptBuilder:
    """Assembles self-contained agent prompts from templates and runtime data."""

    def __init__(self, project_dir: Path, run_dir: Path, run_id: str):
        self.project_dir = project_dir
        self.run_dir = run_dir
        self.run_id = run_id

    def build_specialist_prompt(
        self,
        agent_type: AgentType,
        deal_config: DealConfig,
        subjects: list[SubjectEntry],
        reference_files: dict[str, list[ReferenceFile]],
        subject_mentions: dict[str, list[str]],
        extraction_rules: str,
        governance_rules: str,
        gap_detection_rules: str,
        output_schema: str,
    ) -> str:
        """Build a complete, self-contained specialist prompt."""
        sections = []

        # 1. Role and deal context
        sections.append(self._build_role_section(agent_type, deal_config))

        # 2. Complete subject list with file paths
        sections.append(self._build_subject_list(subjects))

        # 3. Reference files (FULL extracted text)
        agent_refs = reference_files.get(agent_type.value, [])
        sections.append(self._build_reference_section(agent_refs))

        # 4. Subject-mention index
        sections.append(self._build_mentions_section(subject_mentions))

        # 5. Specialist focus areas
        sections.append(f"## YOUR SPECIALIST FOCUS\n\n{SPECIALIST_FOCUS[agent_type]}")

        # 6. Domain rules (copied into prompt, not referenced by path)
        sections.append(f"## EXTRACTION RULES\n\n{extraction_rules}")
        sections.append(f"## GOVERNANCE GRAPH RULES\n\n{governance_rules}")
        sections.append(f"## GAP DETECTION RULES\n\n{gap_detection_rules}")

        # 7. File processing instructions
        sections.append(self._build_file_processing_instructions())

        # 8. Output format
        sections.append(f"## OUTPUT FORMAT\n\n{output_schema}")

        # 9. Manifest requirement
        sections.append(self._build_manifest_requirement(agent_type, subjects))

        # 10. Strict output rules
        sections.append(self._build_output_rules(agent_type))

        return "\n\n---\n\n".join(sections)
```

### 5.2 Required Prompt Sections

Each specialist agent's prompt **MUST** include ALL of the following. Agents cannot read skill files — everything must be inline:

| # | Section | Source | Size Estimate |
|---|---------|--------|--------------|
| 1 | Deal context (buyer, target, subsidiaries) | `deal-config.json` | ~500 tokens |
| 2 | COMPLETE subject list with explicit file paths | `subjects.csv` | ~50 tokens/subject |
| 3 | Reference file extracted text (FULL content) | `reference_files.json` + `index/text/` | Variable (measure each) |
| 4 | Subject-mention index | `subject_mentions.json` | ~20 tokens/subject |
| 5 | Specialist focus areas | Hardcoded per agent type | ~200 tokens |
| 6 | Extraction rules | `domain-definitions.md` sections 1-4 | ~1,500 tokens |
| 7 | Governance graph rules | `domain-definitions.md` section 5 | ~800 tokens |
| 8 | Gap detection rules (incl. cross-reference) | `domain-definitions.md` sections 6-7 | ~700 tokens |
| 9 | File processing instructions | Template | ~300 tokens |
| 10 | Output format (JSON schemas) | `agent-prompts.md` section 4c | ~600 tokens |
| 11 | Manifest requirement | Template | ~500 tokens |

### 5.3 Subject List Format

```
ALL CUSTOMERS (you MUST process every one, every file):

Subject 1: Acme Corp (safe_name: acme_corp)
  Path: ./Above 200K USD/Acme Corp/
  Files (3):
    - ./Above 200K USD/Acme Corp/MSA.pdf
      → pre-extracted at _dd/forensic-dd/index/text/Above_200K_USD__Acme_Corp__MSA.pdf.md
    - ./Above 200K USD/Acme Corp/Order Form 2023.docx
      → pre-extracted at _dd/forensic-dd/index/text/Above_200K_USD__Acme_Corp__Order_Form_2023.docx.md
    - ./Above 200K USD/Acme Corp/DPA.pdf
      → pre-extracted at _dd/forensic-dd/index/text/Above_200K_USD__Acme_Corp__DPA.pdf.md

Subject 2: Beta Inc (safe_name: beta)
  ...

IMPORTANT: Use the exact safe_name provided above as the filename for your output JSON.
Write: {RUN_DIR}/findings/{agent}/acme_corp.json (NOT "Acme Corp.json")

TOTAL: X subjects, Y files. You must process every single one.
```

### 5.4 Reference File Section

Reference files are pasted as **full extracted text**, not file paths:

```
GLOBAL REFERENCE FILES assigned to you:

Reference 1: Subjects Cube Q4 2024.xlsx
  Category: Financial / revenue_by_subject
  Pre-extracted at: _dd/forensic-dd/index/text/Customers_Cube_Q4_2024.xlsx.md
  FULL EXTRACTED CONTENT:
  """
  [complete text from extracted file]
  """
  ALL CUSTOMERS found in this file:
    - Acme Corp: ARR=$120,000, renewal=2025-06-30
    ...

CROSS-REFERENCE REQUIREMENT: For each subject, compare contract terms against
these reference files. You MUST list every reference file in your manifest
under reference_files_processed.
```

---

## 6. Prompt Size Management

### 6.1 Token Estimation

```python
# src/dd_agents/agents/prompt_builder.py (continued)

import tiktoken

class PromptSizeEstimator:
    """Estimates prompt token count before construction."""

    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        # Approximate: 1 token ≈ 4 chars for English text
        self.chars_per_token = 4
        self.context_limit = 200_000  # Claude Sonnet context window
        self.safety_margin = 0.80     # Use at most 80% for prompt

    def estimate_specialist_tokens(
        self,
        subjects: list[SubjectEntry],
        reference_texts: list[str],
        rules_text: str,
    ) -> int:
        subject_tokens = len(subjects) * 50  # ~50 tokens per subject entry
        ref_tokens = sum(len(t) // self.chars_per_token for t in reference_texts)
        rules_tokens = len(rules_text) // self.chars_per_token
        overhead = 2_000  # role, instructions, manifest, output format
        return subject_tokens + ref_tokens + rules_tokens + overhead

    def needs_splitting(self, estimated_tokens: int) -> bool:
        return estimated_tokens > (self.context_limit * self.safety_margin)
```

### 6.2 Subject Splitting

When estimated tokens exceed 80% of context window, split subjects into groups:

```python
# src/dd_agents/agents/specialists.py

async def spawn_specialist_with_splitting(
    runner: BaseAgentRunner,
    agent_type: AgentType,
    prompt_builder: PromptBuilder,
    estimator: PromptSizeEstimator,
    subjects: list[SubjectEntry],
    **kwargs,
) -> list[ResultMessage]:
    """Spawn specialist, splitting into multiple instances if prompt is too large."""

    estimated = estimator.estimate_specialist_tokens(
        subjects, kwargs.get("reference_texts", []), kwargs.get("rules_text", "")
    )

    if not estimator.needs_splitting(estimated):
        # Single instance — all subjects
        prompt = prompt_builder.build_specialist_prompt(
            agent_type=agent_type, subjects=subjects, **kwargs
        )
        result = await runner.spawn(agent_type.value, prompt)
        return [result]

    # Split into groups that fit within context
    max_subjects_per_group = _calculate_group_size(estimator, subjects, kwargs)
    groups = [
        subjects[i:i + max_subjects_per_group]
        for i in range(0, len(subjects), max_subjects_per_group)
    ]

    # Spawn one instance per group in parallel
    import asyncio
    tasks = []
    for idx, group in enumerate(groups):
        prompt = prompt_builder.build_specialist_prompt(
            agent_type=agent_type, subjects=group, **kwargs
        )
        name = f"{agent_type.value}_{idx + 1}"  # 1-based: batch_1, batch_2, ...
        tasks.append(runner.spawn(name, prompt))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Merge outputs from all instances before Judge phase
    _merge_split_outputs(runner.run_dir, agent_type, len(groups))

    return [r for r in results if isinstance(r, ResultMessage)]
```

---

## 7. Agent Output Requirements

### 7.1 Per-Subject JSON Schema

Each specialist writes one JSON per subject to `{RUN_DIR}/findings/{agent}/{subject_safe_name}.json`:

```json
{
  "subject": "Canonical subject name",
  "subject_safe_name": "safe_name per convention",
  "agent": "legal|finance|commercial|producttech",
  "run_id": "20250218_143000",
  "timestamp": "2025-02-18T14:35:00Z",
  "files_analyzed": 3,
  "file_headers": [
    {
      "file_path": "./Above 200K/Acme/MSA.pdf",
      "text_path": "_dd/forensic-dd/index/text/Above_200K__Acme__MSA.pdf.md",
      "doc_type_guess": "MSA",
      "effective_date_guess": "2023-01-15",
      "expiry_date_guess": "2026-01-14",
      "parties": ["Apex Digital Inc.", "Acme Corp"],
      "governed_by": "SELF",
      "references_found": ["Amendment #1"],
      "content_summary": "3-year MSA with standard terms...",
      "cross_reference_data": {}
    }
  ],
  "governance_graph": {
    "edges": [
      {"from": "./MSA.pdf", "to": "./Order Form.pdf", "relation": "governs"}
    ]
  },
  "findings": [
    {
      "severity": "P0",
      "category": "Change of Control",
      "title": "MSA prohibits assignment on change of control",
      "description": "Section 12.3 requires counterparty consent...",
      "citations": [
        {
          "source_type": "file",
          "source_path": "./Above 200K/Acme/MSA.pdf",
          "location": "Section 12.3",
          "exact_quote": "Neither party may assign..."
        }
      ],
      "confidence": "high"
    }
  ],
  "gaps": [
    {
      "gap_type": "Missing_Doc",
      "missing_item": "Amendment #1",
      "referenced_in": "./Above 200K/Acme/MSA.pdf",
      "priority": "P1",
      "impact": "Cannot verify current terms"
    }
  ],
  "cross_references": [],
  "cross_reference_summary": {},
  "metadata": {}
}
```

Full Pydantic model: `AgentFinding` schema in `04-data-models.md`.

### 7.2 Strict Output Rules

1. **Exactly ONE JSON per subject**: `{RUN_DIR}/findings/{agent}/{subject_safe_name}.json`
2. **NO aggregate files**: Never create `_global.json`, `batch_summary.json`, `other_subjects.json`, `pipeline_items.json`, or any file not named after a specific subject
3. **Gaps isolated per agent**: Write to `{RUN_DIR}/findings/{agent}/gaps/{subject_safe_name}.json`
4. **Coverage manifest**: SHOULD write `{RUN_DIR}/findings/{agent}/coverage_manifest.json` (stop hook is relaxed — if all subject JSONs are present, the orchestrator backfills the manifest post-session)
5. **Audit log**: Written by the orchestrator post-session via `_write_audit_log()` (not by the agent)
6. **Use exact safe_name**: Output filenames must match the `subject_safe_name` provided in the prompt
7. **Use canonical field names**: Findings MUST use `"citations"` (not `"evidence"`), citations MUST use `"source_path"` (not `"file"`) and `"exact_quote"` (not `"quote"`). The `finding_schema_guard` PreToolUse hook blocks writes with wrong field names.

PreToolUse hooks validate rules 1-2 (aggregate file guard), rule 7 (finding schema guard), and path boundaries at write time. The Stop hook validates rule 4 at agent completion. See `07-tools-and-hooks.md`.

### 7.3 Coverage Manifest

Every specialist MUST write `{RUN_DIR}/findings/{agent}/coverage_manifest.json`:

```json
{
  "agent": "legal",
  "skill": "forensic-dd",
  "run_id": "20250218_143000",
  "files_assigned": ["./path/to/file1.pdf", "./path/to/file2.docx"],
  "files_read": [
    {"path": "./path/to/file1.pdf", "extraction_quality": "primary", "pages_read": "all", "bytes_analyzed": 24500}
  ],
  "files_skipped": [
    {"path": "./logo.png", "reason": "outside_agent_scope", "reason_detail": "Image contains logo, no contractual content"}
  ],
  "files_failed": [
    {"path": "./corrupted.pdf", "reason": "Extraction returned empty", "fallback_attempted": true, "fallback_result": "All methods returned empty"}
  ],
  "coverage_pct": 0.95,
  "analysis_units_assigned": 34,
  "analysis_units_completed": 34,
  "subjects": [
    {"name": "Acme Corp", "files_assigned": ["./file1.pdf"], "files_processed": ["./file1.pdf"], "files_skipped": [], "status": "complete"}
  ],
  "reference_files_processed": ["./Reference Data/Subjects Cube.xlsx"]
}
```

Manifest validation rules (violations cause audit failure):
- `files_assigned` must match files.txt
- `files_failed` must have `fallback_attempted: true`
- `coverage_pct` must be >= 0.90
- `subjects[].status` must be "complete" or "partial" (never missing)
- `analysis_units_assigned` and `analysis_units_completed` must match subject counts

### 7.4 Audit Log

Every specialist writes `{RUN_DIR}/audit/{agent}/audit_log.jsonl`:

```jsonl
{"ts":"2025-02-18T14:35:00Z","agent":"legal","skill":"forensic-dd","action":"file_read","target":"./Acme/MSA.pdf","result":"success","details":"Extracted via markitdown, 24500 bytes"}
{"ts":"2025-02-18T14:35:05Z","agent":"legal","skill":"forensic-dd","action":"finding_created","target":"forensic-dd_legal_0001","result":"P0","details":"Change of control prohibition in Section 12.3"}
{"ts":"2025-02-18T14:35:10Z","agent":"legal","skill":"forensic-dd","action":"gap_created","target":"Acme Corp","result":"P1","details":"Referenced Amendment #2 not found"}
```

Required actions to log: `file_read`, `finding_created`, `gap_created`, `cross_reference`, `skip`, `error`, `phase_complete`.

---

## 8. Reference File Routing

Global reference files from `_dd/forensic-dd/inventory/reference_files.json` are routed to agents by category:

| Agent | Reference File Categories | Cross-Reference Duties |
|-------|--------------------------|----------------------|
| **Legal** | Corporate/Legal, Compliance | Entity names vs org structure, intercompany agreements, compliance certs |
| **Finance** | Financial, Pricing | Contract values vs revenue data, payment terms vs invoices, discount approvals |
| **Commercial** | Pricing, Sales, Operational | Pricing vs rate cards, discount compliance, renewal dates, churn risk |
| **ProductTech** | Operational, Compliance | Technical SLAs vs actual data, SOC2/security claims, DPA adequacy |

Rules:
- Reference files are routed based on `reference_files.json` which maps each file to its primary agent (Legal, Finance, Commercial, ProductTech). Files relevant to multiple agents are sent to all applicable agents. The routing is determined by file type patterns defined in the extraction phase (step 8, Reference Registry).
- Every reference file must be assigned to at least one agent
- If a reference file doesn't fit any category, assign to ALL agents
- The **FULL extracted text** of each reference file is pasted into the agent's prompt
- Agents must list all reference files in their manifest under `reference_files_processed`

```python
# src/dd_agents/agents/reference_router.py

ROUTING_TABLE: dict[str, list[AgentType]] = {
    "corporate_legal": [AgentType.LEGAL],
    "compliance": [AgentType.LEGAL, AgentType.PRODUCTTECH],
    "financial": [AgentType.FINANCE],
    "pricing": [AgentType.FINANCE, AgentType.COMMERCIAL],
    "sales": [AgentType.COMMERCIAL],
    "operational": [AgentType.COMMERCIAL, AgentType.PRODUCTTECH],
    "uncategorized": [AgentType.LEGAL, AgentType.FINANCE, AgentType.COMMERCIAL, AgentType.PRODUCTTECH],
}

def route_references(
    reference_files: list[ReferenceFile],
) -> dict[str, list[ReferenceFile]]:
    """Route reference files to agents by category."""
    result: dict[str, list[ReferenceFile]] = {t.value: [] for t in AgentType if t != AgentType.JUDGE}

    for ref in reference_files:
        category = ref.category.lower().replace(" ", "_")
        targets = ROUTING_TABLE.get(category, ROUTING_TABLE["uncategorized"])
        for agent_type in targets:
            result[agent_type.value].append(ref)

    # Verify no reference file is unassigned
    assigned = set()
    for refs in result.values():
        assigned.update(r.path for r in refs)
    unassigned = [r for r in reference_files if r.path not in assigned]
    if unassigned:
        for agent_refs in result.values():
            agent_refs.extend(unassigned)

    return result
```

---

## 9. Specialist Spawn Pattern

### 9.1 Parallel Spawn (Pipeline Step 16)

```python
# src/dd_agents/agents/specialists.py

import asyncio
from dd_agents.agents.base import BaseAgentRunner
from dd_agents.agents.prompt_builder import PromptBuilder, AgentType

SPECIALIST_TYPES = [
    AgentType.LEGAL,
    AgentType.FINANCE,
    AgentType.COMMERCIAL,
    AgentType.PRODUCTTECH,
]

async def spawn_all_specialists(
    runner: BaseAgentRunner,
    prompt_builder: PromptBuilder,
    subjects: list[SubjectEntry],
    reference_files: dict[str, list[ReferenceFile]],
    subject_mentions: dict[str, list[str]],
    deal_config: DealConfig,
    rules: dict[str, str],
) -> dict[str, ResultMessage]:
    """Spawn all 4 specialists in parallel. Returns dict of agent_name -> ResultMessage."""

    async def spawn_one(agent_type: AgentType) -> tuple[str, ResultMessage]:
        prompt = prompt_builder.build_specialist_prompt(
            agent_type=agent_type,
            deal_config=deal_config,
            subjects=subjects,
            reference_files=reference_files,
            subject_mentions=subject_mentions,
            extraction_rules=rules["extraction"],
            governance_rules=rules["governance"],
            gap_detection_rules=rules["gap_detection"],
            output_schema=rules["output_schema"],
        )
        result = await runner.spawn(agent_type.value, prompt)
        return (agent_type.value, result)

    results = await asyncio.gather(
        *[spawn_one(t) for t in SPECIALIST_TYPES],
        return_exceptions=True,
    )

    output = {}
    for item in results:
        if isinstance(item, Exception):
            raise item  # Handled by error recovery (12-error-recovery.md)
        name, result = item
        output[name] = result

    return output
```

### 9.2 Incremental Mode

When `execution_mode == "incremental"`, specialists receive only subjects requiring analysis (NEW, CHANGED, STALE_REFRESH). UNCHANGED subjects' findings are carried forward. See `05-orchestrator.md` step 12.

---

## 10. Judge Agent Protocol

### 10.1 Activation

Judge is spawned only when `judge.enabled` is true in deal-config.json. Pipeline steps 19-22 are conditional.

### 10.2 Judge Inputs

The Judge receives:
- All specialist outputs: `{RUN_DIR}/findings/{agent}/*.json` (4 directories)
- Extracted source text: `_dd/forensic-dd/index/text/*.md` (for citation verification)
- Reference files: metadata + key extracted texts
- Deal context: `deal-config.json`
- Subject list: `subjects.csv`
- Judge configuration: sampling rates, score threshold, max iteration rounds

### 10.3 Risk-Based Sampling

| Finding Severity | Default Sample Rate | Rationale |
|-----------------|-------------------|-----------|
| **P0** (deal-stoppers) | 100% | Every P0 must be verified |
| **P1** (material risk) | 20% | Spot-check for accuracy |
| **P2** (moderate risk) | 10% | Light sampling |
| **P3** (informational) | 0% | Not reviewed unless agent score is low |

Additional mandatory reviews:
- **100% completeness check** for subjects with OCR-extracted files (if `judge.ocr_completeness_check` is true)
- **100% review** for subjects where 2+ agents report conflicting severity (if `judge.cross_agent_contradiction_check` is true)

Sampling rates are configurable in deal-config.json:
```json
"judge": {
  "enabled": true,
  "max_iteration_rounds": 2,
  "score_threshold": 70,
  "sampling_rates": { "p0": 1.0, "p1": 0.20, "p2": 0.10, "p3": 0.0 },
  "ocr_completeness_check": true,
  "cross_agent_contradiction_check": true
}
```

### 10.4 Spot-Check Protocol (5 Dimensions)

For each sampled finding, the Judge evaluates along 5 dimensions:

| Dimension | Weight | What It Checks | Scoring |
|-----------|--------|---------------|---------|
| `citation_verification` | **30%** | Does the quoted text exist in the source document? | PASS=100, PARTIAL=50, FAIL=0 |
| `contextual_validation` | **25%** | Is the finding correctly interpreted in context? | PASS=100, PARTIAL=50, FAIL=0 |
| `financial_accuracy` | **20%** | Are numbers, dates, calculations correct? | PASS=100, PARTIAL=50, FAIL=0 |
| `cross_agent_consistency` | **15%** | Do agents agree on facts? | PASS=100, PARTIAL=50, FAIL=0 |
| `completeness` | **10%** | Did the agent process all files and focus areas? | PASS=100, PARTIAL=50, FAIL=0 |

Weight rationale: Forensic contract DD upweights citation accuracy (contracts are quote-heavy) and financial accuracy (cross-reference reconciliation is critical), downweights completeness (enforced separately by manifest audit).

### 10.5 Scoring

**Per-Agent Score (0-100)**:
```
agent_score = 0.30 * citation_verification
            + 0.25 * contextual_validation
            + 0.20 * financial_accuracy
            + 0.15 * cross_agent_consistency
            + 0.10 * completeness
```

**Per-Subject Score (0-100)**:
```
subject_score = average(agent_scores for that subject)
Subjects with contradictions: -20 penalty until resolved
```

### 10.6 Judge Output

Single file: `{RUN_DIR}/judge/quality_scores.json`

Contains `spot_checks[]` and `contradictions[]` arrays inline (NOT separate files). Schema: `QualityScores` in `04-data-models.md`.

```json
{
  "run_id": "20250218_143000",
  "skill": "forensic-dd",
  "judge_config": { "sampling_rates": {"p0": 1.0, "p1": 0.2, "p2": 0.1, "p3": 0.0}, "score_threshold": 70, "max_iteration_rounds": 2 },
  "agent_scores": {
    "legal": {"score": 85, "findings_reviewed": 24, "findings_total": 120, "pass": 20, "partial": 3, "fail": 1, "dimensions": {"citation_verification": 90, "contextual_validation": 85, "financial_accuracy": 80, "cross_agent_consistency": 85, "completeness": 80}},
    "finance": {"score": 72, ...},
    "commercial": {"score": 91, ...},
    "producttech": {"score": 68, ...}
  },
  "unit_scores": {
    "acme_corp": {"score": 90, "agents_reviewed": 4, "contradictions": 0}
  },
  "overall_quality": 79,
  "iteration_round": 1,
  "agents_below_threshold": ["producttech"],
  "spot_checks": [
    {"finding_id": "forensic-dd_legal_0001", "agent": "legal", "analysis_unit": "acme_corp", "severity": "P0", "dimension": "citation_verification", "result": "PASS", "notes": "Quote found at paragraph 12.3"}
  ],
  "contradictions": [
    {"analysis_unit": "acme_corp", "agents": ["legal", "finance"], "fact_in_dispute": "Contract term length", "resolution": "Legal is correct", "winning_agent": "legal"}
  ]
}
```

### 10.7 Iteration Loop

```python
# src/dd_agents/agents/judge.py

async def run_judge_with_iteration(
    runner: BaseAgentRunner,
    prompt_builder: PromptBuilder,
    deal_config: DealConfig,
    max_rounds: int = 2,
    threshold: int = 70,
) -> QualityScores:
    """Run Judge with up to max_rounds of iteration."""

    for round_num in range(1, max_rounds + 1):
        # Spawn Judge
        prompt = prompt_builder.build_judge_prompt(
            deal_config=deal_config,
            round_num=round_num,
        )
        result = await runner.spawn("judge", prompt, max_turns=150, max_budget_usd=3.0)

        # Read scores
        scores = QualityScores.model_validate_json(
            (runner.run_dir / "judge" / "quality_scores.json").read_text()
        )

        # Check if all agents pass
        failing = [
            agent for agent, data in scores.agent_scores.items()
            if data["score"] < threshold
        ]

        if not failing:
            return scores  # All pass — proceed to deterministic merge

        if round_num == max_rounds:
            # Force finalization with quality caveats
            _apply_quality_caveats(runner.run_dir, failing, scores)
            return scores

        # Targeted re-analysis of failing agents
        for agent_name in failing:
            lowest_subjects = _get_lowest_scoring_subjects(
                scores, agent_name, limit=5
            )
            re_prompt = prompt_builder.build_re_analysis_prompt(
                agent_type=AgentType(agent_name),
                subjects=lowest_subjects,
                feedback=_extract_feedback(scores, agent_name),
            )
            await runner.spawn(
                f"{agent_name}_reanalysis",
                re_prompt,
                max_turns=100,
                max_budget_usd=3.0,
            )

    return scores
```

**Re-analysis prompt pattern**:
```
You are the {AGENT_TYPE} specialist performing a TARGETED RE-ANALYSIS.
The Judge found quality issues. RE-ANALYZE ONLY these subjects:
{list of up to 5 subjects}

SPECIFIC ISSUES TO FIX:
{paste relevant spot_check entries and contradiction details}

Write corrected findings to {RUN_DIR}/findings/{agent}/ (overwrite for these subjects only).
Do NOT re-analyze subjects not listed above.
```

**Blend formula** (Round 2 score): `final_score = 0.70 * round2_score + 0.30 * round1_score`

**Overall quality score blending** (used by the Judge to compute the final per-agent quality score from the four top-level dimensions):

```python
final_score = (
    (0.4 * citation_accuracy)
    + (0.3 * completeness)
    + (0.2 * consistency)
    + (0.1 * formatting)
)
```

This blending maps from the 5-dimension spot-check scores (section 10.4) to a single quality score: `citation_accuracy` = `citation_verification`, `completeness` = `completeness` + `contextual_validation` (averaged), `consistency` = `cross_agent_consistency`, `formatting` = derived from structural compliance checks.

**Force finalization**: If still below threshold after max rounds, add `"_quality_caveat"` metadata to every finding from failing agents. Proceed to deterministic merge with caveats.

---

## 11. Merge and Reporting (Deterministic)

> **Changed in v0.4.0**: The ReportingLead agent was removed and replaced by deterministic Python code. This eliminated LLM non-determinism from the merge/reporting phase and reduced per-run cost.

### 11.1 What Replaced ReportingLead

The merge, audit, and report generation steps that ReportingLead previously handled are now performed by deterministic Python modules with no LLM calls:

| Responsibility | Now Handled By | Module |
|---------------|---------------|--------|
| Pre-merge validation | `validation/pre_merge.py` | Validates specialist outputs before merge |
| Finding merge + deduplication | `reporting/merge.py` | 6-step merge protocol (semantic dedup via rapidfuzz) |
| Numerical manifest + audit | `reporting/merge.py` + `validation/` | 6-layer numerical audit |
| Excel report generation | `reporting/` | 14-sheet Excel from `report_schema.json` |
| Report diff | `reporting/` | Deterministic diff against prior run |

See `10-reporting.md` for the full merge protocol and `11-qa-validation.md` for validation details.

---

## 12. LLM Robustness Mitigations

> Full research context and rationale: `22-llm-robustness.md`

The following prompt-level mitigations are derived from the Addleshaw Goddard RAG report (2024, 510 CUAD contracts), Stanford legal AI hallucination study (Magesh et al., 2025), and Anthropic contextual retrieval research (2024). They are integrated directly into agent prompts and the Judge protocol.

### 12.1 Provision-Specific Extraction Templates

For provisions with high formulation variability (AG report F1 < 0.90), each specialist prompt includes per-provision extraction guidance with: legal definition, targeted extraction request, relevant keywords, common formulations, and explicit "If not found" instructions. See `22-llm-robustness.md` §4 for the full provision difficulty spectrum.

Provisions requiring templates per agent:
- **Legal**: Change of Control, Anti-Assignment, Cap on Liability, Exclusivity
- **Finance**: Cap on Liability, Insurance
- **Commercial**: Most Favored Nation, Exclusivity, Termination for Convenience
- **ProductTech**: (none above threshold — tech provisions not in AG study)

Total additional prompt overhead: ~2,700 tokens across all specialists.

### 12.2 Detection Method Enumeration

Agent prompts now list all 9 canonical `DetectionMethod` enum values with semantic descriptions to guide correct classification:
- `checklist` — standard document-pack checklist (expected docs missing)
- `cross_reference` — comparing data across documents (revenue mismatch, date conflict)
- `cross_reference_ghost` — entity referenced in data but has no folder/files in the data room
- `cross_reference_phantom` — contract/document referenced inside another document but not found
- `cross_reference_mismatch` — same data point differs between two sources
- `pattern_check` — structural/format pattern (missing signature, unusual clause)
- `governance_resolution` — governance graph analysis (unresolved governing doc)
- `file_inventory` — file-level inventory check (expected file type missing for subject)
- `file_read_failure` — extraction/read failure (corrupted PDF, empty extraction)

### 12.3 "Not Found" Protocol

Every specialist prompt includes an explicit escape valve for missing information. Without this, LLMs fabricate content rather than admitting absence (AG report finding). Full protocol in `22-llm-robustness.md` §6.

```
NOT FOUND PROTOCOL:
If you search for a specific clause or document and it genuinely does not exist,
record this as a gap with gap_type "Not_Found", NOT as a finding.
DO NOT fabricate clauses. DO NOT infer terms from general legal principles.
Include files_searched array listing every file you checked.
```

### 12.4 Self-Check Before Completion

Before writing the coverage manifest, each specialist executes a self-verification checklist (AG report: follow-up prompts improve accuracy by 9.2%):

```
BEFORE YOU WRITE YOUR COVERAGE MANIFEST:
1. For each P0: re-read the cited section. Is the quote exact? Severity justified?
2. For each subject with zero findings: re-read their files.
3. For each subject with only P3 findings: did you overlook higher-severity issues?
4. Check: did you process ALL reference files listed in your prompt?
YOU MAY HAVE MISSED CRITICAL INFORMATION. Re-examine any subjects where you
produced fewer findings than expected relative to their file count.
```

### 12.5 Adversarial Follow-Up in Judge Protocol

The Judge's review of P0 and P1 findings includes an adversarial re-check step (extends §10.4):

```
For each P0/P1 finding:
1. Read the source document section cited by the agent
2. Ask: "Is there another reasonable interpretation of this clause?"
3. Ask: "Did the agent miss qualifiers, exceptions, or carve-outs?"
4. Check: Does the severity match the actual contractual language?
Go back and re-examine surrounding paragraphs. Clauses often have qualifiers
in preceding or following subsections that materially change severity.
```

### 12.6 Lost-in-the-Middle Prompt Ordering

Agent prompt sections are ordered to place critical content in high-attention zones (beginning and end) and variable data in the middle:

```
[START — high attention]  Role, deal context, specialist focus, strict output rules
[MIDDLE — lower attention] Subject list, subject-mention index, reference file texts
[END — high attention]    Domain rules, output schema, manifest requirement, key rules repeated
```

### 12.7 Large File Handling

Files extracting to >120KB text are flagged in the agent prompt. Agents are instructed to use Grep for targeted keyword search rather than Read for full content, preventing context exhaustion:

```
LARGE FILES (use Grep, not Read):
  - _dd/forensic-dd/index/text/Master_Agreement_v3.pdf.md (245KB)
```

### 12.8 Post-Hoc Severity Recalibration

Despite rubric guidance, LLM agents still over-flag certain clause types (e.g., competitor-only CoC as P0, standard auditor independence as P0). A deterministic recalibration step in `computed_metrics.py` corrects these patterns after merge, before metrics computation and report rendering. Rules are defined in `_RECALIBRATION_RULES`. See `10-reporting.md` §Severity Recalibration for the full rule list and behavior.

---

## 13. Web Research Integration

When web research tools are included in the agent prompt (via `execution.web_research_enabled` in deal-config.json), specialists may use google-researcher-mcp tools for:

- Verifying counterparty claims (e.g., "SOC 2 certified" — check public evidence)
- Looking up public company info (M&A events, name changes, subsidiaries)
- Understanding industry-standard contracting patterns
- Cross-checking regulatory requirements mentioned in contracts

**Security**: Web research tools are disabled by default for specialist agents. If enabled via `deal-config.json` (`execution.web_research_enabled`), the `path_guard` hook restricts web tool usage to the Judge agent only. Specialists operate exclusively on data room contents to prevent hallucination from external sources.

**Rules for web research findings**:
- Citation `source_type` MUST be `"web_research"` with `access_date` field
- Confidence is always `"low"` unless corroborated by a data room document
- Web findings are supplementary — they never override data room evidence
- Mark all web-sourced claims with "needs confirmation" in the description

---

## 14. Agent Lifecycle Summary

```
Pipeline step 14: PromptBuilder constructs 4 specialist prompts
                   ↓
Pipeline step 15: route_references() assigns reference files to agents
                   ↓
Pipeline step 16: spawn_all_specialists() — 4 agents run in parallel via asyncio.gather
                   ↓
Pipeline step 17: Coverage gate validates all subjects have output from all 4 agents
                   ↓
Pipeline step 18: [IF INCREMENTAL] Merge new findings + carry forward unchanged
                   ↓
Pipeline step 19: [IF JUDGE] Spawn Judge agent
                   ↓
Pipeline step 20: [IF JUDGE] Judge samples, spot-checks, scores
                   ↓
Pipeline step 21: [IF JUDGE] Re-spawn failing agents with targeted feedback
                   ↓
Pipeline step 22: [IF JUDGE] Judge round 2 review, force finalization if still < threshold
                   ↓
Pipeline step 23: Deterministic pre-merge validation (validation/pre_merge.py)
                   ↓
Pipeline steps 24-31: Deterministic merge, audit, Excel generation, validation (reporting/merge.py + validation/)
```

**Error recovery**: Any agent spawn failure triggers `spawn_with_retry` from `12-error-recovery.md`. Maximum 3 retries per agent. Partial failures (some subjects missing) trigger targeted re-spawn for the missing subset only.
