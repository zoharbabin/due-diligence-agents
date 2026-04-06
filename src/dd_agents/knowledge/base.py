"""Deal Knowledge Base — persistent CRUD operations on the knowledge store (Issue #178).

Manages the ``_dd/forensic-dd/knowledge/`` directory with atomic writes,
auto-index rebuilds, and structured article storage. All writes use
temp + ``os.replace()`` for crash safety (same pattern as entity resolution
cache in ``persistence/concurrency.py``).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from dd_agents.knowledge._utils import now_iso
from dd_agents.knowledge.articles import ArticleType, KnowledgeArticle
from dd_agents.knowledge.index import KnowledgeIndex

logger = logging.getLogger(__name__)

# Subdirectories within the knowledge base, keyed by ArticleType.
_TYPE_DIRS: dict[ArticleType, str] = {
    ArticleType.ENTITY_PROFILE: "entities",
    ArticleType.CLAUSE_SUMMARY: "clauses",
    ArticleType.CONTRADICTION: "contradictions",
    ArticleType.INSIGHT: "insights",
    ArticleType.ANNOTATION: "annotations",
}


def _atomic_write_json(path: Path, data: dict[str, Any] | list[Any]) -> None:
    """Write JSON atomically: temp file then ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        os.replace(str(tmp), str(path))
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


