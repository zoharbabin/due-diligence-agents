# Project Atlas — Synthetic Deal Bible (internal reference)
> 100% synthetic. No real company, person, or financial data. Engineered to fire the Legal->Finance CoCFinancialImpact cross-domain trigger.

**Target:** Northwind Logistics Software, Inc. — a B2B SaaS provider of cloud freight-management and transportation-orchestration software (TMS) for mid-market shippers and 3PLs; ~$41.2M ARR, Delaware C-corp, HQ Columbus, Ohio.

**Acquirer:** Summit Industrial Group, LLC — a strategic industrial/logistics acquirer (the buyer in Project Atlas).

**Total ARR:** $41.2M

## Customers (ARR concentration)

| Customer | ARR | % of ARR | Key clauses |
|---|---|---|---|
| Meridian Freight Corporation | $12.4M | 30.1% | HERO. MSA §12.3 Change of Control: agreement AUTO-TERMINATES (not consent — automatic) at Meridian's written election wi… |
| Cobalt Retail Group | $9.6M | 23.3% | Order Form + MSA. 36-month PREPAID deal: $28.8M total contract value invoiced and cash-collected up front on 2025-01-15 … |
| Harbor Foods Distribution, LLC | $6.8M | 16.5% | MSA §10.4 Termination for Convenience: customer may terminate without cause on 30 days' written notice with pro-rata ref… |
| Granite Manufacturing Co. | $4.5M | 10.9% | Standard MSA, 2-year term, change-of-control requires consent-not-to-be-unreasonably-withheld (benign — contrast control… |
| Tidewater Distribution N.V. | $3.1M | 7.5% | EU (Belgium) customer — processes EU personal data of drivers/consignees. Data Processing Addendum lists approved sub-pr… |
| Long-tail accounts (47 SMB customers, none >2% individually) | $4.8M | 11.7% | Click-through standard terms, monthly/annual, no negotiated CoC or TfC clauses. Included so customer ARR reconciles exac… |

## Planted findings

- **Legal** — HERO (part 1): Meridian Freight MSA §12.3 gives Meridian an AUTOMATIC termination right, exercisable within 60 days, upon a change of control of Northwind — i.e. Summit's acquisition itself lets the c  
  _doc:_ msa_meridian_freight.pdf.md (§12.3) · _cross-link:_ Fires the deterministic CoCFinancialImpact trigger (agent=legal, category=change_of_control, severit
- **Finance** — HERO (part 2): The CoC-terminable customer (Meridian) is 30.1% of ARR ($12.4M of $41.2M). Because the clause AUTO-terminates material revenue (>20% threshold, COC_AUTOTERM_REVENUE_PCT), exposure is P0  
  _doc:_ arr_schedule.xlsx.md + cap_table_summary.pdf.md (concentration) cross-referenced with msa_meridian_freight.pdf.md (clause) · _cross-link:_ Legal→Finance via CoCFinancialImpact. THE hero cross-domain story.
- **Finance** — Revenue recognition: Cobalt Retail's $28.8M 36-month prepaid (cash collected 2025-01-15) was recognized with a front-loaded Year-1 tranche rather than ratably across 36 months, overstating recognized   
  _doc:_ order_form_cobalt_retail.pdf.md + arr_schedule.xlsx.md (recognition note) + board_deck_excerpt.pdf.md · _cross-link:_ Links to Commercial (contract term vs recognition period) and Tax (timing of revenue).
- **Finance** — Customer concentration: top customer (Meridian) 30.1% and top 3 customers 69.9% of ARR — well above the 30% concentration risk line.  
  _doc:_ arr_schedule.xlsx.md · _cross-link:_ Amplifies the Legal CoC finding — the concentrated customer is also the CoC-terminable one.
- **ProductTech / IP** — IP-assignment gap: the route-optimization engine (a core, demo-critical feature) was built in 2024 by an independent contractor (Signatory C) under an SOW that lacks a present-tense IP assignment; the  
  _doc:_ contractor_agreement_route_engine.pdf.md (SOW § lacks assignment) + employment_ip_agreement.pdf.md (contrast: employees DO assign) · _cross-link:_ Links to Legal (chain of title) and Commercial (the unassigned feature underpins the Meridian contra
- **Regulatory / Data Privacy** — DPA gap: Tidewater (EU/Belgium) personal data is processed by a US-hosted analytics sub-processor that is NOT listed in DPA Annex 2, with no SCCs covering the transfer — GDPR Art. 28 sub-processor and  
  _doc:_ dpa_tidewater.pdf.md (Annex 2 sub-processor list vs actual) · _cross-link:_ Fires DataPrivacyCompliance trigger; links to Cybersecurity (data flows) and Legal (contractual brea
- **Commercial / Legal** — Auto-renewal + termination-for-convenience: Harbor Foods MSA §10.4 allows termination for convenience on only 30 days' notice (below the 90-day threshold) with pro-rata prepaid refund; Cobalt MSA §11.  
  _doc:_ msa_harbor_foods.pdf.md (§10.4) + order_form_cobalt_retail.pdf.md (§11.2) · _cross-link:_ Harbor TfC fires TerminationRevenueExposure (Legal→Finance) since 16.5% > 10% TfC revenue threshold.
- **Legal (control / contrast)** — Benign contrast: Granite Manufacturing MSA CoC requires only consent not-to-be-unreasonably-withheld (no termination right). Planted so the analysis distinguishes a real cliff (Meridian) from a routin  
  _doc:_ msa_granite_manufacturing.pdf.md · _cross-link:_ none (control case).

## Continuity facts (every doc agrees)

- Target legal entity: Northwind Logistics Software, Inc. (Delaware C-corp, HQ Columbus OH) — the 'Provider' in all customer contracts.
- Acquirer: Summit Industrial Group, LLC — its acquisition (>50% equity or substantially all assets) is the change-of-control event.
- Total ARR = $41,200,000 ("$41.2M") as of 2026-03-31, identical in every financial doc.
- Customer ARR reconciles EXACTLY to $41.2M: Meridian $12.4M + Cobalt $9.6M + Harbor $6.8M + Granite $4.5M + Tidewater $3.1M + long-tail $4.8M = $41.2M.
- CoC customer = Meridian Freight Corporation, $12.4M ARR = 30.1% of total — the single largest customer AND the only major auto-terminate-on-CoC contract.
- Meridian MSA §12.3 = AUTOMATIC termination right within 60 days on change of control (not consent); 3-yr term Effective 2025-01-01 to 2027-12-31; billed annually in advance.
- Top-1 concentration = 30.1%; top-3 (Meridian+Cobalt+Harbor) = 69.9%.
- Cobalt prepaid: $28,800,000 total contract value, 36 months, cash collected 2025-01-15, service period 2025-01-01 to 2027-12-31.
- All signatory names are placeholders: Signatory A (Northwind/CEO), Signatory B (Meridian), Signatory C (route-engine contractor), Signatory D (Harbor). 100% synthetic — no real companies, people, or financials.
- Severity mechanics: Meridian CoC is auto-terminate on >20% revenue → P0; Harbor TfC is 30-day notice (<90d) on 16.5% (>10%) → escalated; ARR figures consistent so the Legal→Finance CoCFinancialImpact trigger fires cleanly.
---

## ✅ VERIFIED RESULTS (real pipeline run 2026-06-06)

Ran `dd-agents run examples/project-atlas/deal-config.json` on AWS Bedrock — **all 38 steps, exit 0, all blocking gates passed** (numerical audit 6/6, QA audit, DoD 23/23, schema validation).

- **108 findings** produced across 9 specialists; **44 merged** (2× P0, 10× P1, 17× P2, 15× P3).
- **Hero cross-domain finding landed at P0**, independently surfaced by **Commercial AND Finance** (and the merged view), each citing the exact verbatim quote:
  > *"Meridian Freight (30.1% of ARR) holds unconditional immediate termination right triggered by Summit's acquisition, no cure, pro-rata refund"* — citation: `msa_meridian_freight.pdf.md` §12.3(c)-(d), exact_quote captured.
- Step 18 cross_domain_analysis fired **2 triggers**; step 19 targeted respawn ran.
- Bonus finding (the "humans missed it" beat): *"Management board deck affirmatively misstates CoC/termination exposure on largest customer"* (P2).
- Verdict: **Conditional Go** (honest — a fixable P0).

**Captured launch assets** (`docs/marketing/sample-report-atlas/`): `index.html` (520KB, fully self-contained), `dd_report.xlsx` (14-sheet), `findings_merged.json`.
