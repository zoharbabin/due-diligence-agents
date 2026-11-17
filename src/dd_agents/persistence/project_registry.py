"""Multi-project registry management (Issue #118).

Manages a JSON-based project registry for tracking multiple deals.
Each deal is fully isolated (separate _dd/ directories); the registry
is a convenience index that stores only metadata, never deal data.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dd_agents.models.project import REGISTRY_VERSION, PortfolioComparison, ProjectEntry, ProjectRegistry

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

_DEFAULT_BASE_DIR = "~/.dd-projects"


class RegistryVersionError(RuntimeError):
    """The registry file was written by a newer version of dd-agents."""


@contextlib.contextmanager
def _file_lock(lock_path: Path) -> Iterator[None]:
    """Exclusive cross-process lock held for the ``with`` body (blocks until free)."""
    with lock_path.open("a+b") as handle:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _safe_slug(name: str) -> str:
    """Convert a deal name to a filesystem-safe slug."""
    import re

    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug or "unnamed"


class ProjectRegistryManager:
    """CRUD operations on the project registry file."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        raw = base_dir or os.environ.get("DD_BASE_DIR", _DEFAULT_BASE_DIR)
        self.base_dir = Path(raw).expanduser().resolve()
        self.registry_path = self.base_dir / "project_registry.json"
        self.lock_path = self.base_dir / "project_registry.lock"

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        """Serialize a read-modify-write cycle across processes (CLI and desktop app)."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        with _file_lock(self.lock_path):
            yield

    def _load(self) -> ProjectRegistry:
        if not self.registry_path.exists():
            return ProjectRegistry(base_dir=str(self.base_dir))
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
            found = data.get("version") if isinstance(data, dict) else None
            if isinstance(found, int) and found > REGISTRY_VERSION:
                raise RegistryVersionError(
                    f"{self.registry_path} is format v{found}, written by a newer dd-agents "
                    f"(this version reads v{REGISTRY_VERSION}). Upgrade dd-agents to open it."
                )
            return ProjectRegistry.model_validate(data)
        except RegistryVersionError:
            raise
        except Exception:
            backup = self.registry_path.with_name(self.registry_path.name + ".corrupt")
            shutil.copy2(self.registry_path, backup)
            logger.warning("Corrupt registry file, starting fresh (copy kept at %s): %s", backup, self.registry_path)
            return ProjectRegistry(base_dir=str(self.base_dir))

    def _save(self, registry: ProjectRegistry) -> None:
        """Write atomically: temp file in the same directory, fsync, then replace."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        registry.last_updated = _now_iso()
        registry.base_dir = str(self.base_dir)
        payload = json.dumps(registry.model_dump(), indent=2, default=str)
        fd, tmp_name = tempfile.mkstemp(dir=self.base_dir, prefix=".project_registry.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                tmp.write(payload)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp_name, self.registry_path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            raise

    def list_projects(self) -> list[ProjectEntry]:
        """Return all registered projects."""
        return self._load().projects

    def get_project(self, name_or_slug: str) -> ProjectEntry | None:
        """Look up a project by name or slug."""
        key = name_or_slug.lower()
        for p in self._load().projects:
            if p.slug == key or p.name.lower() == key:
                return p
        return None

    def add_project(
        self,
        name: str,
        data_room_path: str | Path,
        *,
        config_path: str = "",
        deal_type: str = "",
        buyer: str = "",
        target: str = "",
        notes: str = "",
    ) -> ProjectEntry:
        """Register a new deal project."""
        with self._locked():
            registry = self._load()
            slug = _safe_slug(name)

            # Prevent duplicates
            if any(p.slug == slug for p in registry.projects):
                raise ValueError(f"Project '{slug}' already exists in registry")

            entry = ProjectEntry(
                name=name,
                slug=slug,
                path=str(Path(data_room_path).resolve()),
                config_path=config_path,
                created_at=_now_iso(),
                deal_type=deal_type,
                buyer=buyer,
                target=target,
                notes=notes,
            )
            registry.projects.append(entry)
            self._save(registry)
            return entry

    def update_project(self, slug: str, **updates: Any) -> ProjectEntry | None:
        """Update fields on an existing project entry."""
        with self._locked():
            registry = self._load()
            for i, p in enumerate(registry.projects):
                if p.slug == slug:
                    data = p.model_dump()
                    data.update(updates)
                    registry.projects[i] = ProjectEntry.model_validate(data)
                    self._save(registry)
                    return registry.projects[i]
            return None

    def remove_project(self, slug: str) -> bool:
        """Remove a project from the registry (does not delete deal data)."""
        with self._locked():
            registry = self._load()
            before = len(registry.projects)
            registry.projects = [p for p in registry.projects if p.slug != slug]
            if len(registry.projects) < before:
                self._save(registry)
                return True
            return False

    def archive_project(self, slug: str) -> ProjectEntry | None:
        """Mark a project as archived."""
        return self.update_project(slug, status="archived")

    def sync_project_from_run(
        self,
        slug: str,
        run_id: str,
        total_subjects: int,
        total_findings: int,
        finding_counts: dict[str, int],
        risk_score: float,
        status: str = "completed",
        risk_label: str = "",
    ) -> ProjectEntry | None:
        """Update project metadata after a pipeline run completes."""
        with self._locked():
            registry = self._load()
            for i, p in enumerate(registry.projects):
                if p.slug == slug:
                    p.last_run_at = _now_iso()
                    p.last_run_id = run_id
                    p.total_runs += 1
                    p.total_subjects = total_subjects
                    p.total_findings = total_findings
                    p.finding_counts = finding_counts
                    p.risk_score = risk_score
                    p.risk_label = risk_label
                    p.status = status
                    registry.projects[i] = p
                    self._save(registry)
                    return p
            return None

    def compare_projects(self, slugs: list[str] | None = None) -> PortfolioComparison:
        """Build cross-deal comparison data."""
        all_projects = self._load().projects
        if slugs:
            projects = [p for p in all_projects if p.slug in slugs]
        else:
            projects = [p for p in all_projects if p.status != "archived"]

        total_findings = sum(p.total_findings for p in projects)
        risk_scores = [p.risk_score for p in projects if p.risk_score > 0]

        severity_dist: dict[str, int] = {}
        for p in projects:
            for sev, count in p.finding_counts.items():
                severity_dist[sev] = severity_dist.get(sev, 0) + count

        benchmarks: dict[str, float] = {}
        if risk_scores:
            sorted_scores = sorted(risk_scores)
            n = len(sorted_scores)
            benchmarks["min"] = sorted_scores[0]
            benchmarks["max"] = sorted_scores[-1]
            benchmarks["median"] = sorted_scores[n // 2]
            benchmarks["p25"] = sorted_scores[max(0, n // 4)]
            benchmarks["p75"] = sorted_scores[max(0, 3 * n // 4)]

        return PortfolioComparison(
            projects=projects,
            total_findings=total_findings,
            avg_risk_score=sum(risk_scores) / len(risk_scores) if risk_scores else 0.0,
            severity_distribution=severity_dist,
            risk_benchmarks=benchmarks,
        )