class DealKnowledgeBase:
    """Manages the persistent knowledge layer for a deal.

    All writes use atomic file operations for crash safety. The index
    is rebuilt after every write to maintain consistency.

    Use :meth:`batch_writes` as a context manager to defer index rebuilds
    until the batch completes — avoids N+1 rebuilds during compilation.

    Parameters
    ----------
    project_dir:
        Root of the data room (contains ``_dd/``).
    """

    def __init__(self, project_dir: Path) -> None:
        self._project_dir = Path(project_dir)
        self._knowledge_dir = self._project_dir / "_dd" / "forensic-dd" / "knowledge"
        self._batch_depth: int = 0

    @property
    def knowledge_dir(self) -> Path:
        """Absolute path to the knowledge base directory."""
        return self._knowledge_dir

    @property
    def exists(self) -> bool:
        """Whether the knowledge base directory exists."""
        return self._knowledge_dir.is_dir()

    def ensure_dirs(self) -> None:
        """Create all knowledge base subdirectories if needed."""
        self._knowledge_dir.mkdir(parents=True, exist_ok=True)
        for subdir in _TYPE_DIRS.values():
            (self._knowledge_dir / subdir).mkdir(exist_ok=True)

    def batch_writes(self) -> _BatchContext:
        """Context manager to defer index rebuilds until the batch completes.

        Usage::

            with kb.batch_writes():
                kb.write_article(a1)
                kb.write_article(a2)
            # index is rebuilt once here

        Supports nesting — only the outermost ``batch_writes`` triggers
        the rebuild.
        """
        return _BatchContext(self)

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------

    def get_article(self, article_id: str) -> KnowledgeArticle | None:
        """Load a single article by ID. Returns None if not found."""
        for type_dir in _TYPE_DIRS.values():
            path = self._knowledge_dir / type_dir / f"{article_id}.json"
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    return KnowledgeArticle.model_validate(data)
                except (json.JSONDecodeError, ValueError) as exc:
                    logger.warning("Failed to load article %s: %s", article_id, exc)
                    return None
        return None

    def write_article(self, article: KnowledgeArticle) -> KnowledgeArticle:
        """Write an article to disk. Creates parent dirs if needed.

        Returns the article (for chaining).
        """
        self.ensure_dirs()
        subdir = _TYPE_DIRS.get(article.article_type, "insights")
        path = self._knowledge_dir / subdir / f"{article.id}.json"

        if not article.created_at:
            article.created_at = now_iso()
        if not article.updated_at:
            article.updated_at = article.created_at

        _atomic_write_json(path, article.model_dump(mode="json"))
        self._rebuild_index()
        return article

    def update_article(
        self,
        article_id: str,
        updates: dict[str, Any],
    ) -> KnowledgeArticle | None:
        """Update an existing article. Returns None if not found.

        Parameters
        ----------
        article_id:
            ID of the article to update.
        updates:
            Dict of field names to new values. ``version`` is auto-incremented.
        """
        existing = self.get_article(article_id)
        if existing is None:
            return None

        # Guard: prevent callers from changing the article ID via updates
        updates.pop("id", None)

        data = existing.model_dump(mode="json")
        data.update(updates)
        data["version"] = existing.version + 1
        data["updated_at"] = now_iso()

        updated = KnowledgeArticle.model_validate(data)
        subdir = _TYPE_DIRS.get(updated.article_type, "insights")
        path = self._knowledge_dir / subdir / f"{updated.id}.json"
        _atomic_write_json(path, updated.model_dump(mode="json"))
        self._rebuild_index()
        return updated

    def delete_article(self, article_id: str) -> bool:
        """Delete an article from disk. Returns True if found and deleted."""
        for type_dir in _TYPE_DIRS.values():
            path = self._knowledge_dir / type_dir / f"{article_id}.json"
            if path.exists():
                path.unlink()
                self._rebuild_index()
                return True
        return False

    def list_articles(
        self,
        article_type: ArticleType | None = None,
    ) -> list[KnowledgeArticle]:
        """List all articles, optionally filtered by type."""
        articles: list[KnowledgeArticle] = []
        dirs = [_TYPE_DIRS[article_type]] if article_type and article_type in _TYPE_DIRS else list(_TYPE_DIRS.values())
        for type_dir in dirs:
            dir_path = self._knowledge_dir / type_dir
            if not dir_path.is_dir():
                continue
            for path in sorted(dir_path.glob("*.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    articles.append(KnowledgeArticle.model_validate(data))
                except (json.JSONDecodeError, ValueError) as exc:
                    logger.warning("Skipping corrupt article %s: %s", path.name, exc)
        return articles

    def search_articles(
        self,
        query: str,
        limit: int = 10,
        article_type: ArticleType | None = None,
    ) -> list[KnowledgeArticle]:
        """Search articles by keyword match on title and tags.

        Simple substring matching — sufficient at moderate scale (<500 articles).
        For larger knowledge bases, integrate with the vector store.

        Parameters
        ----------
        query:
            Search string (case-insensitive substring match).
        limit:
            Maximum results to return.
        article_type:
            Optional filter by article type.
        """
        query_lower = query.lower()
        results: list[KnowledgeArticle] = []

        for article in self.list_articles(article_type):
            if article.superseded_by:
                continue  # Skip superseded articles
            title_match = query_lower in article.title.lower()
            tag_match = any(query_lower in tag.lower() for tag in article.tags)
            if title_match or tag_match:
                results.append(article)
                if len(results) >= limit:
                    break

        return results

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

    def get_index(self) -> KnowledgeIndex:
        """Load the current index from disk, or build fresh."""
        index_path = self._knowledge_dir / "index.json"
        if index_path.exists():
            try:
                data = json.loads(index_path.read_text(encoding="utf-8"))
                return KnowledgeIndex.model_validate(data)
            except (json.JSONDecodeError, ValueError):
                pass
        return self._rebuild_index()

    def _rebuild_index(self) -> KnowledgeIndex:
        """Rebuild the index from all articles on disk.

        Skipped when inside a :meth:`batch_writes` context — the outermost
        context triggers the rebuild on exit.
        """
        if self._batch_depth > 0:
            return self.get_index() if (self._knowledge_dir / "index.json").exists() else KnowledgeIndex()
        articles = self.list_articles()
        index = KnowledgeIndex.build(articles, now_iso())
        index_path = self._knowledge_dir / "index.json"
        _atomic_write_json(index_path, index.model_dump(mode="json"))
        return index

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> list[str]:
        """Run basic integrity checks. Returns list of issue descriptions."""
        issues: list[str] = []

        if not self._knowledge_dir.is_dir():
            issues.append("Knowledge directory does not exist")
            return issues

        # Check for corrupt articles
        for type_dir in _TYPE_DIRS.values():
            dir_path = self._knowledge_dir / type_dir
            if not dir_path.is_dir():
                continue
            for path in dir_path.glob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    KnowledgeArticle.model_validate(data)
                except Exception as exc:
                    issues.append(f"Corrupt article {path.name}: {exc}")

        # Check index consistency
        index_path = self._knowledge_dir / "index.json"
        if index_path.exists():
            try:
                data = json.loads(index_path.read_text(encoding="utf-8"))
                index = KnowledgeIndex.model_validate(data)
                actual_count = len(self.list_articles())
                if index.total_articles != actual_count:
                    issues.append(f"Index count mismatch: index says {index.total_articles}, actual is {actual_count}")
            except Exception as exc:
                issues.append(f"Corrupt index: {exc}")
        else:
            issues.append("Index file missing")

        # Check for broken links
        all_ids = {a.id for a in self.list_articles()}
        for article in self.list_articles():
            for link_id in article.links:
                if link_id not in all_ids:
                    issues.append(f"Article {article.id} has broken link to {link_id}")

        return issues


class _BatchContext:
    """Context manager that defers index rebuilds until exit.

    Supports nesting — only the outermost context triggers the rebuild.
    """

    def __init__(self, kb: DealKnowledgeBase) -> None:
        self._kb = kb

    def __enter__(self) -> _BatchContext:
        self._kb._batch_depth += 1
        return self

    def __exit__(self, *_args: object) -> None:
        self._kb._batch_depth -= 1
        if self._kb._batch_depth == 0:
            self._kb._rebuild_index()
