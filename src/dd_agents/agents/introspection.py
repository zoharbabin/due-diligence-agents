"""Agent introspection surface (§6.1/§6.4) — pure, no Click.

Renders / validates / previews exactly what the pipeline assembles, so the
``dd-agents agents`` CLI has no parallel prompt logic. Reads from the
:class:`AgentRegistry`, agent descriptors, the safety floor, and the
customization loader.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from dd_agents.agents.prompt_constants import SAFETY_FLOOR_NEGATION_PATTERNS, assemble_safety_floor
from dd_agents.agents.registry import AgentRegistry

if TYPE_CHECKING:
    from dd_agents.models.config import DealConfig

#: Valid severity tokens for the `## Severity Overrides` heading.
_SEVERITY_RE = re.compile(r"^P[0-3]$")


@dataclass(frozen=True)
class AgentSummary:
    """Display row for ``dd-agents agents list``."""

    name: str
    display_name: str
    status: str  # "enabled" | "disabled"
    model: str | None


@dataclass(frozen=True)
class ValidationIssue:
    """A single lint finding for ``dd-agents agents validate``."""

    level: str  # "error" | "warning"
    message: str


def list_agents(deal_config: DealConfig | None = None) -> list[AgentSummary]:
    """Return one :class:`AgentSummary` per registered specialist agent."""
    all_names = AgentRegistry.all_specialist_names()
    active = set(AgentRegistry.resolve_active(deal_config))

    model_resolver = None
    if deal_config is not None:
        model_resolver = getattr(deal_config, "agent_models", None)

    summaries: list[AgentSummary] = []
    for name in all_names:
        descriptor = AgentRegistry.get(name)
        model: str | None = None
        if model_resolver is not None:
            try:
                model = model_resolver.resolve_model(name)
            except Exception:  # noqa: BLE001 — introspection must not crash
                model = None
        summaries.append(
            AgentSummary(
                name=name,
                display_name=descriptor.display_name,
                status="enabled" if name in active else "disabled",
                model=model,
            )
        )
    return summaries


def describe_agent(name: str) -> str:
    """Render an agent's persona, focus areas, and safety floor as markdown."""
    descriptor = AgentRegistry.get(name)

    parts: list[str] = [f"# {descriptor.display_name} Agent (`{name}`)", ""]

    # Persona / role — from the runner's static system prompt.
    placeholder = Path("/nonexistent")
    try:
        runner = descriptor.agent_class(project_dir=placeholder, run_dir=placeholder, run_id="describe")
        persona = runner.get_system_prompt()
    except Exception:  # noqa: BLE001
        persona = ""
    if persona:
        parts += ["## Persona", "", persona, ""]

    if descriptor.focus_areas:
        parts += ["## Focus Areas", ""]
        parts += [f"- {area.replace('_', ' ')}" for area in descriptor.focus_areas]
        parts += [""]

    if descriptor.specialist_focus:
        parts += ["## Specialist Focus", "", descriptor.specialist_focus, ""]

    if descriptor.domain_robustness:
        parts += ["## Domain Guidance", "", descriptor.domain_robustness, ""]

    # The non-removable safety floor (includes the citation mandate).
    parts += ["## Safety Floor (always enforced)", "", assemble_safety_floor(name), ""]

    return "\n".join(parts)


def validate_customizations(project_dir: Path) -> list[ValidationIssue]:
    """Lint the ``dd-config/`` customizations under *project_dir* (fail-closed)."""
    from dd_agents.customization.loader import (
        BUNDLED_PROFILES_DIR,
        CustomizationError,
        parse_persona_file,
        resolve_chain,
    )

    dd_config_dir = project_dir / "dd-config"
    if not dd_config_dir.is_dir():
        return []

    issues: list[ValidationIssue] = []
    known_agents = set(AgentRegistry.all_specialist_names())

    agents_dir = dd_config_dir / "agents"
    if not agents_dir.is_dir():
        return issues

    for agent_file in sorted(agents_dir.glob("*.md")):
        agent = agent_file.stem

        if agent not in known_agents:
            issues.append(
                ValidationIssue(
                    level="error",
                    message=f"Unknown agent '{agent}' (file '{agent_file.name}'). Known: {sorted(known_agents)}",
                )
            )

        # Parse the file (fail-closed on malformed content).
        try:
            layer = parse_persona_file(agent_file)
        except CustomizationError as exc:
            issues.append(ValidationIssue(level="error", message=f"{agent_file.name}: {exc}"))
            continue

        cust = layer.customization

        # Front-matter `agent:` must match the filename stem when declared.
        if layer.agent is not None and layer.agent != agent:
            issues.append(
                ValidationIssue(
                    level="error",
                    message=(f"agent: '{layer.agent}' in front-matter does not match filename '{agent}.md'"),
                )
            )

        # Empty persona heading present but blank. The loader collapses empty
        # content to None, so detect the heading-with-no-body from the raw text.
        raw_text = agent_file.read_text(encoding="utf-8")
        if "## Persona (replaces default)" in raw_text and not cust.persona:
            issues.append(ValidationIssue(level="error", message=f"{agent_file.name}: empty persona override."))

        # Severity tokens must match P0-P3.
        for category, severity in cust.severity_overrides.items():
            if not _SEVERITY_RE.match(severity):
                issues.append(
                    ValidationIssue(
                        level="error",
                        message=f"{agent_file.name}: severity '{severity}' for '{category}' is not P0-P3.",
                    )
                )

        # Safety-floor negation deny-list across all editable text.
        editable = "\n".join(
            [
                cust.persona or "",
                cust.extra_instructions or "",
                *cust.extra_focus_areas,
                *cust.severity_overrides.keys(),
            ]
        )
        for pattern in SAFETY_FLOOR_NEGATION_PATTERNS:
            if pattern.search(editable):
                issues.append(
                    ValidationIssue(
                        level="error",
                        message=(
                            f"{agent_file.name}: text matches a safety-floor-negation pattern "
                            f"('{pattern.pattern}') — the safety floor cannot be overridden."
                        ),
                    )
                )

        # Extends cycle / missing profile (catch CustomizationError).
        if layer.extends is not None:
            try:
                resolve_chain(
                    agent,
                    dd_config_dir=dd_config_dir,
                    deal_cust=None,
                    profiles_dir=BUNDLED_PROFILES_DIR,
                )
            except CustomizationError as exc:
                issues.append(ValidationIssue(level="error", message=f"{agent_file.name}: {exc}"))

    return issues


def preview_prompt(agent_name: str, project_dir: Path | None = None) -> str:
    """Render the fully assembled specialist prompt for *agent_name*.

    Uses synthetic subjects ``["Subject A"]`` and a minimal deal_config so the
    output is byte-identical to what the pipeline would build for that input.
    No disk writes.
    """
    from dd_agents.agents.prompt_builder import PromptBuilder

    base_dir = project_dir if project_dir is not None else Path.cwd()
    builder = PromptBuilder(project_dir=base_dir, run_dir=base_dir, run_id="preview")
    deal_config = {
        "config_version": "1.0.0",
        "buyer": {"name": "B"},
        "target": {"name": "T"},
        "deal": {"type": "acquisition", "focus_areas": [agent_name]},
    }
    return builder.build_specialist_prompt(agent_name, ["Subject A"], deal_config=deal_config)
