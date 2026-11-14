"""Tests for dd_agents.tools._text_lookup.resolve_text_path."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from dd_agents.tools._text_lookup import resolve_text_path


@pytest.fixture()
def text_dir(tmp_path: Path) -> Path:
    """Create a temporary text directory."""
    td = tmp_path / "text"
    td.mkdir()
    return td


@pytest.fixture()
def data_room(tmp_path: Path) -> Path:
    """Create a temporary data room directory."""
    dr = tmp_path / "data_room"
    dr.mkdir()
    return dr


class TestResolveTextPath:
    """Tests for the multi-variant text file resolution."""

    def test_direct_match_relative_path(self, text_dir: Path) -> None:
        """Finds text when source_path matches extraction path form."""
        # _safe_text_name("contracts/sow.pdf") -> "contracts__sow.pdf.md"
        text_file = text_dir / "contracts__sow.pdf.md"
        text_file.write_text("some content")

        result = resolve_text_path("contracts/sow.pdf", text_dir)
        assert result == text_file

    def test_absolute_path_fallback(self, text_dir: Path, data_room: Path) -> None:
        """Finds text via absolute path when relative path doesn't match."""
        abs_path = str((data_room / "contracts" / "sow.pdf").resolve())
        safe_name = abs_path.removeprefix("./").replace("/", "__") + ".md"

        # If the name is short enough, no hash truncation
        if len(safe_name.encode("utf-8")) <= 200:
            text_file = text_dir / safe_name
            text_file.write_text("content from absolute path")

            result = resolve_text_path("contracts/sow.pdf", text_dir, data_room_path=data_room)
            assert result == text_file
        else:
            # Long path triggers hash truncation
            digest = hashlib.sha256(abs_path.encode()).hexdigest()[:12]
            name_part = (
                abs_path.replace("/", "__").encode("utf-8")[: 200 - len(digest) - 4].decode("utf-8", errors="ignore")
            )
            truncated_name = f"{name_part}_{digest}.md"
            text_file = text_dir / truncated_name
            text_file.write_text("content from long absolute path")

            result = resolve_text_path("contracts/sow.pdf", text_dir, data_room_path=data_room)
            assert result == text_file

    def test_dot_slash_prefix_stripped(self, text_dir: Path) -> None:
        """Finds text when source has ./ prefix but stored without."""
        text_file = text_dir / "contracts__sow.pdf.md"
        text_file.write_text("content")

        result = resolve_text_path("./contracts/sow.pdf", text_dir)
        assert result == text_file

    def test_glob_fallback_on_stem(self, text_dir: Path) -> None:
        """Falls back to glob matching on filename stem."""
        # Simulate a file stored with hash suffix due to long absolute path
        text_file = text_dir / "some_prefix__contracts__sow_abc123def456.md"
        text_file.write_text("globbed content")

        result = resolve_text_path("contracts/sow.pdf", text_dir)
        # Glob should find it by stem "sow"
        assert result is not None
        assert "sow" in result.name

    def test_glob_fallback_with_special_chars_in_stem(self, text_dir: Path) -> None:
        """Glob metacharacters in the file name are matched literally."""
        (text_dir / "x__report[v2]_abc123.md").write_text("bracket content")
        (text_dir / "x__reportv_abc123.md").write_text("wrong file")

        result = resolve_text_path("contracts/report[v2].pdf", text_dir)
        assert result is not None
        assert result.name == "x__report[v2]_abc123.md"

    def test_returns_none_when_not_found(self, text_dir: Path) -> None:
        """Returns None when no matching text file exists."""
        result = resolve_text_path("nonexistent/file.pdf", text_dir)
        assert result is None

    def test_returns_none_when_text_dir_missing(self, tmp_path: Path) -> None:
        """Returns None when text_dir doesn't exist."""
        result = resolve_text_path("file.pdf", tmp_path / "no_such_dir")
        assert result is None

    def test_no_data_room_skips_absolute_fallback(self, text_dir: Path) -> None:
        """Without data_room_path, absolute path fallback is skipped."""
        result = resolve_text_path("contracts/sow.pdf", text_dir)
        assert result is None

    def test_long_onedrive_path(self, text_dir: Path, tmp_path: Path) -> None:
        """Simulates the OneDrive long-path scenario that caused the original bug."""
        # Build a long data room path similar to OneDrive
        long_segments = "Library/CloudStorage/OneDrive-Corp/MandA 2025/Outbound/Targets/BlueRush"
        data_room = tmp_path / long_segments
        data_room.mkdir(parents=True)

        # The file as extracted by the pipeline (absolute path)
        abs_path = str((data_room / "contracts" / "MSA.pdf").resolve())
        from dd_agents.extraction.pipeline import ExtractionPipeline

        abs_safe_name = ExtractionPipeline._safe_text_name(abs_path)
        text_file = text_dir / abs_safe_name
        text_file.write_text("extracted text from long path")

        # The relative path the agent would use
        rel_safe_name = ExtractionPipeline._safe_text_name("contracts/MSA.pdf")

        # Verify the names are different (the bug)
        assert abs_safe_name != rel_safe_name, "Names should differ for this test to be meaningful"

        # resolve_text_path should find it via the absolute fallback
        result = resolve_text_path("contracts/MSA.pdf", text_dir, data_room_path=data_room)
        assert result == text_file

    def test_prefers_direct_match_over_fallbacks(self, text_dir: Path, data_room: Path) -> None:
        """Direct match is preferred when both direct and absolute would work."""
        direct_file = text_dir / "contracts__sow.pdf.md"
        direct_file.write_text("direct match")

        result = resolve_text_path("contracts/sow.pdf", text_dir, data_room_path=data_room)
        assert result == direct_file
