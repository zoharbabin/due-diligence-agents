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
                if not isinstance(finding, dict):
                    logger.warning("Skipping non-dict finding from %s: %s", agent, type(finding).__name__)
                    continue
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
                    try:
                        loaded = json.loads(fp.read_text())
                    except (json.JSONDecodeError, OSError) as exc:
                        logger.warning("Skipping corrupt findings file %s: %s", fp, exc)
                        continue
                    if isinstance(loaded, dict):
                        agent_outputs[agent] = loaded
                    else:
                        logger.warning("Findings file %s is not a JSON object (got %s)", fp, type(loaded).__name__)
            if agent_outputs:
                try:
                    results[csn] = self.merge_customer(
                        agent_outputs,
                        customer_safe_name=csn,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("Failed to merge customer %s — skipping", csn)
        return results

    def write_merged(
        self,
        merged: dict[str, MergedCustomerOutput],
        output_dir: Path,
        *,
        clean_stale: bool = True,
    ) -> None:
        """Write per-customer merged JSON files to *output_dir*.

        When *clean_stale* is ``True`` (default), any ``.json`` file in
        *output_dir* that does not correspond to a customer in *merged*
        is removed.  This prevents stale artefacts (e.g.
        ``numerical_manifest.json``, ``coverage_manifest.json``) from
        accumulating across runs.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        # Remove stale files before writing.
        if clean_stale:
            expected_stems = set(merged.keys())
            for existing in output_dir.glob("*.json"):
                if existing.stem not in expected_stems:
                    logger.info("Removing stale merged file: %s", existing.name)
                    try:
                        existing.unlink()
                    except OSError as exc:
                        logger.warning("Failed to remove stale file %s: %s", existing, exc)

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
    def _first_quote(f: dict[str, Any]) -> str:
        """Extract first exact_quote from a finding dict, tolerating bad shapes."""
        cits = f.get("citations")
        if not isinstance(cits, list) or not cits:
            return ""
        first = cits[0]
        if isinstance(first, dict):
            return first.get("exact_quote") or ""
        return ""

    @staticmethod
    def _pick_winner(group: list[dict[str, Any]]) -> dict[str, Any]:
        """Keep highest severity, longest exact_quote.  Record contributors."""
        sorted_group = sorted(
            group,
            key=lambda f: (
                SEVERITY_ORDER.get(f.get("severity", "P3"), 9),
                -len(FindingMerger._first_quote(f)),
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
    def _union_cross_refs(
        agent_outputs: dict[str, dict[str, Any]],
    ) -> list[CrossReference]:
        refs: list[CrossReference] = []
        for _agent, data in agent_outputs.items():
            for cr_dict in data.get("cross_references", []):
                normalised = FindingMerger._normalize_cross_reference(cr_dict)
                try:
                    refs.append(CrossReference.model_validate(normalised))
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
        """(files with governed_by resolved) / total_customer_files."""
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

    @staticmethod
    def _normalize_citation(raw: dict[str, Any]) -> dict[str, Any]:
        """Normalise an agent-produced citation dict to match the Citation schema.

        Agents may produce citations with different field names depending on
        whether they follow the prompt schema (``file_path``, ``page``,
        ``section_ref``) or the Pydantic schema (``source_type``, ``source_path``,
        ``location``).  This method maps the former to the latter so that
        ``Citation.model_validate()`` succeeds.
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
    # instead of P0/P1/P2/P3.  Map common synonyms to standard values.
    _SEVERITY_MAP: dict[str, str] = {
        "critical": "P0",
        "blocker": "P0",
        "deal-stopper": "P0",
        "high": "P1",
        "medium": "P2",
        "moderate": "P2",
        "low": "P3",
        "minor": "P3",
        "info": "P3",
        "informational": "P3",
        "p0": "P0",
        "p1": "P1",
        "p2": "P2",
        "p3": "P3",
    }

    @staticmethod
    def _normalize_severity(raw: str) -> str:
        """Map agent severity strings to ``Severity`` enum values."""
        return FindingMerger._SEVERITY_MAP.get(raw.strip().lower(), "P3")

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
        customer_name: str,
        customer_safe_name: str,
    ) -> list[Finding]:
        """Transform raw dicts into full ``Finding`` models with auto-IDs."""
        results: list[Finding] = []
        dropped: list[dict[str, Any]] = []
        counters: dict[str, int] = {}
        for f in raw_findings:
            agent = self._normalize_agent_name(f.get("agent", "legal"))
            seq = counters.get(agent, 0) + 1
            counters[agent] = seq
            finding_id = f"forensic-dd_{agent}_{customer_safe_name}_{seq:04d}"

            # Normalise severity BEFORE Pydantic validation.
            raw_severity = f.get("severity", "P3")
            severity = self._normalize_severity(str(raw_severity))

            # Truncate title to 120 chars to prevent max_length validation failure.
            title = (f.get("title") or "Untitled finding")[:120]

            # Build Citation objects — handle both nested citations array and
            # flat finding-level fields (file_path, page, section_ref, exact_quote).
            citations_raw = f.get("citations", [])

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

            # P0/P1 findings require exact_quote on all citations.  If any
            # citation lacks it (including synthetic ones), downgrade to P2
            # rather than losing the finding entirely.
            if severity in ("P0", "P1"):
                missing_quote = any(not cit.exact_quote for cit in citations)
                if missing_quote or has_synthetic:
                    original_severity = severity
                    severity = "P2"
                    logger.warning(
                        "Downgraded finding '%s' from %s to P2: citations lack exact_quote",
                        title,
                        original_severity,
                    )

            # Normalise confidence to enum values.
            raw_conf = str(f.get("confidence", "medium")).strip().lower()
            confidence = raw_conf if raw_conf in ("high", "medium", "low") else "medium"

            try:
                from dd_agents.models.enums import AgentName as _AgentName
                from dd_agents.models.enums import Confidence as _Confidence
                from dd_agents.models.enums import Severity as _Severity

                finding = Finding(
                    id=finding_id,
                    severity=_Severity(severity),
                    category=f.get("category", "uncategorized"),
                    title=title,
                    description=f.get("description", ""),
                    citations=citations,
                    confidence=_Confidence(confidence),
                    agent=_AgentName(agent),
                    skill="forensic-dd",
                    run_id=self.run_id,
                    timestamp=self.timestamp,
                    analysis_unit=customer_name,
                    metadata=f.get("metadata", {}),
                )
                results.append(finding)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Finding DROPPED: title=%r agent=%s customer=%s severity=%r->%s error=%s",
                    f.get("title"),
                    agent,
                    customer_name,
                    raw_severity,
                    severity,
                    exc,
                )
                dropped.append({"title": f.get("title"), "agent": agent, "error": str(exc)})

        if dropped:
            logger.warning(
                "Customer %s: %d/%d findings dropped during promotion",
                customer_name,
                len(dropped),
                len(raw_findings),
            )

        return results

    # ------------------------------------------------------------------
    # Step 6 -- Gap collection
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_gap(raw: dict[str, Any], customer_name: str, agent: str) -> dict[str, Any]:
        """Normalise an agent-produced gap to match the Gap Pydantic model.

        Agents commonly produce gaps with simplified fields like::

            {"gap_type": "missing document", "description": "...", "file_path": "..."}

        but the Gap model requires 9 fields including ``why_needed``,
        ``risk_if_missing``, ``request_to_company``, ``evidence``, and
        ``detection_method``.
        """
        g = dict(raw)
        g.setdefault("customer", customer_name)
        g.setdefault("agent", agent)

        # Map priority from severity if missing
        if "priority" not in g and "severity" in g:
            g["priority"] = g.pop("severity")
        g.setdefault("priority", "P2")

        # Normalise gap_type to enum values
        gap_type = g.get("gap_type", "Missing_Doc")
        _gap_type_map: dict[str, str] = {
            "missing document": "Missing_Doc",
            "missing_document": "Missing_Doc",
            "missing doc": "Missing_Doc",
            "missing_doc": "Missing_Doc",
            "missing data": "Missing_Data",
            "missing_data": "Missing_Data",
            "ambiguous link": "Ambiguous_Link",
            "ambiguous_link": "Ambiguous_Link",
            "unreadable": "Unreadable",
            "contradiction": "Contradiction",
            "data mismatch": "Data_Mismatch",
            "data_mismatch": "Data_Mismatch",
        }
        g["gap_type"] = _gap_type_map.get(gap_type.lower(), gap_type) if isinstance(gap_type, str) else gap_type

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
                if isinstance(gap_raw, str):
                    # Agent produced a bare string instead of a gap object —
                    # wrap it so downstream validation can accept or reject it.
                    logger.warning("Gap entry from %s is a bare string: %r", agent, gap_raw[:120])
                    gap_raw = {"missing_item": gap_raw, "gap_type": "Missing_Doc"}
                if not isinstance(gap_raw, dict):
                    logger.warning("Skipping non-dict gap entry from %s: %s", agent, type(gap_raw).__name__)
                    continue
                gap_dict = FindingMerger._normalize_gap(gap_raw, customer_name, agent)
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
