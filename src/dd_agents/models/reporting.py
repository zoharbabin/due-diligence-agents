"""Pydantic models for Excel report schema, formatting, diffs, and contract date reconciliation."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SeverityColor(BaseModel):
    """Color definition for a severity level."""

    bg: str = Field(description="Hex background color code (e.g. '#FF0000')")
    font: str = Field(description="Hex font color code (e.g. '#FFFFFF')")


class GlobalFormatting(BaseModel):
    """Global Excel formatting settings. From report_schema.json."""

    header_bold: bool = Field(default=True, description="Whether header row text is bold")
    header_bg_color: str = Field(default="#4472C4", description="Hex background color for header row")
    header_font_color: str = Field(default="#FFFFFF", description="Hex font color for header row")
    header_font_size: int = Field(default=11, description="Font size in points for header row")
    body_font_size: int = Field(default=10, description="Font size in points for body rows")
    freeze_panes: bool = Field(default=True, description="Whether to freeze the header row")
    freeze_row: int = Field(default=1, description="Row number to freeze at (1 = header only)")
    auto_filter: bool = Field(default=True, description="Whether to enable auto-filter on columns")
    auto_fit_widths: bool = Field(default=True, description="Whether to auto-fit column widths to content")
    max_column_width: int = Field(default=80, description="Maximum column width in characters")
    severity_colors: dict[str, SeverityColor] = Field(
        default_factory=dict, description="Color mapping for severity levels (P0-P3)"
    )
    status_colors: dict[str, SeverityColor] = Field(default_factory=dict, description="Color mapping for status values")


class ColumnDef(BaseModel):
    """Single column definition within a sheet. From report_schema.json."""

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(description="Display name for the column header")
    key: str = Field(description="Data key used to look up values from finding dicts")
    type: str = Field(description="Data type: string, integer, date, currency, percentage, etc.")
    width: int = Field(default=20, description="Column width in characters")
    format: str | None = Field(default=None, description="Excel format string (e.g. '#,##0.00')")
    activation_condition: str | None = Field(
        default=None, description="Condition that must be true for this column to appear"
    )
    field_mapping: str | None = Field(
        default=None, alias="_field_mapping", description="Internal mapping to source data field"
    )
    note: str | None = Field(default=None, alias="_note", description="Internal note about this column")
    algorithm: str | None = Field(
        default=None, alias="_algorithm", description="Algorithm used to compute this column's values"
    )
    derivation: str | None = Field(
        default=None, alias="_derivation", description="How this column's values are derived"
    )


class SortOrder(BaseModel):
    """Sort specification for a sheet."""

    column: str = Field(description="Column key to sort by")
    direction: str = Field(default="asc", description="Sort direction: 'asc' or 'desc'")


class ConditionalFormat(BaseModel):
    """Conditional formatting rule for a column."""

    column: str = Field(description="Column key to apply formatting to")
    rule: str = Field(description="Condition expression (e.g. '> 0', '== P0', 'contains active')")
    format: SeverityColor = Field(description="Colors to apply when the rule matches")


class SummaryFormulaEntry(BaseModel):
    """Individual formula entry within a summary row."""

    column: str = Field(description="Column key this formula applies to")
    value: str | None = Field(default=None, description="Static text value for the summary cell")
    formula: str | None = Field(default=None, description="Pseudo-formula (SUM, COUNTIF, etc.)")


class SheetDef(BaseModel):
    """
    Complete sheet definition. From report_schema.json.
    Each sheet has columns, sort order, conditional formatting, and activation rules.
    """

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(description="Sheet tab name in the Excel workbook")
    required: bool = Field(default=True, description="Whether this sheet must always be included")
    activation_condition: str = Field(
        default="always", description="Condition for including this sheet (e.g. 'always', 'has_gaps')"
    )
    description: str = Field(default="", description="Human-readable description of the sheet's purpose")
    source: str = Field(default="", description="Data source identifier for this sheet")
    source_note: str | None = Field(default=None, alias="_source_note", description="Internal note about data source")
    field_mapping: str | None = Field(
        default=None, alias="_field_mapping", description="Internal mapping to source data"
    )
    row_rule: str = Field(default="", description="Rule for generating rows (e.g. 'one_per_finding')")
    columns: list[ColumnDef] = Field(default_factory=list, description="Column definitions for this sheet")
    sort_order: list[SortOrder] = Field(default_factory=list, description="Default sort order for rows")
    conditional_formatting: list[ConditionalFormat] = Field(
        default_factory=list, description="Conditional formatting rules"
    )
    summary_formulas: dict[str, list[SummaryFormulaEntry]] = Field(
        default_factory=dict, description="Summary row formulas keyed by row label"
    )


class ReportSchema(BaseModel):
    """
    Machine-readable report schema. Loaded from report_schema.json.
    From reporting-protocol.md section 3.
    """

    schema_version: str = Field(description="Semver version of the report schema format")
    description: str = Field(default="", description="Human-readable description of the report schema")
    global_formatting: GlobalFormatting = Field(
        default_factory=GlobalFormatting, description="Global Excel formatting settings"
    )
    sheets: list[SheetDef] = Field(default_factory=list, description="Sheet definitions in display order")

    @model_validator(mode="after")
    def _require_at_least_one_sheet(self) -> ReportSchema:
        """Fail-fast: a report schema with zero sheets is not valid."""
        if not self.sheets:
            msg = (
                "ReportSchema must have at least one sheet definition. "
                "Ensure report_schema.json contains a non-empty 'sheets' array."
            )
            raise ValueError(msg)
        return self


class ReportDiffChange(BaseModel):
    """Single change entry in the report diff. From reporting-protocol.md section 4."""

    change_type: str = Field(
        description="Type of change: new_finding, resolved_finding, changed_severity, "
        "new_gap, resolved_gap, new_customer, removed_customer"
    )
    customer: str = Field(description="Customer name affected by the change")
    finding_summary: str = Field(default="", description="Brief description of the finding")
    prior_severity: str | None = Field(default=None, description="Severity in the prior run (None if new)")
    current_severity: str | None = Field(default=None, description="Severity in the current run (None if resolved)")
    details: str = Field(default="", description="Additional context about the change")


class ReportDiffSummary(BaseModel):
    """Summary counts for the report diff."""

    new_findings: int = Field(default=0, description="Number of findings added since prior run")
    resolved_findings: int = Field(default=0, description="Number of findings resolved since prior run")
    changed_severity: int = Field(default=0, description="Number of findings with changed severity")
    new_gaps: int = Field(default=0, description="Number of gaps added since prior run")
    resolved_gaps: int = Field(default=0, description="Number of gaps resolved since prior run")
    new_customers: int = Field(default=0, description="Number of customers added since prior run")
    removed_customers: int = Field(default=0, description="Number of customers removed since prior run")


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
    summary: ReportDiffSummary = Field(default_factory=ReportDiffSummary, description="Aggregate change counts")
    changes: list[ReportDiffChange] = Field(default_factory=list, description="Individual change entries")


class ContractDateReconciliationEntry(BaseModel):
    """
    Single customer entry in contract date reconciliation.
    From reporting-protocol.md section 5.
    """

    customer: str = Field(description="Customer name")
    database_end_date: str = Field(default="", description="Contract end date from customer database (YYYY-MM-DD)")
    actual_end_date: str = Field(default="", description="Actual end date found in contracts (YYYY-MM-DD)")
    arr: float = Field(default=0.0, description="Annual recurring revenue for this customer")
    status: str = Field(
        default="",
        description="Reconciliation status: Active-Database Stale, Active-Auto-Renewal, "
        "Likely Active-Needs Confirmation, Expired-Confirmed, Expired-No Contracts",
    )
    evidence: str = Field(default="", description="Supporting evidence for the status determination")
    evidence_file: str = Field(default="", description="File path where evidence was found")


class ContractDateReconciliation(BaseModel):
    """
    Complete contract date reconciliation document.
    Written to {RUN_DIR}/contract_date_reconciliation.json.
    From SKILL.md section 5.
    """

    run_id: str = Field(description="Unique run identifier")
    generated_at: str = Field(description="ISO-8601 timestamp of document generation")
    entries: list[ContractDateReconciliationEntry] = Field(
        default_factory=list, description="Per-customer reconciliation entries"
    )
    total_reclassified_arr: float = Field(
        default=0.0, description="Total ARR of customers whose status was reclassified"
    )
    total_expired_arr: float = Field(default=0.0, description="Total ARR of customers confirmed as expired")
