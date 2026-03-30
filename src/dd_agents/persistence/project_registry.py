"""Multi-project registry management (Issue #118).

Manages a JSON-based project registry for tracking multiple deals.
Each deal is fully isolated (separate _dd/ directories); the registry
is a convenience index that stores only metadata, never deal data.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dd_agents.models.project import PortfolioComparison, ProjectEntry, ProjectRegistry

logger = logging.getLogger(__name__)

_DEFAULT_BASE_DIR = "~/.dd-projects"


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

    def _load(self) -> ProjectRegistry:
        if not self.registry_path.exists():
            return ProjectRegistry(base_dir=str(self.base_dir))
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
            return ProjectRegistry.model_validate(data)
        except Exception:
            logger.warning("Corrupt registry file, starting fresh: %s", self.registry_path)
            return ProjectRegistry(base_dir=str(self.base_dir))

    def _save(self, registry: ProjectRegistry) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        registry.last_updated = _now_iso()
        registry.base_dir = str(self.base_dir)
        self.registry_path.write_text(
            json.dumps(registry.model_dump(), indent=2, default=str),
            encoding="utf-8",
        )

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
        total_customers: int,
        total_findings: int,
        finding_counts: dict[str, int],
        risk_score: float,
        status: str = "completed",
    ) -> ProjectEntry | None:
        """Update project metadata after a pipeline run completes."""
        registry = self._load()
        for i, p in enumerate(registry.projects):
            if p.slug == slug:
                p.last_run_at = _now_iso()
                p.last_run_id = run_id
                p.total_runs += 1
                p.total_customers = total_customers
                p.total_findings = total_findings
                p.finding_counts = finding_counts
                p.risk_score = risk_score
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
