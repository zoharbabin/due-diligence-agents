# Due Diligence Agents — targeted search with citation (the "proof" shot)
# Generates: ../assets/03-search-cite.mp4
# Run from repo root: vhs docs/marketing/recordings/03-search-cite.tape
#
# Captures the forensic-proof moment: ask a targeted question, get an answer traced
# to an exact file + section + verbatim quote. The whole brand promise in one command.
# Requires the real run (text index built). Adjust the prompt path to a real search
# prompts file if using `dd-agents search`; this tape uses the single-question `query`.

Output docs/marketing/assets/03-search-cite.mp4

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

Type "# Ask a forensic question. Get an answer you can verify."
Enter
Sleep 1.5s
Type ""
Enter
Type "dd-agents query 'Does any major customer have a change-of-control termination right?' --data-room examples/project-atlas/sample_data_room"
Enter
# Answer scrolls with the cited quote (Meridian MSA section 12.3). Trim + cursor-zoom the citation in post.
Sleep 45s
Type ""
Enter
Type "# Answer cites Meridian Freight MSA 12.3 — verbatim. Not a guess."
Enter
Sleep 3s

# NOTE: confirm exact flags with `dd-agents query --help` / `dd-agents search --help`
# after the run; wire the precise invocation before recording.
