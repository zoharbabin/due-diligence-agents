"""Pre-merge validation and cross-agent anomaly detection (step 23).

Deterministic Python -- no LLM calls.  Reads specialist agent output files
and validates integrity, completeness, and cross-agent consistency before
the merge step (24) processes them.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from dd_agents.utils.constants import ALL_SPECIALIST_AGENTS, NON_SUBJECT_STEMS, SEVERITY_ORDER, SEVERITY_P0, SEVERITY_P1

logger = logging.getLogger(__name__)

# Alias for backward compatibility — canonical definition in utils.constants.
_NON_SUBJECT_STEMS = NON_SUBJECT_STEMS

# Required keys in each finding dict
_REQUIRED_FINDING_KEYS: frozenset[str] = frozenset({"severity", "category", "title", "description", "citations"})

# Required keys in each citation dict
_REQUIRED_CITATION_KEYS: frozenset[str] = frozenset({"source_path", "exact_quote"})


# ---------------------------------------------------------------------------
# Report model
# ---------------------------------------------------------------------------


class PreMergeReport(BaseModel):
    """Structured output of step 23 pre-merge validation."""

    passed: bool = Field(description="True if no critical issues (corrupt JSON, etc.)")
    total_subjects: int = Field(description="Number of subjects validated")
    total_findings: int = Field(description="Total finding count across all agents and subjects")
    findings_per_agent: dict[str, int] = Field(default_factory=dict, description="Agent name -> total finding count")
    file_completeness_issues: list[dict[str, Any]] = Field(
        default_factory=list, description="Missing agent files per subject"
    )
    json_integrity_issues: list[dict[str, Any]] = Field(
        default_factory=list, description="Corrupt or unparseable JSON files"
    )
    schema_issues: list[dict[str, Any]] = Field(default_factory=list, description="Findings missing required keys")
    citation_path_issues: list[dict[str, Any]] = Field(
        default_factory=list, description="Citations with invalid source_path"
    )
    asymmetric_risk_anomalies: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Subjects where one agent found P0/P1 but another found zero findings",
    )
    severity_disagreements: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Categories where agents disagree by 2+ severity levels on same subject",
    )
    summary_matrix: dict[str, dict[str, int]] = Field(
        default_factory=dict, description="Subject -> agent -> finding count"
    )


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


class PreMergeValidator:
    """Pre-merge validation and cross-agent anomaly detection (step 23).

    Deterministic Python -- no LLM calls.  Reads specialist agent output
    files and validates integrity, completeness, and cross-agent consistency
    before the merge step (24) processes them.
    """

    def __init__(
        self,
        run_dir: Path,
        findings_dir: Path,
        subject_safe_names: list[str],
        file_inventory: list[str],
    ) -> None:
        self.run_dir = Path(run_dir)
        self.findings_dir = Path(findings_dir)
        self.subject_safe_names = subject_safe_names
        self.file_inventory_set = frozenset(file_inventory)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def validate(self) -> PreMergeReport:
        """Run all checks.  Returns structured report."""
        completeness_issues = self._check_file_completeness()
        parsed, json_issues = self._check_json_integrity()
        schema_issues = self._check_schema_compliance(parsed)
        citation_issues = self._check_citation_paths(parsed)
        asymmetric = self._detect_asymmetric_risk(parsed)
        disagreements = self._detect_severity_disagreements(parsed)
        matrix = self._build_summary_matrix(parsed)

        # Compute totals
        total_findings = 0
        findings_per_agent: dict[str, int] = {}
        for agent in ALL_SPECIALIST_AGENTS:
            agent_count = 0
            for subject in self.subject_safe_names:
                key = f"{agent}/{subject}"
                if key in parsed:
                    findings_list = parsed[key]
                    agent_count += len(findings_list)
            findings_per_agent[agent] = agent_count
            total_findings += agent_count

        # Critical failure = any corrupt JSON
        passed = len(json_issues) == 0

        report = PreMergeReport(
            passed=passed,
            total_subjects=len(self.subject_safe_names),
            total_findings=total_findings,
            findings_per_agent=findings_per_agent,
            file_completeness_issues=completeness_issues,
            json_integrity_issues=json_issues,
            schema_issues=schema_issues,
            citation_path_issues=citation_issues,
            asymmetric_risk_anomalies=asymmetric,
            severity_disagreements=disagreements,
            summary_matrix=matrix,
        )

        self._log_summary(report)
        return report

    # ------------------------------------------------------------------
    # Pre-merge validation
    # ------------------------------------------------------------------

    def _check_file_completeness(self) -> list[dict[str, Any]]:
        """Verify 4 agent files per subject."""
        issues: list[dict[str, Any]] = []
        for subject in self.subject_safe_names:
            missing_agents: list[str] = []
            for agent in ALL_SPECIALIST_AGENTS:
                fpath = self.findings_dir / agent / f"{subject}.json"
                if not fpath.exists():
                    missing_agents.append(agent)
            if missing_agents:
                issues.append(
                    {
                        "subject": subject,
                        "missing_agents": missing_agents,
                    }
                )
                logger.warning(
                    "Pre-merge: subject %s missing files from agents: %s",
                    subject,
                    ", ".join(missing_agents),
                )
        return issues

    def _check_json_integrity(
        self,
    ) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
        """Parse all JSON files, return (parsed_data, issues).

        Keys in ``parsed_data`` are ``"agent/subject"`` strings mapping to
        the findings list from that file.
        """
        parsed: dict[str, list[dict[str, Any]]] = {}
        issues: list[dict[str, Any]] = []

        for agent in ALL_SPECIALIST_AGENTS:
            agent_dir = self.findings_dir / agent
            if not agent_dir.is_dir():
                continue
            for fpath in sorted(agent_dir.glob("*.json")):
                stem = fpath.stem
                if stem in _NON_SUBJECT_STEMS:
                    continue
                if stem not in self.subject_safe_names:
                    continue
                try:
                    data = json.loads(fpath.read_text(encoding="utf-8"))
                    findings_list: list[dict[str, Any]] = []
                    if isinstance(data, dict):
                        raw = data.get("findings", [])
                        if isinstance(raw, list):
                            findings_list = raw
                    key = f"{agent}/{stem}"
                    parsed[key] = findings_list
                except (json.JSONDecodeError, OSError) as exc:
                    issues.append(
                        {
                            "agent": agent,
                            "subject": stem,
                            "file": str(fpath),
                            "error": str(exc),
                        }
                    )
                    logger.error("Pre-merge: corrupt JSON in %s: %s", fpath, exc)
        return parsed, issues

    def _check_schema_compliance(self, parsed: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        """Spot-check required keys in findings and citations."""
        issues: list[dict[str, Any]] = []
        for key, findings in parsed.items():
            agent, subject = key.split("/", 1)
            for idx, finding in enumerate(findings):
                if not isinstance(finding, dict):
                    issues.append(
                        {
                            "agent": agent,
                            "subject": subject,
                            "finding_index": idx,
                            "error": "finding is not a dict",
                            "missing_keys": [],
                        }
                    )
                    continue
                missing = [k for k in _REQUIRED_FINDING_KEYS if k not in finding]
                if missing:
                    issues.append(
                        {
                            "agent": agent,
                            "subject": subject,
                            "finding_index": idx,
                            "missing_keys": missing,
                        }
                    )
                # Check citations
                citations = finding.get("citations")
                if isinstance(citations, list):
                    for c_idx, cit in enumerate(citations):
                        if not isinstance(cit, dict):
                            continue
                        cit_missing = [k for k in _REQUIRED_CITATION_KEYS if k not in cit]
                        if cit_missing:
                            issues.append(
                                {
                                    "agent": agent,
                                    "subject": subject,
                                    "finding_index": idx,
                                    "citation_index": c_idx,
                                    "missing_keys": cit_missing,
                                }
                            )
        return issues

    def _check_citation_paths(self, parsed: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        """Verify citation source_paths exist in file inventory."""
        if not self.file_inventory_set:
            return []

        issues: list[dict[str, Any]] = []
        for key, findings in parsed.items():
            agent, subject = key.split("/", 1)
            for idx, finding in enumerate(findings):
                if not isinstance(finding, dict):
                    continue
                citations = finding.get("citations")
                if not isinstance(citations, list):
                    continue
                for c_idx, cit in enumerate(citations):
                    if not isinstance(cit, dict):
                        continue
                    source_path = cit.get("source_path", "")
                    if not source_path:
                        continue
                    if source_path not in self.file_inventory_set:
                        issues.append(
                            {
                                "agent": agent,
                                "subject": subject,
                                "finding_index": idx,
                                "citation_index": c_idx,
                                "source_path": source_path,
                            }
                        )
        return issues

    # ------------------------------------------------------------------
    # Cross-agent anomaly detection
    # ------------------------------------------------------------------

    def _detect_asymmetric_risk(self, parsed: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        """Flag subjects with P0/P1 from one agent but zero from another."""
        anomalies: list[dict[str, Any]] = []
        for subject in self.subject_safe_names:
            agents_with_high: list[str] = []
            agents_with_zero: list[str] = []
            for agent in ALL_SPECIALIST_AGENTS:
                key = f"{agent}/{subject}"
                findings = parsed.get(key, [])
                has_high = any(
                    isinstance(f, dict) and f.get("severity") in (SEVERITY_P0, SEVERITY_P1) for f in findings
                )
                if has_high:
                    agents_with_high.append(agent)
                if len(findings) == 0:
                    agents_with_zero.append(agent)

            if agents_with_high and agents_with_zero:
                anomalies.append(
                    {
                        "subject": subject,
                        "agents_with_p0_p1": agents_with_high,
                        "agents_with_zero": agents_with_zero,
                    }
                )
                logger.warning(
                    "Pre-merge: asymmetric risk for %s: %s found P0/P1, %s found nothing",
                    subject,
                    agents_with_high,
                    agents_with_zero,
                )
        return anomalies

    def _detect_severity_disagreements(self, parsed: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        """Flag 2+ severity level disagreements on shared categories."""
        disagreements: list[dict[str, Any]] = []

        for subject in self.subject_safe_names:
            # Build category -> agent -> min severity rank
            category_agent_severity: dict[str, dict[str, int]] = {}
            for agent in ALL_SPECIALIST_AGENTS:
                key = f"{agent}/{subject}"
                for finding in parsed.get(key, []):
                    if not isinstance(finding, dict):
                        continue
                    cat = finding.get("category", "")
                    sev = finding.get("severity", "")
                    rank = SEVERITY_ORDER.get(sev)
                    if rank is None or not cat:
                        continue
                    if cat not in category_agent_severity:
                        category_agent_severity[cat] = {}
                    # Keep most severe (lowest rank) per agent per category
                    prev = category_agent_severity[cat].get(agent)
                    if prev is None or rank < prev:
                        category_agent_severity[cat][agent] = rank

            # Check for disagreements (2+ agents, 2+ severity gap)
            for cat, agent_ranks in category_agent_severity.items():
                if len(agent_ranks) < 2:
                    continue
                ranks = list(agent_ranks.values())
                gap = max(ranks) - min(ranks)
                if gap >= 2:
                    # Invert SEVERITY_ORDER for display
                    inv_order = {v: k for k, v in SEVERITY_ORDER.items()}
                    disagreements.append(
                        {
                            "subject": subject,
                            "category": cat,
                            "agent_severities": {a: inv_order.get(r, f"rank_{r}") for a, r in agent_ranks.items()},
                            "severity_gap": gap,
                        }
                    )
        return disagreements

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def _build_summary_matrix(self, parsed: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, int]]:
        """Subject -> agent -> finding count matrix."""
        matrix: dict[str, dict[str, int]] = {}
        for subject in self.subject_safe_names:
            matrix[subject] = {}
            for agent in ALL_SPECIALIST_AGENTS:
                key = f"{agent}/{subject}"
                matrix[subject][agent] = len(parsed.get(key, []))
        return matrix

    def _log_summary(self, report: PreMergeReport) -> None:
        """Log a human-readable summary."""
        logger.info(
            "Pre-merge validation: %d subjects, %d total findings, passed=%s",
            report.total_subjects,
            report.total_findings,
            report.passed,
        )
        if report.file_completeness_issues:
            logger.warning(
                "  File completeness issues: %d subjects affected",
                len(report.file_completeness_issues),
            )
        if report.json_integrity_issues:
            logger.error(
                "  JSON integrity issues: %d files corrupt",
                len(report.json_integrity_issues),
            )
        if report.schema_issues:
            logger.warning(
                "  Schema issues: %d findings affected",
                len(report.schema_issues),
            )
        if report.citation_path_issues:
            logger.warning(
                "  Citation path issues: %d citations with unknown paths",
                len(report.citation_path_issues),
            )
        if report.asymmetric_risk_anomalies:
            logger.warning(
                "  Asymmetric risk anomalies: %d subjects",
                len(report.asymmetric_risk_anomalies),
            )
        if report.severity_disagreements:
            logger.warning(
                "  Severity disagreements: %d categories",
                len(report.severity_disagreements),
            )
        for agent, count in report.findings_per_agent.items():
            logger.info("  Agent %s: %d findings", agent, count)
