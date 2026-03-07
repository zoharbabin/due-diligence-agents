# Reading the Report

The pipeline produces two report formats: an interactive HTML report for navigation
and drill-down, and a 14-sheet Excel report for detailed data analysis.

## HTML Report

Open `_dd/forensic-dd/runs/<timestamp>/report/dd_report.html` in any modern browser.
The report is fully self-contained with no external dependencies.

### Navigation

The left sidebar lists all report sections with scroll tracking -- the active section
highlights as you scroll. Click any section to jump directly to it.

Each section in the sidebar displays a RAG (Red/Amber/Green) indicator showing the
risk status for that area at a glance.

### Severity Filtering

Use the severity filter controls at the top to show or hide findings by priority level:

| Level | Meaning | Color |
|-------|---------|-------|
| P0 | Critical -- deal breakers, immediate action required | Red |
| P1 | High -- significant risk, requires attention before close | Orange |
| P2 | Medium -- notable issues, manageable with remediation | Yellow |
| P3 | Low -- minor concerns, monitor post-close | Blue |
| P4 | Informational -- observations, no action needed | Gray |

### Report Sections

The report follows a top-down drill-down structure:

**Red Flag Assessment** (quick-scan mode only)
Stoplight signal (red/yellow/green) with critical flags from the Red Flag Scanner.
Only present when `--quick-scan` was used.

**Executive Summary**
Go/No-Go recommendation, risk heatmap, deal breakers, and key metrics. This is the
board-level view -- start here.

**Dashboard**
Deal header with buyer/target names, deal type, and metric cards showing material
finding counts by severity.

**Financial Impact**
Revenue-at-risk waterfall chart and treemap visualization. Quantifies the financial
exposure from identified contract risks.

**SaaS Health Metrics**
KPI cards for key SaaS metrics and customer tier distribution analysis.

**Valuation Impact Bridge**
Shows how identified risks map to potential valuation adjustments.

**P0/P1 Findings Table**
Sortable table of all critical and high-severity findings across all entities.
Each row includes entity name, domain, category, severity, and description.

**Domain Analysis**
Dedicated sections for each specialist domain (Legal, Finance, Commercial, ProductTech).
Each shows category breakdowns, finding counts, and per-entity details.

Specialized sub-sections include:
- Change of Control analysis
- Termination for Convenience analysis
- Data Privacy compliance
- Discount and Pricing analysis
- Renewal and Contract Expiry
- Regulatory and Compliance
- Insurance and Liability
- IP and Technology License Risk
- Cross-Domain Risk Correlation

**Cross-Reference Reconciliation**
Findings corroborated or contradicted across multiple agents or documents.

**Entity Health Tiers**
Entities ranked by overall risk, grouped into health tiers.

**Recommendations**
Prioritized action items: pre-close requirements, closing conditions, and
post-close monitoring items.

**Integration Playbook**
Post-close integration priorities and governance recommendations (when buyer
strategy is configured).

**Appendix sections** (collapsed by default):
- Missing or Incomplete Data (gaps in coverage)
- Entity Detail (per-entity drill-down with all findings)
- Methodology and Limitations
- Data Quality (governance, QA, noise findings)
- Run Diff (incremental mode: what changed since last run)

### RAG Indicators

Each section displays a RAG status:

- **Red**: Critical issues found, immediate attention needed
- **Amber**: Notable issues present, review recommended
- **Green**: No significant issues, area looks clean

### Global Search

Use the search bar to filter findings across the entire report by keyword.

### Print Mode

The report includes print-optimized CSS. Use your browser's print function
(Ctrl+P / Cmd+P) for a clean PDF-style output.

## Excel Report

The Excel report at `dd_report.xlsx` contains 14 sheets:

| Sheet | Content |
|-------|---------|
| Executive Summary | High-level metrics and Go/No-Go signal |
| Dashboard | Finding counts by severity and domain |
| Legal Findings | All legal domain findings with citations |
| Finance Findings | All finance domain findings |
| Commercial Findings | All commercial domain findings |
| ProductTech Findings | All product/tech domain findings |
| Cross-Reference | Multi-agent corroborated findings |
| Gaps | Missing documents and coverage gaps |
| Entity Summary | Per-entity risk scores and health tiers |
| Governance Graph | Entity relationships and ownership structure |
| Recommendations | Prioritized action items |
| Numerical Manifest | All extracted financial figures with audit trail |
| Metadata | Run configuration, timing, costs, versions |
| Diff | Changes from prior run (incremental mode only) |

Sheets use conditional formatting: red for P0/P1, yellow for P2, no fill for P3/P4.

## Next Steps

- [Running the Pipeline](running-pipeline.md) -- Re-run with different settings
- [Deal Configuration](deal-configuration.md) -- Adjust focus areas or enable the Judge
- [CLI Reference](cli-reference.md) -- Export and search commands
