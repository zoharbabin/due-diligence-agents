from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SeverityColor(BaseModel):
    """Color definition for a severity level."""

    bg: str  # Hex color code
    font: str  # Hex color code


class GlobalFormatting(BaseModel):
    """Global Excel formatting settings. From report_schema.json."""

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
    severity_colors: dict[str, SeverityColor] = Field(default_factory=dict)
    status_colors: dict[str, SeverityColor] = Field(default_factory=dict)


class ColumnDef(BaseModel):
    """Single column definition within a sheet. From report_schema.json."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    key: str
    type: str  # string, integer, date, currency, percentage, etc.
    width: int = 20
    format: str | None = None  # Excel format string
    activation_condition: str | None = None
    field_mapping: str | None = Field(default=None, alias="_field_mapping")
    note: str | None = Field(default=None, alias="_note")
    algorithm: str | None = Field(default=None, alias="_algorithm")
    derivation: str | None = Field(default=None, alias="_derivation")


class SortOrder(BaseModel):
    """Sort specification for a sheet."""

    column: str
    direction: str = "asc"  # "asc" or "desc"


class ConditionalFormat(BaseModel):
    """Conditional formatting rule for a column."""

    column: str
    rule: str  # e.g., "> 0", "== P0", "contains active"
    format: SeverityColor


class SummaryFormulaEntry(BaseModel):
    """Individual formula entry within a summary row."""

    column: str
    value: str | None = None  # Static text value
    formula: str | None = None  # Pseudo-formula (SUM, COUNTIF, etc.)


class SheetDef(BaseModel):
    """
    Complete sheet definition. From report_schema.json.
    Each sheet has columns, sort order, conditional formatting, and activation rules.
    """

    model_config = ConfigDict(populate_by_name=True)

    name: str
    required: bool = True
    activation_condition: str = "always"
    description: str = ""
    source: str = ""
    source_note: str | None = Field(default=None, alias="_source_note")
    field_mapping: str | None = Field(default=None, alias="_field_mapping")
    row_rule: str = ""
    columns: list[ColumnDef] = Field(default_factory=list)
    sort_order: list[SortOrder] = Field(default_factory=list)
    conditional_formatting: list[ConditionalFormat] = Field(default_factory=list)
    summary_formulas: dict[str, list[SummaryFormulaEntry]] = Field(default_factory=dict)


class ReportSchema(BaseModel):
    """
    Machine-readable report schema. Loaded from report_schema.json.
    From reporting-protocol.md section 3.
    """

    schema_version: str  # Semver
    description: str = ""
    global_formatting: GlobalFormatting = Field(default_factory=GlobalFormatting)
    sheets: list[SheetDef] = Field(default_factory=list)


class ReportDiffChange(BaseModel):
    """Single change entry in the report diff. From reporting-protocol.md section 4."""

    change_type: str  # new_finding, resolved_finding,
    # changed_severity, new_gap, resolved_gap,
    # new_customer, removed_customer
    customer: str
    finding_summary: str = ""
    prior_severity: str | None = None
    current_severity: str | None = None
    details: str = ""


class ReportDiffSummary(BaseModel):
    """Summary counts for the report diff."""

    new_findings: int = 0
    resolved_findings: int = 0
    changed_severity: int = 0
    new_gaps: int = 0
    resolved_gaps: int = 0
    new_customers: int = 0
    removed_customers: int = 0


class ReportDiff(BaseModel):
    """
    Report diff comparing current vs prior run.
    Written to {RUN_DIR}/report_diff.json.
    From reporting-protocol.md section 4.

    Both current_run_id and prior_run_id are required so that diffs
    can be traced back to specific runs in the run history.
    """

    current_run_id: str = Field(description="Run ID of the current (newer) run")
    prior_run_id: str = Field(description="Run ID of the prior (older) run being compared against")
    summary: ReportDiffSummary = Field(default_factory=ReportDiffSummary)
    changes: list[ReportDiffChange] = Field(default_factory=list)


class ContractDateReconciliationEntry(BaseModel):
    """
    Single customer entry in contract date reconciliation.
    From reporting-protocol.md section 5.
    """

    customer: str
    database_end_date: str = ""  # YYYY-MM-DD
    actual_end_date: str = ""  # YYYY-MM-DD
    arr: float = 0.0
    status: str = ""  # Active-Database Stale, Active-Auto-Renewal,
    # Likely Active-Needs Confirmation,
    # Expired-Confirmed, Expired-No Contracts
    evidence: str = ""
    evidence_file: str = ""


class ContractDateReconciliation(BaseModel):
    """
    Complete contract date reconciliation document.
    Written to {RUN_DIR}/contract_date_reconciliation.json.
    From SKILL.md section 5.
    """

    run_id: str
    generated_at: str  # ISO-8601
    entries: list[ContractDateReconciliationEntry] = Field(default_factory=list)
    total_reclassified_arr: float = 0.0
    total_expired_arr: float = 0.0
