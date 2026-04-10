"""Data room health assessment — pre-flight quality check (Issue #149).

Scans a data room directory and produces a health report covering:
- File type distribution and extraction readiness
- Subject folder detection
- Potential issues (empty files, unsupported types, deeply nested structures)
- Overall completeness score (0-100)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# Supported file extensions for extraction (from extraction pipeline).
_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pdf",
        ".docx",
        ".doc",
        ".xlsx",
        ".xls",
        ".csv",
        ".pptx",
        ".ppt",
        ".txt",
        ".md",
        ".rtf",
        ".html",
        ".htm",
        ".eml",
        ".msg",
        ".json",
        ".xml",
    }
)

# Files/dirs to skip during scanning.
_SKIP_NAMES: frozenset[str] = frozenset(
    {
        ".DS_Store",
        "Thumbs.db",
        "__MACOSX",
        ".git",
        ".svn",
        "node_modules",
        "__pycache__",
        "_dd",
    }
)


class DataRoomAssessor:
    """Assess data room quality and completeness."""

    def __init__(self, data_room_path: Path) -> None:
        self.data_room = data_room_path

    def assess(self) -> dict[str, Any]:
        """Run full assessment and return structured report."""
        files = self._discover_files()
        file_types = self._analyze_file_types(files)
        subjects = self._detect_subjects(files)
        issues = self._detect_issues(files, file_types, subjects)
        score = self._compute_score(files, file_types, issues)
        recommendations = self._generate_recommendations(file_types, issues, subjects)

        supported = sum(1 for f in files if f.suffix.lower() in _SUPPORTED_EXTENSIONS)

        return {
            "overall_score": score,
            "total_files": len(files),
            "supported_files": supported,
            "unsupported_files": len(files) - supported,
            "estimated_subjects": len(subjects),
            "file_types": file_types,
            "subject_folders": sorted(subjects),
            "issues": issues,
            "recommendations": recommendations,
        }

    def _discover_files(self) -> list[Path]:
        """Walk the data room and collect all files."""
        files: list[Path] = []
        for item in self.data_room.rglob("*"):
            if any(skip in item.parts for skip in _SKIP_NAMES):
                continue
            if item.is_file():
                files.append(item)
        return files

    def _analyze_file_types(self, files: list[Path]) -> dict[str, dict[str, Any]]:
        """Count files by extension and mark support status."""
        counts: dict[str, int] = {}
        for f in files:
            ext = f.suffix.lower() or "(no extension)"
            counts[ext] = counts.get(ext, 0) + 1

        return {
            ext: {
                "count": count,
                "supported": ext in _SUPPORTED_EXTENSIONS,
            }
            for ext, count in counts.items()
        }

    def _detect_subjects(self, files: list[Path]) -> list[str]:
        """Detect likely subject folders (immediate children of data room)."""
        subject_dirs: set[str] = set()
        for f in files:
            try:
                relative = f.relative_to(self.data_room)
            except ValueError:
                continue
            parts = relative.parts
            if len(parts) >= 2:
                top_dir = parts[0]
                if not top_dir.startswith(".") and top_dir not in _SKIP_NAMES:
                    subject_dirs.add(top_dir)
        return sorted(subject_dirs)

    def _detect_issues(
        self,
        files: list[Path],
        file_types: dict[str, dict[str, Any]],
        subjects: list[str],
    ) -> list[dict[str, str]]:
        """Identify potential problems."""
        issues: list[dict[str, str]] = []

        # Empty files
        empty_count = sum(1 for f in files if f.stat().st_size == 0)
        if empty_count > 0:
            issues.append(
                {
                    "severity": "warning",
                    "message": f"{empty_count} empty file(s) detected — these will produce no analysis results.",
                }
            )

        # Large files (>50MB)
        large = [f for f in files if f.stat().st_size > 50 * 1024 * 1024]
        if large:
            issues.append(
                {
                    "severity": "warning",
                    "message": (
                        f"{len(large)} file(s) exceed 50MB. Large files may be slow to extract "
                        "and could impact agent context windows."
                    ),
                }
            )

        # Unsupported file types
        unsupported = {ext: info for ext, info in file_types.items() if not info.get("supported")}
        if unsupported:
            total_unsupported = sum(info["count"] for info in unsupported.values())
            if total_unsupported > len(files) * 0.2:
                issues.append(
                    {
                        "severity": "warning",
                        "message": (
                            f"{total_unsupported} files ({total_unsupported * 100 // max(len(files), 1)}%) "
                            f"have unsupported extensions: {', '.join(sorted(unsupported.keys()))}. "
                            "These will be skipped during extraction."
                        ),
                    }
                )

        # No PDFs (unusual for a contract data room)
        if ".pdf" not in file_types:
            issues.append(
                {
                    "severity": "warning",
                    "message": "No PDF files found. Most contract data rooms contain PDFs.",
                }
            )

        # Very few files
        if len(files) < 5:
            issues.append(
                {
                    "severity": "critical",
                    "message": f"Only {len(files)} file(s) found. This seems too few for meaningful analysis.",
                }
            )

        # No subject folders detected
        if not subjects:
            issues.append(
                {
                    "severity": "info",
                    "message": (
                        "No subject subfolders detected. Files may be organized differently. "
                        "Entity resolution will attempt to identify subjects from file content."
                    ),
                }
            )

        # Deeply nested structure
        max_depth = 0
        for f in files:
            try:
                depth = len(f.relative_to(self.data_room).parts)
                max_depth = max(max_depth, depth)
            except ValueError:
                continue
        if max_depth > 6:
            issues.append(
                {
                    "severity": "info",
                    "message": (
                        f"Folder structure is {max_depth} levels deep. Very deep nesting may slow file discovery."
                    ),
                }
            )

        return issues

    @staticmethod
    def _compute_score(
        files: list[Path],
        file_types: dict[str, dict[str, Any]],
        issues: list[dict[str, str]],
    ) -> int:
        """Compute overall health score (0-100)."""
        if not files:
            return 0

        score = 100

        # Deduct for unsupported files
        supported = sum(info["count"] for info in file_types.values() if info.get("supported"))
        support_ratio = supported / max(len(files), 1)
        if support_ratio < 1.0:
            score -= int((1.0 - support_ratio) * 30)

        # Deduct for issues
        for issue in issues:
            if issue["severity"] == "critical":
                score -= 25
            elif issue["severity"] == "warning":
                score -= 10

        # Bonus for having PDFs (core contract format)
        if ".pdf" in file_types:
            score = min(score + 5, 100)

        # Bonus for having spreadsheets (reference data)
        if ".xlsx" in file_types or ".xls" in file_types or ".csv" in file_types:
            score = min(score + 5, 100)

        return max(0, min(100, score))

    @staticmethod
    def _generate_recommendations(
        file_types: dict[str, dict[str, Any]],
        issues: list[dict[str, str]],
        subjects: list[str],
    ) -> list[str]:
        """Generate actionable recommendations."""
        recs: list[str] = []

        unsupported = {ext for ext, info in file_types.items() if not info.get("supported")}
        if ".zip" in unsupported or ".rar" in unsupported:
            recs.append("Extract compressed archives (.zip/.rar) before running the pipeline.")

        if ".png" in file_types or ".jpg" in file_types or ".jpeg" in file_types:
            recs.append(
                "Image files detected. Install OCR support (pip install dd-agents[ocr]) "
                "for text extraction from scanned documents."
            )

        if not subjects:
            recs.append(
                "Organize files into subject subfolders (one folder per entity) for best entity resolution results."
            )

        critical_count = sum(1 for i in issues if i["severity"] == "critical")
        if critical_count > 0:
            recs.append("Address critical issues before running the pipeline.")

        if not recs:
            recs.append("Data room looks ready for analysis. Run: dd-agents run deal-config.json")

        return recs
