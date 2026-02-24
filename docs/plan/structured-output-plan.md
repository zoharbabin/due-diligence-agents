# Structured LLM Output via Claude Agent SDK `output_format`

> Implementation plan for Issue #4.
> Branch: `feat/issue-4-structured-output`

## Context

Replace fragile prompt-based JSON parsing in `analyzer.py` with Claude's native
**structured output** via the `output_format` parameter on `ClaudeAgentOptions`.
Uses constrained decoding — the model physically cannot produce tokens that
violate the schema — eliminating an entire class of parsing bugs with **zero new
dependencies**.

### Why not `instructor`?

`instructor` requires patching a real LLM client's `.create()` method (e.g.,
`anthropic.AsyncAnthropic`). Our project calls all LLMs through
`claude_agent_sdk.query()` — an opaque subprocess wrapper. Per `CLAUDE.md`: "ALL
LLM calls MUST go through `claude_agent_sdk`". The SDK already supports structured
output natively via `output_format` on `ClaudeAgentOptions`.

---

## Phase 1: Schema Builder + `_call_claude` Enhancement

### 1a. `_build_analysis_schema(column_names)` in `analyzer.py`

Builds a JSON Schema dict dynamically from column names. Key constraints:

- `confidence` uses `enum: ["HIGH", "MEDIUM", "LOW"]`
- All citation fields (`file_path`, `page`, `section_ref`, `exact_quote`) required
- `additionalProperties: false` on all objects
- All column names in top-level `required`

### 1b. Enhance `_call_claude` signature

Add optional `output_schema: dict[str, Any] | None = None` parameter.
When provided, pass as `output_format={"type": "json_schema", "schema": schema}`
on `ClaudeAgentOptions`.

### 1c. Three schema variants

| Phase | Columns in Schema |
|-------|-------------------|
| Phase 1 (Map) | All `self._prompts.columns` |
| Phase 3 (Synthesis) | Only `conflicted_columns` |
| Phase 4 (Validation) | Only `not_addressed` columns |

---

## Phase 2: Simplify Response Parsing

- Delete `raw_decode()` + `rfind("}")` fallback chain from `_extract_json_text()`
- Keep markdown fence stripping as safety net
- Empty `{}` / missing column checks → defensive assertions

---

## Phase 3: Simplify Prompts

- Remove "Return ONLY raw JSON" boilerplate from system, synthesis, and validation prompts
- Prompts focus on analysis quality, not formatting instructions

---

## Phase 4: Tests

- Add `TestAnalysisSchema` class (5 tests)
- Update `_call_claude` mock signatures
- All 997+ existing tests remain valid

---

## Verification

```bash
pytest tests/unit/ -x -q && mypy src/ --strict && ruff check src/ tests/
```
