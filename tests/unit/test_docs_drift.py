"""Documentation drift guard (CLAUDE.md "Docs anti-drift" rule).

Fails CI when user-facing docs contradict code-derived ground truth. The point
is mechanical: if someone adds a 10th specialist, a 39th step, or renames the
published Docker image, the docs that state those facts must change in the same
PR or this test goes red.

Scope is deliberately narrow to stay false-positive-free:
  * Only the *primary* user-facing docs are scanned (README, DOCKERHUB, the
    mkdocs site under docs/, excluding point-in-time marketing recordings).
  * Only a handful of stable, code-derivable invariants are asserted.
  * MCP @tool annotations are checked for the structural contracts CLAUDE.md
    promises (a non-empty description; read/write side-effect honesty).

Ground truth is read from code at test time — never hardcoded here — so the
guard tracks the code, not a second copy of the numbers.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Primary, current-state docs. Excludes docs/marketing/** (point-in-time
# recordings/decks).
_PRIMARY_DOCS = [
    "README.md",
    "DOCKERHUB.md",
    "docs/index.md",
    "docs/README.md",
    "docs/user-guide/getting-started.md",
    "docs/user-guide/deal-configuration.md",
    "docs/user-guide/running-pipeline.md",
    "docs/user-guide/reading-report.md",
    "docs/user-guide/cli-reference.md",
    "docs/user-guide/troubleshooting.md",
    "docs/agent-customization.md",
    "docs/search-guide.md",
    "docs/knowledge-architecture.md",
    "examples/quickstart/README.md",
]


def _doc_text() -> dict[str, str]:
    out: dict[str, str] = {}
    for rel in _PRIMARY_DOCS:
        p = REPO_ROOT / rel
        if p.exists():
            out[rel] = p.read_text(encoding="utf-8")
    return out


# --------------------------------------------------------------------------- #
# Code-derived ground truth
# --------------------------------------------------------------------------- #
def _specialist_count() -> int:
    import dd_agents.agents.specialists  # noqa: F401  (registers built-ins)
    from dd_agents.agents.registry import AgentRegistry

    return len(AgentRegistry.all_specialist_names())


def _total_agent_count() -> int:
    """Total agents docs headline as "N AI agents" = registered specialists +
    the non-specialist synthesis runners. The synthesis agents aren't registry-
    enumerated, so importing the classes here means dropping one (e.g. removing
    RedFlagScannerAgent) changes this number and trips the doc guard."""
    from dd_agents.agents.acquirer_intelligence import AcquirerIntelligenceAgent
    from dd_agents.agents.executive_synthesis import ExecutiveSynthesisAgent
    from dd_agents.agents.judge import JudgeAgent
    from dd_agents.agents.red_flag_scanner import RedFlagScannerAgent

    synthesis = {JudgeAgent, ExecutiveSynthesisAgent, RedFlagScannerAgent, AcquirerIntelligenceAgent}
    return _specialist_count() + len(synthesis)


def _pipeline_step_count() -> int:
    from dd_agents.orchestrator.steps import PipelineStep

    return len(list(PipelineStep))


def _blocking_gate_count() -> int:
    """Number of blocking validation gates, derived from the enum so adding or
    removing a gate trips the docs that headline this as "5 blocking gates"."""
    from dd_agents.orchestrator.steps import PipelineStep

    return sum(1 for s in PipelineStep if s.is_blocking_gate)


def _excel_sheet_count() -> int:
    import json

    schema = json.loads((REPO_ROOT / "config" / "report_schema.json").read_text())
    return len(schema["sheets"])


def _docker_image() -> str:
    """The published Docker image base name, from the release workflow."""
    wf = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text()
    m = re.search(r"/(due-diligence-agents)\b", wf)
    assert m, "could not locate published Docker image name in release.yml"
    return f"zoharbabin/{m.group(1)}"


# --------------------------------------------------------------------------- #
# Drift assertions
# --------------------------------------------------------------------------- #
def _offenders(pattern: str, expected: int) -> dict[str, list[int]]:
    """Map each doc that states a count via *pattern* != *expected* to the
    wrong integers it states. Empty dict means no drift."""
    out: dict[str, list[int]] = {}
    for f, t in _doc_text().items():
        wrong = sorted({int(m) for m in re.findall(pattern, t) if int(m) != expected})
        if wrong:
            out[f] = wrong
    return out


# Spelled-out numbers some docs use for the blocking-gate count.
_NUM_WORDS = {4: "four", 5: "five", 6: "six", 7: "seven"}


def test_specialist_count_in_docs_matches_code() -> None:
    n = _specialist_count()
    bad = _offenders(r"\b(\d+) specialist", n)
    assert not bad, f"Docs cite a specialist count != {n} (code truth): {bad}"


def test_total_agent_count_in_docs_matches_code() -> None:
    n = _total_agent_count()
    # Only the unambiguous total phrasing "N AI agents" — NOT bare "N agents",
    # which docs also use for non-total counts ("9 agents by default",
    # "pass-2 agents"). This is why docs should headline the total as "AI agents".
    bad = _offenders(r"\b(\d+) AI agents\b", n)
    assert not bad, f"Docs cite a total-agent count != {n} (9 specialists + 4 synthesis): {bad}"


def test_pipeline_step_count_in_docs_matches_code() -> None:
    n = _pipeline_step_count()
    # Hyphenated "N-step" is always the pipeline. The space form "N steps" is
    # only counted when "pipeline"/"orchestrator" sits IMMEDIATELY adjacent
    # (directly before or after the count), so unrelated prose that merely
    # mentions a pipeline in the same sentence (e.g. "5 steps; then the
    # pipeline runs") is not a false positive, and a "10 steps" math example
    # is ignored. The (?<![\d.]) lookbehind stops a version-like "1.38-step"
    # from harvesting its fractional digits.
    # Patterns are case-insensitive on the keywords so the docs' own title-case
    # heading "## The 38-Step Pipeline" is guarded too.
    bad = _offenders(r"(?<![\d.])(\d+)-(?i:steps?)\b", n)
    bad |= _offenders(r"(?<![\d.])(\d+) (?i:steps?),? (?:async )?(?i:pipeline|orchestrat)", n)
    bad |= _offenders(r"(?i:pipeline|orchestrat)\w*[^.\n]{0,20}?(?<![\d.])(\d+) (?i:steps?)\b", n)
    assert not bad, f"Docs cite a pipeline-step count != {n} (code truth): {bad}"


def test_blocking_gate_count_in_docs_matches_code() -> None:
    n = _blocking_gate_count()
    # The PIPELINE blocking-gate count is always tied to the word "blocking"
    # ("5 blocking gates", "5 blocking quality gates", "Five blocking gates",
    # "Five steps are blocking gates"). We deliberately do NOT match bare
    # "N quality gates" because that phrasing is also used for the unrelated
    # per-method *extraction* quality gates ("passes through 6 quality gates").
    digit = _offenders(r"(?<![\d.])(\d+)(?: \w+){0,2} blocking (?:quality )?gates?\b", n)
    digit |= _offenders(r"(?<![\d.])(\d+) blocking", n)
    spelled = {
        f
        for f, t in _doc_text().items()
        if re.search(r"\b(four|five|six|seven)\b[^.\n]{0,40}blocking gate", t, re.IGNORECASE)
        and not re.search(rf"\b{_NUM_WORDS[n]}\b[^.\n]{{0,40}}blocking gate", t, re.IGNORECASE)
    }
    assert not digit, f"Docs cite a blocking-gate count != {n} (code truth): {digit}"
    assert not spelled, f"Docs spell out a blocking-gate count != {n} ({_NUM_WORDS[n]}): {sorted(spelled)}"


def test_excel_sheet_count_in_docs_matches_schema() -> None:
    n = _excel_sheet_count()
    # (?<![\d.]) so a version-like "1.14 sheets" can't harvest "14".
    # Case-insensitive on "sheet" to catch title-case ("14-Sheet").
    bad = _offenders(r"(?<![\d.])(\d+)[ -](?i:sheets?)\b", n)
    assert not bad, f"Docs cite an Excel sheet count != {n} (report_schema.json): {bad}"


def test_docker_image_name_is_correct_everywhere() -> None:
    image = _docker_image()
    wrong: dict[str, list[str]] = {}
    for f, t in _doc_text().items():
        # any zoharbabin/<name> reference that points at a docker pull/run must
        # use the published image, never a stale short name like dd-agents.
        for m in re.finditer(r"docker (?:pull|run)[^\n]*?zoharbabin/([a-z0-9-]+)", t):
            if f"zoharbabin/{m.group(1)}" != image:
                wrong.setdefault(f, []).append(m.group(1))
    assert not wrong, f"Docs reference a wrong Docker image (expected {image}): {wrong}"


# --------------------------------------------------------------------------- #
# MCP tool-annotation contract (CLAUDE.md tooling rule)
# --------------------------------------------------------------------------- #
def _tool_annotations() -> list[tuple[str, str]]:
    src = (REPO_ROOT / "src" / "dd_agents" / "tools" / "mcp_server.py").read_text()
    return re.findall(r'@tool\(\s*"([^"]+)"\s*,\s*"([^"]+)"', src)


def test_every_mcp_tool_has_a_nonempty_description() -> None:
    tools = _tool_annotations()
    assert tools, "no @tool annotations found — parser drift"
    empty = [name for name, desc in tools if not desc.strip()]
    assert not empty, f"MCP tools missing a description: {empty}"


@pytest.mark.parametrize(
    "name,must_contain",
    [
        # Write/side-effecting tools must be honest about their effect in the
        # description the model sees (CLAUDE.md: read/write capability explicit).
        ("save_memory", ("save",)),
        ("flag_finding", ("flag",)),
        ("extract_document", ("extract",)),
        ("run_export_script", ("generate", "excel", "execute")),
    ],
)
def test_side_effecting_tool_descriptions_declare_their_effect(name: str, must_contain: tuple[str, ...]) -> None:
    tools = dict(_tool_annotations())
    assert name in tools, f"{name} tool annotation not found"
    desc = tools[name].lower()
    assert any(k in desc for k in must_contain), (
        f"{name} description does not declare its write/side-effect (looked for any of {must_contain}): {tools[name]!r}"
    )
