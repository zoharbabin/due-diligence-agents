"""Eval framework fixtures, options, and marker registration."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import pytest

from .metrics import compute_agent_metrics
from .models import AgentEvalMetrics, EvalBaseline, GroundTruth

logger = logging.getLogger(__name__)

_EVALS_DIR = Path(__file__).parent
_GROUND_TRUTH_DIR = _EVALS_DIR / "ground_truth"
_CONTRACTS_DIR = _GROUND_TRUTH_DIR / "contracts"
_EXPECTED_DIR = _GROUND_TRUTH_DIR / "expected"
_BASELINES_DIR = _EVALS_DIR / "baselines"


def pytest_configure(config: pytest.Config) -> None:
    """Register eval markers so pytest doesn't warn about unknown markers."""
    config.addinivalue_line("markers", "eval: agent quality evaluation tests (require API key)")
    config.addinivalue_line("markers", "golden_path: golden path eval cases only")
    config.addinivalue_line("markers", "adversarial: adversarial eval cases only")
    config.addinivalue_line("markers", "edge_case: edge case eval cases only")
    config.addinivalue_line("markers", "cross_domain: cross-domain eval cases only")


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add custom eval CLI options."""
    parser.addoption(
        "--update-baseline",
        action="store_true",
        default=False,
        help="Save current eval metrics as the new baseline in baselines/latest.json",
    )
    parser.addoption(
        "--eval-tags",
        action="store",
        default="",
        help="Comma-separated tags to filter eval cases (e.g. golden_path,adversarial)",
    )


def _load_ground_truths(tag_filter: set[str] | None = None) -> list[GroundTruth]:
    """Load all ground truth JSON files from the expected/ directory.

    Args:
        tag_filter: If provided, only return ground truths matching at least one tag.
    """
    truths: list[GroundTruth] = []
    if not _EXPECTED_DIR.exists():
        return truths
    for agent_dir in sorted(_EXPECTED_DIR.iterdir()):
        if not agent_dir.is_dir():
            continue
        for gt_file in sorted(agent_dir.glob("*.json")):
            data = json.loads(gt_file.read_text())
            gt = GroundTruth.model_validate(data)
            if tag_filter and not tag_filter.intersection(gt.tags):
                continue
            truths.append(gt)
    return truths


@pytest.fixture(scope="session")
def all_ground_truths(request: pytest.FixtureRequest) -> list[GroundTruth]:
    """All ground truth definitions, optionally filtered by --eval-tags."""
    raw_tags: str = request.config.getoption("--eval-tags", default="")
    tag_filter = {t.strip() for t in raw_tags.split(",") if t.strip()} if raw_tags else None
    return _load_ground_truths(tag_filter)


@pytest.fixture(scope="session")
def ground_truths_by_agent(all_ground_truths: list[GroundTruth]) -> dict[str, list[GroundTruth]]:
    """Ground truths grouped by agent name."""
    by_agent: dict[str, list[GroundTruth]] = {}
    for gt in all_ground_truths:
        by_agent.setdefault(gt.agent, []).append(gt)
    return by_agent


@pytest.fixture(scope="session")
def baseline() -> EvalBaseline | None:
    """Load the stored baseline metrics, or None if empty/missing."""
    baseline_path = _BASELINES_DIR / "latest.json"
    if not baseline_path.exists():
        return None
    data = json.loads(baseline_path.read_text())
    if not data or not data.get("metrics"):
        return None
    return EvalBaseline.model_validate(data)


@pytest.fixture(scope="session")
def contracts_dir() -> Path:
    """Path to the synthetic contracts directory."""
    return _GROUND_TRUTH_DIR / "contracts"


@pytest.fixture
def update_baseline(request: pytest.FixtureRequest) -> bool:
    """Whether --update-baseline was passed on the command line."""
    val: bool = request.config.getoption("--update-baseline")
    return val


def save_baseline(metrics: dict[str, AgentEvalMetrics]) -> None:
    """Save metrics dict as the new baseline to baselines/latest.json."""
    import datetime
    import subprocess

    commit = ""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            commit = result.stdout.strip()
    except Exception:
        pass

    baseline_obj = EvalBaseline(
        timestamp=datetime.datetime.now(tz=datetime.UTC).isoformat(),
        commit=commit,
        metrics=metrics,
    )
    _BASELINES_DIR.mkdir(parents=True, exist_ok=True)
    baseline_path = _BASELINES_DIR / "latest.json"
    baseline_path.write_text(baseline_obj.model_dump_json(indent=2) + "\n")


def make_finding_dict(
    *,
    category: str,
    severity: str = "P2",
    title: str = "",
    description: str = "",
    source_path: str = "",
    location: str = "",
    exact_quote: str = "placeholder quote",
) -> dict[str, Any]:
    """Helper to build a synthetic finding dict for testing metrics functions."""
    return {
        "category": category,
        "severity": severity,
        "title": title or f"Finding: {category}",
        "description": description or f"Description for {category}",
        "citations": [
            {
                "source_type": "file",
                "source_path": source_path,
                "location": location,
                "exact_quote": exact_quote,
            }
        ],
        "confidence": "high",
    }


# ---------------------------------------------------------------------------
# Credential detection — supports both direct API key and AWS Bedrock
# ---------------------------------------------------------------------------


def _has_api_credentials() -> bool:
    """Check if Claude API credentials are available (direct or Bedrock)."""
    import os

    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    if os.environ.get("CLAUDE_CODE_USE_BEDROCK"):
        return bool(
            os.environ.get("AWS_PROFILE")
            or (os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY"))
        )
    return False


# ---------------------------------------------------------------------------
# Live eval runner — spawns real agents against ground truth contracts
# ---------------------------------------------------------------------------


def _setup_eval_project(
    tmp_dir: Path,
    contract_name: str,
    subject_safe_name: str,
) -> tuple[Path, Path]:
    """Create the minimal project directory structure for an agent eval run.

    Returns (project_dir, run_dir).
    """
    contract_source = _CONTRACTS_DIR / contract_name
    if not contract_source.exists():
        raise FileNotFoundError(f"Contract not found: {contract_source}")

    project_dir = tmp_dir / "project"
    run_dir = tmp_dir / "run"

    dd_base = project_dir / "_dd" / "forensic-dd"
    text_dir = dd_base / "index" / "text"
    text_dir.mkdir(parents=True, exist_ok=True)

    # Place the contract as an extracted text file
    text_file = text_dir / f"{contract_name}"
    text_file.write_text(contract_source.read_text())

    # Create findings output directory for the agent
    findings_dir = run_dir / "findings"
    findings_dir.mkdir(parents=True, exist_ok=True)

    # Create agent_output dir for raw output persistence
    (run_dir / "agent_output").mkdir(parents=True, exist_ok=True)

    return project_dir, run_dir


def _extract_findings_from_disk(
    run_dir: Path,
    agent_name: str,
    subject_safe_name: str,
) -> list[dict[str, Any]]:
    """Read findings JSON written by the agent to disk.

    Agents write to: {run_dir}/findings/{agent_name}/{subject_safe_name}.json
    The JSON has: {"findings": [...], "gaps": [...], ...}
    """
    findings_path = run_dir / "findings" / agent_name / f"{subject_safe_name}.json"
    if not findings_path.exists():
        logger.warning("No findings file at %s", findings_path)
        return []

    try:
        data = json.loads(findings_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read findings from %s: %s", findings_path, exc)
        return []

    if isinstance(data, dict):
        findings: list[dict[str, Any]] = data.get("findings", [])
        return findings
    return []


async def _run_agent_on_contract(
    agent_name: str,
    contract_name: str,
    tmp_dir: Path,
) -> list[dict[str, Any]]:
    """Spawn a single specialist agent against a ground truth contract.

    Returns the list of finding dicts produced by the agent.
    """
    from dd_agents.agents.registry import AgentRegistry
    from dd_agents.models.inventory import SubjectEntry

    subject_safe_name = contract_name.replace(".md", "").replace(".", "_")

    project_dir, run_dir = _setup_eval_project(tmp_dir, contract_name, subject_safe_name)

    # Create the findings subdirectory for this agent
    (run_dir / "findings" / agent_name).mkdir(parents=True, exist_ok=True)

    descriptor = AgentRegistry.get(agent_name)
    runner = descriptor.agent_class(
        project_dir=project_dir,
        run_dir=run_dir,
        run_id="eval",
    )

    # Build a subject entry pointing to the contract
    text_path = str(project_dir / "_dd" / "forensic-dd" / "index" / "text" / contract_name)
    subject = SubjectEntry(
        group="eval",
        name=subject_safe_name,
        safe_name=subject_safe_name,
        path=f"eval/{subject_safe_name}",
        file_count=1,
        files=[text_path],
    )

    state: dict[str, Any] = {
        "subjects": [subject],
    }

    # Reduce budget and turns for eval runs — we only need one contract analyzed
    runner.max_turns = 50
    runner.max_budget_usd = 2.0
    runner.timeout_seconds = 300

    result = await runner.run(state)

    if result.get("status") != "success":
        logger.warning(
            "Agent %s returned status=%s for %s: %s",
            agent_name,
            result.get("status"),
            contract_name,
            result.get("error", ""),
        )

    return _extract_findings_from_disk(run_dir, agent_name, subject_safe_name)


# ---------------------------------------------------------------------------
# Session-scoped live eval results cache
# ---------------------------------------------------------------------------

# Accumulated across the session by the eval_results fixture
_session_metrics: dict[str, AgentEvalMetrics] = {}


@pytest.fixture(scope="session")
def eval_results(
    all_ground_truths: list[GroundTruth],
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, AgentEvalMetrics]:
    """Run all agents against their ground truth contracts and compute metrics.

    Session-scoped: runs once, results shared across all live eval tests.
    Returns agent_name -> AgentEvalMetrics (aggregated across all contracts for that agent).
    """
    if not _has_api_credentials():
        pytest.skip("No API credentials (ANTHROPIC_API_KEY or Bedrock); skipping live evals")

    # Group ground truths by agent
    by_agent: dict[str, list[GroundTruth]] = {}
    for gt in all_ground_truths:
        by_agent.setdefault(gt.agent, []).append(gt)

    results: dict[str, AgentEvalMetrics] = {}

    for agent_name, gts in sorted(by_agent.items()):
        per_contract_metrics: list[AgentEvalMetrics] = []
        total_findings = 0

        for gt in gts:
            eval_tmp = tmp_path_factory.mktemp(f"eval_{agent_name}_{gt.contract.replace('.', '_')}")
            try:
                produced = asyncio.run(_run_agent_on_contract(agent_name, gt.contract, eval_tmp))
            except Exception as exc:
                logger.error("Agent %s failed on %s: %s", agent_name, gt.contract, exc)
                produced = []

            for f in produced:
                cat = f.get("category", "?")
                sev = f.get("severity", "?")
                title = f.get("title", "?")[:80]
                logger.info(
                    "  [%s/%s] cat=%s sev=%s title=%s",
                    agent_name,
                    gt.contract,
                    cat,
                    sev,
                    title,
                )
            total_findings += len(produced)
            contract_metrics = compute_agent_metrics(produced, gt)
            per_contract_metrics.append(contract_metrics)
            logger.info(
                "  %s/%s: recall=%.2f precision=%.2f FP=%.2f (%d findings)",
                agent_name,
                gt.contract,
                contract_metrics.finding_recall,
                contract_metrics.finding_precision,
                contract_metrics.false_positive_rate,
                contract_metrics.finding_count,
            )

        n = len(per_contract_metrics)
        metrics = AgentEvalMetrics(
            agent_name=agent_name,
            finding_recall=sum(m.finding_recall for m in per_contract_metrics) / n if n else 0.0,
            finding_precision=sum(m.finding_precision for m in per_contract_metrics) / n if n else 0.0,
            citation_accuracy=sum(m.citation_accuracy for m in per_contract_metrics) / n if n else 0.0,
            severity_accuracy=sum(m.severity_accuracy for m in per_contract_metrics) / n if n else 0.0,
            false_positive_rate=sum(m.false_positive_rate for m in per_contract_metrics) / n if n else 0.0,
            f1_score=sum(m.f1_score for m in per_contract_metrics) / n if n else 0.0,
            finding_count=total_findings,
        )
        results[agent_name] = metrics
        logger.info(
            "Agent %s eval: recall=%.2f precision=%.2f F1=%.2f citations=%.2f severity=%.2f FP=%.2f (%d findings)",
            agent_name,
            metrics.finding_recall,
            metrics.finding_precision,
            metrics.f1_score,
            metrics.citation_accuracy,
            metrics.severity_accuracy,
            metrics.false_positive_rate,
            metrics.finding_count,
        )

    global _session_metrics  # noqa: PLW0603
    _session_metrics = results
    return results


@pytest.fixture(scope="session")
def cross_agent_results(
    all_ground_truths: list[GroundTruth],
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, list[dict[str, Any]]]:
    """Run all agents against a shared cross-domain contract and collect findings.

    Uses cross_domain_finance_legal.md — a revenue schedule with a buried CoC clause
    that both legal and finance agents should analyze.
    """
    if not _has_api_credentials():
        pytest.skip("No API credentials (ANTHROPIC_API_KEY or Bedrock); skipping live evals")

    from dd_agents.agents.registry import AgentRegistry

    cross_contract = "cross_domain_finance_legal.md"
    if not (_CONTRACTS_DIR / cross_contract).exists():
        pytest.skip(f"Cross-domain contract {cross_contract} not found")

    agent_names = AgentRegistry.all_specialist_names()
    results: dict[str, list[dict[str, Any]]] = {}

    for agent_name in agent_names:
        eval_tmp = tmp_path_factory.mktemp(f"cross_{agent_name}")
        try:
            produced = asyncio.run(_run_agent_on_contract(agent_name, cross_contract, eval_tmp))
        except Exception as exc:
            logger.error("Cross-agent eval: %s failed on %s: %s", agent_name, cross_contract, exc)
            produced = []
        results[agent_name] = produced

    return results


# ---------------------------------------------------------------------------
# Per-agent metrics fixture (used by TestAgentEvals)
# ---------------------------------------------------------------------------


@pytest.fixture(params=["legal", "finance", "commercial", "producttech", "cybersecurity"])
def agent_metrics(request: pytest.FixtureRequest, eval_results: dict[str, AgentEvalMetrics]) -> AgentEvalMetrics:
    """Per-agent metrics from the live eval run, parametrized across all agents."""
    agent_name: str = request.param
    if agent_name not in eval_results:
        pytest.skip(f"No eval results for agent {agent_name}")
    return eval_results[agent_name]


# ---------------------------------------------------------------------------
# Baseline persistence hook
# ---------------------------------------------------------------------------


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Save baseline after a successful eval run if --update-baseline was passed."""
    if not session.config.getoption("--update-baseline", default=False):
        return
    if not _session_metrics:
        return
    if exitstatus != 0:
        logger.warning("Session failed (exit %d) — not updating baseline", exitstatus)
        return
    save_baseline(_session_metrics)
    logger.info("Baseline updated with %d agent metrics", len(_session_metrics))
