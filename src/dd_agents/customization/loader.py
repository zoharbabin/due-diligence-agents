"""Customization loader — one format, one merge rule (AD-1/AD-5/§6.2/§6.7).

Parses ``dd-config/agents/{agent}.md`` markdown overrides (YAML front-matter +
markdown body), resolves the ``extends:`` profile chain against the bundled
profile library, and folds every layer with a single merge rule into a frozen
:class:`ResolvedCustomization`.

Pure module: no LLM calls, no Click, no pipeline imports beyond ``models``.
All loader errors are fail-closed (:class:`CustomizationError`).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from dd_agents.models.config import AgentCustomization

#: Default location of the bundled starter profile library.
BUNDLED_PROFILES_DIR: Path = Path(__file__).resolve().parent / "profiles"

#: Front-matter keys recognised in a persona file. Anything else is fail-closed.
_ALLOWED_FRONT_MATTER_KEYS: frozenset[str] = frozenset({"agent", "status", "model_profile", "extends"})

#: The exactly-four recognised ``##`` headings in the markdown body.
_HEADING_PERSONA = "Persona (replaces default)"
_HEADING_FOCUS = "Additional Focus Areas"
_HEADING_INSTRUCTIONS = "Additional Instructions"
_HEADING_SEVERITY = "Severity Overrides"
_ALLOWED_HEADINGS: frozenset[str] = frozenset(
    {_HEADING_PERSONA, _HEADING_FOCUS, _HEADING_INSTRUCTIONS, _HEADING_SEVERITY}
)


class CustomizationError(Exception):
    """Fail-closed loader error (malformed file, unknown key/heading, cycle)."""


@dataclass(frozen=True)
class PersonaLayer:
    """A single parsed persona file: customization + front-matter + content hash."""

    customization: AgentCustomization
    status: str
    model_profile: str | None
    extends: str | None
    content_hash: str
    agent: str | None = None


@dataclass(frozen=True)
class ResolvedCustomization:
    """The folded result of an agent's customization chain (frozen)."""

    agent: str
    customization: AgentCustomization
    model_profile: str | None
    layer_hashes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _split_front_matter(text: str) -> tuple[dict[str, object], str]:
    """Split leading ``---`` YAML front-matter from the markdown body."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        # No front-matter — treat the whole file as body.
        return {}, text

    # Find the closing fence.
    closing = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            closing = idx
            break
    if closing is None:
        raise CustomizationError("Unterminated YAML front-matter (missing closing '---').")

    fm_text = "\n".join(lines[1:closing])
    body = "\n".join(lines[closing + 1 :])
    try:
        parsed = yaml.safe_load(fm_text) if fm_text.strip() else {}
    except yaml.YAMLError as exc:
        raise CustomizationError(f"Malformed YAML front-matter: {exc}") from exc
    if parsed is None:
        parsed = {}
    if not isinstance(parsed, dict):
        raise CustomizationError("YAML front-matter must be a mapping.")
    return parsed, body


def _parse_body(body: str) -> dict[str, str]:
    """Group the markdown body into ``{heading: content}`` for known headings."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            heading = stripped[3:].strip()
            if heading not in _ALLOWED_HEADINGS:
                raise CustomizationError(f"Unknown heading '## {heading}'. Allowed: {sorted(_ALLOWED_HEADINGS)}")
            current = heading
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return {h: "\n".join(lines).strip() for h, lines in sections.items()}


def _parse_bullets(content: str) -> list[str]:
    """Extract ``- `` bullet items from a section body, preserving order."""
    items: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            items.append(stripped[2:].strip())
    return items


def _parse_severity_overrides(content: str) -> dict[str, str]:
    """Parse ``- category: P1`` bullets into a severity override map."""
    overrides: dict[str, str] = {}
    for item in _parse_bullets(content):
        if ":" not in item:
            raise CustomizationError(f"Malformed severity override bullet (expected 'category: P1'): '{item}'")
        category, _, severity = item.partition(":")
        overrides[category.strip()] = severity.strip()
    return overrides


def parse_persona_file(path: Path) -> PersonaLayer:
    """Parse a persona markdown file into a :class:`PersonaLayer` (fail-closed)."""
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise CustomizationError(f"Cannot read persona file '{path}': {exc}") from exc

    content_hash = hashlib.sha256(raw_bytes).hexdigest()
    text = raw_bytes.decode("utf-8")

    front_matter, body = _split_front_matter(text)
    unknown_keys = set(front_matter) - _ALLOWED_FRONT_MATTER_KEYS
    if unknown_keys:
        raise CustomizationError(
            f"Unknown front-matter key(s) {sorted(unknown_keys)}. Allowed: {sorted(_ALLOWED_FRONT_MATTER_KEYS)}"
        )

    sections = _parse_body(body)

    persona = sections.get(_HEADING_PERSONA) or None
    extra_focus_areas = _parse_bullets(sections.get(_HEADING_FOCUS, "")) if _HEADING_FOCUS in sections else []
    extra_instructions = sections.get(_HEADING_INSTRUCTIONS, "") if _HEADING_INSTRUCTIONS in sections else ""
    severity_overrides = (
        _parse_severity_overrides(sections.get(_HEADING_SEVERITY, "")) if _HEADING_SEVERITY in sections else {}
    )

    customization = AgentCustomization(
        persona=persona,
        extra_focus_areas=extra_focus_areas,
        extra_instructions=extra_instructions,
        severity_overrides=severity_overrides,
    )

    status = str(front_matter.get("status", "") or "")
    model_profile_raw = front_matter.get("model_profile")
    model_profile = str(model_profile_raw) if model_profile_raw is not None else None
    extends_raw = front_matter.get("extends")
    extends = str(extends_raw) if extends_raw is not None else None
    agent_raw = front_matter.get("agent")
    agent = str(agent_raw) if agent_raw is not None else None

    return PersonaLayer(
        customization=customization,
        status=status,
        model_profile=model_profile,
        extends=extends,
        content_hash=content_hash,
        agent=agent,
    )


