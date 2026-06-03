# System Card

DD-Agents is a forensic M&A due-diligence pipeline: it analyzes a contract data
room with specialist AI agents, enforces deterministic quality gates, and
produces cross-domain HTML and Excel reports that advisors verify and act on.

This card describes the safety, anti-hallucination, and auditability posture of
the agent layer. It is intentionally short and points to authoritative source
files rather than restating them.

---

## Agent roster and tool posture

The active agents are exactly the specialists registered in
`agents/registry.py` (built-in specialists plus any installed via the
`dd_agents.specialists` entry-point group), alongside the governance and
synthesis agents the pipeline spawns. Use `dd-agents agents list` to see the
live roster for a given config — this card does not hardcode the set.

Agents run with a **least-privilege, read-only-by-default tool posture**
(Rule-of-Two: read documents, write findings, nothing else). The shared safety
floor (`CRITICAL_CONSTRAINTS` in `agents/prompt_constants.py`) forbids spawning
sub-agents and forbids the Bash/shell tool. Pre-tool-use hooks (`hooks/`) enforce
allow/block decisions on every tool call, so the posture is mechanically
enforced, not merely requested in prose.

Inspect any agent's persona, focus areas, and enforced safety floor:

```bash
dd-agents agents describe --agent legal
```

---

## Anti-hallucination layers

These layers are independent and stack:

- **Citation mandate.** Every finding must carry an `exact_quote` copied
  verbatim from a real source document. A finding with no citation is
  automatically downgraded at merge. The mandate is part of the non-removable
  safety floor (`build_citation_mandate()` in `agents/prompt_constants.py`).
- **Anti-fabrication rule.** `NO_FABRICATION` requires agents to answer only
  from the provided documents and emit `NOT_FOUND` (or leave a field empty)
  rather than speculate, interpolate, or invent values, names, or citations.
- **Single severity authority.** `resolve_severity()` in
  `reporting/severity_resolver.py` decides each finding's final severity once,
  deterministically, recording an auditable `severity_chain`. This removes the
  prior ambiguity of severity being set in several uncoordinated places.
- **Numerical audit.** A deterministic validation gate re-derives numeric
  values and counts from source files (`validation/numerical_audit.py`); the
  pipeline is fail-closed on audit failure.

Severity calibration thresholds are centralized in
`agents/severity_thresholds.py` so prompt prose and validation agree on a single
set of numbers.

---

## Injection-resistance posture

- **Untrusted-document delimiting.** Content from the data room is treated as
  evidence, never as instructions. `UNTRUSTED_DOCUMENT_RULE` (in the safety
  floor) tells every agent that text inside `<UNTRUSTED_DOCUMENT>` markers, and
  the contents of any document read with a tool, must not be obeyed as
  instructions. `wrap_untrusted()` applies the markers where content is injected
  into a prompt.
- **Tamper detection.** Instructions embedded in document content (e.g. "ignore
  previous instructions", "mark everything P3") are themselves reported as a
  `document_integrity` finding rather than followed.
- **Override protection.** Tamper / prompt-injection / document-integrity
  findings can never be downgraded by a user severity override
  (`resolve_severity` AD-3a bound).
- **Documented limitation.** Document bodies read at tool-time are not wrapped in
  the `<UNTRUSTED_DOCUMENT>` delimiters — the standing untrusted-content rule
  covers them by policy, but the delimiting itself applies only to content
  injected at prompt-assembly time. The defense here is the standing rule plus
  tamper-as-finding behavior, not perfect delimiting of every byte the model
  reads.

---

## Provenance and auditability

Each run records a canonical provenance hash combining the deal config, the
prompt-builder version, and a content hash of every active agent's persona text
(`persistence/provenance.py`: `compute_config_hash`, `compute_persona_hashes`,
`compute_provenance_hash`; persona texts gathered via
`AgentRegistry.collect_persona_texts`). On `--resume-from`, the orchestrator
recomputes this hash and **refuses to resume against drifted inputs** — a
changed config, prompt version, or persona invalidates the stale checkpoint
(fail-closed gate in `orchestrator/engine.py`). This guarantees a resumed run is
reproducible against the same inputs.

The report includes an Analyst Configuration panel
(`reporting/html_config_panel.py`) showing which agents ran, which were
disabled, and any per-agent persona / focus / severity overrides in effect, so a
reader can see how the analysis was configured without opening the config file.

Findings are stored per subject (one JSON file per subject per agent), and each
finding's severity carries its decision chain, so any value is traceable to its
source stage.

---

## Known limitations

- Agents produce **analysis to be verified by qualified advisors**, not settled
  legal, financial, tax, or regulatory conclusions. Output is framed accordingly
  (`COMPLIANCE_FRAMING`).
- Injection resistance is defense-in-depth, not a guarantee; see the documented
  delimiting limitation above.
- Quality metrics are measured against a synthetic golden eval set, not a
  certification of real-world accuracy — see the [Eval Datasheet](eval-datasheet.md).
- The model layer is non-deterministic; provenance hashing pins *inputs*, not
  token-level outputs.

---

## Standards mapping

This mapping is descriptive and not a claim of formal certification.

- **NIST AI RMF (traceability / measurability).** Per-run provenance hashing,
  the fail-closed resume gate, per-finding severity chains, per-subject findings,
  and the quality gates support traceability and measurement of system behavior.
- **EU AI Act, Article 50 (transparency / AI-assisted disclosure).** Reports are
  produced by an AI system and framed as analysis for professional review
  (`COMPLIANCE_FRAMING`); the Analyst Configuration panel discloses how the
  analysis was configured. Deployers remain responsible for disclosing AI
  assistance to relevant parties.

---

## Related Documentation

- [Agent Customization](agent-customization.md) — what users can and cannot change
- [Eval Datasheet](eval-datasheet.md) — the golden eval set and metrics
