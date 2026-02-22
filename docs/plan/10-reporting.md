# 10 — Reporting (Excel Generation, Merge/Dedup, Report Diff, Date Reconciliation)

The Reporting Lead is the final agent in the pipeline. It receives merged specialist findings, builds the numerical manifest, runs QA checks, generates the 14-sheet Excel report from `report_schema.json`, and produces the report diff. This document specifies every data transformation between raw agent outputs and the final Excel file.

---

## Merge and Deduplicate Protocol

Before any report generation, the Reporting Lead merges findings from all 4 specialist agents per customer. This is a 6-step protocol executed in order.

### Step 1 -- Collect

For each customer in `customers.csv`, read:
- `{RUN_DIR}/findings/legal/{customer_safe_name}.json`
- `{RUN_DIR}/findings/finance/{customer_safe_name}.json`
- `{RUN_DIR}/findings/commercial/{customer_safe_name}.json`
- `{RUN_DIR}/findings/producttech/{customer_safe_name}.json`

If any agent file is missing for a customer, the coverage gate (pipeline step 17) should have already caught it. If still missing at merge time, log a P1 gap and continue with available outputs.

### Step 2 -- Merge

Combine all findings from the 4 agent files into a single per-customer profile. Preserve the `agent` field on each finding for sheet routing.

### Step 3 -- Deduplicate

When multiple agents flagged the same issue (same clause reference, same file):
- **Keep** the finding with the highest severity
- **Keep** the finding with the most specific citation (longest `exact_quote`)
- **Record** which agents independently identified it (adds confidence weight)

Dedup matching key: `citations[0].source_path` + `citations[0].location` (clause/section reference). Two findings referencing the same clause in the same file are duplicates.

**Dedup tiebreaker**: When two agents report the same finding (matched by entity + document + issue type), the finding with the higher severity is kept. If severity is equal, the finding with more citations is kept. If still tied, the finding from the agent with the higher quality score (from Judge) is kept.

### Step 4 -- Cross-Validate

When agents disagree on severity for the same finding:
- **Escalate** to the higher severity
- **Note** the disagreement in finding metadata: `{"severity_disagreement": {"legal": "P2", "finance": "P1"}, "resolved_to": "P1"}`

### Step 5 -- Consolidate Governance

Use the Legal agent's governance graph as primary. If other agents discovered governance links that Legal missed, merge them into the consolidated graph. The Legal agent is authoritative for governance; other agents supplement.

### Step 6 -- Merge Gap Files

Collect gap files from all agents:
- `{RUN_DIR}/findings/{agent}/gaps/{customer_safe_name}.json` for each agent

Merge into `{RUN_DIR}/findings/merged/gaps/{customer_safe_name}.json`. Deduplicate gaps by `missing_item` -- keep the gap with the highest priority.

### Merge Output

Write each customer's merged output to `{RUN_DIR}/findings/merged/{customer_safe_name}.json`.

Write each customer's merged gaps to `{RUN_DIR}/findings/merged/gaps/{customer_safe_name}.json`.

```python
# src/dd_agents/reporting/merger.py

from pydantic import BaseModel, Field
from typing import Optional

class MergedCustomerOutput(BaseModel):
    """Schema for {RUN_DIR}/findings/merged/{customer_safe_name}.json"""

    findings: list[dict] = Field(
        description="Array conforming to finding.schema.json. "
        "Fields id, agent, skill, run_id, timestamp, analysis_unit "
        "added during merge."
    )
    cross_references: list[dict] = Field(
        default_factory=list,
        description="Union of cross-reference objects from all agents. "
        "Used by Data_Reconciliation sheet."
    )
    cross_reference_summary: dict = Field(
        default_factory=dict,
        description="Merged summary: reference_files_checked union, "
        "totals summed across agents."
    )
    governance_graph: dict = Field(
        default_factory=dict,
        description="Consolidated governance graph. Legal agent primary, "
        "others supplementary."
    )
    governance_resolved_pct: float = Field(
        ge=0.0, le=1.0,
        description="(files with governed_by in [file_path, 'SELF']) "
        "/ total_customer_files"
    )
```

