"""Loader for the built-in agent prompt Markdown (source-of-truth for prompt prose).

Three entry points:

* :func:`load_builtin_specialist` — parse ``specialists/{agent}.md`` into a
  :class:`BuiltinPrompt` (``role`` / ``specialist_focus`` / ``domain_guidance``),
  with severity-threshold placeholders resolved.
* :func:`load_named_prompt` — read a whole-body prompt
  (``synthesis/*.md``, ``auto_config/*.md``) as a single resolved string.
* :func:`load_search_templates` — rebuild the ``PROMPT_TEMPLATES`` mapping from
  ``search/templates/*.md``.

Design rules (KISS, zero new dependencies):

* Front-matter is parsed with the same ``yaml`` already used by
  :mod:`dd_agents.customization.loader`; bodies are split on ``## Heading``.
* Numbers are placeholders (``{TFC_REVENUE_PCT}``) resolved via plain
  ``str.replace`` against :mod:`dd_agents.agents.severity_thresholds` — never
  ``str.format`` (the prompts contain literal ``{`` / ``}`` JSON braces).
* Fail-closed: unknown front-matter keys, an unresolved ``{…_PCT|_DAYS}``
  placeholder, or a missing required heading raises :class:`PromptLoadError`.
* Results are cached per resolved path so repeated assembly never re-reads disk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from dd_agents.agents import severity_thresholds as _thr

#: Root of the packaged prompt Markdown tree.
PROMPTS_DIR: Path = Path(__file__).resolve().parent

#: Severity-threshold placeholders → current value. Single source of truth is
#: ``severity_thresholds.py``; the Markdown references these names, never the literals.
_THRESHOLD_PLACEHOLDERS: dict[str, int] = {
    "TFC_REVENUE_PCT": _thr.TFC_REVENUE_PCT,
    "TFC_NOTICE_DAYS": _thr.TFC_NOTICE_DAYS,
    "ARR_MISMATCH_P1_PCT": _thr.ARR_MISMATCH_P1_PCT,
    "ARR_MISMATCH_P2_PCT": _thr.ARR_MISMATCH_P2_PCT,
    "COC_REVENUE_PCT": _thr.COC_REVENUE_PCT,
    "COC_AUTOTERM_REVENUE_PCT": _thr.COC_AUTOTERM_REVENUE_PCT,
}

#: Detects a leftover threshold-shaped placeholder so a typo fails closed rather
#: than silently shipping ``{TFC_REVENU_PCT}`` to the model.
_UNRESOLVED_PLACEHOLDER = re.compile(r"\{[A-Z][A-Z0-9_]*_(?:PCT|DAYS)\}")


class PromptLoadError(Exception):
    """Raised when a built-in prompt Markdown file is missing or malformed (fail-closed)."""


def resolve_thresholds(text: str) -> str:
    """Substitute ``{NAME}`` severity-threshold placeholders with their integer values.

    Uses literal replacement (not ``str.format``) so the JSON braces that pervade
    these prompts are untouched. Fail-closed on an unresolved threshold-shaped
    placeholder.
    """
    for name, value in _THRESHOLD_PLACEHOLDERS.items():
        text = text.replace("{" + name + "}", str(value))
    leftover = _UNRESOLVED_PLACEHOLDER.search(text)
    if leftover:
        raise PromptLoadError(
            f"unresolved severity-threshold placeholder {leftover.group(0)!r} — "
            f"known placeholders: {sorted(_THRESHOLD_PLACEHOLDERS)}"
        )
    return text


@dataclass(frozen=True)
class BuiltinPrompt:
    """Parsed built-in specialist prompt sections (placeholders already resolved)."""

    agent: str
    role: str
    specialist_focus: str
    domain_guidance: str


def _split_front_matter(raw: str) -> tuple[dict[str, Any], str]:
    """Split a ``---`` YAML front-matter block from the Markdown body.

    Front-matter is optional for built-in prompts (unlike user override files);
    a file with no leading ``---`` is treated as all-body.
    """
    if not raw.startswith("---"):
        return {}, raw
    parts = raw.split("---", 2)
    if len(parts) < 3:
        raise PromptLoadError("front-matter opened with '---' but never closed")
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - defensive
        raise PromptLoadError(f"invalid YAML front-matter: {exc}") from exc
    if not isinstance(meta, dict):
        raise PromptLoadError("front-matter must be a mapping")
    return meta, parts[2]


#: The exactly-three top-level section headings a specialist prompt file carries.
#: We split ONLY on these so the section bodies may themselves contain ``##``/``###``
#: markdown (the domain-guidance prose is richly sub-headed) without being mis-split.
_SPECIALIST_HEADINGS: frozenset[str] = frozenset({"Role", "Specialist Focus", "Domain Guidance"})


def _split_sections(body: str, known_headings: frozenset[str] = _SPECIALIST_HEADINGS) -> dict[str, str]:
    """Split a Markdown body into ``{heading: content}`` on ``## <known heading>`` lines.

    Only ``## `` lines whose text is in *known_headings* start a new section; any
    other ``##``/``###`` line is ordinary content within the current section.
    """
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in body.splitlines():
        if line.startswith("## ") and line[3:].strip() in known_headings:
            if current is not None:
                sections[current] = "\n".join(buf).strip("\n")
            current = line[3:].strip()
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip("\n")
    return sections


@cache
def _read(path: Path) -> str:
    if not path.is_file():
        raise PromptLoadError(f"built-in prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


@cache
def load_builtin_specialist(agent: str) -> BuiltinPrompt:
    """Load and parse ``specialists/{agent}.md`` into a resolved :class:`BuiltinPrompt`."""
    raw = _read(PROMPTS_DIR / "specialists" / f"{agent}.md")
    _, body = _split_front_matter(raw)
    sections = _split_sections(body)
    missing = {"Role", "Specialist Focus", "Domain Guidance"} - set(sections)
    if missing:
        raise PromptLoadError(f"specialist prompt {agent!r} missing required heading(s): {sorted(missing)}")
    return BuiltinPrompt(
        agent=agent,
        role=resolve_thresholds(sections["Role"]),
        specialist_focus=resolve_thresholds(sections["Specialist Focus"]),
        domain_guidance=resolve_thresholds(sections["Domain Guidance"]),
    )


@cache
def load_named_prompt(category: str, name: str) -> str:
    """Load a whole-body prompt (``{category}/{name}.md``) as a resolved string.

    Used for synthesis and auto-config prompts that are single bodies rather than
    section-structured specialist prompts. Any front-matter is ignored; the body
    is returned verbatim (placeholders resolved, trailing newline stripped).
    """
    raw = _read(PROMPTS_DIR / category / f"{name}.md")
    _, body = _split_front_matter(raw)
    return resolve_thresholds(body.strip("\n"))


@cache
def load_search_templates() -> dict[str, dict[str, Any]]:
    """Rebuild the ``PROMPT_TEMPLATES`` mapping from ``search/templates/*.md``.

    Each file's front-matter carries ``id``/``name``/``description``; the body
    holds ``### Column Name`` blocks whose text is the column prompt. Returns the
    same ``{id: {name, description, columns: [{name, prompt}]}}`` shape the search
    command consumes.
    """
    templates: dict[str, dict[str, Any]] = {}
    tdir = PROMPTS_DIR / "search" / "templates"
    for path in sorted(tdir.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        meta, body = _split_front_matter(raw)
        tid = str(meta.get("id") or path.stem)
        columns: list[dict[str, str]] = []
        current: str | None = None
        buf: list[str] = []
        for line in body.splitlines():
            if line.startswith("### "):
                if current is not None:
                    columns.append({"name": current, "prompt": "\n".join(buf).strip()})
                current = line[4:].strip()
                buf = []
            elif current is not None:
                buf.append(line)
        if current is not None:
            columns.append({"name": current, "prompt": "\n".join(buf).strip()})
        templates[tid] = {
            "name": str(meta.get("name") or tid),
            "description": str(meta.get("description") or ""),
            "columns": columns,
        }
    return templates
