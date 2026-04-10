"""Compile pipeline findings into knowledge articles (Issue #178).

After each pipeline run, the compiler reads merged findings and
creates/updates entity profiles, clause summaries, and contradiction
articles in the Deal Knowledge Base.

This runs as a non-blocking step after finalization — compilation
failures are logged as warnings, never pipeline errors.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from dd_agents.knowledge.base import DealKnowledgeBase

from pydantic import BaseModel, Field

from dd_agents.knowledge._utils import now_iso
from dd_agents.knowledge.articles import ArticleType, KnowledgeArticle, KnowledgeSource
from dd_agents.utils.constants import FINDINGS_DIR

logger = logging.getLogger(__name__)


class CompilationResult(BaseModel):
    """Summary of a knowledge compilation pass."""

    articles_created: int = Field(default=0, description="New articles created")
    articles_updated: int = Field(default=0, description="Existing articles updated")
    contradictions_found: int = Field(default=0, description="New contradictions detected")
    entities_enriched: list[str] = Field(default_factory=list, description="Entity safe_names enriched")


def _finding_to_source(finding: dict[str, Any], run_id: str) -> KnowledgeSource:
    """Extract the primary KnowledgeSource from a finding dict."""
    citations = finding.get("citations", [])
    if citations:
        c = citations[0]
        return KnowledgeSource(
            source_path=c.get("source_path", ""),
            page=str(c.get("page_number", c.get("location", ""))),
            section_ref=c.get("location", ""),
            exact_quote=c.get("exact_quote", "") or "",
            run_id=run_id,
            timestamp=finding.get("timestamp", ""),
        )
    return KnowledgeSource(source_path="", run_id=run_id, timestamp=finding.get("timestamp", ""))


def _entity_article_id(entity_safe_name: str) -> str:
    """Deterministic article ID for an entity profile."""
    return f"entity_{entity_safe_name}"


def _clause_article_id(clause_type: str) -> str:
    """Deterministic article ID for a clause summary."""
    return f"clause_{clause_type}"


def _contradiction_id(entity: str, detail: str) -> str:
    """Deterministic article ID for a contradiction."""
    h = hashlib.sha256(f"{entity}|{detail}".encode()).hexdigest()[:12]
    return f"contradiction_{h}"


class KnowledgeCompiler:
    """Compile pipeline findings into Deal Knowledge Base articles.

    Parameters
    ----------
    knowledge_base:
        The DealKnowledgeBase instance to write to.
    """

    def __init__(self, knowledge_base: DealKnowledgeBase) -> None:
        self._kb = knowledge_base

    def compile_from_run(self, run_dir: Path, run_id: str) -> CompilationResult:
        """Compile merged findings from a completed pipeline run.

        Parameters
        ----------
        run_dir:
            Absolute path to the run directory (e.g. ``runs/20260307_143000``).
        run_id:
            The run identifier string.

        Returns
        -------
        CompilationResult
            Summary of what was compiled.
        """
        self._kb.ensure_dirs()
        result = CompilationResult()
        now = now_iso()
        created_by = f"pipeline:{run_id}"

        # Load all merged findings
        merged_dir = run_dir / FINDINGS_DIR / "merged"
        if not merged_dir.is_dir():
            logger.warning("No merged findings directory at %s", merged_dir)
            return result

        # Group findings by entity
        entity_findings: dict[str, list[dict[str, Any]]] = {}
        for path in sorted(merged_dir.glob("*.json")):
            if path.name.startswith("_"):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                findings_list = data.get("findings", []) if isinstance(data, dict) else []
                subj = data.get("subject_safe_name", path.stem) if isinstance(data, dict) else path.stem
                if findings_list:
                    entity_findings[subj] = findings_list
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning("Skipping corrupt merged file %s: %s", path.name, exc)

        # Batch all writes to rebuild the index only once at the end.
        with self._kb.batch_writes():
            # Compile entity profiles
            for entity_safe_name, findings in entity_findings.items():
                created = self._compile_entity_profile(
                    entity_safe_name,
                    findings,
                    run_id,
                    now,
                    created_by,
                )
                if created:
                    result.articles_created += 1
                else:
                    result.articles_updated += 1
                result.entities_enriched.append(entity_safe_name)

            # Compile clause summaries across all entities
            all_findings = [f for fl in entity_findings.values() for f in fl]
            clause_stats = self._compile_clause_summaries(
                all_findings,
                entity_findings,
                run_id,
                now,
                created_by,
            )
            result.articles_created += clause_stats["created"]
            result.articles_updated += clause_stats["updated"]

            # Detect contradictions
            contras = self._detect_contradictions(entity_findings, run_id, now, created_by)
            result.contradictions_found = contras

        logger.info(
            "Knowledge compilation: %d created, %d updated, %d contradictions, %d entities",
            result.articles_created,
            result.articles_updated,
            result.contradictions_found,
            len(result.entities_enriched),
        )
        return result

    def _compile_entity_profile(
        self,
        entity_safe_name: str,
        findings: list[dict[str, Any]],
        run_id: str,
        now: str,
        created_by: str,
    ) -> bool:
        """Create or update an entity profile article. Returns True if created (new)."""
        article_id = _entity_article_id(entity_safe_name)
        existing = self._kb.get_article(article_id)

        # Compute severity distribution
        severity_dist: dict[str, int] = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        categories: dict[str, str] = {}
        sources: list[KnowledgeSource] = []

        for f in findings:
            sev = f.get("severity", "P3")
            if sev in severity_dist:
                severity_dist[sev] += 1
            cat = f.get("category", "unknown")
            title = f.get("title", "")
            categories[cat] = f"{sev} — {title}"
            sources.append(_finding_to_source(f, run_id))

        # Build run history
        run_entry = {
            "run_id": run_id,
            "findings_count": len(findings),
            "top_severity": next(
                (s for s in ["P0", "P1", "P2", "P3"] if severity_dist.get(s, 0) > 0),
                "P3",
            ),
        }

        content: dict[str, Any] = {
            "entity_safe_name": entity_safe_name,
            "document_count": len({s.source_path for s in sources if s.source_path}),
            "total_findings": len(findings),
            "severity_distribution": severity_dist,
            "key_clauses": categories,
        }

        if existing:
            # Merge with existing profile
            old_content = existing.content
            old_history = old_content.get("cross_run_history", [])
            old_history.append(run_entry)
            content["cross_run_history"] = old_history
            # Merge sources (deduplicate by source_path)
            existing_paths = {s.source_path for s in existing.sources}
            new_sources = existing.sources + [s for s in sources if s.source_path not in existing_paths]
            self._kb.update_article(
                article_id,
                {
                    "content": content,
                    "sources": [s.model_dump(mode="json") for s in new_sources],
                    "tags": [entity_safe_name, f"findings:{len(findings)}"],
                    "updated_by": created_by,
                },
            )
            return False
        else:
            content["cross_run_history"] = [run_entry]
            article = KnowledgeArticle(
                id=article_id,
                article_type=ArticleType.ENTITY_PROFILE,
                title=f"Entity Profile: {entity_safe_name}",
                content=content,
                sources=sources[:50],  # Cap sources to prevent bloat
                tags=[entity_safe_name, f"findings:{len(findings)}"],
                created_at=now,
                updated_at=now,
                created_by=created_by,
                updated_by=created_by,
            )
            self._kb.write_article(article)
            return True

    def _compile_clause_summaries(
        self,
        all_findings: list[dict[str, Any]],
        entity_findings: dict[str, list[dict[str, Any]]],
        run_id: str,
        now: str,
        created_by: str,
    ) -> dict[str, int]:
        """Compile cross-entity clause-type summaries. Returns counts."""
        stats = {"created": 0, "updated": 0}

        # Group findings by category
        by_category: dict[str, list[dict[str, Any]]] = {}
        for f in all_findings:
            cat = f.get("category", "unknown")
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(f)

        for category, findings in by_category.items():
            article_id = _clause_article_id(category)
            existing = self._kb.get_article(article_id)

            severity_dist: dict[str, int] = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
            entities_affected: set[str] = set()
            for f in findings:
                sev = f.get("severity", "P3")
                if sev in severity_dist:
                    severity_dist[sev] += 1
                entities_affected.add(f.get("analysis_unit", "unknown"))

            content: dict[str, Any] = {
                "clause_type": category,
                "entities_affected": len(entities_affected),
                "severity_distribution": severity_dist,
                "entity_list": sorted(entities_affected),
            }

            if existing:
                self._kb.update_article(
                    article_id,
                    {
                        "content": content,
                        "updated_by": created_by,
                        "tags": [category, f"entities:{len(entities_affected)}"],
                    },
                )
                stats["updated"] += 1
            else:
                article = KnowledgeArticle(
                    id=article_id,
                    article_type=ArticleType.CLAUSE_SUMMARY,
                    title=f"Clause Summary: {category}",
                    content=content,
                    tags=[category, f"entities:{len(entities_affected)}"],
                    created_at=now,
                    updated_at=now,
                    created_by=created_by,
                    updated_by=created_by,
                )
                self._kb.write_article(article)
                stats["created"] += 1

        return stats

    def _detect_contradictions(
        self,
        entity_findings: dict[str, list[dict[str, Any]]],
        run_id: str,
        now: str,
        created_by: str,
    ) -> int:
        """Detect contradictions between findings for the same entity. Returns count."""
        count = 0

        for entity, findings in entity_findings.items():
            # Group by category — contradictions are within same category
            by_cat: dict[str, list[dict[str, Any]]] = {}
            for f in findings:
                cat = f.get("category", "unknown")
                if cat not in by_cat:
                    by_cat[cat] = []
                by_cat[cat].append(f)

            for cat, cat_findings in by_cat.items():
                if len(cat_findings) < 2:
                    continue

                # Check for severity disagreements across agents
                severities = {f.get("agent", ""): f.get("severity", "") for f in cat_findings}
                unique_sevs = set(severities.values())
                if len(unique_sevs) > 1:
                    detail = f"{entity}|{cat}|severity_disagreement"
                    article_id = _contradiction_id(entity, detail)

                    if self._kb.get_article(article_id) is None:
                        article = KnowledgeArticle(
                            id=article_id,
                            article_type=ArticleType.CONTRADICTION,
                            title=f"Severity disagreement: {entity} / {cat}",
                            content={
                                "entity": entity,
                                "category": cat,
                                "type": "severity_disagreement",
                                "agent_severities": severities,
                                "description": (f"Agents disagree on severity for {cat} clause: {severities}"),
                            },
                            sources=[_finding_to_source(f, run_id) for f in cat_findings[:5]],
                            tags=[entity, cat, "contradiction"],
                            links=[_entity_article_id(entity)],
                            created_at=now,
                            updated_at=now,
                            created_by=created_by,
                            updated_by=created_by,
                        )
                        self._kb.write_article(article)
                        count += 1

        return count
