"""Coverage gate validator (pipeline step 17).

For each agent type, counts unique ``{subject_safe_name}.json`` files
against the expected subject count. Detects missing subjects,
aggregate files (should be per-subject), and empty outputs.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from dd_agents.models.audit import AuditCheck
from dd_agents.utils.constants import ALL_SPECIALIST_AGENTS

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class CoverageValidator:
    """Validate per-agent output file coverage against expected subjects."""

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #

    def validate(
        self,
        agent_output_dirs: dict[str, Path],
        expected_subjects: list[str],
    ) -> list[AuditCheck]:
        """Run coverage checks for every specialist agent.

        Parameters
        ----------
        agent_output_dirs:
            Mapping of agent name -> directory containing per-subject
            JSON output files.
        expected_subjects:
            List of ``subject_safe_name`` strings that each agent is
            expected to produce output for.

        Returns
        -------
        list[AuditCheck]
            One :class:`AuditCheck` per agent, plus an aggregate check.
        """
        results: list[AuditCheck] = []
        expected_set = set(expected_subjects)

        for agent in ALL_SPECIALIST_AGENTS:
            agent_dir = agent_output_dirs.get(agent)
            check = self._check_agent(agent, agent_dir, expected_set)
            results.append(check)

        # Aggregate check
        all_passed = all(r.passed for r in results)
        results.append(
            AuditCheck(
                passed=all_passed,
                dod_checks=[1, 3],
                details={
                    "aggregate": True,
                    "agents_checked": len(results),
                    "all_passed": all_passed,
                },
                rule="All specialist agents must have per-subject output for every expected subject.",
            )
        )
        return results

    # ------------------------------------------------------------------ #
    # internal helpers
    # ------------------------------------------------------------------ #

    def _check_agent(
        self,
        agent: str,
        agent_dir: Path | None,
        expected: set[str],
    ) -> AuditCheck:
        if agent_dir is None or not agent_dir.exists():
            return AuditCheck(
                passed=False,
                dod_checks=[1, 3],
                details={
                    "agent": agent,
                    "error": "output directory missing",
                    "missing_subjects": sorted(expected),
                    "aggregate_files": [],
                    "empty_files": [],
                },
            )

        json_files = list(agent_dir.glob("*.json"))
        found_names: set[str] = set()
        aggregate_files: list[str] = []
        empty_files: list[str] = []

        for jf in json_files:
            stem = jf.stem
            # Detect aggregate/non-subject files
            if stem in ("coverage_manifest", "audit_log", "summary", "all_subjects"):
                aggregate_files.append(jf.name)
                continue

            found_names.add(stem)

            # Detect empty output (file < 3 bytes or empty findings)
            if jf.stat().st_size < 3:
                empty_files.append(jf.name)
                continue
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
                if isinstance(data, dict) and not data.get("findings") and not data.get("gaps"):
                    empty_files.append(jf.name)
            except (json.JSONDecodeError, OSError):
                empty_files.append(jf.name)

        missing_subjects = sorted(expected - found_names)
        passed = len(missing_subjects) == 0 and len(empty_files) == 0

        return AuditCheck(
            passed=passed,
            dod_checks=[1, 3],
            details={
                "agent": agent,
                "expected_count": len(expected),
                "found_count": len(found_names),
                "missing_subjects": missing_subjects,
                "aggregate_files": aggregate_files,
                "empty_files": empty_files,
            },
        )
