"""Finding merge and deduplication across specialist agents.

Implements the 6-step merge/dedup protocol from 10-reporting.md:
1. Collect agent outputs per subject
2. Merge findings into combined list
3. Deduplicate by match key (citation source_path + location)
4. Cross-validate severity disagreements
5. Consolidate governance graphs (Legal primary)
6. Merge gap files
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from dd_agents.models.enums import AgentName, Confidence, Severity, SourceType
from dd_agents.models.finding import (
    Citation,
    CrossReference,
    CrossReferenceSummary,
    Finding,
    Gap,
    MergedSubjectOutput,
)
from dd_agents.models.governance import GovernanceEdge, GovernanceGraph
from dd_agents.utils.constants import ALL_SPECIALIST_AGENTS, NON_SUBJECT_STEMS, SEVERITY_ORDER, SEVERITY_P3
from dd_agents.utils.naming import subject_safe_name as compute_safe_name

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class FindingMerger:
    """Executes the 6-step merge/dedup protocol for specialist agent outputs."""

    def __init__(
        self,
        run_id: str = "",
        timestamp: str = "",
        file_inventory: list[str] | None = None,
        file_precedence: dict[str, float] | None = None,
    ) -> None:
        self.run_id = run_id or datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        self.timestamp = timestamp or datetime.now(UTC).isoformat()
        self._file_index = self._build_file_index(file_inventory or [])
        self._file_precedence: dict[str, float] = file_precedence or {}

    # ------------------------------------------------------------------
    # File inventory index for citation path resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _build_file_index(file_inventory: list[str]) -> dict[str, list[str]]:
        """Build a basename → full-path(s) index from the files.txt inventory.

        Returns a dict mapping each lowercase basename to a list of full
        paths (multiple files can share a basename across directories).
        """
        index: dict[str, list[str]] = {}
        for path in file_inventory:
            if not path.strip():
                continue
            basename = path.rsplit("/", 1)[-1].lower()
            index.setdefault(basename, []).append(path)
        return index

    def _resolve_citation_path(self, source_path: str) -> str:
        """Resolve an agent-produced source_path against the file inventory.

        Tries progressively looser matching strategies:
        1. Exact match in inventory (pass through)
        2. Strip .md extraction artifact suffix
        3. Strip absolute /Users/... prefix to data-room root
        4. Basename lookup in the file index

        Returns the best matching path, or the original if no match.
        """
        if not self._file_index or not source_path:
            return source_path

        sp = source_path.strip()

        # Collect all known full paths for fast lookup.
        all_paths: set[str] | None = None

        def _known_paths() -> set[str]:
            nonlocal all_paths
            if all_paths is None:
                all_paths = {p for paths in self._file_index.values() for p in paths}
            return all_paths

        # 1. Exact match — nothing to fix.
        if sp in _known_paths():
            return sp

        # 2. Strip .md extraction artifact suffix (e.g. "file.xlsx.md" → "file.xlsx").
        if sp.endswith(".md") and "." in sp[:-3]:
            stripped = sp[:-3]
            if stripped in _known_paths():
                return stripped
            sp = stripped  # continue matching with stripped version

        # 3. Strip absolute path prefix — find the data-room top-level folder
        #    pattern (e.g. "1. Due Diligence/") and match from there.
        segments = sp.split("/")
        for i, seg in enumerate(segments):
            if seg and seg[:1].isdigit() and ". " in seg:
                candidate = "/".join(segments[i:])
                if candidate in _known_paths():
                    return candidate
                break

        # 4. Basename lookup: find the file in the index by its filename.
        basename = segments[-1].lower() if segments else ""
        if basename and basename in self._file_index:
            matches = self._file_index[basename]
            if len(matches) == 1:
                # Unambiguous — use the known full path.
                return matches[0]
            # Multiple files with same basename — try to pick the one whose
            # path suffix best matches the agent's partial path.
            sp_lower = sp.lower()
            for match in matches:
                if match.lower().endswith(sp_lower):
                    return match
            # Try matching last 2 path segments.
            if len(segments) >= 2:
                suffix = "/".join(segments[-2:]).lower()
                for match in matches:
                    if match.lower().endswith(suffix):
                        return match
            # Ambiguous but still better than an unresolved path — use first.
            return matches[0]

        return source_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def merge_subject(
        self,
        agent_outputs: dict[str, dict[str, Any]],
        subject_name: str = "",
        subject_safe_name: str = "",
    ) -> MergedSubjectOutput:
        """Merge findings from specialist agents for one subject.

        Parameters
        ----------
        agent_outputs:
            ``{agent_name: raw_json_dict}`` for each agent that produced output.
        subject_name:
            Canonical subject display name.  Falls back to the first agent
            output's ``subject`` field when not provided.
        subject_safe_name:
            Filesystem-safe slug.  Computed from *subject_name* when absent.
        """
        # Resolve subject identity
        if not subject_name:
            for data in agent_outputs.values():
                subject_name = data.get("subject", "unknown")
                break
        if not subject_safe_name and subject_name.strip():
            subject_safe_name = compute_safe_name(subject_name)

        # Step 2 -- Merge
        all_findings: list[dict[str, Any]] = []
        for agent, data in agent_outputs.items():
            for finding in data.get("findings", []):
                if not isinstance(finding, dict):
                    logger.warning("Skipping non-dict finding from %s: %s", agent, type(finding).__name__)
                    continue
                finding = dict(finding)  # shallow copy to avoid mutation
                finding["agent"] = agent
                # Coerce singular "citation" dict → "citations" array.
                # Some agents produce {"citation": {...}} instead of
                # {"citations": [{...}]}.  Normalise early so downstream
                # code only deals with the plural form.
                if "citations" not in finding and "citation" in finding:
                    cit = finding.pop("citation")
                    if isinstance(cit, dict):
                        finding["citations"] = [cit]
                    elif isinstance(cit, list):
                        finding["citations"] = cit
                all_findings.append(finding)

        # Step 3 -- Deduplicate (citation-based key matching)
        deduped = self._deduplicate(all_findings)

        # Step 3b -- Semantic dedup (Issue #150): catch near-duplicates
        # that differ in citation location but describe the same issue.
        deduped = self._semantic_dedup(deduped)

        # Step 4 -- Cross-validate severity disagreements (already handled
        # inside _pick_winner, but record metadata)
        deduped = self._resolve_severity_disagreements(deduped)

        # Auto-generate finding IDs and promote to full Finding dicts
        promoted, dropped = self._promote_findings(
            deduped,
            subject_name,
            subject_safe_name,
        )

        # Step 5 -- Consolidate governance
        governance = self._consolidate_governance(agent_outputs)

        # Step 6 -- Merge gap files from all agents
        merged_gaps = self._collect_gaps(agent_outputs, subject_name)

        # Cross-references
        cross_refs = self._union_cross_refs(agent_outputs)

        # Detect cross-agent conflicts (Issue #82).
        conflicts = self._detect_cross_agent_conflicts(cross_refs)
        if conflicts:
            logger.warning(
                "Detected %d cross-agent conflicts for subject %s",
                len(conflicts),
                subject_name,
            )

        xref_summary = self._merge_xref_summaries(agent_outputs)

        # Governance resolved %
        gov_pct = self._compute_gov_pct(governance, agent_outputs)

        # Pre-generation validation: warn about P0/P1 findings with empty citations
        self._validate_finding_citations(promoted)

        return MergedSubjectOutput(
            subject=subject_name,
            subject_safe_name=subject_safe_name,
            findings=promoted,
            gaps=merged_gaps,
            cross_references=cross_refs,
            cross_reference_summary=xref_summary,
            governance_graph=governance,
            governance_resolved_pct=gov_pct,
            dropped_findings=dropped,
            cross_agent_conflicts=conflicts,
        )

    # Non-subject JSON files that agents may write alongside subject findings.
    _NON_SUBJECT_STEMS = NON_SUBJECT_STEMS

    def merge_all(
        self,
        findings_dir: Path,
        *,
        expected_subjects: list[str] | None = None,
    ) -> dict[str, MergedSubjectOutput]:
        """Process all subjects found under *findings_dir*.

        Expects the directory layout::

            findings_dir/
                legal/<subject_safe_name>.json
                finance/<subject_safe_name>.json
                commercial/<subject_safe_name>.json
                producttech/<subject_safe_name>.json

        Parameters
        ----------
        findings_dir:
            Root of the per-agent findings directories.
        expected_subjects:
            If provided, discovered stems are validated against this
            canonical list.  Unknown stems are mapped to the closest
            expected name (via fuzzy match) and a warning is logged.

        Returns ``{subject_safe_name: MergedSubjectOutput}``.
        """
        # Discover all subject safe name across agents
        subject_names: set[str] = set()
        for agent in ALL_SPECIALIST_AGENTS:
            agent_dir = findings_dir / agent
            if agent_dir.is_dir():
                for fp in agent_dir.glob("*.json"):
                    if fp.stem not in self._NON_SUBJECT_STEMS:
                        subject_names.add(fp.stem)

        # Validate discovered stems against expected subject list (Issue #88).
        if expected_subjects is not None:
            expected_set = set(expected_subjects)
            unknown_stems = subject_names - expected_set
            if unknown_stems:
                _rf_available = True
                try:
                    from rapidfuzz import process as rf_process
                except ImportError:
                    _rf_available = False

                for stem in sorted(unknown_stems):
                    best_match: str | None = None
                    if _rf_available and expected_subjects:
                        result = rf_process.extractOne(stem, expected_subjects)
                        if result and result[1] >= 80.0:
                            best_match = result[0]
                    if best_match:
                        logger.warning(
                            "Unknown subject stem %r — fuzzy-matched to %r (renaming files)",
                            stem,
                            best_match,
                        )
                        # Rename agent files from unknown stem to canonical name
                        for agent in ALL_SPECIALIST_AGENTS:
                            src = findings_dir / agent / f"{stem}.json"
                            dst = findings_dir / agent / f"{best_match}.json"
                            if src.exists() and not dst.exists():
                                src.rename(dst)
                        subject_names.discard(stem)
                        subject_names.add(best_match)
                    else:
                        logger.warning(
                            "Unknown subject stem %r not in expected list and no fuzzy match — keeping as-is",
                            stem,
                        )

            missing = expected_set - subject_names
            if missing:
                logger.warning(
                    "%d expected subjects have no findings: %s",
                    len(missing),
                    sorted(missing)[:10],
                )

        results: dict[str, MergedSubjectOutput] = {}
        failed_subjects: list[dict[str, Any]] = []
        for csn in sorted(subject_names):
            agent_outputs: dict[str, dict[str, Any]] = {}
            for agent in ALL_SPECIALIST_AGENTS:
                fp = findings_dir / agent / f"{csn}.json"
                if fp.exists():
                    try:
                        loaded = json.loads(fp.read_text(encoding="utf-8"))
                    except (json.JSONDecodeError, OSError) as exc:
                        logger.warning("Skipping corrupt findings file %s: %s", fp, exc)
                        continue
                    if isinstance(loaded, dict):
                        agent_outputs[agent] = loaded
                    else:
                        logger.warning("Findings file %s is not a JSON object (got %s)", fp, type(loaded).__name__)
            if agent_outputs:
                try:
                    results[csn] = self.merge_subject(
                        agent_outputs,
                        subject_safe_name=csn,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Failed to merge subject %s — quarantined", csn)
                    failed_subjects.append(
                        {
                            "subject": csn,
                            "error": str(exc),
                            "agents_available": list(agent_outputs.keys()),
                            "timestamp": self.timestamp,
                        }
                    )

        # Persist quarantine manifest so failed subjects leave an audit trail.
        if failed_subjects:
            quarantine_dir = findings_dir / "merged"
            quarantine_dir.mkdir(parents=True, exist_ok=True)
            quarantine_path = quarantine_dir / "_quarantine.json"
            quarantine_path.write_text(
                json.dumps(failed_subjects, indent=2),
                encoding="utf-8",
            )
            logger.error(
                "%d subject(s) quarantined due to merge failure — see %s",
                len(failed_subjects),
                quarantine_path,
            )
        # Check agent coverage (Issue #85).
        coverage_gaps = self.check_agent_coverage(results)
        if coverage_gaps:
            logger.warning(
                "Agent coverage gaps detected: %d subjects missing agents",
                len(coverage_gaps),
            )

        return results

    def write_merged(
        self,
        merged: dict[str, MergedSubjectOutput],
        output_dir: Path,
        *,
        clean_stale: bool = True,
    ) -> None:
        """Write per-subject merged JSON files to *output_dir*.

        When *clean_stale* is ``True`` (default), any ``.json`` file in
        *output_dir* that does not correspond to a subject in *merged*
        is removed.  This prevents stale artefacts (e.g.
        ``numerical_manifest.json``, ``coverage_manifest.json``) from
        accumulating across runs.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        # Archive stale files before writing (never delete outright).
        if clean_stale:
            expected_stems = set(merged.keys())
            # Internal merge artefacts — never treated as stale subjects.
            internal_prefixes = ("_quarantine", "_dropped", "_archive")
            archive_dir = output_dir / "_archive"
            for existing in output_dir.glob("*.json"):
                if existing.stem.startswith(internal_prefixes):
                    continue
                if existing.stem not in expected_stems:
                    archive_dir.mkdir(parents=True, exist_ok=True)
                    dest = archive_dir / existing.name
                    logger.info("Archiving stale merged file: %s → _archive/", existing.name)
                    try:
                        existing.rename(dest)
                    except OSError as exc:
                        logger.warning("Failed to archive stale file %s: %s", existing, exc)

        for csn, mco in merged.items():
            out_path = output_dir / f"{csn}.json"
            out_path.write_text(mco.model_dump_json(indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    # Agent coverage validation (Issue #85)
    # ------------------------------------------------------------------

    @staticmethod
    def check_agent_coverage(
        merged: dict[str, MergedSubjectOutput],
        findings_dir: Path | None = None,
    ) -> list[dict[str, Any]]:
        """Verify every subject has findings or gaps from all 4 specialist agents.

        Distinguishes two failure modes when *findings_dir* is provided:

        - ``missing_output``: Agent never produced a JSON file for this subject.
          Indicates a pipeline failure (agent crash, batch omission).
        - ``no_findings``: Agent produced a file but it contained zero findings
          and zero gaps.  May be legitimate (clean subject) or indicate
          extraction/analysis failure.

        Returns a list of coverage gaps::

            [{"subject": str,
              "missing_agents": [str],       # no content at all
              "missing_output": [str],       # no JSON file on disk
              "no_findings": [str]}]         # file exists, empty content
        """
        expected_agents = set(ALL_SPECIALIST_AGENTS)
        gaps: list[dict[str, Any]] = []
        for csn, mco in merged.items():
            actual_agents: set[str] = set()
            for f in mco.findings:
                actual_agents.add(f.agent.value if hasattr(f.agent, "value") else str(f.agent))
            for g in mco.gaps:
                if g.agent:
                    actual_agents.add(g.agent.value if hasattr(g.agent, "value") else str(g.agent))
            missing = expected_agents - actual_agents
            if missing:
                missing_output: list[str] = []
                no_findings: list[str] = []

                if findings_dir is not None:
                    for agent_name in sorted(missing):
                        agent_file = findings_dir / agent_name / f"{csn}.json"
                        if agent_file.exists():
                            no_findings.append(agent_name)
                        else:
                            missing_output.append(agent_name)
                else:
                    # Without findings_dir, all missing agents are undifferentiated.
                    missing_output = sorted(missing)

                gaps.append(
                    {
                        "subject": csn,
                        "missing_agents": sorted(missing),
                        "missing_output": missing_output,
                        "no_findings": no_findings,
                    }
                )
                if missing_output:
                    logger.warning(
                        "Subject %s missing agent output files: %s",
                        csn,
                        missing_output,
                    )
                if no_findings:
                    logger.info(
                        "Subject %s has empty agent output (no findings/gaps): %s",
                        csn,
                        no_findings,
                    )
        if gaps:
            logger.warning(
                "%d/%d subjects have incomplete agent coverage",
                len(gaps),
                len(merged),
            )
        return gaps

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
    def _first_source_path(f: dict[str, Any]) -> str:
        """Extract first citation source_path from a finding dict."""
        cits = f.get("citations")
        if not isinstance(cits, list) or not cits:
            return ""
        first = cits[0]
        if isinstance(first, dict):
            return first.get("source_path") or ""
        return ""

    @staticmethod
    def _first_quote(f: dict[str, Any]) -> str:
        """Extract first exact_quote from a finding dict, tolerating bad shapes."""
        cits = f.get("citations")
        if not isinstance(cits, list) or not cits:
            return ""
        first = cits[0]
        if isinstance(first, dict):
            return first.get("exact_quote") or ""
        return ""

    def _pick_winner(self, group: list[dict[str, Any]]) -> dict[str, Any]:
        """Keep highest severity, highest source precedence, longest quote.  Record contributors."""
        sorted_group = sorted(
            group,
            key=lambda f: (
                SEVERITY_ORDER.get(f.get("severity", SEVERITY_P3), 9),
                -self._source_precedence(f),
                -len(FindingMerger._first_quote(f)),
            ),
        )
        winner = dict(sorted_group[0])
        winner.setdefault("metadata", {})
        winner["metadata"]["contributing_agents"] = [a for a in {f.get("agent", "") for f in group} if a]
        return winner

    def _source_precedence(self, finding: dict[str, Any]) -> float:
        """Look up the precedence score for a finding's primary citation source."""
        if not self._file_precedence:
            return 0.0
        source = self._first_source_path(finding)
        if not source:
            return 0.0
        # Try exact match first
        if source in self._file_precedence:
            return self._file_precedence[source]
        # Basename fallback: take the maximum score among matches
        # (multiple subjects may have files with the same name)
        basename = source.rsplit("/", 1)[-1].lower() if "/" in source else source.lower()
        matches = [
            score
            for path, score in self._file_precedence.items()
            if path.lower().endswith("/" + basename) or path.lower() == basename
        ]
        return max(matches) if matches else 0.0

    # ------------------------------------------------------------------
    # Semantic dedup (Issue #150)
    # ------------------------------------------------------------------

    _SEMANTIC_THRESHOLD: int = 80  # rapidfuzz token_sort_ratio threshold

    def _semantic_dedup(self, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Merge semantically similar findings using fuzzy title matching.

        Uses rapidfuzz token_sort_ratio on titles to catch near-duplicates
        from *different agents* that describe the same issue with different
        wording. Same-agent findings are never merged (they may describe
        distinct issues in different documents).
        """
        if len(findings) <= 1:
            return findings

        from rapidfuzz import fuzz

        merged_indices: set[int] = set()
        result: list[dict[str, Any]] = []

        for i, fi in enumerate(findings):
            if i in merged_indices:
                continue
            group = [fi]
            ti = str(fi.get("title", ""))
            ai = fi.get("agent", "")
            for j in range(i + 1, len(findings)):
                if j in merged_indices:
                    continue
                fj = findings[j]
                aj = fj.get("agent", "")
                # Only merge across different agents (including both-empty)
                if ai == aj:
                    continue
                # Only merge if referencing the same document (require both paths known)
                si = self._first_source_path(fi)
                sj = self._first_source_path(fj)
                if not si or not sj or si != sj:
                    continue
                tj = str(fj.get("title", ""))
                score = fuzz.token_sort_ratio(ti, tj)
                if score >= self._SEMANTIC_THRESHOLD:
                    group.append(fj)
                    merged_indices.add(j)
            if len(group) == 1:
                result.append(group[0])
            else:
                winner = self._pick_winner(group)
                winner.setdefault("metadata", {})["semantic_dedup"] = True
                # Aggregate agents from both agent field AND prior dedup contributing_agents
                all_agents: set[str] = set()
                for f in group:
                    if f.get("agent"):
                        all_agents.add(f["agent"])
                    for ca in f.get("metadata", {}).get("contributing_agents", []):
                        if ca:
                            all_agents.add(ca)
                winner["metadata"]["contributing_agents"] = sorted(all_agents)
                winner["metadata"]["corroborated_by"] = len(all_agents)
                result.append(winner)
        return result

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
    def _normalize_governance_edge(raw: dict[str, Any]) -> dict[str, Any]:
        """Normalise an agent-produced governance edge to match GovernanceEdge schema.

        Agents commonly produce ``{"from": "...", "to": "..."}`` but the Pydantic
        model expects ``from_file`` and ``to_file``.
        """
        e = dict(raw)
        # Map from/to → from_file/to_file
        if "from_file" not in e and "from" in e:
            e["from_file"] = e.pop("from")
        if "to_file" not in e and "to" in e:
            e["to_file"] = e.pop("to")
        # Map source/target alternative names
        if "from_file" not in e and "source" in e:
            e["from_file"] = e.pop("source")
        if "to_file" not in e and "target" in e:
            e["to_file"] = e.pop("target")
        # Ensure required fields have string values
        e.setdefault("from_file", "")
        e.setdefault("to_file", "")
        # Map reason → link_reason
        if "link_reason" not in e and "reason" in e:
            e["link_reason"] = e.pop("reason")
        return e

    @staticmethod
    def _consolidate_governance(
        agent_outputs: dict[str, dict[str, Any]],
    ) -> GovernanceGraph:
        """Legal agent is authoritative; others supplement."""
        edges: list[GovernanceEdge] = []
        seen: set[tuple[str, str]] = set()

        def _try_add_edge(edge_dict: dict[str, Any], source_agent: str) -> None:
            normalised = FindingMerger._normalize_governance_edge(edge_dict)
            try:
                edge = GovernanceEdge.model_validate(normalised)
            except Exception:  # noqa: BLE001
                logger.warning("Skipping invalid governance edge from %s: %s", source_agent, edge_dict)
                return
            key = (edge.from_file, edge.to_file)
            if key not in seen:
                edges.append(edge)
                seen.add(key)

        def _get_edges(data: dict[str, Any]) -> list[Any]:
            gg = data.get("governance_graph")
            if not isinstance(gg, dict):
                return []
            edges_val = gg.get("edges")
            return edges_val if isinstance(edges_val, list) else []

        # Legal primary
        legal_data = agent_outputs.get("legal", {})
        for edge_dict in _get_edges(legal_data):
            _try_add_edge(edge_dict, "legal")

        # Others additive
        for agent, data in agent_outputs.items():
            if agent == "legal":
                continue
            for edge_dict in _get_edges(data):
                _try_add_edge(edge_dict, agent)

        return GovernanceGraph(edges=edges)

    # ------------------------------------------------------------------
    # Cross-reference helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_cross_reference(raw: dict[str, Any]) -> dict[str, Any]:
        """Normalise an agent-produced cross-reference to match CrossReference schema.

        Agents may use field names like ``source_file``, ``target_category``,
        ``status`` instead of the Pydantic model's ``contract_source``,
        ``reference_source``, ``match_status``.
        """
        cr = dict(raw)
        # Map data_point from alternative names
        if "data_point" not in cr:
            cr["data_point"] = cr.pop("item", cr.pop("field", cr.pop("metric", "unknown")))
        # Map match_status from alternative names
        if "match_status" not in cr and "status" in cr:
            cr["match_status"] = cr.pop("status")
        # Build contract_source from flat fields if missing
        if "contract_source" not in cr:
            src: dict[str, Any] = {}
            if "source_file" in cr:
                src["file"] = cr.pop("source_file")
            if "source_page" in cr:
                src["page"] = cr.pop("source_page")
            if "source_quote" in cr:
                src["quote"] = cr.pop("source_quote")
            if src:
                cr["contract_source"] = src
        # Build reference_source from flat fields if missing
        if "reference_source" not in cr:
            ref: dict[str, Any] = {}
            if "reference_file" in cr:
                ref["file"] = cr.pop("reference_file")
            elif "target_file" in cr:
                ref["file"] = cr.pop("target_file")
            if "target_category" in cr:
                ref["tab"] = cr.pop("target_category")
            if ref:
                cr["reference_source"] = ref
        return cr

    @staticmethod
    def _coerce_cross_reference_entry(entry: Any, agent: str) -> dict[str, Any] | None:
        """Coerce a non-dict cross-reference entry into a minimal dict.

        Agents sometimes produce bare strings (e.g. "Revenue terms match
        between MSA and Order Form") instead of structured objects.  Rather
        than silently dropping this data, we parse it into a minimal
        CrossReference dict so the information is preserved.

        Returns ``None`` only for truly unrecoverable types (e.g. ``int``,
        ``bool``, ``None``).
        """
        if isinstance(entry, dict):
            return entry
        if isinstance(entry, str) and entry.strip():
            text = entry.strip()
            # Infer match_status from keywords in the string.
            lower = text.lower()
            if any(w in lower for w in ("mismatch", "discrepan", "differ", "variance", "conflict")):
                status = "mismatch"
            elif re.search(r"\b(?:match(?:ed|es)?|consistent|aligned?|confirmed?)\b", lower):
                status = "match"
            else:
                status = "not_available"
            logger.warning(
                "Recovered bare-string cross-reference from %s as data_point (status=%s): %r",
                agent,
                status,
                text[:120],
            )
            return {
                "data_point": text[:200],
                "match_status": status,
                "interpretation": f"Auto-recovered from unstructured agent output ({agent})",
            }
        logger.warning(
            "Dropping unrecoverable cross-reference entry from %s: type=%s",
            agent,
            type(entry).__name__,
        )
        return None

    @staticmethod
    def _is_empty_shell_cross_ref(cr: dict[str, Any]) -> bool:
        """Detect empty-shell cross-references that carry no useful data.

        Agents sometimes produce structural placeholders with
        ``data_point="unknown"`` and empty value fields.  These pollute
        the report without adding analytical value.
        """
        dp = str(cr.get("data_point", "")).strip().lower()
        if dp in ("unknown", "", "n/a", "none"):
            # Check if ANY value field is populated.
            for key in ("contract_value", "reference_value", "variance", "interpretation"):
                val = cr.get(key)
                if val and str(val).strip():
                    return False
            # Check nested source objects for real content.
            for src_key in ("contract_source", "reference_source"):
                src = cr.get(src_key)
                if isinstance(src, dict):
                    for v in src.values():
                        if v and str(v).strip():
                            return False
            return True
        return False

    @staticmethod
    def _union_cross_refs(
        agent_outputs: dict[str, dict[str, Any]],
    ) -> list[CrossReference]:
        refs: list[CrossReference] = []
        empty_shell_count = 0
        for agent, data in agent_outputs.items():
            for cr_raw in data.get("cross_references", []):
                cr_dict = FindingMerger._coerce_cross_reference_entry(cr_raw, agent)
                if cr_dict is None:
                    continue
                normalised = FindingMerger._normalize_cross_reference(cr_dict)
                # Filter out empty-shell cross-references that carry no
                # analytical data (e.g. data_point="unknown", empty values).
                if FindingMerger._is_empty_shell_cross_ref(normalised):
                    empty_shell_count += 1
                    continue
                try:
                    refs.append(CrossReference.model_validate(normalised))
                except Exception:  # noqa: BLE001
                    logger.warning("Skipping invalid cross-reference from %s: %s", agent, cr_dict)
        if empty_shell_count:
            logger.info(
                "Filtered %d empty-shell cross-references (data_point=unknown, no values)",
                empty_shell_count,
            )
        return refs

    @staticmethod
    def _detect_cross_agent_conflicts(
        cross_refs: list[CrossReference],
    ) -> list[dict[str, Any]]:
        """Detect conflicting values for the same data_point across agents.

        Groups cross-references by (data_point, data_type) and flags entries
        where different agents report different contract_value or reference_value
        for the same metric.

        Returns a list of conflict dicts with: data_point, agents, values, severity.
        """
        from collections import defaultdict

        # Group by data_point (normalized).
        groups: dict[str, list[CrossReference]] = defaultdict(list)
        for cr in cross_refs:
            key = cr.data_point.strip().lower()
            if key and key != "unknown":
                groups[key].append(cr)

        conflicts: list[dict[str, Any]] = []
        for data_point, refs in groups.items():
            if len(refs) < 2:
                continue
            # Check if contract_value or reference_value differ across refs.
            contract_values = {r.contract_value.strip() for r in refs if r.contract_value.strip()}
            reference_values = {r.reference_value.strip() for r in refs if r.reference_value.strip()}
            if len(contract_values) > 1 or len(reference_values) > 1:
                conflicts.append(
                    {
                        "data_point": data_point,
                        "contract_values": sorted(contract_values),
                        "reference_values": sorted(reference_values),
                        "ref_count": len(refs),
                    }
                )
                logger.warning(
                    "Cross-agent conflict on '%s': contract_values=%s, reference_values=%s",
                    data_point,
                    sorted(contract_values),
                    sorted(reference_values),
                )
        return conflicts

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
            if summary and isinstance(summary, dict):
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
        """(files with governed_by resolved) / total_subject_files."""
        total_files = 0
        resolved = 0
        for data in agent_outputs.values():
            for fh in data.get("file_headers", []):
                if not isinstance(fh, dict):
                    continue
                total_files += 1
                gb = fh.get("governed_by", "UNRESOLVED")
                if gb != "UNRESOLVED":
                    resolved += 1
        if total_files == 0:
            return 0.0
        return min(round(resolved / total_files, 4), 1.0)

    # ------------------------------------------------------------------
    # Citation normalisation
    # ------------------------------------------------------------------

    def _normalize_citation(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Normalise an agent-produced citation dict to match the Citation schema.

        Agents may produce citations with different field names depending on
        whether they follow the prompt schema (``file_path``, ``page``,
        ``section_ref``) or the Pydantic schema (``source_type``, ``source_path``,
        ``location``).  This method maps the former to the latter so that
        ``Citation.model_validate()`` succeeds.

        When a file inventory is available, also resolves agent-produced paths
        against the inventory to fix common mismatches (basename-only paths,
        ``.md`` extraction artifacts, absolute path prefixes).
        """
        c = dict(raw)  # shallow copy to avoid mutation

        # Map file_path → source_path (prompt schema → Pydantic schema).
        if "source_path" not in c and "file_path" in c:
            c["source_path"] = c.pop("file_path")

        # Default source_type to "file" when missing.
        if "source_type" not in c:
            c["source_type"] = "file"

        # Coerce None values to safe defaults (agents may write null fields).
        if not c.get("source_path"):
            c["source_path"] = ""
        if not c.get("source_type"):
            c["source_type"] = "file"

        # Resolve source_path against the file inventory.
        sp = c.get("source_path", "")
        if sp and not sp.startswith("["):
            c["source_path"] = self._resolve_citation_path(sp)

        # Build location from page / section_ref when location is absent.
        if "location" not in c:
            parts: list[str] = []
            section = c.pop("section_ref", None)
            page = c.pop("page", None)
            if section:
                parts.append(str(section))
            if page is not None:
                parts.append(f"p. {page}")
            c["location"] = ", ".join(parts) if parts else ""
        else:
            # Clean up extra keys even when location is present.
            c.pop("section_ref", None)
            c.pop("page", None)

        return c

    # ------------------------------------------------------------------
    # Finding promotion
    # ------------------------------------------------------------------

    # Severity normalization: agents may emit "high"/"medium"/"low"/"critical"
    # instead of P0/P1/P2/P3.  Map common synonyms to standard Severity values.
    _SEVERITY_MAP: dict[str, Severity] = {
        "critical": Severity.P0,
        "blocker": Severity.P0,
        "deal-stopper": Severity.P0,
        "high": Severity.P1,
        "medium": Severity.P2,
        "moderate": Severity.P2,
        "low": Severity.P3,
        "minor": Severity.P3,
        "info": Severity.P3,
        "informational": Severity.P3,
        "p0": Severity.P0,
        "p1": Severity.P1,
        "p2": Severity.P2,
        "p3": Severity.P3,
    }

    @staticmethod
    def _normalize_severity(raw: str) -> Severity:
        """Map agent severity strings to ``Severity`` enum values."""
        return FindingMerger._SEVERITY_MAP.get(raw.strip().lower(), Severity.P3)

    @staticmethod
    def _normalize_agent_name(raw: str) -> str:
        """Normalise agent name to match ``AgentName`` enum values."""
        cleaned = raw.strip().lower().replace("-", "").replace("_", "").replace(" ", "")
        agent_map: dict[str, str] = {
            "legal": "legal",
            "finance": "finance",
            "commercial": "commercial",
            "producttech": "producttech",
            "product_tech": "producttech",
            "product-tech": "producttech",
            "product": "producttech",
        }
        return agent_map.get(cleaned, raw.strip().lower())

    def _promote_findings(
        self,
        raw_findings: list[dict[str, Any]],
        subject_name: str,
        subject_safe_name: str,
    ) -> tuple[list[Finding], list[dict[str, Any]]]:
        """Transform raw dicts into full ``Finding`` models with auto-IDs.

        Returns
        -------
        tuple[list[Finding], list[dict[str, Any]]]
            (promoted findings, dropped findings with error context).
        """
        results: list[Finding] = []
        dropped: list[dict[str, Any]] = []
        counters: dict[str, int] = {}
        for f in raw_findings:
            agent = self._normalize_agent_name(f.get("agent", "legal"))
            seq = counters.get(agent, 0) + 1
            counters[agent] = seq
            finding_id = f"forensic-dd_{agent}_{subject_safe_name}_{seq:04d}"

            # Normalise severity BEFORE Pydantic validation.
            raw_severity = f.get("severity", SEVERITY_P3)
            severity = self._normalize_severity(str(raw_severity))

            # Truncate title to 120 chars to prevent max_length validation failure.
            title = (f.get("title") or "Untitled finding")[:120]

            # Build Citation objects — handle both nested citations array and
            # flat finding-level fields (file_path, page, section_ref, exact_quote).
            # Also accept "evidence" as an alias (some agents produce this key).
            citations_raw = f.get("citations") or f.get("evidence") or []

            # Normalise "evidence" items: map {"file": ..., "page": ...}
            # to the standard citation shape {"file_path": ..., "page": ...}.
            if citations_raw and isinstance(citations_raw[0], dict) and "file" in citations_raw[0]:
                citations_raw = [
                    {("file_path" if k == "file" else k): v for k, v in item.items()}
                    if isinstance(item, dict)
                    else item
                    for item in citations_raw
                ]

            # If no citations array, construct one from flat finding-level fields.
            if not citations_raw:
                flat_cit: dict[str, Any] = {}
                for key in (
                    "file_path",
                    "source_path",
                    "source_type",
                    "page",
                    "section_ref",
                    "location",
                    "exact_quote",
                ):
                    if key in f:
                        flat_cit[key] = f[key]
                if flat_cit:
                    citations_raw = [flat_cit]

            citations: list[Citation] = []
            has_synthetic = False
            for c in citations_raw:
                if isinstance(c, dict):
                    normalised = self._normalize_citation(c)
                    try:
                        citations.append(Citation.model_validate(normalised))
                    except Exception:  # noqa: BLE001
                        # Last resort: construct a minimal citation preserving
                        # whatever fields we can salvage.
                        logger.warning(
                            "Citation validation failed for finding '%s'; constructing fallback. Raw: %s",
                            f.get("title", "untitled"),
                            c,
                        )
                        citations.append(
                            Citation(
                                source_type=SourceType("file"),
                                source_path=normalised.get("source_path") or "[unknown]",
                                location=normalised.get("location") or "",
                                exact_quote=normalised.get("exact_quote") or None,
                            )
                        )
                elif isinstance(c, Citation):
                    citations.append(c)

            # Ensure at least one citation -- mark as synthetic so QA can flag it
            if not citations:
                logger.warning(
                    "Finding '%s' (agent=%s) has no citations; adding synthetic placeholder",
                    f.get("title", "untitled"),
                    agent,
                )
                has_synthetic = True
                citations = [
                    Citation(
                        source_type=SourceType("file"),
                        source_path="[synthetic:no_citation_provided]",
                        location="",
                    )
                ]

            # P0/P1 findings require real citations: non-empty source_path
            # AND exact_quote on every citation.  If any citation fails these
            # checks (including synthetic ones), downgrade to P2 rather than
            # losing the finding entirely.
            if severity in (Severity.P0, Severity.P1):
                missing_quote = any(not cit.exact_quote for cit in citations)
                empty_source = any(
                    not cit.source_path or cit.source_path.startswith("[synthetic:") for cit in citations
                )
                if missing_quote or has_synthetic or empty_source:
                    original_severity = severity
                    severity = Severity.P2
                    reason = (
                        "citations lack exact_quote" if missing_quote else "citations have empty/synthetic source_path"
                    )
                    logger.warning(
                        "Downgraded finding '%s' from %s to P2: %s",
                        title,
                        original_severity,
                        reason,
                    )

            # P2 findings: require exact_quote on at least one citation.
            # Downgrade to P3 if all citations are synthetic OR missing quotes.
            # Exception: if step 23 already downgraded for citation issues, don't
            # apply a second penalty — one severity-level drop is sufficient.
            elif severity == Severity.P2:
                pre_merge_downgraded = "Downgraded" in str(f.get("verification_note", ""))
                all_synthetic = has_synthetic or all(
                    not cit.source_path or cit.source_path.startswith("[synthetic:") for cit in citations
                )
                all_missing_quote = all(not cit.exact_quote for cit in citations)
                if pre_merge_downgraded:
                    logger.debug(
                        "Preserving P2 for '%s': already downgraded at pre-merge validation",
                        title,
                    )
                elif all_synthetic:
                    severity = Severity.P3
                    logger.warning(
                        "Downgraded finding '%s' from P2 to P3: no real citation provided",
                        title,
                    )
                elif all_missing_quote:
                    severity = Severity.P3
                    logger.warning(
                        "Downgraded finding '%s' from P2 to P3: all citations lack exact_quote",
                        title,
                    )

            # Normalise confidence to enum values.
            raw_conf = str(f.get("confidence", "medium")).strip().lower()
            confidence = Confidence(raw_conf) if raw_conf in ("high", "medium", "low") else Confidence.MEDIUM

            # Degrade confidence when citations are weak — synthetic or missing
            # exact_quote on any citation caps confidence at medium.
            has_weak_citation = has_synthetic or any(not cit.exact_quote for cit in citations)
            if has_weak_citation and confidence == Confidence.HIGH:
                confidence = Confidence.MEDIUM

            # Ensure description is non-empty -- agents occasionally omit it.
            # Fall back to title (always present by this point) rather than
            # dropping the finding or failing the format audit.
            description = f.get("description") or title

            # --- Issue #145: Stamp per-finding provenance ---
            meta = dict(f.get("metadata", {}))
            contributing = meta.get("contributing_agents", [agent])
            was_deduped = meta.get("semantic_dedup", False)
            merge_action = (
                "semantic_deduped"
                if was_deduped
                else ("severity_escalated" if meta.get("severity_disagreement") else "kept")
            )
            original_sev = self._normalize_severity(str(raw_severity))
            meta["provenance"] = {
                "agent_name": agent,
                "contributing_agents": contributing if isinstance(contributing, list) else [agent],
                "merge_action": merge_action,
                "citation_verified": not has_synthetic,
                "original_severity": original_sev,
                "recalibrated": severity != original_sev,
                "recalibration_reason": ("citation_downgrade" if severity != original_sev else ""),
            }

            try:
                finding = Finding(
                    id=finding_id,
                    severity=severity,
                    category=f.get("category", "uncategorized"),
                    title=title,
                    description=description,
                    citations=citations,
                    confidence=confidence,
                    agent=AgentName(agent),
                    skill="forensic-dd",
                    run_id=self.run_id,
                    timestamp=self.timestamp,
                    analysis_unit=subject_name,
                    metadata=meta,
                )
                results.append(finding)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Finding DROPPED: title=%r agent=%s subject=%s severity=%r->%s error=%s",
                    f.get("title"),
                    agent,
                    subject_name,
                    raw_severity,
                    severity,
                    exc,
                )
                dropped.append({"title": f.get("title"), "agent": agent, "error": str(exc)})

        if dropped:
            logger.warning(
                "Subject %s: %d/%d findings dropped during promotion",
                subject_name,
                len(dropped),
                len(raw_findings),
            )

        return results, dropped

    # ------------------------------------------------------------------
    # Step 6 -- Gap collection
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce_gap_type(raw_value: Any, agent: str) -> str:
        """Coerce an arbitrary agent-produced gap_type to a valid GapType enum value.

        The 6 GapType categories form a specificity hierarchy:

        * 4 *specific* categories have distinctive vocabulary that can't
          be confused with anything else (Unreadable, Contradiction,
          Data_Mismatch, Ambiguous_Link).
        * 2 *broad* categories split on whether the document exists but
          is incomplete (Missing_Data) or is entirely absent (Missing_Doc).

        We check specific → broad, defaulting to Missing_Doc.
        """
        if not isinstance(raw_value, str) or not raw_value.strip():
            return "Missing_Doc"

        valid = {"Missing_Doc", "Missing_Data", "Ambiguous_Link", "Unreadable", "Contradiction", "Data_Mismatch"}
        if raw_value in valid:
            return raw_value

        s = raw_value.strip().lower().replace("-", "_")

        def _contains(*stems: str) -> bool:
            return any(stem in s for stem in stems)

        # --- Specific categories (distinctive vocabulary) ---

        # Document exists but can't be parsed
        if _contains("unreadab", "ocr", "garble", "illegib", "image_only", "scan_qual"):
            return "Unreadable"
        # Two sources say opposite things
        if _contains("contradict", "conflict"):
            return "Contradiction"
        # Values disagree between sources
        if _contains("mismatch", "discrepan", "inconsisten"):
            return "Data_Mismatch"
        # Governance link can't be resolved
        if _contains("ambiguous", "unclear"):
            return "Ambiguous_Link"

        # --- Broad categories: Missing_Data vs Missing_Doc ---

        # Document exists but its content is incomplete / redacted / empty
        if _contains("incomplete", "partial", "redact", "blank", "empty", "no_data"):
            return "Missing_Data"
        # Qualifier implies the *data* is absent (not the document itself)
        if _contains("information", "detail", "analysis", "metric", "content", "category", "breakdown"):
            return "Missing_Data"

        # Default: the document itself is absent
        return "Missing_Doc"

    @staticmethod
    def _coerce_gap_string(text: str, agent: str) -> dict[str, Any]:
        """Recover a structured gap dict from a bare string.

        Agents sometimes produce gaps as plain strings (e.g. "Missing DPA
        for data processing").  Rather than a minimal wrap, we extract as
        much structure as possible using keyword analysis.
        """
        text = text.strip()
        lower = text.lower()
        logger.warning(
            "Recovered bare-string gap from %s as structured object: %r",
            agent,
            text[:120],
        )

        # Infer gap_type from keywords.
        gap_type = FindingMerger._coerce_gap_type(text, agent)

        # Infer priority from severity-like keywords.
        if any(w in lower for w in ("critical", "blocker", "deal-stopper", "urgent")):
            priority = Severity.P0.value
        elif any(w in lower for w in ("important", "significant", "material")):
            priority = Severity.P1.value
        else:
            priority = Severity.P2.value  # default for gaps

        # Extract a concise missing_item from the text (truncate at first
        # sentence boundary or 200 chars).
        missing_item = text
        for sep in (". ", "; ", " — ", " - "):
            idx = text.find(sep)
            if 0 < idx < 200:
                missing_item = text[:idx]
                break
        missing_item = missing_item[:200]

        return {
            "missing_item": missing_item,
            "gap_type": gap_type,
            "priority": priority,
            "why_needed": text if text != missing_item else "Required for due diligence analysis",
            "risk_if_missing": "Incomplete analysis — potential blind spot",
            "detection_method": "checklist",
        }

    @staticmethod
    def _normalize_gap(raw: dict[str, Any], subject_name: str, agent: str) -> dict[str, Any]:
        """Normalise an agent-produced gap to match the Gap Pydantic model.

        Agents commonly produce gaps with simplified fields like::

            {"gap_type": "missing document", "description": "...", "file_path": "..."}

        but the Gap model requires 9 fields including ``why_needed``,
        ``risk_if_missing``, ``request_to_company``, ``evidence``, and
        ``detection_method``.
        """
        g = dict(raw)
        g.setdefault("subject", subject_name)
        g.setdefault("agent", agent)

        # Map priority from severity if missing, coercing plain-English levels
        if "priority" not in g and "severity" in g:
            g["priority"] = g.pop("severity")
        g.setdefault("priority", Severity.P2.value)
        _priority_map: dict[str, str] = {
            "critical": Severity.P0.value,
            "deal-stopper": Severity.P0.value,
            "high": Severity.P1.value,
            "major": Severity.P1.value,
            "medium": Severity.P2.value,
            "moderate": Severity.P2.value,
            "important": Severity.P2.value,
            "low": Severity.P3.value,
            "minor": Severity.P3.value,
            "informational": Severity.P3.value,
            "info": Severity.P3.value,
        }
        raw_prio = g["priority"]
        if isinstance(raw_prio, str) and raw_prio.lower() in _priority_map:
            g["priority"] = _priority_map[raw_prio.lower()]

        # Normalise gap_type to one of the 6 valid GapType enum values.
        g["gap_type"] = FindingMerger._coerce_gap_type(g.get("gap_type"), agent)

        # Map missing_item from alternative names
        if "missing_item" not in g:
            g["missing_item"] = g.pop("document", g.pop("item", g.pop("title", "Unknown document")))

        # Map description → why_needed if why_needed is missing
        if "why_needed" not in g:
            g["why_needed"] = g.pop("description", g.pop("reason", "Required for due diligence analysis"))
        # Map risk → risk_if_missing
        if "risk_if_missing" not in g:
            g["risk_if_missing"] = g.pop("risk", g.pop("impact", "Incomplete analysis — potential blind spot"))
        # Default request_to_company
        if "request_to_company" not in g:
            missing = g.get("missing_item", "this document")
            g["request_to_company"] = f"Please provide {missing}"
        # Map file_path/source → evidence
        if "evidence" not in g:
            evidence_parts: list[str] = []
            if "file_path" in g:
                evidence_parts.append(f"Referenced in: {g.pop('file_path')}")
            if "section_ref" in g:
                evidence_parts.append(f"Section: {g.pop('section_ref')}")
            if "context" in g:
                evidence_parts.append(g.pop("context"))
            g["evidence"] = "; ".join(evidence_parts) if evidence_parts else "Identified during analysis"
        # Default detection_method
        if "detection_method" not in g:
            g["detection_method"] = "checklist"
        # Map source_file from file_path if present
        if "source_file" not in g and "file_path" in g:
            g["source_file"] = g.pop("file_path")
        return g

    @staticmethod
    def _collect_gaps(
        agent_outputs: dict[str, dict[str, Any]],
        subject_name: str,
    ) -> list[Gap]:
        """Collect and deduplicate gaps from all specialist agents.

        Each agent may produce a ``gaps`` list in its output.  This method
        unions them, deduplicating by ``(missing_item, gap_type)`` and keeping
        the highest-priority entry when duplicates exist.
        """
        seen: dict[tuple[str, str], dict[str, Any]] = {}

        for agent, data in agent_outputs.items():
            for gap_raw in data.get("gaps", []):
                if isinstance(gap_raw, str):
                    # Agent produced a bare string instead of a gap object —
                    # recover as much structure as we can from the text.
                    gap_raw = FindingMerger._coerce_gap_string(gap_raw, agent)
                if not isinstance(gap_raw, dict):
                    logger.warning("Skipping non-dict gap entry from %s: %s", agent, type(gap_raw).__name__)
                    continue
                gap_dict = FindingMerger._normalize_gap(gap_raw, subject_name, agent)
                dedup_key = (gap_dict.get("missing_item", ""), gap_dict.get("gap_type", ""))
                existing = seen.get(dedup_key)
                if existing is None:
                    seen[dedup_key] = gap_dict
                else:
                    # Keep higher priority
                    existing_prio = SEVERITY_ORDER.get(existing.get("priority", SEVERITY_P3), 9)
                    new_prio = SEVERITY_ORDER.get(gap_dict.get("priority", SEVERITY_P3), 9)
                    if new_prio < existing_prio:
                        seen[dedup_key] = gap_dict

        gaps: list[Gap] = []
        for gap_dict in seen.values():
            try:
                gaps.append(Gap.model_validate(gap_dict))
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Skipping invalid gap during merge: %s (reason: %s)",
                    gap_dict.get("missing_item", ""),
                    str(exc)[:200],
                )
        return gaps

    # ------------------------------------------------------------------
    # Chat-to-pipeline corrections overlay
    # ------------------------------------------------------------------

    @staticmethod
    def apply_corrections(
        merged: dict[str, MergedSubjectOutput],
        project_dir: Path,
    ) -> int:
        """Apply chat-originated finding corrections to merged output.

        Loads corrections from the chat directory and applies them
        non-destructively to the merged findings.  Original severity is
        preserved in ``metadata["_original_severity"]`` for audit trail.

        Returns the number of corrections applied.
        """
        chat_dir = project_dir / "_dd" / "forensic-dd" / "chat"
        corrections_path = chat_dir / "corrections.jsonl"
        if not corrections_path.exists():
            return 0

        from dd_agents.chat.corrections import CorrectionStore

        store = CorrectionStore(chat_dir)
        corrections = store.corrections_by_finding_id()
        if not corrections:
            return 0

        applied = 0
        for _subject, mco in merged.items():
            for finding in mco.findings:
                fid = finding.id
                corr = corrections.get(fid)

                # Fallback: fuzzy title match for cross-run stability
                if corr is None:
                    all_corrections = store.load_corrections()
                    for c in all_corrections:
                        from rapidfuzz import fuzz

                        score = fuzz.token_sort_ratio(finding.title.lower(), c.finding_title.lower())
                        if score >= 80:
                            corr = c
                            break

                if corr is None:
                    continue

                meta = finding.metadata or {}
                if corr.action == "dismiss":
                    meta["_dismissed"] = True
                    meta["_original_severity"] = finding.severity.value
                    meta["_correction_id"] = corr.id
                    meta["_correction_reason"] = corr.reason
                    finding.metadata = meta
                    applied += 1
                elif corr.action in ("downgrade", "upgrade") and corr.new_severity:
                    meta["_original_severity"] = finding.severity.value
                    meta["_correction_id"] = corr.id
                    meta["_correction_reason"] = corr.reason
                    finding.severity = Severity(corr.new_severity)
                    finding.metadata = meta
                    applied += 1
                elif corr.action == "adjust":
                    meta["_correction_id"] = corr.id
                    meta["_correction_reason"] = corr.reason
                    finding.metadata = meta
                    applied += 1

        if applied:
            logger.info("Applied %d chat corrections to merged findings", applied)
        return applied

    # ------------------------------------------------------------------
    # Pre-generation citation validation (Issue #48)
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_finding_citations(findings: list[Finding]) -> None:
        """Warn when findings have empty or synthetic citations.

        This is a pre-generation quality gate.  It does not reject findings
        outright but it logs warnings for synthetic or missing citations
        so they surface in audit logs.
        """
        for finding in findings:
            for cit in finding.citations:
                if not cit.source_path or cit.source_path.startswith("[synthetic:"):
                    logger.warning(
                        "%s finding %s has synthetic/empty citation — flagged for QA audit",
                        finding.severity.value,
                        finding.id,
                    )
                if finding.severity in (Severity.P0, Severity.P1, Severity.P2) and not cit.exact_quote:
                    logger.warning(
                        "%s finding %s is missing exact_quote in citation — flagged for QA audit",
                        finding.severity.value,
                        finding.id,
                    )