```python
# src/dd_agents/reporting/merger.py (continued)

class MergeEngine:
    """Executes the 6-step merge/dedup protocol."""

    def __init__(self, run_dir: Path, customers: list[CustomerInfo]):
        self.run_dir = run_dir
        self.customers = customers
        self.agents = ["legal", "finance", "commercial", "producttech"]

    async def merge_all(self) -> MergeSummary:
        """Process all customers with per-customer write discipline."""
        merged_count = 0
        for customer in self.customers:
            await self._merge_customer(customer)
            merged_count += 1
            # Checkpoint after each customer -- do NOT buffer all in memory
            await self._write_checkpoint("merge_in_progress", merged_count)

        await self._write_checkpoint("merge_complete", merged_count)
        return MergeSummary(customers_merged=merged_count, ...)

    async def _merge_customer(self, customer: CustomerInfo) -> None:
        """Merge one customer and write immediately."""
        # Step 1: Collect
        agent_findings = {}
        for agent in self.agents:
            path = self.run_dir / "findings" / agent / f"{customer.safe_name}.json"
            if path.exists():
                agent_findings[agent] = json.loads(path.read_text())

        # Step 2: Merge into combined list
        all_findings = []
        for agent, data in agent_findings.items():
            for finding in data.get("findings", []):
                finding["agent"] = agent  # ensure agent field set
                all_findings.append(finding)

        # Step 3: Deduplicate (same clause + same file)
        deduped = self._deduplicate(all_findings)

        # Step 4: Cross-validate severity disagreements
        deduped = self._resolve_severity_disagreements(deduped)

        # Step 5: Consolidate governance
        governance = self._consolidate_governance(agent_findings)

        # Step 6: handled in merge_gaps_all()

        # Build merged output
        merged = MergedCustomerOutput(
            findings=deduped,
            cross_references=self._union_cross_refs(agent_findings),
            cross_reference_summary=self._merge_xref_summaries(agent_findings),
            governance_graph=governance,
            governance_resolved_pct=self._compute_gov_pct(governance, customer),
        )

        # Write immediately -- per-customer write discipline
        out = self.run_dir / "findings" / "merged" / f"{customer.safe_name}.json"
        out.write_text(merged.model_dump_json(indent=2))

    def _deduplicate(self, findings: list[dict]) -> list[dict]:
        """Dedup key: citations[0].source_path + citations[0].location."""
        groups: dict[str, list[dict]] = {}
        for f in findings:
            cit = f.get("citations", [{}])[0]
            key = (cit.get("source_path", ""), cit.get("location", ""))
            groups.setdefault(key, []).append(f)

        result = []
        for key, group in groups.items():
            if len(group) == 1:
                result.append(group[0])
            else:
                winner = self._pick_winner(group)
                result.append(winner)
        return result

    def _pick_winner(self, group: list[dict]) -> dict:
        """Highest severity, longest exact_quote. Record contributing agents."""
        SEVERITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        sorted_group = sorted(
            group,
            key=lambda f: (
                SEVERITY_RANK.get(f.get("severity", "P3"), 9),
                -len(f.get("citations", [{}])[0].get("exact_quote", "")),
            ),
        )
        winner = sorted_group[0]
        winner["metadata"] = winner.get("metadata", {})
        winner["metadata"]["contributing_agents"] = [
            f["agent"] for f in group
        ]
        return winner
```

---

## Excel Report Structure -- 14 Sheets

The Excel report is defined by `report_schema.json`. The generated `build_report.py` MUST load this schema via `json.load()` and MUST NOT hardcode sheet definitions, column lists, or sort orders.

### Sheet-to-Agent Routing Table

Findings are routed by the `agent` field, NOT by `category`. Category is a column within each sheet.

| Sheet | Filter Logic | Source |
|-------|-------------|--------|
| Summary | Aggregated counts per customer (all agents) | `merged/*.json` + `counts.json` |
| Wolf_Pack | `finding.severity in ['P0', 'P1']` from all agents | `merged/*.json` |
| Legal_Risks | `finding.agent == 'legal'` | `merged/*.json` |
| Commercial_Data | `finding.agent == 'commercial'` | `merged/*.json` |
| Financials | `finding.agent == 'finance'` | `merged/*.json` |
| Product_Scope | `finding.agent == 'producttech'` | `merged/*.json` |
| Data_Reconciliation | `cross_references[]` data from any agent | `merged/*.json` cross_references |
| Missing_Docs_Gaps | All gap files | `merged/gaps/*.json` |
| Contract_Date_Reconciliation | Conditional on `source_of_truth.customer_database` | `contract_date_reconciliation.json` |
| Reference_Files_Index | Always | `reference_files.json` |
| Entity_Resolution_Log | Always | `entity_matches.json` |
| Quality_Audit | Conditional on `judge.enabled` | `quality_scores.json` |
| Run_Diff | Conditional on prior run + `reporting.include_diff_sheet` | `report_diff.json` |
| _Metadata | Conditional on `reporting.include_metadata_sheet` | `deal-config.json` + manifest |

