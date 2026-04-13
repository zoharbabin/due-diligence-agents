"""Unit tests for the Deal Knowledge Base (Issue #178)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from dd_agents.knowledge.articles import ArticleType, KnowledgeArticle, KnowledgeSource
from dd_agents.knowledge.base import DealKnowledgeBase
from dd_agents.knowledge.compiler import CompilationResult, KnowledgeCompiler
from dd_agents.knowledge.index import KnowledgeIndex

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def kb_dir(tmp_path: Path) -> Path:
    """Return a temporary project dir for knowledge base tests."""
    return tmp_path


@pytest.fixture()
def kb(kb_dir: Path) -> DealKnowledgeBase:
    """Return an initialized DealKnowledgeBase."""
    dkb = DealKnowledgeBase(kb_dir)
    dkb.ensure_dirs()
    return dkb


def _make_article(
    article_id: str = "test_001",
    article_type: ArticleType = ArticleType.ENTITY_PROFILE,
    title: str = "Test Article",
    tags: list[str] | None = None,
    links: list[str] | None = None,
    superseded_by: str | None = None,
) -> KnowledgeArticle:
    """Helper to create a test article."""
    return KnowledgeArticle(
        id=article_id,
        article_type=article_type,
        title=title,
        content={"key": "value"},
        sources=[
            KnowledgeSource(
                source_path="contracts/msa.pdf",
                page="5",
                section_ref="Section 4.3",
                exact_quote="The parties agree...",
                run_id="run_001",
            ),
        ],
        tags=tags if tags is not None else ["test", "entity_a"],
        links=links or [],
        created_at="2026-03-07T14:30:00+00:00",
        updated_at="2026-03-07T14:30:00+00:00",
        created_by="pipeline:run_001",
        updated_by="pipeline:run_001",
        superseded_by=superseded_by,
    )


# ---------------------------------------------------------------------------
# Article model tests
# ---------------------------------------------------------------------------


class TestKnowledgeArticle:
    def test_article_creation(self) -> None:
        article = _make_article()
        assert article.id == "test_001"
        assert article.article_type == ArticleType.ENTITY_PROFILE
        assert article.version == 1
        assert len(article.sources) == 1
        assert article.sources[0].source_path == "contracts/msa.pdf"

    def test_article_types(self) -> None:
        for at in ArticleType:
            article = _make_article(article_type=at)
            assert article.article_type == at

    def test_knowledge_source_provenance(self) -> None:
        source = KnowledgeSource(
            source_path="contracts/msa.pdf",
            page="5",
            section_ref="Section 4.3",
            exact_quote="The parties agree...",
            run_id="run_001",
            timestamp="2026-03-07T14:30:00+00:00",
        )
        assert source.source_path == "contracts/msa.pdf"
        assert source.exact_quote == "The parties agree..."

    def test_article_serialization_roundtrip(self) -> None:
        article = _make_article()
        data = article.model_dump(mode="json")
        restored = KnowledgeArticle.model_validate(data)
        assert restored.id == article.id
        assert restored.sources[0].exact_quote == article.sources[0].exact_quote

    def test_title_max_length(self) -> None:
        with pytest.raises(ValueError):
            _make_article(title="x" * 201)


# ---------------------------------------------------------------------------
# DealKnowledgeBase CRUD tests
# ---------------------------------------------------------------------------


class TestDealKnowledgeBaseCRUD:
    def test_ensure_dirs_creates_structure(self, kb: DealKnowledgeBase) -> None:
        assert kb.exists
        assert (kb.knowledge_dir / "entities").is_dir()
        assert (kb.knowledge_dir / "clauses").is_dir()
        assert (kb.knowledge_dir / "contradictions").is_dir()
        assert (kb.knowledge_dir / "insights").is_dir()
        assert (kb.knowledge_dir / "annotations").is_dir()

    def test_write_and_get_article(self, kb: DealKnowledgeBase) -> None:
        article = _make_article()
        kb.write_article(article)
        loaded = kb.get_article("test_001")
        assert loaded is not None
        assert loaded.id == "test_001"
        assert loaded.title == "Test Article"
        assert loaded.content == {"key": "value"}

    def test_get_nonexistent_returns_none(self, kb: DealKnowledgeBase) -> None:
        assert kb.get_article("does_not_exist") is None

    def test_update_article(self, kb: DealKnowledgeBase) -> None:
        article = _make_article()
        kb.write_article(article)
        updated = kb.update_article("test_001", {"title": "Updated Title"})
        assert updated is not None
        assert updated.title == "Updated Title"
        assert updated.version == 2

    def test_update_nonexistent_returns_none(self, kb: DealKnowledgeBase) -> None:
        assert kb.update_article("nope", {"title": "X"}) is None

    def test_delete_article(self, kb: DealKnowledgeBase) -> None:
        kb.write_article(_make_article())
        assert kb.delete_article("test_001") is True
        assert kb.get_article("test_001") is None

    def test_delete_nonexistent_returns_false(self, kb: DealKnowledgeBase) -> None:
        assert kb.delete_article("nope") is False

    def test_list_articles_all(self, kb: DealKnowledgeBase) -> None:
        kb.write_article(_make_article("a1", ArticleType.ENTITY_PROFILE))
        kb.write_article(_make_article("a2", ArticleType.CLAUSE_SUMMARY))
        kb.write_article(_make_article("a3", ArticleType.INSIGHT))
        articles = kb.list_articles()
        assert len(articles) == 3

    def test_list_articles_by_type(self, kb: DealKnowledgeBase) -> None:
        kb.write_article(_make_article("a1", ArticleType.ENTITY_PROFILE))
        kb.write_article(_make_article("a2", ArticleType.CLAUSE_SUMMARY))
        entities = kb.list_articles(ArticleType.ENTITY_PROFILE)
        assert len(entities) == 1
        assert entities[0].id == "a1"

    def test_search_articles_by_title(self, kb: DealKnowledgeBase) -> None:
        kb.write_article(_make_article("a1", title="NovaBridge Software Profile"))
        kb.write_article(_make_article("a2", title="Pinnacle Analytics Profile"))
        results = kb.search_articles("novabridge")
        assert len(results) == 1
        assert results[0].id == "a1"

    def test_search_articles_by_tag(self, kb: DealKnowledgeBase) -> None:
        article = _make_article("a1", tags=["change_of_control", "legal"])
        kb.write_article(article)
        results = kb.search_articles("change_of_control")
        assert len(results) == 1

    def test_search_skips_superseded(self, kb: DealKnowledgeBase) -> None:
        article = _make_article("a1", title="Old Profile", superseded_by="a2")
        kb.write_article(article)
        results = kb.search_articles("Old Profile")
        assert len(results) == 0

    def test_atomic_write_crash_safety(self, kb: DealKnowledgeBase) -> None:
        """Verify that a successfully written article is readable."""
        article = _make_article()
        kb.write_article(article)
        # Read the raw JSON to verify it's valid
        path = kb.knowledge_dir / "entities" / "test_001.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["id"] == "test_001"

    def test_article_stored_in_correct_subdir(self, kb: DealKnowledgeBase) -> None:
        kb.write_article(_make_article("e1", ArticleType.ENTITY_PROFILE))
        kb.write_article(_make_article("c1", ArticleType.CLAUSE_SUMMARY))
        kb.write_article(_make_article("i1", ArticleType.INSIGHT))
        kb.write_article(_make_article("n1", ArticleType.ANNOTATION))
        kb.write_article(_make_article("x1", ArticleType.CONTRADICTION))

        assert (kb.knowledge_dir / "entities" / "e1.json").exists()
        assert (kb.knowledge_dir / "clauses" / "c1.json").exists()
        assert (kb.knowledge_dir / "insights" / "i1.json").exists()
        assert (kb.knowledge_dir / "annotations" / "n1.json").exists()
        assert (kb.knowledge_dir / "contradictions" / "x1.json").exists()


# ---------------------------------------------------------------------------
# Index tests
# ---------------------------------------------------------------------------


class TestKnowledgeIndex:
    def test_index_built_after_write(self, kb: DealKnowledgeBase) -> None:
        kb.write_article(_make_article("a1", ArticleType.ENTITY_PROFILE))
        index = kb.get_index()
        assert index.total_articles == 1
        assert index.entity_count == 1

    def test_index_reflects_multiple_articles(self, kb: DealKnowledgeBase) -> None:
        kb.write_article(_make_article("a1", ArticleType.ENTITY_PROFILE))
        kb.write_article(_make_article("a2", ArticleType.CLAUSE_SUMMARY))
        kb.write_article(_make_article("a3", ArticleType.INSIGHT))
        index = kb.get_index()
        assert index.total_articles == 3
        assert index.entity_count == 1
        assert "entity_profile" in index.by_type
        assert "clause_summary" in index.by_type

    def test_index_updated_after_delete(self, kb: DealKnowledgeBase) -> None:
        kb.write_article(_make_article("a1"))
        kb.write_article(_make_article("a2"))
        kb.delete_article("a1")
        index = kb.get_index()
        assert index.total_articles == 1

    def test_index_build_from_articles(self) -> None:
        articles = [
            _make_article("a1", ArticleType.ENTITY_PROFILE),
            _make_article("a2", ArticleType.CLAUSE_SUMMARY),
        ]
        index = KnowledgeIndex.build(articles, "2026-03-07T14:30:00+00:00")
        assert index.total_articles == 2

    def test_index_summary_generation(self, kb: DealKnowledgeBase) -> None:
        kb.write_article(_make_article("a1", ArticleType.ENTITY_PROFILE, "Entity Profile: Acme"))
        index = kb.get_index()
        summary = index.generate_summary(max_chars=1000)
        assert "Entity Profile: Acme" in summary
        assert len(summary) <= 1000

    def test_index_summary_respects_char_limit(self) -> None:
        articles = [_make_article(f"a{i}", ArticleType.ENTITY_PROFILE, f"Profile {i}") for i in range(50)]
        index = KnowledgeIndex.build(articles, "2026-03-07T14:30:00+00:00")
        summary = index.generate_summary(max_chars=200)
        assert len(summary) <= 200


# ---------------------------------------------------------------------------
# Compiler tests
# ---------------------------------------------------------------------------


def _make_merged_findings_dir(run_dir: Path) -> None:
    """Create a mock merged findings directory."""
    merged_dir = run_dir / "findings" / "merged"
    merged_dir.mkdir(parents=True, exist_ok=True)

    # Subject A: 2 findings (P0 + P1)
    (merged_dir / "subject_a.json").write_text(
        json.dumps(
            {
                "subject_safe_name": "subject_a",
                "findings": [
                    {
                        "severity": "P0",
                        "category": "change_of_control",
                        "title": "CoC requires Board consent",
                        "agent": "legal",
                        "analysis_unit": "subject_a",
                        "timestamp": "2026-03-07T14:30:00+00:00",
                        "citations": [
                            {
                                "source_path": "subject_a/msa.pdf",
                                "location": "Section 4.3",
                                "exact_quote": "Board consent required for change of control",
                                "page_number": 5,
                            }
                        ],
                    },
                    {
                        "severity": "P1",
                        "category": "termination",
                        "title": "Short notice period",
                        "agent": "legal",
                        "analysis_unit": "subject_a",
                        "timestamp": "2026-03-07T14:30:00+00:00",
                        "citations": [
                            {
                                "source_path": "subject_a/msa.pdf",
                                "location": "Section 8.2",
                                "exact_quote": "30-day notice for termination",
                            }
                        ],
                    },
                ],
            }
        )
    )

    # Subject B: 1 finding (P2)
    (merged_dir / "subject_b.json").write_text(
        json.dumps(
            {
                "subject_safe_name": "subject_b",
                "findings": [
                    {
                        "severity": "P2",
                        "category": "change_of_control",
                        "title": "Standard CoC clause",
                        "agent": "legal",
                        "analysis_unit": "subject_b",
                        "timestamp": "2026-03-07T14:30:00+00:00",
                        "citations": [
                            {
                                "source_path": "subject_b/agreement.pdf",
                                "location": "Section 3.1",
                                "exact_quote": "Standard change of control provision",
                            }
                        ],
                    },
                ],
            }
        )
    )


class TestKnowledgeCompiler:
    def test_compile_creates_entity_profiles(self, kb: DealKnowledgeBase, tmp_path: Path) -> None:
        run_dir = tmp_path / "run_001"
        _make_merged_findings_dir(run_dir)

        compiler = KnowledgeCompiler(kb)
        result = compiler.compile_from_run(run_dir, "run_001")

        assert result.articles_created >= 2  # At least 2 entity profiles
        assert "subject_a" in result.entities_enriched
        assert "subject_b" in result.entities_enriched

        # Verify entity profile content
        profile = kb.get_article("entity_subject_a")
        assert profile is not None
        assert profile.article_type == ArticleType.ENTITY_PROFILE
        assert profile.content["total_findings"] == 2
        assert profile.content["severity_distribution"]["P0"] == 1

    def test_compile_creates_clause_summaries(self, kb: DealKnowledgeBase, tmp_path: Path) -> None:
        run_dir = tmp_path / "run_001"
        _make_merged_findings_dir(run_dir)

        compiler = KnowledgeCompiler(kb)
        compiler.compile_from_run(run_dir, "run_001")

        clause = kb.get_article("clause_change_of_control")
        assert clause is not None
        assert clause.article_type == ArticleType.CLAUSE_SUMMARY
        assert clause.content["entities_affected"] == 2

    def test_compile_incremental_update(self, kb: DealKnowledgeBase, tmp_path: Path) -> None:
        """Second compile should update, not duplicate."""
        run_dir = tmp_path / "run_001"
        _make_merged_findings_dir(run_dir)

        compiler = KnowledgeCompiler(kb)
        compiler.compile_from_run(run_dir, "run_001")
        r2 = compiler.compile_from_run(run_dir, "run_002")

        # Second run should update existing profiles
        assert r2.articles_updated > 0

        # Entity profile should have 2 run history entries
        profile = kb.get_article("entity_subject_a")
        assert profile is not None
        history = profile.content.get("cross_run_history", [])
        assert len(history) == 2

    def test_compile_empty_findings(self, kb: DealKnowledgeBase, tmp_path: Path) -> None:
        run_dir = tmp_path / "empty_run"
        result = KnowledgeCompiler(kb).compile_from_run(run_dir, "empty")
        assert result.articles_created == 0

    def test_compilation_result_model(self) -> None:
        result = CompilationResult(
            articles_created=5,
            articles_updated=3,
            contradictions_found=1,
            entities_enriched=["a", "b"],
        )
        assert result.articles_created == 5
        data = result.model_dump()
        restored = CompilationResult.model_validate(data)
        assert restored.entities_enriched == ["a", "b"]


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


class TestKnowledgeValidation:
    def test_validate_empty_kb(self, kb: DealKnowledgeBase) -> None:
        # Empty KB should report missing index
        issues = kb.validate()
        assert any("Index file missing" in i for i in issues)

    def test_validate_healthy_kb(self, kb: DealKnowledgeBase) -> None:
        kb.write_article(_make_article("a1"))
        issues = kb.validate()
        assert len(issues) == 0

    def test_validate_broken_links(self, kb: DealKnowledgeBase) -> None:
        article = _make_article("a1", links=["nonexistent_id"])
        kb.write_article(article)
        issues = kb.validate()
        assert any("broken link" in i for i in issues)

    def test_validate_corrupt_article(self, kb: DealKnowledgeBase) -> None:
        kb.ensure_dirs()
        # Write invalid JSON
        (kb.knowledge_dir / "entities" / "bad.json").write_text("{invalid}")
        issues = kb.validate()
        assert any("Corrupt article" in i for i in issues)

    def test_nonexistent_kb_reports_issue(self, tmp_path: Path) -> None:
        kb = DealKnowledgeBase(tmp_path / "nonexistent")
        issues = kb.validate()
        assert any("does not exist" in i for i in issues)


# ---------------------------------------------------------------------------
# Batch writes tests
# ---------------------------------------------------------------------------


class TestBatchWrites:
    def test_batch_writes_defers_index_rebuild(self, kb: DealKnowledgeBase) -> None:
        """Index should only rebuild once at the end of a batch."""
        with kb.batch_writes():
            kb.write_article(_make_article("a1", ArticleType.ENTITY_PROFILE))
            kb.write_article(_make_article("a2", ArticleType.CLAUSE_SUMMARY))
            kb.write_article(_make_article("a3", ArticleType.INSIGHT))
        # After batch, index should reflect all 3 articles
        index = kb.get_index()
        assert index.total_articles == 3

    def test_batch_writes_nesting(self, kb: DealKnowledgeBase) -> None:
        """Nested batches only rebuild at outermost exit."""
        with kb.batch_writes():
            kb.write_article(_make_article("a1"))
            with kb.batch_writes():
                kb.write_article(_make_article("a2"))
            # Inner batch exits — still inside outer, no rebuild yet
            assert kb._batch_depth == 1
        # Now outer exits, index is rebuilt
        assert kb._batch_depth == 0
        index = kb.get_index()
        assert index.total_articles == 2

    def test_update_article_id_overwrite_guard(self, kb: DealKnowledgeBase) -> None:
        """Passing 'id' in updates dict should not change article ID."""
        kb.write_article(_make_article("a1"))
        updated = kb.update_article("a1", {"id": "HIJACKED", "title": "New Title"})
        assert updated is not None
        assert updated.id == "a1"  # ID unchanged
        assert updated.title == "New Title"
        # Old ID should still be loadable
        assert kb.get_article("a1") is not None
        assert kb.get_article("HIJACKED") is None


# ---------------------------------------------------------------------------
# Contradiction detection tests (U1)
# ---------------------------------------------------------------------------


class TestContradictionDetection:
    def test_compiler_detects_severity_disagreement(self, kb: DealKnowledgeBase, tmp_path: Path) -> None:
        """Contradictions are created when agents disagree on severity for same category."""
        run_dir = tmp_path / "run_001"
        merged_dir = run_dir / "findings" / "merged"
        merged_dir.mkdir(parents=True)

        # Same subject, same category, different agents with different severities
        (merged_dir / "subject_x.json").write_text(
            json.dumps(
                {
                    "subject_safe_name": "subject_x",
                    "findings": [
                        {
                            "severity": "P0",
                            "category": "termination",
                            "title": "Critical termination clause",
                            "agent": "legal",
                            "analysis_unit": "subject_x",
                            "timestamp": "2026-03-07T14:30:00+00:00",
                            "citations": [],
                        },
                        {
                            "severity": "P2",
                            "category": "termination",
                            "title": "Standard termination clause",
                            "agent": "commercial",
                            "analysis_unit": "subject_x",
                            "timestamp": "2026-03-07T14:30:00+00:00",
                            "citations": [],
                        },
                    ],
                }
            )
        )

        compiler = KnowledgeCompiler(kb)
        result = compiler.compile_from_run(run_dir, "run_001")
        assert result.contradictions_found >= 1

        # Verify contradiction article exists
        contradictions = kb.list_articles(ArticleType.CONTRADICTION)
        assert len(contradictions) >= 1
        assert contradictions[0].content["type"] == "severity_disagreement"

    def test_no_contradiction_when_same_severity(self, kb: DealKnowledgeBase, tmp_path: Path) -> None:
        """No contradiction when agents agree on severity."""
        run_dir = tmp_path / "run_001"
        merged_dir = run_dir / "findings" / "merged"
        merged_dir.mkdir(parents=True)

        (merged_dir / "subject_y.json").write_text(
            json.dumps(
                {
                    "subject_safe_name": "subject_y",
                    "findings": [
                        {
                            "severity": "P1",
                            "category": "change_of_control",
                            "title": "CoC clause",
                            "agent": "legal",
                            "analysis_unit": "subject_y",
                            "timestamp": "2026-03-07T14:30:00+00:00",
                            "citations": [],
                        },
                        {
                            "severity": "P1",
                            "category": "change_of_control",
                            "title": "CoC clause v2",
                            "agent": "commercial",
                            "analysis_unit": "subject_y",
                            "timestamp": "2026-03-07T14:30:00+00:00",
                            "citations": [],
                        },
                    ],
                }
            )
        )

        compiler = KnowledgeCompiler(kb)
        result = compiler.compile_from_run(run_dir, "run_001")
        assert result.contradictions_found == 0


# ---------------------------------------------------------------------------
# Article type change ghost file test (U5)
# ---------------------------------------------------------------------------


class TestArticleTypeChange:
    def test_article_type_change_leaves_no_ghost(self, kb: DealKnowledgeBase) -> None:
        """Changing article_type via update should not leave a ghost file in the old subdir."""
        article = _make_article("x1", ArticleType.ENTITY_PROFILE)
        kb.write_article(article)
        assert (kb.knowledge_dir / "entities" / "x1.json").exists()

        # Delete and re-write with a different type
        kb.delete_article("x1")
        new_article = _make_article("x1", ArticleType.INSIGHT)
        kb.write_article(new_article)

        # Should exist in insights, not in entities
        assert (kb.knowledge_dir / "insights" / "x1.json").exists()
        assert not (kb.knowledge_dir / "entities" / "x1.json").exists()
