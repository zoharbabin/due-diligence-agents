"""Agent runners for screening officer discovery and profile research (Issue #274).

Not specialists: they write no per-subject findings and are not in the agent
registry. ``dd_agents.screening.research`` validates what they write.

Isolation is the point of having two runners:

* ``OfficerDiscoveryRunner`` reads data room text and has no web tools.
* ``ProfileResearchRunner`` has web tools and cannot read the data room.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dd_agents.agents.base import BaseAgentRunner
from dd_agents.agents.prompts.loader import load_named_prompt

if TYPE_CHECKING:
    from pathlib import Path

    from dd_agents.models.config import DealConfig
    from dd_agents.tools.external_mcp import ExternalAccess


class OfficerDiscoveryRunner(BaseAgentRunner):
    coverage_stop_guard = False
    max_turns: int = 40

    def get_agent_name(self) -> str:
        return "officer_discovery"

    def get_system_prompt(self) -> str:
        return load_named_prompt("screening", "officer_discovery")

    def get_tools(self) -> list[str]:
        return ["Read", "Write", "Glob", "Grep"]


class ProfileResearchRunner(BaseAgentRunner):
    coverage_stop_guard = False
    max_turns: int = 60

    def __init__(
        self,
        project_dir: Path,
        run_dir: Path,
        run_id: str,
        deal_config: DealConfig | None = None,
        *,
        access: ExternalAccess,
    ) -> None:
        super().__init__(project_dir, run_dir, run_id, deal_config)
        self._access = access

    def get_agent_name(self) -> str:
        return "profile_research"

    def get_system_prompt(self) -> str:
        return load_named_prompt("screening", "profile_research")

    def get_tools(self) -> list[str]:
        return ["Write"]

    def get_external_access(self) -> ExternalAccess | None:
        return self._access