### Sheet Activation Conditions

Each sheet in `report_schema.json` has an `activation_condition` field. The `build_report.py` script MUST evaluate these conditions and skip sheets that are not activated:

- `"always"` -- always include (Summary, Wolf_Pack, Legal_Risks, Commercial_Data, Financials, Product_Scope, Data_Reconciliation, Missing_Docs_Gaps, Reference_Files_Index, Entity_Resolution_Log)
- `"judge.enabled in deal-config.json"` -- Quality_Audit
- `"source_of_truth.customer_database exists in deal-config.json"` -- Contract_Date_Reconciliation
- `"prior run exists AND reporting.include_diff_sheet is true"` -- Run_Diff
- `"reporting.include_metadata_sheet is true"` -- _Metadata

### Overall Risk Rating Algorithm

Used in the Summary sheet `overall_risk_rating` column. The algorithm considers BOTH finding severity AND gap priority:

```python
# src/dd_agents/reporting/risk_rating.py

def compute_overall_risk(
    findings: list[dict],
    gaps: list[dict],
) -> str:
    """
    Rating algorithm (considers findings AND gaps):
    - Critical: any P0 finding OR any P0 gap
    - High: any P1 finding or P1 gap, no P0s
    - Medium: any P2 finding or P2 gap, no P0/P1
    - Low: P3 only
    - Clean: no findings except domain_reviewed_no_issues, and no gaps
    """
    severities = {f["severity"] for f in findings
                  if f.get("category") != "domain_reviewed_no_issues"}
    gap_priorities = {g["priority"] for g in gaps}
    all_levels = severities | gap_priorities

    if "P0" in all_levels:
        return "Critical"
    if "P1" in all_levels:
        return "High"
    if "P2" in all_levels:
        return "Medium"
    if "P3" in all_levels:
        return "Low"
    return "Clean"
```

Rationale: gap priorities carry the same materiality signal as finding severities. A P0 gap (e.g., ghost customer with $500K ARR and no contracts) is a deal-stopper just like a P0 finding.

---

## Report Schema System

### Schema Loading

```python
# src/dd_agents/reporting/schema_loader.py

import json
from pathlib import Path
from pydantic import BaseModel, Field

class SheetColumn(BaseModel):
    name: str
    key: str
    type: str                               # string, integer, date, currency, percentage, etc.
    width: int
    format: str = ""
    activation_condition: str = "always"     # column-level activation (e.g., Judge columns)

class SheetDefinition(BaseModel):
    name: str
    required: bool
    activation_condition: str
    description: str
    source: str
    row_rule: str
    columns: list[SheetColumn]
    sort_order: list[dict] = Field(default_factory=list)
    conditional_formatting: list[dict] = Field(default_factory=list)
    summary_formulas: dict = Field(default_factory=dict)

class GlobalFormatting(BaseModel):
    header_bold: bool = True
    header_bg_color: str = "#4472C4"
    header_font_color: str = "#FFFFFF"
    header_font_size: int = 11
    body_font_size: int = 10
    freeze_panes: bool = True
    freeze_row: int = 1
    auto_filter: bool = True
    auto_fit_widths: bool = True
    max_column_width: int = 80
    severity_colors: dict[str, dict] = Field(default_factory=dict)
    status_colors: dict[str, dict] = Field(default_factory=dict)

class ReportSchema(BaseModel):
    schema_version: str
    description: str
    global_formatting: GlobalFormatting
    sheets: list[SheetDefinition]

def load_report_schema(
    deal_config: dict,
    default_path: Path = Path("report_schema.json"),
) -> ReportSchema:
    """
    Load report_schema.json at startup.
    If deal-config has reporting.report_schema_override, use that path instead.
    """
    override = (
        deal_config
        .get("reporting", {})
        .get("report_schema_override")
    )
    schema_path = Path(override) if override else default_path
    with open(schema_path) as f:
        raw = json.load(f)
    return ReportSchema.model_validate(raw)
```

### Schema-Driven Generation Rules

These 5 rules are enforced at QA check 8k. Violations are QA failures:

1. **Schema-loaded, not hardcoded.** The generated `build_report.py` MUST `import json` and `json.load()` the schema file. It MUST NOT hardcode sheet definitions, column lists, or sort orders.

