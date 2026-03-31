# Reading the Report

The pipeline produces two report formats: an interactive HTML report for navigation and drill-down, and a 14-sheet Excel report for detailed analysis by deal teams. Both include sourced citations, severity filtering, and cross-domain correlation.

**This report is designed to accelerate your advisors' work, not replace it.** Share findings with your legal, financial, and technical advisors for verification before presenting to a board or making business decisions.

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

The report follows a top-down drill-down structure, organized into four tiers:
deal-level decisions, domain deep-dives, cross-cutting analysis, and appendices.

#### Deal-Level Decision View

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
KPI cards for key SaaS metrics (NRR, GRR, churn, LTV) and customer tier distribution.

**Valuation Impact Bridge**
Shows how identified risks map to potential valuation adjustments, bridging from
headline valuation to risk-adjusted valuation.

**P0/P1 Findings Table**
Sortable table of all critical and high-severity findings across all entities.
Each row includes entity name, domain, category, severity, and description.

#### Domain Deep-Dive

**Change of Control Analysis**
Detailed analysis of change-of-control clauses: consent requirements, notification
obligations, termination triggers, and revenue at risk.

**Termination for Convenience Analysis**
Revenue quality assessment based on TfC clause exposure: notice periods, cure windows,
and uncommitted revenue.

**Data Privacy Compliance**
Privacy and data protection analysis: GDPR/CCPA compliance, data processing agreements,
cross-border transfer mechanisms, and breach notification obligations.

**Risk Heatmap**
Domain-level risk summary showing severity distribution across Legal, Finance,
Commercial, and ProductTech domains.

**Domain Sections** (Legal, Finance, Commercial, ProductTech)
Category breakdowns within each specialist domain, with finding counts and
per-entity details. Each domain section is capped at the most significant findings
with expand/collapse for full detail.

**Discount & Pricing Analysis**
Discount patterns, pricing consistency, and margin erosion across the contract portfolio.

**Renewal & Contract Expiry**
Upcoming renewal dates, auto-renewal terms, evergreen clauses, and expiry concentration.

**Regulatory & Compliance**
Regulatory obligations, audit rights, compliance certifications, and industry-specific
requirements found in contracts.

**Legal Entity Distribution**
Breakdown of contracts by legal entity and jurisdiction, highlighting entity
fragmentation and multi-jurisdiction exposure.

**Contract Date Timeline**
Visual timeline of contract start/end dates, showing concentration risk around
key periods and upcoming expirations.

**Insurance & Liability Analysis**
Liability caps, indemnification provisions, insurance requirements, and uncapped
liability exposure across the portfolio.

**IP & Technology License Risk**
Intellectual property ownership, license grant scope, open-source obligations,
and technology transfer provisions.

**Cross-Domain Risk Correlation**
Findings that span multiple specialist domains, showing how risks in one area
compound or contradict risks in another.

**Contract Clause Library**
Searchable catalog of key contract clauses identified by AI analysis across the portfolio,
organized by clause type (CoC, TfC, liability, IP, privacy, etc.) with exact quotes and source citations.

**Key Employee & Organizational Risk**
Key-person dependencies, non-compete/non-solicit provisions, and organizational
risks identified in employment agreements and corporate documents.

**Technology Stack Assessment**
Technology dependencies, platform risks, technical debt indicators, and integration
complexity findings from product/tech analysis.

**Product Adoption Matrix**
Product and feature adoption patterns across the customer base, highlighting
concentration risk and cross-sell/upsell indicators.

#### Cross-Cutting Analysis

**Cross-Reference Reconciliation**
Findings corroborated or contradicted across multiple agents or documents.

**Entity Health Tiers**
Entities ranked by overall risk, grouped into health tiers (green/amber/red).

**Recommendations**
Prioritized action items: pre-close requirements, closing conditions, and
post-close monitoring items.

**Post-Close Integration Playbook**
Integration priorities, governance recommendations, and day-1 readiness checklist.
Present when buyer strategy is configured in the deal config.

**Governance Graph**
Visual representation of entity relationships, ownership structure, and
corporate hierarchy extracted from the data room.

**Buyer Strategy & Acquirer Intelligence** (conditional)
Acquisition thesis alignment, synergy validation, and deal-specific risk assessment.
Only present when `buyer_strategy` is configured in the deal config.

#### Appendix (collapsed by default)

**Missing or Incomplete Data**
Data availability limitations, documentation gaps, and extraction quality issues.
Findings about missing or unreadable data are separated here from the main analysis
to avoid inflating domain-level severity counts.

**Entity Detail**
Per-entity drill-down with all findings, organized by domain and category.

**Methodology & Limitations**
Pipeline methodology, agent descriptions, analysis scope, and known limitations.

**Data Quality**
Governance metrics, QA audit results, and noise findings filtered from the main report.

**Run Diff** (incremental mode only)
What changed since the previous pipeline run: new findings, resolved findings,
and severity changes.

### RAG Indicators

Each section displays a RAG status:

- **Red**: Critical issues found, immediate attention needed
- **Amber**: Notable issues present, review recommended
- **Green**: No significant issues, area looks clean

### Global Search

Use the search bar to filter findings across the entire report by keyword.

### Print Mode

The report includes print-optimized CSS. Use your browser's print function
(Ctrl+P / Cmd+P) for a clean PDF-style output. For higher-fidelity PDF export,
use:

```bash
dd-agents export-pdf _dd/forensic-dd/runs/latest/report/dd_report.html
```

## Excel Report

The Excel report at `dd_report.xlsx` contains 14 sheets:

| Sheet | Content |
|-------|---------|
| Summary | High-level metrics and Go/No-Go signal |
| Wolf_Pack | Top critical/high findings across all domains |
| Legal_Risks | All legal domain findings with citations |
| Financials | All finance domain findings |
| Commercial_Data | All commercial domain findings |
| Product_Scope | All product/tech domain findings |
| Data_Reconciliation | Multi-agent corroborated findings |
| Missing_Docs_Gaps | Missing documents and coverage gaps |
| Contract_Date_Reconciliation | Contract date cross-reference with source of truth |
| Reference_Files_Index | Index of reference/cross-cutting documents |
| Entity_Resolution_Log | Entity matching decisions and confidence scores |
| Quality_Audit | QA validation results and audit trail |
| Run_Diff | Changes from prior run (incremental mode only) |
| _Metadata | Run configuration, timing, costs, versions |

Sheets use conditional formatting: red for P0/P1, yellow for P2, no fill for P3/P4.

## Next Steps

- [Running the Pipeline](running-pipeline.md) -- Re-run with different settings
- [Deal Configuration](deal-configuration.md) -- Adjust focus areas or enable the Judge
- [CLI Reference](cli-reference.md) -- Export and search commands
