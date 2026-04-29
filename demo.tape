# Due Diligence Agents — Real M&A Analysis Demo
# Shows an actual deal scenario: acquiring NovaBridge Solutions
# Generate: vhs demo.tape
# Output: demo.gif

Output demo.gif
Set FontSize 13
Set Width 1200
Set Height 700
Set Theme "Catppuccin Mocha"
Set TypingSpeed 25ms
Set Padding 15
Set Framerate 24

# ─── Clear & Title ────────────────────────────────────────────────────────────
Hide
Type "clear"
Enter
Show
Sleep 300ms
Type "# Scenario: Meridian Holdings acquiring NovaBridge Solutions ($85-110M)"
Enter
Type "# Data room: 3 customer contracts + buyer overview"
Enter
Sleep 2.5s

# ─── 1. Scan the data room & generate config ─────────────────────────────────
Type ""
Enter
Type "dd-agents init --non-interactive --data-room examples/quickstart/sample_data_room --buyer 'Meridian Holdings' --target 'NovaBridge Solutions' --output /tmp/deal-config.json"
Enter
Sleep 4s

# ─── 2. Validate configuration ───────────────────────────────────────────────
Type ""
Enter
Type "dd-agents validate /tmp/deal-config.json"
Enter
Sleep 2.5s

# ─── 3. Show the 38-step pipeline (dry run) ──────────────────────────────────
Type ""
Enter
Type "# Preview the full analysis pipeline — 38 steps, 5 blocking quality gates"
Enter
Sleep 1s
Type "dd-agents run examples/quickstart/deal-config.json --dry-run"
Enter
Sleep 9s

# ─── 4. Query: Revenue at risk ───────────────────────────────────────────────
Type ""
Enter
Type "# After a pipeline run completes: ask deal-specific questions with exact citations"
Enter
Sleep 1.5s
Type "dd-agents query --report /tmp/demo_project/_dd/forensic-dd/runs/latest -q 'What is the total revenue at risk from change of control clauses?'"
Enter
Sleep 20s

# ─── 5. Query: Which contracts survive ───────────────────────────────────────
Type ""
Enter
Type "dd-agents query --report /tmp/demo_project/_dd/forensic-dd/runs/latest -q 'Which contracts can we keep without customer consent after acquisition?'"
Enter
Sleep 20s

# ─── 6. Query: IC memo summary ───────────────────────────────────────────────
Type ""
Enter
Type "dd-agents query --report /tmp/demo_project/_dd/forensic-dd/runs/latest -q 'Summarize the P0 and P1 findings I should flag in the IC memo'"
Enter
Sleep 20s

# ─── 7. Contract search template ─────────────────────────────────────────────
Type ""
Enter
Type "# Targeted contract search — ask specific questions across all contracts"
Enter
Sleep 1s
Type "jq '{name, description, columns: [.columns[] | .name]}' examples/search/change_of_control.json"
Enter
Sleep 5s

# ─── 8. Wrap-up ──────────────────────────────────────────────────────────────
Type ""
Enter
Type "# Output: Interactive HTML + 14-sheet Excel + structured JSON"
Enter
Type "# Sample report: https://zoharbabin.github.io/due-diligence-agents/"
Enter
Type "# pip install dd-agents[pdf]"
Enter
Sleep 4s