2. **Sheet fidelity.** For each sheet in `report_schema.json -> sheets[]`, the script MUST create a worksheet with the exact sheet name, columns (in order), column widths, sort order, and conditional formatting as defined in the schema.

3. **Activation conditions.** For each sheet's `activation` condition, the script MUST check the condition and skip the sheet if not met.

4. **Summary formulas.** `summary_formulas` defined in the schema (COUNTIF, COUNTA, COUNTA_UNIQUE, SUM, SUMIF) MUST be implemented as actual computed values in summary rows. These are pseudo-formula notation -- the script translates them into Python/openpyxl operations.

5. **No phantom data.** The script MUST NOT hardcode data values (financial figures, customer names, finding counts). ALL data comes from the JSON source files listed in the schema's `source` field per sheet.

### Data Source Files

The generated `build_report.py` reads these files:

| File | Used By |
|------|---------|
| `{RUN_DIR}/findings/merged/*.json` | Summary, Wolf_Pack, Legal_Risks, Commercial_Data, Financials, Product_Scope, Data_Reconciliation |
| `{RUN_DIR}/findings/merged/gaps/*.json` | Missing_Docs_Gaps, Summary (gap counts) |
| `_dd/forensic-dd/inventory/counts.json` | Summary (file counts) |
| `_dd/forensic-dd/inventory/reference_files.json` | Reference_Files_Index |
| `_dd/forensic-dd/inventory/entity_matches.json` | Entity_Resolution_Log |
| `_dd/forensic-dd/inventory/customers.csv` | Summary (customer list) |
| `{RUN_DIR}/numerical_manifest.json` | _Metadata (counts) |
| `{RUN_DIR}/judge/quality_scores.json` | Quality_Audit, Summary (judge scores) -- single file containing `spot_checks` and `contradictions` arrays inline |
| `{RUN_DIR}/report_diff.json` | Run_Diff |
| `{RUN_DIR}/contract_date_reconciliation.json` | Contract_Date_Reconciliation |
| `deal-config.json` | _Metadata (buyer, target, execution mode) |

### Schema Self-Validation (Post-Generation)

After Excel generation, validate the output against `report_schema.json`:
- All sheets whose activation condition is met exist in the workbook
- Column names in each sheet match the schema column definitions (in order)
- Sort orders are applied correctly
- Conditional formatting rules are present
- Summary formula rows exist where defined

```python
# src/dd_agents/reporting/schema_validator.py

class SchemaValidator:
    """Post-generation validation: Excel output matches report_schema.json."""

    def __init__(self, schema: ReportSchema, workbook_path: Path):
        self.schema = schema
        self.wb_path = workbook_path

    def validate(self, context: ActivationContext) -> ValidationResult:
        """Check all schema constraints against generated Excel."""
        import openpyxl
        wb = openpyxl.load_workbook(self.wb_path)

        errors = []
        for sheet_def in self.schema.sheets:
            if not self._is_activated(sheet_def, context):
                if sheet_def.name in wb.sheetnames:
                    errors.append(f"Sheet {sheet_def.name} present but "
                                  f"activation condition not met")
                continue

            if sheet_def.name not in wb.sheetnames:
                errors.append(f"Missing required sheet: {sheet_def.name}")
                continue

            ws = wb[sheet_def.name]
            self._validate_columns(sheet_def, ws, errors)
            self._validate_summary_rows(sheet_def, ws, errors)

        return ValidationResult(
            passed=len(errors) == 0,
            errors=errors,
        )
```

---

## Excel Formatting

All formatting is defined in `report_schema.json -> global_formatting` and applied uniformly by `build_report.py`.

### Global Formatting

| Property | Value |
|----------|-------|
| Header background | `#4472C4` (bold, white text) |
| Header font size | 11 |
| Body font size | 10 |
| Freeze panes | Row 1 (all sheets) |
| Auto-filter | All columns (all sheets) |
| Auto-fit widths | Enabled, max 80 characters |

### Severity Colors

| Severity | Background | Font |
|----------|-----------|------|
| P0 | `#FF0000` (red) | `#FFFFFF` (white) |
| P1 | `#FFA500` (orange) | `#000000` (black) |
| P2 | `#FFFF00` (yellow) | `#000000` (black) |
| P3 | `#FFFFFF` (white) | `#000000` (black) |

### Status Colors (Contract Date Reconciliation)

