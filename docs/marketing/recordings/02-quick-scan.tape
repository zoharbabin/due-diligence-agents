# Due Diligence Agents — quick-scan red-flag triage
# Generates: ../assets/02-quick-scan.mp4
# Run from repo root: vhs docs/marketing/recordings/02-quick-scan.tape
#
# Captures the fast triage path: GREEN/YELLOW/RED in minutes. Records the COMMAND +
# its real output. Run a real quick-scan first so output is genuine, OR keep --dry-run
# to show the plan. The live scan is the better footage — record after the pipeline run.

Output docs/marketing/assets/02-quick-scan.mp4

Set FontSize 18
Set Width 1920
Set Height 1080
Set Theme "Catppuccin Mocha"
Set TypingSpeed 25ms
Set Padding 30
Set Framerate 30

Hide
Type "clear"
Enter
Show
Sleep 500ms

Type "# Don't have hours? Triage the deal in minutes."
Enter
Sleep 1.5s
Type ""
Enter
Type "dd-agents run examples/project-atlas/deal-config.json --quick-scan"
Enter
# Live scan scrolls here; in --dry-run it prints the plan. Trim/zoom the GREEN/YELLOW/RED verdict in post.
Sleep 60s
Type ""
Enter
Type "# RED on Northwind: a 30%-of-ARR customer can walk if the deal closes."
Enter
Sleep 3s
