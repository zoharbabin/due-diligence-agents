# Due Diligence Agents — Project Atlas pipeline run (HERO terminal shot)
# Generates: ../assets/01-atlas-run.mp4
# Run from repo root: vhs docs/marketing/recordings/01-atlas-run.tape
#
# Captures the headline moment: 13 AI agents reading the Northwind data room across
# 9 domains, the cross-domain analysis step firing (Legal CoC -> Finance exposure).
# NOTE: uses --dry-run for a fast, deterministic, always-clean recording of the PLAN.
# For the LIVE run footage (real agent output scrolling), see the variant block at the
# bottom and record after a real `dd-agents run` has populated the report.

Output docs/marketing/assets/01-atlas-run.mp4

Set FontSize 18
Set Width 1920
Set Height 1080
Set Theme "Catppuccin Mocha"
Set TypingSpeed 25ms
Set Padding 30
Set Framerate 30
Set PlaybackSpeed 1

Hide
Type "clear"
Enter
Show
Sleep 500ms

Type "# Project Atlas — acquiring Northwind Logistics Software ($41.2M ARR)"
Enter
Type "# 13 AI agents. 9 domains. Every document in the data room."
Enter
Sleep 2.5s
Type ""
Enter

# --- Show the data room ---
Type "ls examples/project-atlas/sample_data_room/Northwind_Logistics/"
Enter
Sleep 3s
Type ""
Enter

# --- Preview the pipeline (the 38 steps, 5 blocking gates, cross-domain step 18) ---
Type "# Preview the forensic pipeline — note step 18: cross-domain analysis"
Enter
Sleep 1s
Type "dd-agents run examples/project-atlas/deal-config.json --dry-run"
Enter
Sleep 10s
Type ""
Enter

Type "# Then run it for real:  dd-agents run examples/project-atlas/deal-config.json"
Enter
Sleep 3s

# ─────────────────────────────────────────────────────────────────────────────
# LIVE-RUN VARIANT (record separately, after a real run):
#   Replace the --dry-run line above with:
#     Type "dd-agents run examples/project-atlas/deal-config.json"
#     Enter
#     Sleep 90s        # let the real agent/pipeline output scroll; trim in edit
#   Keep FontSize >=18 and cursor-zoom the cross_domain_analysis + report-generation lines in post.
# ─────────────────────────────────────────────────────────────────────────────