| Status | Background | Font |
|--------|-----------|------|
| Active | `#C6EFCE` (green) | `#006100` |
| Expired | `#FFC7CE` (red) | `#9C0006` |
| Needs Confirmation | `#FFEB9C` (yellow) | `#9C5700` |

```python
# src/dd_agents/reporting/excel_writer.py

from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

class ExcelFormatter:
    """Applies global_formatting from report_schema.json."""

    def __init__(self, formatting: GlobalFormatting):
        self.fmt = formatting
        self.header_fill = PatternFill(
            start_color=formatting.header_bg_color.lstrip("#"),
            end_color=formatting.header_bg_color.lstrip("#"),
            fill_type="solid",
        )
        self.header_font = Font(
            bold=formatting.header_bold,
            color=formatting.header_font_color.lstrip("#"),
            size=formatting.header_font_size,
        )
        self.body_font = Font(size=formatting.body_font_size)

    def apply_headers(self, ws, columns: list[SheetColumn]) -> None:
        """Write header row with formatting."""
        for col_idx, col_def in enumerate(columns, start=1):
            cell = ws.cell(row=1, column=col_idx, value=col_def.name)
            cell.fill = self.header_fill
            cell.font = self.header_font

    def apply_freeze_panes(self, ws) -> None:
        if self.fmt.freeze_panes:
            ws.freeze_panes = f"A{self.fmt.freeze_row + 1}"

    def apply_auto_filter(self, ws) -> None:
        if self.fmt.auto_filter and ws.max_row > 1:
            last_col = get_column_letter(ws.max_column)
            ws.auto_filter.ref = f"A1:{last_col}{ws.max_row}"

    def apply_column_widths(self, ws, columns: list[SheetColumn]) -> None:
        for col_idx, col_def in enumerate(columns, start=1):
            width = min(col_def.width, self.fmt.max_column_width)
            ws.column_dimensions[get_column_letter(col_idx)].width = width

    def apply_severity_formatting(self, ws, severity_col: int) -> None:
        """Color cells based on severity value."""
        for row in range(2, ws.max_row + 1):
            cell = ws.cell(row=row, column=severity_col)
            severity = str(cell.value)
            if severity in self.fmt.severity_colors:
                colors = self.fmt.severity_colors[severity]
                cell.fill = PatternFill(
                    start_color=colors["bg"].lstrip("#"),
                    end_color=colors["bg"].lstrip("#"),
                    fill_type="solid",
                )
                cell.font = Font(
                    size=self.fmt.body_font_size,
                    color=colors["font"].lstrip("#"),
                )
```

---

## Report Diff Protocol

When a prior run exists, generate a diff comparing current findings against the most recent prior run.

### Diff Algorithm

