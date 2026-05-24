# DD-Agents v1.6 — Marketing Demo Recording
# Generates: assets/demo-v1.6-hq.mp4
# Run from repo root: vhs docs/marketing/demo-v1.6.tape

Output docs/marketing/assets/demo-v1.6-hq.mp4

Set FontSize 18
Set Width 1920
Set Height 1080
Set Theme "Catppuccin Mocha"
Set TypingSpeed 25ms
Set Padding 30
Set Framerate 30
Set PlaybackSpeed 1

# ─── Setup (run from repo root) ───────────────────────────────────────────────
Hide
Type "clear"
Enter
Show
Sleep 500ms
Type "# DD-Agents v1.6 — AI-Powered M&A Due Diligence"
Enter
Type "# Forensic contract analysis across 9 domains using 13 specialist AI agents"
Enter
Sleep 2.5s

# ─── 1. Scan data room & generate config ─────────────────────────────────────
Type ""
Enter
Type "# Step 1: Point at a data room → auto-generate deal config"
Enter
Sleep 1s
Type "dd-agents init --non-interactive --data-room examples/quickstart/sample_data_room --buyer 'Meridian Holdings' --target 'NovaBridge Solutions' --output /tmp/demo-config.json --force"
Enter
Sleep 5s

# ─── 2. Validate configuration ───────────────────────────────────────────────
Type ""
Enter
Type "# Step 2: Validate the configuration"
Enter
Sleep 800ms
Type "dd-agents validate /tmp/demo-config.json"
Enter
Sleep 3.5s

# ─── 3. Assess data room readiness ───────────────────────────────────────────
Type ""
Enter
Type "# Step 3: Check data room quality before running"
Enter
Sleep 800ms
Type "dd-agents assess examples/quickstart/sample_data_room"
Enter
Sleep 4s

# ─── 4. Preview the pipeline (dry-run) ───────────────────────────────────────
Type ""
Enter
Type "# Step 4: Preview the 38-step analysis pipeline (5 blocking quality gates)"
Enter
Sleep 800ms
Type "dd-agents run examples/quickstart/deal-config.json --dry-run"
Enter
Sleep 10s

# ─── 5. Show available commands ──────────────────────────────────────────────
Type ""
Enter
Type "# 16 commands — from one-shot search to interactive chat"
Enter
Sleep 800ms
Type "dd-agents --help"
Enter
Sleep 5s

# ─── 6. Wrap-up ──────────────────────────────────────────────────────────────
Type ""
Enter
Type "# ─────────────────────────────────────────────────────"
Enter
Type "# pip install dd-agents[pdf]"
Enter
Type "# github.com/zoharbabin/due-diligence-agents"
Enter
Type "# Sample report: zoharbabin.github.io/due-diligence-agents"
Enter
Type "# ─────────────────────────────────────────────────────"
Enter
Sleep 4s
