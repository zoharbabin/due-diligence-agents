"""Coverage gate validator (pipeline step 17).

For each agent type, counts unique ``{customer_safe_name}.json`` files
against the expected customer count. Detects missing customers,
aggregate files (should be per-customer), and empty outputs.
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
    """Validate per-agent output file coverage against expected customers."""

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #

    def validate(
        self,
        agent_output_dirs: dict[str, Path],
        expected_customers: list[str],
    ) -> list[AuditCheck]:
        """Run coverage checks for every specialist agent.

        Parameters
        ----------
        agent_output_dirs:
            Mapping of agent name -> directory containing per-customer
            JSON output files.
        expected_customers:
            List of ``customer_safe_name`` strings that each agent is
            expected to produce output for.

        Returns
        -------
        list[AuditCheck]
            One :class:`AuditCheck` per agent, plus an aggregate check.
        """
        results: list[AuditCheck] = []
        expected_set = set(expected_customers)

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
                rule="All specialist agents must have per-customer output for every expected customer.",
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
                    "missing_customers": sorted(expected),
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
            # Detect aggregate/non-customer files
            if stem in ("coverage_manifest", "audit_log", "summary", "all_customers"):
                aggregate_files.append(jf.name)
                continue

            found_names.add(stem)

            # Detect empty output (file < 3 bytes or empty findings)
            if jf.stat().st_size < 3:
                empty_files.append(jf.name)
                continue
            try:
                data = json.loads(jf.read_text())
                if isinstance(data, dict) and not data.get("findings") and not data.get("gaps"):
                    empty_files.append(jf.name)
            except (json.JSONDecodeError, OSError):
                empty_files.append(jf.name)

        missing_customers = sorted(expected - found_names)
        passed = len(missing_customers) == 0 and len(empty_files) == 0

        return AuditCheck(
            passed=passed,
            dod_checks=[1, 3],
            details={
                "agent": agent,
                "expected_count": len(expected),
                "found_count": len(found_names),
                "missing_customers": missing_customers,
                "aggregate_files": aggregate_files,
                "empty_files": empty_files,
            },
        )