```python
# src/dd_agents/reporting/diff_engine.py

from dataclasses import dataclass
from enum import Enum

class ChangeType(str, Enum):
    NEW_FINDING = "new_finding"
    RESOLVED_FINDING = "resolved_finding"
    CHANGED_SEVERITY = "changed_severity"
    NEW_GAP = "new_gap"
    RESOLVED_GAP = "resolved_gap"
    NEW_CUSTOMER = "new_customer"
    REMOVED_CUSTOMER = "removed_customer"

@dataclass
class DiffChange:
    change_type: ChangeType
    customer: str
    finding_summary: str = ""
    prior_severity: str | None = None
    current_severity: str | None = None
    details: str = ""

class ReportDiffEngine:
    """Compare current run findings against prior run."""

    def compute_diff(
        self,
        current_findings: dict[str, list[dict]],   # customer -> findings
        prior_findings: dict[str, list[dict]],
        current_gaps: dict[str, list[dict]],
        prior_gaps: dict[str, list[dict]],
    ) -> list[DiffChange]:
        changes = []

        # Customer-level changes
        current_customers = set(current_findings.keys())
        prior_customers = set(prior_findings.keys())

        for c in current_customers - prior_customers:
            changes.append(DiffChange(
                change_type=ChangeType.NEW_CUSTOMER,
                customer=c,
                details=f"New customer in current run",
            ))

        for c in prior_customers - current_customers:
            changes.append(DiffChange(
                change_type=ChangeType.REMOVED_CUSTOMER,
                customer=c,
                details=f"Customer removed from current run",
            ))

        # Finding-level changes (shared customers)
        for customer in current_customers & prior_customers:
            changes.extend(self._diff_findings(
                customer,
                current_findings[customer],
                prior_findings[customer],
            ))
            changes.extend(self._diff_gaps(
                customer,
                current_gaps.get(customer, []),
                prior_gaps.get(customer, []),
            ))

        return changes

    def _finding_match_key(self, finding: dict) -> str:
        """Match key: customer + category + citations[0].location"""
        cit = finding.get("citations", [{}])[0]
        return f"{finding.get('category', '')}|{cit.get('location', '')}"

    def _gap_match_key(self, gap: dict) -> str:
        """Gap match key: gap_type + missing_item (normalized)."""
        missing = gap.get("missing_item", "").lower().rstrip(".,;:!?")
        return f"{gap.get('gap_type', '')}|{missing}"

    def _diff_findings(
        self, customer: str, current: list[dict], prior: list[dict]
    ) -> list[DiffChange]:
        changes = []
        current_by_key = {self._finding_match_key(f): f for f in current}
        prior_by_key = {self._finding_match_key(f): f for f in prior}

        for key, finding in current_by_key.items():
            if key not in prior_by_key:
                changes.append(DiffChange(
                    change_type=ChangeType.NEW_FINDING,
                    customer=customer,
                    finding_summary=finding.get("title", ""),
                    current_severity=finding.get("severity"),
                    details=f"New finding in current run",
                ))
            else:
                prior_f = prior_by_key[key]
                if finding.get("severity") != prior_f.get("severity"):
                    changes.append(DiffChange(
                        change_type=ChangeType.CHANGED_SEVERITY,
                        customer=customer,
                        finding_summary=finding.get("title", ""),
                        prior_severity=prior_f.get("severity"),
                        current_severity=finding.get("severity"),
                    ))

        for key, finding in prior_by_key.items():
            if key not in current_by_key:
                changes.append(DiffChange(
                    change_type=ChangeType.RESOLVED_FINDING,
                    customer=customer,
                    finding_summary=finding.get("title", ""),
                    prior_severity=finding.get("severity"),
                ))

        return changes

    def _diff_gaps(
        self, customer: str, current: list[dict], prior: list[dict]
    ) -> list[DiffChange]:
        changes = []
        current_keys = {self._gap_match_key(g) for g in current}
        prior_keys = {self._gap_match_key(g) for g in prior}

        for g in current:
            if self._gap_match_key(g) not in prior_keys:
                changes.append(DiffChange(
                    change_type=ChangeType.NEW_GAP,
                    customer=customer,
                    finding_summary=g.get("missing_item", ""),
                    details=f"gap_type={g.get('gap_type', '')}",
                ))

        for g in prior:
            if self._gap_match_key(g) not in current_keys:
                changes.append(DiffChange(
                    change_type=ChangeType.RESOLVED_GAP,
                    customer=customer,
                    finding_summary=g.get("missing_item", ""),
                    details=f"gap_type={g.get('gap_type', '')}",
                ))

        return changes
```

### Diff Output Schema

Write `{RUN_DIR}/report_diff.json`:

```json
{
  "run_id": "20250220_091500",
  "prior_run_id": "20250218_143000",
  "summary": {
    "new_findings": 12,
    "resolved_findings": 3,
    "changed_severity": 5,
    "new_gaps": 8,
    "resolved_gaps": 2,
    "new_customers": 2,
    "removed_customers": 1
  },
  "changes": [
    {
      "change_type": "new_finding",
      "customer": "Acme Corp",
      "finding_summary": "Change of control clause requires 60-day written notice",
      "prior_severity": null,
      "current_severity": "P1",
      "details": "Found in newly added MSA Amendment 3"
    },
    {
      "change_type": "changed_severity",
      "customer": "Beta Inc",
      "finding_summary": "Uncapped indemnification clause in MSA Section 8.2",
      "prior_severity": "P1",
      "current_severity": "P0",
      "details": "Escalated after Amendment 2 removed the liability cap"
    }
  ]
}
```

The Run_Diff sheet is populated from this file. If no prior run exists, omit the sheet or include a single row: "First run -- no prior data for comparison."

---

## Contract Date Reconciliation

### Activation

This protocol runs ONLY when `source_of_truth.customer_database` exists in `deal-config.json`. It runs during the inventory phase (before agents spawn) -- pipeline step 11.

### Reconciliation Protocol

Contract date reconciliation extracts dates using regex patterns (ISO 8601, US date formats, written dates) from extracted text, then validates by cross-referencing dates across related documents (e.g., MSA effective date should precede SOW start date).

For every customer where the database shows `contract_end < current_date` AND `ARR > 0`:

