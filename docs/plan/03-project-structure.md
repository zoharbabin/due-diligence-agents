# 03 — Project Structure

> **Historical design spec, reduced to its durable parts.** The file-by-file
> repository layout that once lived here was a hand-maintained mirror of
> `src/dd_agents/` that drifted from the code. For the current package map, the
> authoritative source is the **Architecture Map in `CLAUDE.md`** (it annotates
> each package and its entry point and references source files, so it can't go
> stale), plus the live `src/dd_agents/` tree and `pyproject.toml`. What remains
> below are the stable *design contracts* — the layering rules and architectural
> constraints — which hold regardless of how individual files move.

## Where to look

| You want… | Look at |
|---|---|
| The package map (one line per package + entry point) | `CLAUDE.md` → *Architecture Map* |
| The actual module layout | `src/dd_agents/` |
| Dependencies, extras, entry point, build config | `pyproject.toml` |
| How to add an agent / report section / pipeline step / hook | `CLAUDE.md` → *Key Patterns* |

## Dependency Rules

The import graph is a DAG. These rules are load-bearing — a violation is a
review-blocking defect:

1. **Models are leaf modules.** Files under `models/` import only `pydantic` and
   other model files — never orchestrator, agents, extraction, or any runtime module.
2. **No circular imports.** The orchestrator sits at the top of the DAG; models sit at the bottom.
3. **`utils/constants.py` is the true leaf.** Zero internal imports; importable by every other module.
4. **Agents depend on hooks and tools**, not the reverse. Hooks and tools import from `models` only.
5. **The orchestrator is the composition root.** It imports everything and wires the modules together.

## Key Architectural Constraints

1. **Flat model imports.** Every model is importable from `dd_agents.models` via the `__init__.py` re-export.
2. **Config files ship outside `src/`.** `deal-config.template.json`, `deal-config.schema.json`, and
   `report_schema.json` live in `config/` at the repo root and are referenced by path at runtime.
3. **Entry point is `cli.py`** registered via `[project.scripts]` (`dd-agents = "dd_agents.cli:main"`).
4. **Tests mirror source structure.** Unit tests cover models and pure functions; integration tests use a
   sample data-room fixture; E2E tests require an API key and run the full pipeline.
5. **Vector store is fully optional.** Every `vector_store` code path checks for ChromaDB availability and
   degrades gracefully when it is absent.
