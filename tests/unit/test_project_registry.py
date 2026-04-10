"""Tests for Multi-Project Portfolio View & Cross-Deal Analytics (Issue #118)."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003

import pytest

from dd_agents.models.project import PortfolioComparison, ProjectEntry, ProjectRegistry
from dd_agents.persistence.project_registry import (
    ProjectRegistryManager,
    _safe_slug,
)


class TestProjectModels:
    """Test project data models."""

    def test_project_entry_defaults(self) -> None:
        entry = ProjectEntry(name="Test Deal", slug="test_deal", path="/tmp/test", created_at="2026-01-01T00:00:00Z")
        assert entry.status == "created"
        assert entry.total_runs == 0
        assert entry.total_findings == 0
        assert entry.risk_score == 0.0
        assert entry.finding_counts == {}
        assert entry.locked_by is None

    def test_project_entry_with_data(self) -> None:
        entry = ProjectEntry(
            name="Alpha Deal",
            slug="alpha_deal",
            path="/data/alpha",
            created_at="2026-01-01T00:00:00Z",
            status="completed",
            total_runs=3,
            total_subjects=50,
            total_findings=200,
            finding_counts={"P0": 5, "P1": 20, "P2": 75, "P3": 100},
            deal_type="acquisition",
            buyer="Buyer Co",
            target="Target Inc",
            risk_score=72.5,
        )
        assert entry.total_findings == 200
        assert entry.finding_counts["P0"] == 5
        assert entry.risk_score == 72.5

    def test_project_registry_defaults(self) -> None:
        reg = ProjectRegistry(base_dir="/tmp")
        assert reg.version == 1
        assert reg.projects == []
        assert reg.last_updated == ""

    def test_portfolio_comparison_defaults(self) -> None:
        comp = PortfolioComparison()
        assert comp.projects == []
        assert comp.total_arr == 0.0
        assert comp.avg_risk_score == 0.0
        assert comp.severity_distribution == {}


class TestSafeSlug:
    """Test the slug generation function."""

    def test_basic_name(self) -> None:
        assert _safe_slug("Alpha Deal") == "alpha_deal"

    def test_special_characters(self) -> None:
        assert _safe_slug("Acme & Partners, Inc.") == "acme_partners_inc"

    def test_empty_name(self) -> None:
        assert _safe_slug("") == "unnamed"

    def test_numbers(self) -> None:
        assert _safe_slug("Deal 2026-Q1") == "deal_2026_q1"

    def test_already_clean(self) -> None:
        assert _safe_slug("simple") == "simple"


class TestProjectRegistryManager:
    """Test project registry CRUD operations."""

    @pytest.fixture()
    def manager(self, tmp_path: Path) -> ProjectRegistryManager:
        return ProjectRegistryManager(base_dir=tmp_path)

    def test_empty_registry(self, manager: ProjectRegistryManager) -> None:
        projects = manager.list_projects()
        assert projects == []

    def test_add_project(self, manager: ProjectRegistryManager, tmp_path: Path) -> None:
        data_room = tmp_path / "data_room"
        data_room.mkdir()
        entry = manager.add_project("Alpha Deal", data_room, deal_type="acquisition", buyer="Buyer", target="Target")
        assert entry.slug == "alpha_deal"
        assert entry.status == "created"
        assert entry.buyer == "Buyer"
        assert entry.target == "Target"

    def test_add_duplicate_raises(self, manager: ProjectRegistryManager, tmp_path: Path) -> None:
        manager.add_project("Alpha Deal", tmp_path / "a")
        with pytest.raises(ValueError, match="already exists"):
            manager.add_project("Alpha Deal", tmp_path / "b")

    def test_list_projects(self, manager: ProjectRegistryManager, tmp_path: Path) -> None:
        manager.add_project("Deal A", tmp_path / "a")
        manager.add_project("Deal B", tmp_path / "b")
        projects = manager.list_projects()
        assert len(projects) == 2
        assert projects[0].slug == "deal_a"
        assert projects[1].slug == "deal_b"

    def test_get_project_by_slug(self, manager: ProjectRegistryManager, tmp_path: Path) -> None:
        manager.add_project("My Deal", tmp_path / "data")
        found = manager.get_project("my_deal")
        assert found is not None
        assert found.name == "My Deal"

    def test_get_project_by_name(self, manager: ProjectRegistryManager, tmp_path: Path) -> None:
        manager.add_project("Alpha Deal", tmp_path / "data")
        found = manager.get_project("Alpha Deal")
        assert found is not None
        assert found.slug == "alpha_deal"

    def test_get_project_not_found(self, manager: ProjectRegistryManager) -> None:
        assert manager.get_project("nonexistent") is None

    def test_update_project(self, manager: ProjectRegistryManager, tmp_path: Path) -> None:
        manager.add_project("Deal X", tmp_path / "x")
        updated = manager.update_project("deal_x", status="running", notes="In progress")
        assert updated is not None
        assert updated.status == "running"
        assert updated.notes == "In progress"

    def test_update_nonexistent(self, manager: ProjectRegistryManager) -> None:
        assert manager.update_project("nope", status="running") is None

    def test_remove_project(self, manager: ProjectRegistryManager, tmp_path: Path) -> None:
        manager.add_project("To Remove", tmp_path / "rem")
        assert manager.remove_project("to_remove") is True
        assert manager.list_projects() == []

    def test_remove_nonexistent(self, manager: ProjectRegistryManager) -> None:
        assert manager.remove_project("nope") is False

    def test_archive_project(self, manager: ProjectRegistryManager, tmp_path: Path) -> None:
        manager.add_project("Old Deal", tmp_path / "old")
        archived = manager.archive_project("old_deal")
        assert archived is not None
        assert archived.status == "archived"

    def test_sync_project_from_run(self, manager: ProjectRegistryManager, tmp_path: Path) -> None:
        manager.add_project("Active Deal", tmp_path / "active")
        result = manager.sync_project_from_run(
            slug="active_deal",
            run_id="run_20260101_120000",
            total_subjects=50,
            total_findings=200,
            finding_counts={"P0": 5, "P1": 20, "P2": 75, "P3": 100},
            risk_score=65.0,
        )
        assert result is not None
        assert result.total_runs == 1
        assert result.total_subjects == 50
        assert result.total_findings == 200
        assert result.risk_score == 65.0
        assert result.status == "completed"
        assert result.last_run_id == "run_20260101_120000"

    def test_registry_persists(self, tmp_path: Path) -> None:
        mgr1 = ProjectRegistryManager(base_dir=tmp_path)
        mgr1.add_project("Persisted", tmp_path / "data")
        mgr2 = ProjectRegistryManager(base_dir=tmp_path)
        projects = mgr2.list_projects()
        assert len(projects) == 1
        assert projects[0].name == "Persisted"

    def test_corrupt_registry_recovery(self, tmp_path: Path) -> None:
        registry_path = tmp_path / "project_registry.json"
        tmp_path.mkdir(exist_ok=True)
        registry_path.write_text("not json", encoding="utf-8")
        mgr = ProjectRegistryManager(base_dir=tmp_path)
        assert mgr.list_projects() == []


class TestPortfolioComparison:
    """Test cross-deal comparison functionality."""

    @pytest.fixture()
    def populated_manager(self, tmp_path: Path) -> ProjectRegistryManager:
        mgr = ProjectRegistryManager(base_dir=tmp_path)
        mgr.add_project("Deal A", tmp_path / "a", deal_type="acquisition")
        mgr.sync_project_from_run("deal_a", "r1", 50, 200, {"P0": 5, "P1": 20}, 72.0)
        mgr.add_project("Deal B", tmp_path / "b", deal_type="merger")
        mgr.sync_project_from_run("deal_b", "r2", 30, 100, {"P0": 2, "P1": 10}, 45.0)
        mgr.add_project("Deal C", tmp_path / "c", deal_type="acquisition")
        mgr.sync_project_from_run("deal_c", "r3", 80, 400, {"P0": 10, "P1": 50}, 88.0)
        return mgr

    def test_compare_all(self, populated_manager: ProjectRegistryManager) -> None:
        comp = populated_manager.compare_projects()
        assert len(comp.projects) == 3
        assert comp.total_findings == 700
        assert comp.avg_risk_score == pytest.approx(68.333, rel=1e-2)
        assert comp.severity_distribution["P0"] == 17
        assert comp.severity_distribution["P1"] == 80

    def test_compare_subset(self, populated_manager: ProjectRegistryManager) -> None:
        comp = populated_manager.compare_projects(slugs=["deal_a", "deal_b"])
        assert len(comp.projects) == 2
        assert comp.total_findings == 300

    def test_compare_benchmarks(self, populated_manager: ProjectRegistryManager) -> None:
        comp = populated_manager.compare_projects()
        assert comp.risk_benchmarks["min"] == 45.0
        assert comp.risk_benchmarks["max"] == 88.0

    def test_compare_excludes_archived(self, populated_manager: ProjectRegistryManager) -> None:
        populated_manager.archive_project("deal_b")
        comp = populated_manager.compare_projects()
        assert len(comp.projects) == 2

    def test_compare_empty(self, tmp_path: Path) -> None:
        mgr = ProjectRegistryManager(base_dir=tmp_path)
        comp = mgr.compare_projects()
        assert comp.projects == []
        assert comp.avg_risk_score == 0.0