1. Classify as "Database-Expired"
2. Search the data room for renewal evidence (order forms, auto-renewal clauses, POs)
3. Determine actual status using auto-renewal detection: check MSA for auto-renewal clause, notice period, and termination evidence

### 5 Status Classifications

| Status | Meaning |
|--------|---------|
| `Active-Database Stale` | Contract is active; database end date is outdated |
| `Active-Auto-Renewal` | Contract auto-renewed; database does not reflect renewal |
| `Likely Active` | Evidence suggests active but needs confirmation |
| `Expired-Confirmed` | Contract genuinely expired; confirmed by documentation |
| `Expired-No Contracts` | No contract documents found in data room |

### Output Schema

Write `{RUN_DIR}/contract_date_reconciliation.json`:

```python
# src/dd_agents/reporting/date_reconciliation.py

class ReconciliationStatus(str, Enum):
    ACTIVE_DB_STALE = "Active-Database Stale"
    ACTIVE_AUTO_RENEWAL = "Active-Auto-Renewal"
    LIKELY_ACTIVE = "Likely Active"
    EXPIRED_CONFIRMED = "Expired-Confirmed"
    EXPIRED_NO_CONTRACTS = "Expired-No Contracts"

class ReconciliationEntry(BaseModel):
    customer: str
    database_end_date: str            # YYYY-MM-DD
    actual_end_date: str | None       # YYYY-MM-DD or null
    arr: float                        # Annual Recurring Revenue
    status: ReconciliationStatus
    evidence: str                     # description of evidence
    evidence_file: str | None         # file path if applicable

class ContractDateReconciliation(BaseModel):
    generated_at: str                 # ISO-8601
    run_id: str
    total_reconciled: int
    entries: list[ReconciliationEntry]
    summary: ReconciliationSummary

class ReconciliationSummary(BaseModel):
    total_reclassified_arr: float     # ARR for Active-* statuses
    total_expired_arr: float          # ARR for Expired-* statuses
    by_status: dict[str, int]         # count per status
```

### Excel Sheet Specification

The Contract_Date_Reconciliation sheet uses these color rules:

| Condition | Background | Font |
|-----------|-----------|------|
| Status contains "active" | `#C6EFCE` (green) | `#006100` |
| Status contains "expired" | `#FFC7CE` (red) | `#9C0006` |
| Status contains "confirmation" | `#FFEB9C` (yellow) | `#9C5700` |

Sort: Status ascending (reclassified first), then customer name ascending.

Summary rows at bottom:
- Total reclassified ARR (sum of ARR where status contains "active")
- Total expired ARR (sum of ARR where status contains "expired")

### Materiality

Stale dates directly impact valuation:
- **Undervaluation**: Active contracts counted as churned
- **Overvaluation**: Expired contracts carrying ARR
- **Consent risk**: Miscounting contracts requiring change-of-control consent

The total ARR impact is logged as a P1 finding.

---

## Reporting Lead Checkpointing

The Reporting Lead processes many customers sequentially and may approach context limits. Checkpointing prevents data loss from context exhaustion.

### Checkpoint Protocol

```python
# src/dd_agents/reporting/checkpoint.py

class ReportCheckpoint(BaseModel):
    phase: str                        # current phase name
    customers_merged: int = 0
    gaps_merged: int = 0
    numerical_manifest_built: bool = False
    qa_checks_complete: bool = False
    excel_generated: bool = False
    timestamp: str                    # ISO-8601

CHECKPOINT_PATH = "{RUN_DIR}/report/checkpoint.json"
```

### Write Discipline

1. **After merge/dedup (step 24)**: Write `{RUN_DIR}/findings/merged/` files immediately after each customer. Do not accumulate all work in memory.
2. **After gap merge (step 25)**: Write gap files immediately.
3. **After numerical manifest (step 26)**: Write `{RUN_DIR}/numerical_manifest.json` immediately.
4. **Per-customer write discipline**: When merging findings, write each customer's merged JSON as soon as that customer is complete.
5. **Checkpoint file**: Write `{RUN_DIR}/report/checkpoint.json` after each major phase.

### Context Budget for Large Deal Rooms

When processing >100 customers, batch processing in groups of 50 customers for the merge phase. Write intermediate results between batches.

```python
# src/dd_agents/reporting/batch_processor.py

BATCH_SIZE = 50  # customers per merge batch

class BatchMergeProcessor:

    async def merge_in_batches(
        self, customers: list[CustomerInfo]
    ) -> None:
        for batch_start in range(0, len(customers), BATCH_SIZE):
            batch = customers[batch_start:batch_start + BATCH_SIZE]
            for customer in batch:
                await self.merge_engine.merge_customer(customer)
            # Write checkpoint between batches
            await self.write_checkpoint(
                phase="merge_batch_complete",
                customers_merged=batch_start + len(batch),
            )
```

