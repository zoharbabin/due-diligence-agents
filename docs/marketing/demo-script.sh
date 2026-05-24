#!/usr/bin/env bash
# =============================================================================
# DD-Agents Marketing Demo Script
# =============================================================================
# This script demonstrates the full dd-agents workflow:
#   1. Pipeline run — scanning a data room with 13 AI agents
#   2. Natural-language query — asking questions about findings
#   3. Report generation — HTML report with interactive features
#
# Prerequisites:
#   pip install dd-agents[pdf]
#   export ANTHROPIC_API_KEY=sk-ant-...
#
# For terminal recording with asciinema:
#   asciinema rec demo.cast --title "DD-Agents: AI-Powered M&A Due Diligence"
#   Then run this script inside the recording session.
# =============================================================================

set -e

# --- Colors for pretty output ---
BOLD='\033[1m'
DIM='\033[2m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}  DD-Agents: AI-Powered M&A Due Diligence${NC}"
echo -e "${DIM}  Forensic analysis of contract data rooms using 13 specialist AI agents${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# --- Step 1: Show the data room structure ---
echo -e "${BLUE}▶ Data Room Structure${NC}"
echo ""
echo "  examples/quickstart/sample_data_room/"
echo "  ├── Acme_Corp/"
echo "  │   ├── MSA-NexGen-Acme-2024.pdf"
echo "  │   ├── Amendment-1-Pricing.pdf"
echo "  │   └── SOW-Implementation-Services.pdf"
echo "  ├── Beta_Inc/"
echo "  │   ├── Master-License-Agreement.pdf"
echo "  │   └── Addendum-Data-Processing.pdf"
echo "  ├── Gamma_LLC/"
echo "  │   ├── Service-Agreement-2023.pdf"
echo "  │   └── NDA-Mutual-2024.pdf"
echo "  └── _reference/"
echo "      ├── Revenue-Breakdown-FY24.xlsx"
echo "      ├── Org-Chart-Analysis.pdf"
echo "      └── Transfer-Pricing-Study.pdf"
echo ""
sleep 2

# --- Step 2: Run the pipeline ---
echo -e "${BLUE}▶ Running the 38-step forensic analysis pipeline...${NC}"
echo ""
echo -e "  ${YELLOW}$ dd-agents run examples/quickstart/deal-config.json${NC}"
echo ""
sleep 1

# Simulated pipeline output (representative of actual run)
echo -e "  ${DIM}[Step  1/38]${NC} Loading deal configuration..."
echo -e "  ${DIM}[Step  2/38]${NC} Validating data room structure..."
echo -e "  ${DIM}[Step  3/38]${NC} Extracting documents (PDF, DOCX, XLSX)..."
echo -e "  ${DIM}[Step  4/38]${NC} Building document inventory (12 files, 3 subjects)"
echo -e "  ${DIM}[Step  5/38]${NC} Computing document precedence scores..."
echo -e "  ${DIM}[Step  6/38]${NC} Resolving entity names (5 canonical entities found)"
sleep 1
echo -e "  ${DIM}[Step  7/38]${NC} Spawning 9 specialist agents..."
echo -e "  ${GREEN}           ├── Legal Agent${NC}          analyzing 3 subjects..."
echo -e "  ${GREEN}           ├── Finance Agent${NC}        analyzing 3 subjects..."
echo -e "  ${GREEN}           ├── Commercial Agent${NC}     analyzing 3 subjects..."
echo -e "  ${GREEN}           ├── Product & Tech Agent${NC} analyzing 3 subjects..."
echo -e "  ${GREEN}           ├── Cybersecurity Agent${NC}  analyzing 3 subjects..."
echo -e "  ${GREEN}           ├── HR Agent${NC}             analyzing 3 subjects..."
echo -e "  ${GREEN}           ├── Tax Agent${NC}            analyzing 3 subjects..."
echo -e "  ${GREEN}           ├── Regulatory Agent${NC}     analyzing 3 subjects..."
echo -e "  ${GREEN}           └── ESG Agent${NC}            analyzing 3 subjects..."
sleep 2
echo -e "  ${DIM}[Step 14/38]${NC} Merging findings across agents (67 findings found)"
echo -e "  ${DIM}[Step 15/38]${NC} Semantic deduplication (removed 12 overlaps)"
echo -e "  ${DIM}[Step 16/38]${NC} Running Red Flag Scanner..."
echo -e "  ${RED}           ⚠  2 critical deal-breakers flagged${NC}"
sleep 1
echo -e "  ${DIM}[Step 18/38]${NC} Cross-domain trigger analysis (7 rules evaluated)..."
echo -e "  ${YELLOW}           → 3 cross-domain verifications triggered${NC}"
echo -e "  ${DIM}[Step 19/38]${NC} Spawning targeted pass-2 agents..."
echo -e "  ${DIM}[Step 20/38]${NC} Merging cross-domain findings..."
sleep 1
echo -e "  ${DIM}[Step 25/38]${NC} Running 31 substantive quality checks..."
echo -e "  ${DIM}[Step 28/38]${NC} Executive synthesis..."
echo -e "  ${DIM}[Step 30/38]${NC} Generating HTML report..."
echo -e "  ${DIM}[Step 32/38]${NC} Compiling knowledge base..."
echo -e "  ${DIM}[Step 38/38]${NC} Pipeline complete."
echo ""
echo -e "  ${GREEN}✓ Report:${NC}   _dd/reports/report.html"
echo -e "  ${GREEN}✓ Excel:${NC}    _dd/reports/report.xlsx (14 sheets)"
echo -e "  ${GREEN}✓ Runtime:${NC}  4m 32s | Cost: $2.47"
echo ""
sleep 2

