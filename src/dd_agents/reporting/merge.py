"""Finding merge and deduplication across specialist agents.

Implements the 6-step merge/dedup protocol from 10-reporting.md:
1. Collect agent outputs per customer
2. Merge findings into combined list
3. Deduplicate by match key (citation source_path + location)
4. Cross-validate severity disagreements
5. Consolidate governance graphs (Legal primary)
6. Merge gap files
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from dd_agents.models.enums import SourceType
from dd_agents.models.finding import (
    Citation,
    CrossReference,
    CrossReferenceSummary,
    Finding,
    Gap,
    MergedCustomerOutput,
)
from dd_agents.models.governance import GovernanceEdge, GovernanceGraph
from dd_agents.utils.constants import ALL_SPECIALIST_AGENTS, SEVERITY_ORDER
from dd_agents.utils.naming import customer_safe_name as compute_safe_name

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class FindingMerger:
    """Executes the 6-step merge/dedup protocol for specialist agent outputs."""

    def __init__(self, run_id: str = "", timestamp: str = "") -> None:
        self.run_id = run_id or datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        self.timestamp = timestamp or datetime.now(UTC).isoformat()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def merge_customer(
        self,
        agent_outputs: dict[str, dict[str, Any]],
        customer_name: str = "",
        customer_safe_name: str = "",
    ) -> MergedCustomerOutput:
        """Merge findings from specialist agents for one customer.

        Parameters
        ----------
        agent_outputs:
            ``{agent_name: raw_json_dict}`` for each agent that produced output.
        customer_name:
            Canonical customer display name.  Falls back to the first agent
            output's ``customer`` field when not provided.
        customer_safe_name:
            Filesystem-safe slug.  Computed from *customer_name* when absent.
        """
        # Resolve customer identity
        if not customer_name:
            for data in agent_outputs.values():
                customer_name = data.get("customer", "unknown")
                break
        if not customer_safe_name and customer_name.strip():
            customer_safe_name = compute_safe_name(customer_name)

        # Step 2 -- Merge
        all_findings: list[dict[str, Any]] = []
        for agent, data in agent_outputs.items():
            for finding in data.get("findings", []):
                finding = dict(finding)  # shallow copy to avoid mutation
                finding["agent"] = agent
                all_findings.append(finding)

        # Step 3 -- Deduplicate
        deduped = self._deduplicate(all_findings)

        # Step 4 -- Cross-validate severity disagreements (already handled
        # inside _pick_winner, but record metadata)
        deduped = self._resolve_severity_disagreements(deduped)

        # Auto-generate finding IDs and promote to full Finding dicts
        promoted = self._promote_findings(
            deduped,
            customer_name,
            customer_safe_name,
        )

        # Step 5 -- Consolidate governance
        governance = self._consolidate_governance(agent_outputs)

        # Step 6 -- Merge gap files from all agents
        merged_gaps = self._collect_gaps(agent_outputs, customer_name)

        # Cross-references
        cross_refs = self._union_cross_refs(agent_outputs)
        xref_summary = self._merge_xref_summaries(agent_outputs)

        # Governance resolved %
        gov_pct = self._compute_gov_pct(governance, agent_outputs)

        # Pre-generation validation: warn about P0/P1 findings with empty citations
        self._validate_finding_citations(promoted)

        return MergedCustomerOutput(
            customer=customer_name,
            customer_safe_name=customer_safe_name,
            findings=promoted,
            gaps=merged_gaps,
            cross_references=cross_refs,
            cross_reference_summary=xref_summary,
            governance_graph=governance,
            governance_resolved_pct=gov_pct,
        )

    def merge_all(self, findings_dir: Path) -> dict[str, MergedCustomerOutput]:
        """Process all customers found under *findings_dir*.

        Expects the directory layout::

            findings_dir/
                legal/<customer_safe_name>.json
                finance/<customer_safe_name>.json
                commercial/<customer_safe_name>.json
                producttech/<customer_safe_name>.json

        Returns ``{customer_safe_name: MergedCustomerOutput}``.
        """
        # Discover all customer safe names across agents
        customer_names: set[str] = set()
        for agent in ALL_SPECIALIST_AGENTS:
            agent_dir = findings_dir / agent
            if agent_dir.is_dir():
                for fp in agent_dir.glob("*.json"):
                    customer_names.add(fp.stem)

        results: dict[str, MergedCustomerOutput] = {}
        for csn in sorted(customer_names):
            agent_outputs: dict[str, dict[str, Any]] = {}
            for agent in ALL_SPECIALIST_AGENTS:
                fp = findings_dir / agent / f"{csn}.json"
                if fp.exists():
                    agent_outputs[agent] = json.loads(fp.read_text())
            if agent_outputs:
                results[csn] = self.merge_customer(
                    agent_outputs,
                    customer_safe_name=csn,
                )
        return results

    def write_merged(
        self,
        merged: dict[str, MergedCustomerOutput],
        output_dir: Path,
    ) -> None:
        """Write per-customer merged JSON files to *output_dir*."""
        output_dir.mkdir(parents=True, exist_ok=True)
        for csn, mco in merged.items():
            out_path = output_dir / f"{csn}.json"
            out_path.write_text(mco.model_dump_json(indent=2))

    # ------------------------------------------------------------------
    # Deduplication helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _match_key(finding: dict[str, Any]) -> tuple[str, ...]:
        """Dedup key: (citation source_path, citation location).

        When citation fields are empty, include finding_id or agent_name + title
        so that distinct findings are not collapsed into one.
        """
        cit = (finding.get("citations") or [{}])[0] if "citations" in finding else {}
        source_path = ""
        location = ""
        if isinstance(cit, dict):
            source_path = cit.get("source_path", "")
            location = cit.get("location", "")

        # When both citation fields are empty, add discriminator to avoid
        # collapsing distinct findings into a single group.
        if not source_path and not location:
            discriminator = finding.get("id", "") or f"{finding.get('agent', '')}:{finding.get('title', '')}"
            return (source_path, location, discriminator)
        return (source_path, location)

    def _deduplicate(self, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
        for f in findings:
            key = self._match_key(f)
            groups.setdefault(key, []).append(f)

        result: list[dict[str, Any]] = []
        for _key, group in groups.items():
            if len(group) == 1:
                result.append(group[0])
            else:
                result.append(self._pick_winner(group))
        return result

    @staticmethod
    def _pick_winner(group: list[dict[str, Any]]) -> dict[str, Any]:
        """Keep highest severity, longest exact_quote.  Record contributors."""
        sorted_group = sorted(
            group,
            key=lambda f: (
                SEVERITY_ORDER.get(f.get("severity", "P3"), 9),
                -len((f.get("citations") or [{}])[0].get("exact_quote", "") if f.get("citations") else ""),
            ),
        )
        winner = dict(sorted_group[0])
        winner.setdefault("metadata", {})
        winner["metadata"]["contributing_agents"] = [a for a in {f.get("agent", "") for f in group} if a]
        return winner

    # ------------------------------------------------------------------
    # Cross-validation
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_severity_disagreements(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Add severity_disagreement metadata when contributing agents differed."""
        for f in findings:
            meta = f.get("metadata", {})
            contributors = meta.get("contributing_agents", [])
            if len(contributors) > 1:
                # Nothing more to do at this point -- the winner already has
                # the highest severity.  We just annotate for traceability.
                meta.setdefault("severity_disagreement", {})
        return findings

    # ------------------------------------------------------------------
    # Governance consolidation
    # ------------------------------------------------------------------

    @staticmethod
    def _consolidate_governance(
        agent_outputs: dict[str, dict[str, Any]],
    ) -> GovernanceGraph:
        """Legal agent is authoritative; others supplement."""
        edges: list[GovernanceEdge] = []
        seen: set[tuple[str, str]] = set()

        # Legal primary
        legal_data = agent_outputs.get("legal", {})
        for edge_dict in legal_data.get("governance_graph", {}).get("edges", []):
            edge = GovernanceEdge.model_validate(edge_dict)
            key = (edge.from_file, edge.to_file)
            if key not in seen:
                edges.append(edge)
                seen.add(key)

        # Others additive
        for agent, data in agent_outputs.items():
            if agent == "legal":
                continue
            for edge_dict in data.get("governance_graph", {}).get("edges", []):
                edge = GovernanceEdge.model_validate(edge_dict)
                key = (edge.from_file, edge.to_file)
                if key not in seen:
                    edges.append(edge)
                    seen.add(key)

        return GovernanceGraph(edges=edges)

    # ------------------------------------------------------------------
    # Cross-reference helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _union_cross_refs(
        agent_outputs: dict[str, dict[str, Any]],
    ) -> list[CrossReference]:
        refs: list[CrossReference] = []
        for _agent, data in agent_outputs.items():
            for cr_dict in data.get("cross_references", []):
                try:
                    refs.append(CrossReference.model_validate(cr_dict))
                except Exception:  # noqa: BLE001
                    logger.warning("Skipping invalid cross-reference: %s", cr_dict)
        return refs

    @staticmethod
    def _merge_xref_summaries(
        agent_outputs: dict[str, dict[str, Any]],
    ) -> CrossReferenceSummary | None:
        merged_files: set[str] = set()
        total_compared = 0
        total_matches = 0
        total_mismatches = 0
        total_na = 0
        total_findings = 0
        total_gaps = 0
        has_any = False

        for data in agent_outputs.values():
            summary = data.get("cross_reference_summary")
            if summary:
                has_any = True
                merged_files.update(summary.get("reference_files_checked", []))
                total_compared += summary.get("data_points_compared", 0)
                total_matches += summary.get("matches", 0)
                total_mismatches += summary.get("mismatches", 0)
                total_na += summary.get("not_available", 0)
                total_findings += summary.get("findings_generated", 0)
                total_gaps += summary.get("gaps_generated", 0)

        if not has_any:
            return None

        return CrossReferenceSummary(
            reference_files_checked=sorted(merged_files),
            data_points_compared=total_compared,
            matches=total_matches,
            mismatches=total_mismatches,
            not_available=total_na,
            findings_generated=total_findings,
            gaps_generated=total_gaps,
        )

    @staticmethod
    def _compute_gov_pct(
        governance: GovernanceGraph,
        agent_outputs: dict[str, dict[str, Any]],
    ) -> float:
        """(files with governed_by resolved) / total_customer_files."""
        total_files = 0
        resolved = 0
        for data in agent_outputs.values():
            for fh in data.get("file_headers", []):
                total_files += 1
                gb = fh.get("governed_by", "UNRESOLVED")
                if gb != "UNRESOLVED":
                    resolved += 1
        if total_files == 0:
            return 0.0
        return min(round(resolved / total_files, 4), 1.0)

    # ------------------------------------------------------------------
    # Finding promotion
    # ------------------------------------------------------------------

    def _promote_findings(
        self,
        raw_findings: list[dict[str, Any]],
        customer_name: str,
        customer_safe_name: str,
    ) -> list[Finding]:
        """Transform raw dicts into full ``Finding`` models with auto-IDs."""
        results: list[Finding] = []
        counters: dict[str, int] = {}
        for f in raw_findings:
            agent = f.get("agent", "legal")
            seq = counters.get(agent, 0) + 1
            counters[agent] = seq
            finding_id = f"forensic-dd_{agent}_{customer_safe_name}_{seq:04d}"

            # Build Citation objects
            citations_raw = f.get("citations", [])
            citations: list[Citation] = []
            for c in citations_raw:
                if isinstance(c, dict):
                    citations.append(Citation.model_validate(c))
                else:
                    citations.append(c)

            # Ensure at least one citation -- mark as synthetic so QA can flag it
            if not citations:
                logger.warning(
                    "Finding '%s' (agent=%s) has no citations; adding synthetic placeholder",
                    f.get("title", "untitled"),
                    agent,
                )
                citations = [
                    Citation(
                        source_type=SourceType("file"),
                        source_path="[synthetic:no_citation_provided]",
                        location="",
                    )
                ]

            try:
                finding = Finding(
                    id=finding_id,
                    severity=f.get("severity", "P3"),
                    category=f.get("category", "uncategorized"),
                    title=f.get("title", "Untitled finding"),
                    description=f.get("description", ""),
                    citations=citations,
                    confidence=f.get("confidence", "medium"),
                    agent=agent,
                    skill="forensic-dd",
                    run_id=self.run_id,
                    timestamp=self.timestamp,
                    analysis_unit=customer_name,
                    metadata=f.get("metadata", {}),
                )
                results.append(finding)
            except Exception:  # noqa: BLE001
                logger.warning("Skipping finding that failed validation: %s", f.get("title"))
        return results

    # ------------------------------------------------------------------
    # Step 6 -- Gap collection
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_gaps(
        agent_outputs: dict[str, dict[str, Any]],
        customer_name: str,
    ) -> list[Gap]:
        """Collect and deduplicate gaps from all specialist agents.

        Each agent may produce a ``gaps`` list in its output.  This method
        unions them, deduplicating by ``(missing_item, gap_type)`` and keeping
        the highest-priority entry when duplicates exist.
        """
        seen: dict[tuple[str, str], dict[str, Any]] = {}

        for agent, data in agent_outputs.items():
            for gap_raw in data.get("gaps", []):
                gap_dict = dict(gap_raw)  # shallow copy
                gap_dict.setdefault("agent", agent)
                gap_dict.setdefault("customer", customer_name)
                dedup_key = (gap_dict.get("missing_item", ""), gap_dict.get("gap_type", ""))
                existing = seen.get(dedup_key)
                if existing is None:
                    seen[dedup_key] = gap_dict
                else:
                    # Keep higher priority
                    existing_prio = SEVERITY_ORDER.get(existing.get("priority", "P3"), 9)
                    new_prio = SEVERITY_ORDER.get(gap_dict.get("priority", "P3"), 9)
                    if new_prio < existing_prio:
                        seen[dedup_key] = gap_dict

        gaps: list[Gap] = []
        for gap_dict in seen.values():
            try:
                gaps.append(Gap.model_validate(gap_dict))
            except Exception:  # noqa: BLE001
                logger.warning("Skipping invalid gap during merge: %s", gap_dict.get("missing_item", ""))
        return gaps

    # ------------------------------------------------------------------
    # Pre-generation citation validation (Issue #48)
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_finding_citations(findings: list[Finding]) -> None:
        """Warn when P0/P1 findings have empty or synthetic citations.

        This is a pre-generation quality gate.  It does not reject findings
        outright (the Finding model validator already does that for missing
        exact_quote on P0/P1), but it logs warnings for synthetic citations
        so they surface in audit logs.
        """
        for finding in findings:
            if finding.severity in ("P0", "P1"):
                for cit in finding.citations:
                    if not cit.source_path or cit.source_path.startswith("[synthetic:"):
                        logger.warning(
                            "P0/P1 finding %s has synthetic/empty citation — this will be flagged by QA audit",
                            finding.id,
                        )
                    if not cit.exact_quote:
                        logger.warning(
                            "P0/P1 finding %s is missing exact_quote in citation — this will be flagged by QA audit",
                            finding.id,
                        )
