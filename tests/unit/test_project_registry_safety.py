"""Registry safety: atomic writes, cross-process locking, version guard, corrupt backup.

The desktop app and the CLI both write ``project_registry.json``.
"""

from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path  # noqa: TC003
from unittest import mock

import pytest

from dd_agents.models.project import REGISTRY_VERSION
from dd_agents.persistence.project_registry import (
    ProjectRegistryManager,
    RegistryVersionError,
)


def _add_one(base_dir: str, index: int) -> None:
    ProjectRegistryManager(base_dir).add_project(f"Deal {index}", f"/tmp/room_{index}")


class TestAtomicSave:
    def test_saved_file_carries_current_version(self, tmp_path: Path) -> None:
        ProjectRegistryManager(tmp_path).add_project("Deal A", "/tmp/a")
        data = json.loads((tmp_path / "project_registry.json").read_text(encoding="utf-8"))
        assert data["version"] == REGISTRY_VERSION

    def test_no_temp_files_left_behind(self, tmp_path: Path) -> None:
        mgr = ProjectRegistryManager(tmp_path)
        mgr.add_project("Deal A", "/tmp/a")
        mgr.add_project("Deal B", "/tmp/b")
        names = sorted(p.name for p in tmp_path.iterdir() if p.name != "project_registry.lock")
        assert names == ["project_registry.json"]

    def test_failed_replace_keeps_old_file_intact(self, tmp_path: Path) -> None:
        mgr = ProjectRegistryManager(tmp_path)
        mgr.add_project("Deal A", "/tmp/a")
        before = (tmp_path / "project_registry.json").read_bytes()
        with mock.patch("os.replace", side_effect=OSError("disk full")), pytest.raises(OSError):
            mgr.add_project("Deal B", "/tmp/b")
        assert (tmp_path / "project_registry.json").read_bytes() == before
        assert not [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]


class TestConcurrentWriters:
    def test_parallel_adds_lose_nothing(self, tmp_path: Path) -> None:
        ctx = multiprocessing.get_context("spawn")
        workers = [ctx.Process(target=_add_one, args=(str(tmp_path), i)) for i in range(8)]
        for w in workers:
            w.start()
        for w in workers:
            w.join(timeout=60)
        assert all(w.exitcode == 0 for w in workers)
        slugs = {p.slug for p in ProjectRegistryManager(tmp_path).list_projects()}
        assert slugs == {f"deal_{i}" for i in range(8)}


class TestVersionGuard:
    def _write_newer(self, tmp_path: Path) -> bytes:
        payload = {"version": REGISTRY_VERSION + 1, "base_dir": str(tmp_path), "projects": [], "future": {"x": 1}}
        raw = json.dumps(payload).encode()
        (tmp_path / "project_registry.json").write_bytes(raw)
        return raw

    def test_newer_registry_is_refused_on_read(self, tmp_path: Path) -> None:
        self._write_newer(tmp_path)
        with pytest.raises(RegistryVersionError, match="newer"):
            ProjectRegistryManager(tmp_path).list_projects()

    def test_newer_registry_is_never_overwritten(self, tmp_path: Path) -> None:
        raw = self._write_newer(tmp_path)
        with pytest.raises(RegistryVersionError):
            ProjectRegistryManager(tmp_path).add_project("Deal A", "/tmp/a")
        assert (tmp_path / "project_registry.json").read_bytes() == raw

    def test_same_version_loads(self, tmp_path: Path) -> None:
        mgr = ProjectRegistryManager(tmp_path)
        mgr.add_project("Deal A", "/tmp/a")
        assert [p.slug for p in mgr.list_projects()] == ["deal_a"]


class TestCorruptFile:
    def test_corrupt_file_is_backed_up_before_reset(self, tmp_path: Path) -> None:
        path = tmp_path / "project_registry.json"
        path.write_text("{not json", encoding="utf-8")
        mgr = ProjectRegistryManager(tmp_path)
        assert mgr.list_projects() == []
        mgr.add_project("Deal A", "/tmp/a")
        backup = tmp_path / "project_registry.json.corrupt"
        assert backup.read_text(encoding="utf-8") == "{not json"
        assert [p.slug for p in mgr.list_projects()] == ["deal_a"]

    def test_missing_file_makes_no_backup(self, tmp_path: Path) -> None:
        ProjectRegistryManager(tmp_path).list_projects()
        assert not (tmp_path / "project_registry.json.corrupt").exists()


def test_lock_file_lives_in_base_dir(tmp_path: Path) -> None:
    ProjectRegistryManager(tmp_path).add_project("Deal A", "/tmp/a")
    assert os.path.exists(tmp_path / "project_registry.lock")