### Resumption

If the Reporting Lead is re-spawned after failure (error recovery), it reads the checkpoint file and resumes from the last completed phase rather than restarting from scratch.

---

## Report Generation Pipeline

The complete reporting pipeline executes as pipeline steps 23-31:

| Pipeline Step | Action | Output |
|---------------|--------|--------|
| 23 | Spawn Reporting Lead | -- |
| 24 | Merge and deduplicate findings | `{RUN_DIR}/findings/merged/{customer_safe_name}.json` |
| 25 | Merge gap files | `{RUN_DIR}/findings/merged/gaps/{customer_safe_name}.json` |
| 26 | Build numerical manifest | `{RUN_DIR}/numerical_manifest.json` |
| 27 | Numerical audit (5-layer, BLOCKING) | Pass/fail |
| 28 | Full QA audit (fail-closed) | `{RUN_DIR}/audit.json` |
| 29 | Build report diff (if prior run) | `{RUN_DIR}/report_diff.json` |
| 30 | Generate Excel from schema | `{RUN_DIR}/report/Due_Diligence_Report_{run_id}.xlsx` |
| 31 | Post-generation validation | Schema validation + Layer 4 cross-format parity |

```python
# src/dd_agents/reporting/pipeline.py

class ReportingPipeline:
    """Orchestrates the full reporting sequence (steps 23-31)."""

    def __init__(
        self,
        run_dir: Path,
        schema: ReportSchema,
        deal_config: dict,
        state: PipelineState,
    ):
        self.run_dir = run_dir
        self.schema = schema
        self.deal_config = deal_config
        self.state = state
        self.merge_engine = MergeEngine(run_dir, state.customers)
        self.manifest_builder = NumericalManifestBuilder(run_dir)
        self.validator = NumericalValidator(run_dir)
        self.qa_runner = QARunner(run_dir, deal_config)
        self.diff_engine = ReportDiffEngine()
        self.excel_writer = ExcelReportWriter(run_dir, schema)

    async def execute(self) -> ReportingResult:
        # Step 24: Merge/dedup
        merge_result = await self.merge_engine.merge_all()

        # Step 25: Merge gaps
        await self.merge_engine.merge_gaps_all()

        # Step 26: Numerical manifest
        manifest = await self.manifest_builder.build()

        # Step 27: Numerical audit (BLOCKING)
        audit_result = await self.validator.validate_layers_1_3_5(manifest)
        if not audit_result.passed:
            manifest = await self.validator.fix_and_revalidate(manifest)
            if not manifest:
                raise BlockingGateFailure("Numerical audit failed")

        # Step 28: Full QA
        qa_result = await self.qa_runner.run_all_checks()
        if not qa_result.audit_passed:
            raise BlockingGateFailure(f"QA failed: {qa_result.failures}")

        # Step 29: Report diff
        if self.state.prior_run_id:
            diff = self.diff_engine.compute_diff(...)
            self._write_diff(diff)

        # Step 30: Generate Excel
        await self.excel_writer.generate(manifest, qa_result)

        # Step 31: Post-generation validation
        schema_result = SchemaValidator(self.schema, self.excel_path).validate(...)
        layer4_result = await self.validator.validate_layer_4(manifest)
        if not schema_result.passed or not layer4_result.passed:
            await self.excel_writer.regenerate_and_revalidate()

        return ReportingResult(success=True, report_path=self.excel_path)
```

---

## Non-Determinism Caveat

The `build_report.py` script is generated by the Reporting Lead agent from the schema definition. While the goal is deterministic output (same data + same schema = identical Excel), the script generation itself is LLM-based and may produce structurally equivalent but textually different code across runs. The post-generation schema validation (QA check 8k) mitigates this by verifying the output matches the schema regardless of script implementation details.

**Non-determinism handling**: LLM-generated content (finding descriptions, severity rationale) is inherently non-deterministic. Validation gates check structural correctness (schema compliance, required fields, numerical consistency) rather than textual identity. Report diff compares findings by `finding_id` and checks for structural changes (added/removed/severity-changed), not prose differences.

In the SDK migration, `build_report.py` generation is replaced by the `ExcelReportWriter` class which directly implements the schema-driven generation rules in deterministic Python code.
