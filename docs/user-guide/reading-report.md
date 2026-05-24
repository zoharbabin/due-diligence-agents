# Reading the Report

The pipeline produces two report formats: an interactive HTML report for navigation and drill-down, and a 14-sheet Excel report for detailed analysis. Both include sourced citations, severity classifications, and cross-domain correlation. These reports provide deep, granular analysis across 9 specialist domains — structured output your team uses as the basis for their own deliverables (board presentations, advisor memos, negotiation checklists, integration plans).

**This tool does not replace professional advisors.** Use the structured findings alongside your advisory process to search, correlate, and track risks more efficiently.

## HTML Report

Open `_dd/forensic-dd/runs/<timestamp>/report/dd_report.html` in any modern browser.
The report is fully self-contained (no external dependencies, works offline).

### Report Structure — Progressive Disclosure

The report uses a 4-layer progressive disclosure design. You get the answer first, then drill down for detail:

**Layer 1: The Decision (visible on load, no scrolling required)**
- Deal context header (buyer → target, deal type)
- Go/No-Go verdict with executive narrative explaining the recommendation
- Key takeaways as full sentences with severity icons
- Domain risk strip showing all 9 domains with severity bars

**Layer 2: What To Do About It (click to expand)**
- Action items with urgency timelines, owners, and rationale
- Financial impact quantification
- Valuation bridge (risk-adjusted)
- Buyer strategy alignment (when configured)

**Layer 3: Domain Details (click to expand)**
- Domain overview cards with finding previews and narrative headlines
- Cross-domain risk correlation
- Per-domain deep-dive sections (expandable)

**Layer 4: Full Evidence & Appendix (click to expand)**
- Red flag assessment, dashboard, SaaS metrics
- All findings table (sortable, filterable)
- Specialized analyses (CoC, TfC, privacy, discount, renewal, compliance)
- Entity distribution, timeline, liability, IP risk
- Clause library, key employee, tech stack, product adoption
- Cross-reference reconciliation, entity health tiers
- Recommendations, integration playbook, governance graph
- Data gaps, per-entity detail, methodology, data quality

### Navigation

Click the hamburger menu (☰) in the top-left corner to open the sidebar. The sidebar lists key sections grouped by category (Decision, Domains, Analysis, Evidence) with RAG status dots.

**Clicking a sidebar link automatically expands the parent layer** if it's collapsed, then scrolls to the section. You don't need to manually expand layers before navigating.

### Severity Filtering

The filter bar (visible in Layer 3) lets you show or hide findings by severity and domain:

| Level | Meaning | Color |
|-------|---------|-------|
| P0 | Critical — deal breakers, immediate action required | Red |
| P1 | High — significant risk, requires attention before close | Orange |
| P2 | Medium — notable issues, manageable with remediation | Yellow |
| P3 | Low — minor concerns, monitor post-close | Blue |

### The Verdict Block

The first thing you see is the verdict card. When executive synthesis runs (the default), this shows the LLM-calibrated Go/No-Go signal with the full executive narrative integrated — explaining not just WHAT the verdict is but WHY, what's at risk, and what to do about it.

The verdict considers:
- All findings across 9 domains
- Deal context and buyer thesis (when configured)
- Mitigability and timeline to resolution
- Cross-domain compound risks

Risk labels (Critical, High, Medium, Low, Clean) reflect severity of findings. The signal (No-Go, Proceed with Caution, Conditional Go, Go) reflects the overall recommendation accounting for mitigability.

### Domain Overview Cards

In Layer 3, domain cards show:
- Domain name with risk badge (High/Medium/Low/Clean)
- Severity bar showing finding distribution
- Top 3 findings preview with severity tags
- LLM-generated narrative headline (when narrative data available)
- Link to full domain detail

Cards with no findings show a compact "No findings" state.

### RAG Indicators

Each sidebar link and domain card displays a RAG status:

- **Red**: Critical issues found, immediate attention needed
- **Amber**: Notable issues present, review recommended
- **Green**: No significant issues, area looks clean

### Presentation Mode

Click the "Present" button in the sidebar footer to enter presentation mode — removes navigation chrome for screen-sharing or projecting.

### Print Mode

The report includes print-optimized CSS. Use your browser's print function
(Ctrl+P / Cmd+P) for a clean layout with all sections expanded. For higher-fidelity PDF export:

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

Sheets use conditional formatting: red for P0/P1, yellow for P2, no fill for P3.

## Next Steps

- [Running the Pipeline](running-pipeline.md) — Re-run with different settings
- [Deal Configuration](deal-configuration.md) — Adjust focus areas or enable the Judge
- [CLI Reference](cli-reference.md) — Export and search commands
