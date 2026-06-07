"""E2E test fixtures and shared setup.

E2E tests require:
- A valid ANTHROPIC_API_KEY or AWS Bedrock credentials
- Network access for Claude API calls
- A sample data room directory

Mark E2E tests with @pytest.mark.e2e (CI) or @pytest.mark.local (deep, local-only).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from pathlib import Path  # noqa: TC003

import pytest


def _has_api_key() -> bool:
    """Check if Claude API credentials are available (direct or Bedrock)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    # AWS Bedrock: CLAUDE_CODE_USE_BEDROCK + AWS credentials
    if os.environ.get("CLAUDE_CODE_USE_BEDROCK"):
        return bool(
            os.environ.get("AWS_PROFILE")
            or (os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY"))
        )
    return False


skip_no_api_key = pytest.mark.skipif(
    not _has_api_key(),
    reason="No API credentials (ANTHROPIC_API_KEY or Bedrock); skipping",
)


# ---------------------------------------------------------------------------
# Golden sample: Project Atlas (examples/project-atlas/)
#
# E2E tests run against the SAME committed synthetic deal used by the docs,
# the public sample report, and the launch demo — one golden sample everywhere.
# Atlas is engineered so the hero Legal->Finance cross-domain finding (a
# change-of-control clause on a customer worth ~30% of ARR) is real and cited.
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
ATLAS_DIR = REPO_ROOT / "examples" / "project-atlas"
ATLAS_DATA_ROOM = ATLAS_DIR / "sample_data_room"
ATLAS_CONFIG = ATLAS_DIR / "deal-config.json"


def _copy_atlas_data_room(dest: Path) -> Path:
    """Copy the committed Project Atlas data room (source docs only, no run output)."""
    shutil.copytree(
        ATLAS_DATA_ROOM,
        dest,
        ignore=shutil.ignore_patterns("_dd", "knowledge"),
    )
    return dest


@pytest.fixture()
def e2e_data_room(tmp_path: Path) -> Path:
    """Provide the golden Project Atlas data room for E2E testing."""
    return _copy_atlas_data_room(tmp_path / "data_room")


@pytest.fixture()
def e2e_deal_config(tmp_path: Path, e2e_data_room: Path) -> Path:
    """Provide the Project Atlas deal config, repointed at the copied data room.

    Enables Judge + cross-agent checks for a thorough E2E exercise.
    """
    config = json.loads(ATLAS_CONFIG.read_text(encoding="utf-8"))
    # Point the config at the copied data room (the engine resolves data_room.path).
    config["data_room"]["path"] = str(e2e_data_room)
    # E2E exercises the full feature set, including the Judge.
    config["judge"] = {
        "enabled": True,
        "max_iteration_rounds": 2,
        "score_threshold": 70,
        "sampling_rates": {"p0": 1.0, "p1": 0.20, "p2": 0.10, "p3": 0.0},
        "ocr_completeness_check": True,
        "cross_agent_contradiction_check": True,
    }
    # Keep E2E cost/latency bounded — use the economy model profile.
    config["agent_models"] = {"profile": "economy"}
    config_path = tmp_path / "deal-config.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config_path


@pytest.fixture()
def e2e_project_dir(tmp_path: Path, e2e_data_room: Path, e2e_deal_config: Path) -> Path:
    """Set up a complete project directory for E2E testing.

    Copies the Atlas data room and config into a single project directory
    that the pipeline engine can work with, with the config repointed locally.
    """
    project = tmp_path / "project"
    shutil.copytree(e2e_data_room, project)
    config = json.loads(e2e_deal_config.read_text(encoding="utf-8"))
    config["data_room"]["path"] = str(project)
    (project / "deal-config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    return project


@pytest.fixture(scope="class")
def live_pipeline_result(tmp_path_factory: pytest.TempPathFactory) -> tuple[object, Path]:
    """Run the full pipeline once (all features incl. Judge), share across test class.

    Returns (PipelineState, project_dir). Expensive — runs real agents via API.
    """
    from dd_agents.orchestrator.engine import PipelineEngine

    tmp_path = tmp_path_factory.mktemp("live_e2e")

    # --- Build the project from the golden Project Atlas example ---
    project = _copy_atlas_data_room(tmp_path / "project")
    config = json.loads(ATLAS_CONFIG.read_text(encoding="utf-8"))
    config["data_room"]["path"] = str(project)
    # Exercise the full feature set, including the Judge, in the live run.
    config["judge"] = {
        "enabled": True,
        "max_iteration_rounds": 2,
        "score_threshold": 70,
        "sampling_rates": {"p0": 1.0, "p1": 0.20, "p2": 0.10, "p3": 0.0},
        "ocr_completeness_check": True,
        "cross_agent_contradiction_check": True,
    }
    config["agent_models"] = {"profile": "economy"}
    config_path = project / "deal-config.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    # --- Run pipeline with live progress ---
    # Enable live logging so step progress is visible during the run.
    # The engine logs "Step N/35: step_name" via dd_agents.orchestrator.engine.
    root_logger = logging.getLogger("dd_agents")
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S"))
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    print("\n" + "=" * 70)
    print("LIVE E2E: Starting full pipeline (all features, Judge enabled)")
    print(f"  Project dir: {project}")
    print("=" * 70, flush=True)

    t0 = time.monotonic()
    engine = PipelineEngine(project_dir=project, deal_config_path=config_path)
    state = asyncio.run(engine.run(resume_from_step=0))
    elapsed = time.monotonic() - t0

    print("=" * 70)
    print(f"LIVE E2E: Pipeline finished in {elapsed:.0f}s — {len(state.completed_steps)} steps completed")
    print("=" * 70 + "\n", flush=True)

    root_logger.removeHandler(handler)

    return state, project
