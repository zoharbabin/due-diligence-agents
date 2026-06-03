"""Rule-of-Two security posture assertions (audit §7.3).

Every specialist agent is read + write-to-``_dd/`` only — no network or
exfiltration tools. Write/Edit outside ``_dd/`` is blocked by ``path_guard``,
and dangerous shell commands are blocked by ``bash_guard``.
"""

from __future__ import annotations

from pathlib import Path

from dd_agents.agents.registry import AgentRegistry
from dd_agents.hooks.pre_tool import bash_guard, path_guard

# Tool-name substrings that would indicate network / exfiltration capability.
_NETWORK_TOKENS: tuple[str, ...] = ("web", "fetch", "http", "curl", "browser", "mail")


def test_no_specialist_has_network_tool() -> None:
    names = AgentRegistry.all_specialist_names()
    assert names, "no specialist agents registered"
    placeholder = Path("/nonexistent")
    for name in names:
        descriptor = AgentRegistry.get(name)
        runner = descriptor.agent_class(project_dir=placeholder, run_dir=placeholder, run_id="rule-of-two")
        tools = runner.get_tools()
        for tool in tools:
            lowered = tool.lower()
            for token in _NETWORK_TOKENS:
                assert token not in lowered, f"agent '{name}' exposes network tool '{tool}' (token '{token}')"


def test_path_guard_blocks_write_outside_dd() -> None:
    result = path_guard("Write", {"file_path": "/etc/passwd"}, project_dir="/tmp/project")
    assert result["decision"] == "block"


def test_path_guard_allows_write_inside_dd() -> None:
    result = path_guard(
        "Write",
        {"file_path": "/tmp/project/_dd/findings/legal/subject_a.json"},
        project_dir="/tmp/project",
    )
    assert result["decision"] == "allow"


def test_bash_guard_blocks_dangerous_command() -> None:
    result = bash_guard("Bash", {"command": "rm -rf /"})
    assert result["decision"] == "block"
