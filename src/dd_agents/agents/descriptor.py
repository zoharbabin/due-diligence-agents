"""AgentDescriptor — frozen metadata for specialist agents.

Every specialist agent registers an ``AgentDescriptor`` with the
``AgentRegistry``.  Downstream systems (reporting, validation, merge,
prompt building) read descriptors instead of importing agent classes
directly, decoupling them from the agent implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dd_agents.agents.base import BaseAgentRunner

# 12 visually distinct colours pre-assigned for built-in + future agents.
# Chosen for WCAG 2.1 AA contrast on white backgrounds.
DEFAULT_AGENT_COLORS: dict[str, str] = {
    "legal": "#4a90d9",
    "finance": "#2d8a4e",
    "commercial": "#7c3aed",
    "producttech": "#d97706",
    "hr": "#c2185b",
    "tax": "#00838f",
    "cybersecurity": "#4e342e",
    "regulatory": "#6a1b9a",
    "esg": "#2d6a4f",
    "insurance": "#1565c0",
    "operations": "#ef6c00",
    "ip": "#ad1457",
}


@dataclass(frozen=True)
class AgentDescriptor:
    """Immutable metadata describing a specialist agent.

    Fields are consumed by different pipeline subsystems:
    - Reporting: ``display_name``, ``color``
    - Validation: ``name``
    - Prompts: ``focus_areas``, ``specialist_focus``, ``citation_examples``
    - Spawning: ``agent_class``, ``max_subjects_per_batch``, ``max_tokens_per_batch``
    - Reference routing: ``reference_categories``
    """

    name: str
    display_name: str
    color: str
    focus_areas: tuple[str, ...]
    reference_categories: tuple[str, ...]
    agent_class: type[BaseAgentRunner]
    specialist_focus: str
    citation_examples: str = ""
    max_subjects_per_batch: int = 20
    max_tokens_per_batch: int = 40_000
    is_builtin: bool = True
    source_package: str = ""
    # Additional prompt text appended after specialist_focus.
    domain_robustness: str = ""
