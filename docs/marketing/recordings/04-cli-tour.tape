# Due Diligence Agents — CLI breadth tour (dev-credible B-roll)
# Generates: ../assets/04-cli-tour.mp4
# Run from repo root: vhs docs/marketing/recordings/04-cli-tour.tape

Output docs/marketing/assets/04-cli-tour.mp4

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

Type "# A real CLI — not a toy. 16 commands, fail-closed quality gates."
Enter
Sleep 2s
Type ""
Enter

Type "dd-agents --help"
Enter
Sleep 5s
Type ""
Enter

Type "# Validate a deal config (fail-closed)"
Enter
Type "dd-agents validate examples/project-atlas/deal-config.json"
Enter
Sleep 4s
Type ""
Enter

Type "# Score a data room before you spend a dollar of LLM budget"
Enter
Type "dd-agents assess examples/project-atlas/sample_data_room"
Enter
Sleep 5s