# --- Step 3: Show report highlights ---
echo -e "${BLUE}▶ Report Highlights${NC}"
echo ""
echo -e "  ${RED}┌─────────────────────────────────────────────────┐${NC}"
echo -e "  ${RED}│  VERDICT: NO-GO                                 │${NC}"
echo -e "  ${RED}│  2 critical deal-breakers identified             │${NC}"
echo -e "  ${RED}│  requiring resolution before proceeding          │${NC}"
echo -e "  ${RED}└─────────────────────────────────────────────────┘${NC}"
echo ""
echo "  Findings:  P0: 1  │  P1: 5  │  P2: 6  │  P3: 3"
echo "  Domains:   Legal (4) │ Finance (2) │ Commercial (1) │ Product&Tech (3)"
echo "             Cybersecurity (1) │ HR (2) │ Tax (1) │ Regulatory (1) │ ESG (1)"
echo ""
echo "  Top Action Items:"
echo "    1. [Pre-close]    Negotiate CoC waivers from enterprise customers"
echo "    2. [Pre-close]    Confirm IP assignment chain for 3 contractors"
echo "    3. [Pre-close]    Map TfC exposure by revenue impact"
echo "    4. [Post-close]   Remediate SOC 2 certification"
echo "    5. [Post-close]   Address transfer pricing compliance"
echo ""
sleep 2

# --- Step 4: Query the findings ---
echo -e "${BLUE}▶ Natural-Language Query Interface${NC}"
echo ""
echo -e "  ${YELLOW}$ dd-agents query examples/quickstart/deal-config.json${NC}"
echo ""
echo -e "  ${DIM}Connected to deal: Meridian Holdings → NovaBridge Solutions${NC}"
echo -e "  ${DIM}Knowledge base: 55 findings, 3 entities, 9 domains${NC}"
echo ""
echo -e "  ${BOLD}You:${NC} What is the total revenue at risk from the CoC clauses?"
echo ""
sleep 1
echo -e "  ${GREEN}DD-Agents:${NC}"
echo ""
echo "  Based on the analysis, the Change of Control clauses create"
echo "  **\$6.8M in directly at-risk ARR** (54% of NexGen SaaS's contracted"
echo "  revenue). This includes:"
echo ""
echo "  1. **Enterprise MSA §12.4** — Tier 1 customers can terminate within"
echo "     30 days of a CoC event without penalty"
echo "     *Source: MSA-NexGen-Acme-2024.pdf, page 15, §12.4*"
echo ""
echo "  2. **Velocity Cloud TfC exposure** — Top 3 contracts (\$4.2M) have"
echo "     60-day TfC provisions that could be exercised during transition"
echo "     *Source: Contract-Risk-Summary.xlsx*"
echo ""
echo "  Combined exposure: **\$11.0M** (48% of total portfolio ARR of \$23M)."
echo "  This concentration of termination risk significantly exceeds the 20%"
echo "  threshold for \"Proceed with Conditions\" under the deal risk framework."
echo ""
sleep 2

echo -e "  ${BOLD}You:${NC} What would you recommend to mitigate this before close?"
echo ""
sleep 1
echo -e "  ${GREEN}DD-Agents:${NC}"
echo ""
echo "  Recommended pre-close mitigation strategy:"
echo ""
echo "  | # | Action                                      | Owner        | Timeline  |"
echo "  |---|---------------------------------------------|--------------|-----------|"
echo "  | 1 | Negotiate CoC consent/waiver with Tier 1    | Legal Counsel| Pre-close |"
echo "  | 2 | Structure escrow holdback for unresolved CoC| M&A Counsel  | Pre-close |"
echo "  | 3 | Extend TfC notice from 60d to 12mo         | Commercial   | Pre-close |"
echo "  | 4 | Obtain key customer reaffirmation letters   | Deal Team    | Pre-close |"
echo ""
echo "  If CoC waivers cannot be obtained for the \$6.8M exposure, consider"
echo "  a purchase price reduction of 15-25% of at-risk ARR (\$1.0M-\$1.7M)"
echo "  or an escrow mechanism tied to 12-month customer retention."
echo ""
echo "  *Based on findings: Legal/CoC analysis, Contract-Risk-Summary.xlsx*"
echo ""
sleep 2

# --- Step 5: Export ---
echo -e "${BLUE}▶ Document Export${NC}"
echo ""
echo -e "  ${BOLD}You:${NC} Export the CoC risk summary as a Word document for the IC memo"
echo ""
sleep 1
echo -e "  ${GREEN}DD-Agents:${NC} Generated document:"
echo -e "  ${GREEN}  → _dd/exports/coc-risk-summary.docx${NC} (3 pages)"
echo ""
echo "  Includes:"
echo "  • Executive summary with deal-breaker classification"
echo "  • Revenue impact table by entity"
echo "  • Recommended mitigation actions with ownership"
echo "  • Source citations for each finding"
echo ""
sleep 1

# --- Footer ---
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  ${BOLD}DD-Agents${NC} — Forensic M&A due diligence in minutes, not weeks."
echo ""
echo "  Install:    pip install dd-agents[pdf]"
echo "  GitHub:     github.com/zoharbabin/due-diligence-agents"
echo "  PyPI:       pypi.org/project/dd-agents"
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
