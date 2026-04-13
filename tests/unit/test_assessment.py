"""Unit tests for the dd_agents.assessment module (Issue #149).

Tests the DataRoomAssessor for data room health checks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dd_agents.assessment import DataRoomAssessor

if TYPE_CHECKING:
    from pathlib import Path


class TestDataRoomAssessor:
    """Tests for DataRoomAssessor."""

    def test_empty_data_room(self, tmp_path: Path) -> None:
        """Empty data room produces score of 0."""
        assessor = DataRoomAssessor(tmp_path)
        report = assessor.assess()
        assert report["overall_score"] == 0
        assert report["total_files"] == 0

    def test_healthy_data_room(self, tmp_path: Path) -> None:
        """Well-structured data room scores high."""
        # Create subject folders with contract files
        for subject in ["acme", "beta_corp", "gamma_llc"]:
            subject_dir = tmp_path / subject
            subject_dir.mkdir()
            (subject_dir / "msa.pdf").write_bytes(b"%PDF-1.4 fake content here " * 100)
            (subject_dir / "sow.docx").write_bytes(b"PK fake docx " * 100)

        # Add reference data
        (tmp_path / "reference_data.xlsx").write_bytes(b"PK fake xlsx " * 100)

        assessor = DataRoomAssessor(tmp_path)
        report = assessor.assess()
        assert report["overall_score"] >= 80
        assert report["total_files"] == 7
        assert report["supported_files"] == 7
        assert report["estimated_subjects"] == 3

    def test_detects_empty_files(self, tmp_path: Path) -> None:
        """Empty files generate a warning."""
        (tmp_path / "empty.pdf").write_text("")
        (tmp_path / "real.pdf").write_bytes(b"%PDF-1.4 content " * 100)
        (tmp_path / "real2.pdf").write_bytes(b"%PDF-1.4 content " * 100)
        (tmp_path / "real3.pdf").write_bytes(b"%PDF-1.4 content " * 100)
        (tmp_path / "real4.pdf").write_bytes(b"%PDF-1.4 content " * 100)

        assessor = DataRoomAssessor(tmp_path)
        report = assessor.assess()
        warning_msgs = [i["message"] for i in report["issues"] if i["severity"] == "warning"]
        assert any("empty file" in m for m in warning_msgs)

    def test_detects_unsupported_types(self, tmp_path: Path) -> None:
        """Many unsupported files generate a warning."""
        for i in range(8):
            (tmp_path / f"image_{i}.psd").write_bytes(b"fake photoshop " * 10)
        (tmp_path / "contract.pdf").write_bytes(b"%PDF " * 10)
        (tmp_path / "contract2.pdf").write_bytes(b"%PDF " * 10)

        assessor = DataRoomAssessor(tmp_path)
        report = assessor.assess()
        assert report["unsupported_files"] == 8
        warning_msgs = [i["message"] for i in report["issues"]]
        assert any("unsupported" in m.lower() for m in warning_msgs)

    def test_few_files_critical_issue(self, tmp_path: Path) -> None:
        """Very few files produce a critical issue."""
        (tmp_path / "one.pdf").write_bytes(b"%PDF " * 10)

        assessor = DataRoomAssessor(tmp_path)
        report = assessor.assess()
        critical = [i for i in report["issues"] if i["severity"] == "critical"]
        assert len(critical) >= 1

    def test_subject_detection(self, tmp_path: Path) -> None:
        """Subject folders are detected from directory structure."""
        for name in ["AlphaCo", "BetaInc", "GammaCorp"]:
            d = tmp_path / name
            d.mkdir()
            (d / "contract.pdf").write_bytes(b"%PDF " * 100)
            (d / "addendum.pdf").write_bytes(b"%PDF " * 100)

        assessor = DataRoomAssessor(tmp_path)
        report = assessor.assess()
        assert report["estimated_subjects"] == 3
        assert set(report["subject_folders"]) == {"AlphaCo", "BetaInc", "GammaCorp"}

    def test_recommendations_for_archives(self, tmp_path: Path) -> None:
        """Compressed archives trigger extraction recommendation."""
        for i in range(6):
            (tmp_path / f"doc_{i}.pdf").write_bytes(b"%PDF " * 100)
        (tmp_path / "data.zip").write_bytes(b"PK " * 100)

        assessor = DataRoomAssessor(tmp_path)
        report = assessor.assess()
        assert any("compressed" in r.lower() or "extract" in r.lower() for r in report["recommendations"])

    def test_recommendations_for_images(self, tmp_path: Path) -> None:
        """Image files trigger OCR recommendation."""
        for i in range(6):
            (tmp_path / f"doc_{i}.pdf").write_bytes(b"%PDF " * 100)
        (tmp_path / "scan.png").write_bytes(b"\x89PNG " * 100)

        assessor = DataRoomAssessor(tmp_path)
        report = assessor.assess()
        assert any("ocr" in r.lower() for r in report["recommendations"])

    def test_no_pdf_warning(self, tmp_path: Path) -> None:
        """Data room without PDFs generates warning."""
        for i in range(6):
            (tmp_path / f"doc_{i}.docx").write_bytes(b"PK " * 100)

        assessor = DataRoomAssessor(tmp_path)
        report = assessor.assess()
        warning_msgs = [i["message"] for i in report["issues"]]
        assert any("pdf" in m.lower() for m in warning_msgs)

    def test_skips_hidden_and_system_dirs(self, tmp_path: Path) -> None:
        """Hidden directories and system folders are excluded."""
        # Create files in hidden/system dirs (should be skipped)
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("git config")
        (tmp_path / "__MACOSX").mkdir()
        (tmp_path / "__MACOSX" / "resource").write_bytes(b"mac data")

        # Real files
        for i in range(6):
            (tmp_path / f"doc_{i}.pdf").write_bytes(b"%PDF " * 100)

        assessor = DataRoomAssessor(tmp_path)
        report = assessor.assess()
        assert report["total_files"] == 6

    def test_score_clamped_to_0_100(self, tmp_path: Path) -> None:
        """Score is always between 0 and 100."""
        assessor = DataRoomAssessor(tmp_path)
        report = assessor.assess()
        assert 0 <= report["overall_score"] <= 100