# ---------------------------------------------------------------------------
# Merge — the ONE merge rule
# ---------------------------------------------------------------------------


def _dedup_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _merge(a: AgentCustomization, b: AgentCustomization) -> AgentCustomization:
    """Fold *b* onto *a* with the single merge rule.

    - scalars (persona): b-wins-if-set-else-a.
    - lists (extra_focus_areas): a + b, dedup preserving order.
    - maps (severity_overrides): ``{**a, **b}``.
    - extra_instructions: ``a + "\\n\\n" + b`` if both set, else whichever is set.
    """
    persona = b.persona if b.persona is not None else a.persona

    extra_focus_areas = _dedup_preserve_order([*a.extra_focus_areas, *b.extra_focus_areas])

    severity_overrides = {**a.severity_overrides, **b.severity_overrides}

    if a.extra_instructions and b.extra_instructions:
        extra_instructions = a.extra_instructions + "\n\n" + b.extra_instructions
    else:
        extra_instructions = a.extra_instructions or b.extra_instructions

    return AgentCustomization(
        persona=persona,
        extra_focus_areas=extra_focus_areas,
        extra_instructions=extra_instructions,
        severity_overrides=severity_overrides,
    )


# ---------------------------------------------------------------------------
# Chain resolution
# ---------------------------------------------------------------------------


def _resolve_profile_chain(
    start: str,
    profiles_dir: Path,
) -> list[PersonaLayer]:
    """Resolve a profile ``extends`` chain into ordered layers (base → leaf).

    Follows each profile's front-matter ``extends`` left-to-right. Detects
    cycles via a seen-set (raises on repeat). Returns layers in
    base-first order so that later (more specific) layers merge on top.
    """
    chain: list[PersonaLayer] = []
    seen: set[str] = set()
    name: str | None = start
    while name is not None:
        if name in seen:
            raise CustomizationError(f"Cyclic 'extends' chain detected at profile '{name}'.")
        seen.add(name)
        profile_path = profiles_dir / f"{name}.md"
        if not profile_path.exists():
            raise CustomizationError(f"Profile '{name}' not found at '{profile_path}'.")
        layer = parse_persona_file(profile_path)
        chain.append(layer)
        name = layer.extends
    # chain currently leaf→base; reverse so base merges first.
    chain.reverse()
    return chain


def resolve_chain(
    agent: str,
    dd_config_dir: Path | None,
    deal_cust: AgentCustomization | None,
    profiles_dir: Path,
) -> ResolvedCustomization:
    """Resolve the full customization chain for *agent* and fold it.

    Layer order (each folds onto the previous with :func:`_merge`):
      built-in (empty) → resolved ``extends`` profile chain → the
      ``{dd_config_dir}/agents/{agent}.md`` override → ``deal_cust``.

    The ``extends`` entry point is the dd-config agent file's front-matter.
    """
    merged = AgentCustomization()  # built-in baseline (empty)
    layer_hashes: list[str] = []
    model_profile: str | None = None

    agent_file_layer: PersonaLayer | None = None
    if dd_config_dir is not None:
        agent_file = dd_config_dir / "agents" / f"{agent}.md"
        if agent_file.exists():
            agent_file_layer = parse_persona_file(agent_file)

    # Resolve the profile chain declared by the agent file's `extends`.
    if agent_file_layer is not None and agent_file_layer.extends is not None:
        for profile_layer in _resolve_profile_chain(agent_file_layer.extends, profiles_dir):
            merged = _merge(merged, profile_layer.customization)
            layer_hashes.append(profile_layer.content_hash)
            if profile_layer.model_profile is not None:
                model_profile = profile_layer.model_profile

    # Apply the dd-config agent override file.
    if agent_file_layer is not None:
        merged = _merge(merged, agent_file_layer.customization)
        layer_hashes.append(agent_file_layer.content_hash)
        if agent_file_layer.model_profile is not None:
            model_profile = agent_file_layer.model_profile

    # Apply the deal-config customization (highest precedence).
    if deal_cust is not None:
        merged = _merge(merged, deal_cust)

    return ResolvedCustomization(
        agent=agent,
        customization=merged,
        model_profile=model_profile,
        layer_hashes=layer_hashes,
    )


def load_dd_config(project_dir: Path) -> dict[str, ResolvedCustomization] | None:
    """Load and resolve customizations for every registered agent.

    Returns ``None`` when ``{project_dir}/dd-config/`` is absent (back-compat:
    the pipeline runs unchanged). Otherwise resolves every registered
    specialist agent's chain.
    """
    dd_config_dir = project_dir / "dd-config"
    if not dd_config_dir.is_dir():
        return None

    from dd_agents.agents.registry import AgentRegistry

    resolved: dict[str, ResolvedCustomization] = {}
    for agent in AgentRegistry.all_specialist_names():
        resolved[agent] = resolve_chain(
            agent,
            dd_config_dir=dd_config_dir,
            deal_cust=None,
            profiles_dir=BUNDLED_PROFILES_DIR,
        )
    return resolved
