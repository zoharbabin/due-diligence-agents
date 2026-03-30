"""Tests for visual grounding coordinate index and related models.

Covers:
    - TextBlock model serialization/deserialization
    - CoordinateIndex add_file and get_blocks CRUD operations
    - CoordinateIndex find_quote — matching a quote substring to blocks
    - Round-trip persistence (save to JSON, load back)
    - BoundingBox model basic validation
    - Citation with optional page_number and bounding_box fields (backward compat)
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from dd_agents.extraction.coordinates import CoordinateIndex, TextBlock
from dd_agents.models.enums import SourceType
from dd_agents.models.finding import BoundingBox, Citation

if TYPE_CHECKING:
    from pathlib import Path


# ======================================================================
# TextBlock serialization
# ======================================================================


class TestTextBlock:
    """Tests for TextBlock model serialization and deserialization."""

    def test_serialize_round_trip(self) -> None:
        """TextBlock should serialize to dict and deserialize back identically."""
        block = TextBlock(page=1, x0=10.0, y0=20.0, x1=200.0, y1=40.0, text="Section A")
        data = block.model_dump()
        restored = TextBlock.model_validate(data)
        assert restored == block

    def test_serialize_to_json_string(self) -> None:
        """model_dump_json should produce valid JSON with all fields."""
        block = TextBlock(page=3, x0=0.0, y0=0.0, x1=100.5, y1=50.25, text="Sample text")
        raw = block.model_dump_json()
        parsed = json.loads(raw)
        assert parsed["page"] == 3
        assert parsed["x1"] == 100.5
        assert parsed["text"] == "Sample text"

    def test_default_empty_text(self) -> None:
        """Text field should default to empty string when omitted."""
        block = TextBlock(page=1, x0=0, y0=0, x1=100, y1=50)
        assert block.text == ""


# ======================================================================
# CoordinateIndex CRUD
# ======================================================================


class TestCoordinateIndexCRUD:
    """Tests for CoordinateIndex add_file and get_blocks operations."""

    def test_add_and_get_blocks(self) -> None:
        """Adding blocks for a file should be retrievable via get_blocks."""
        idx = CoordinateIndex()
        blocks = [
            TextBlock(page=1, x0=0, y0=0, x1=100, y1=20, text="First block"),
            TextBlock(page=1, x0=0, y0=25, x1=100, y1=45, text="Second block"),
        ]
        idx.add_file("docs/contract_a.pdf", blocks)
        result = idx.get_blocks("docs/contract_a.pdf")
        assert len(result) == 2
        assert result[0].text == "First block"
        assert result[1].text == "Second block"

    def test_get_blocks_unknown_file_returns_empty(self) -> None:
        """Querying an unindexed file should return an empty list."""
        idx = CoordinateIndex()
        assert idx.get_blocks("nonexistent.pdf") == []

    def test_files_property_sorted(self) -> None:
        """The files property should return sorted file paths."""
        idx = CoordinateIndex()
        idx.add_file("z_file.pdf", [])
        idx.add_file("a_file.pdf", [])
        idx.add_file("m_file.pdf", [])
        assert idx.files == ["a_file.pdf", "m_file.pdf", "z_file.pdf"]

    def test_add_file_overwrites_previous(self) -> None:
        """Adding blocks for an already-indexed file replaces the old blocks."""
        idx = CoordinateIndex()
        idx.add_file("doc.pdf", [TextBlock(page=1, x0=0, y0=0, x1=50, y1=10, text="Old")])
        idx.add_file("doc.pdf", [TextBlock(page=2, x0=0, y0=0, x1=50, y1=10, text="New")])
        result = idx.get_blocks("doc.pdf")
        assert len(result) == 1
        assert result[0].text == "New"
        assert result[0].page == 2

    def test_get_blocks_returns_copy(self) -> None:
        """get_blocks should return a copy, not a reference to the internal list."""
        idx = CoordinateIndex()
        idx.add_file("doc.pdf", [TextBlock(page=1, x0=0, y0=0, x1=50, y1=10, text="A")])
        blocks = idx.get_blocks("doc.pdf")
        blocks.append(TextBlock(page=2, x0=0, y0=0, x1=50, y1=10, text="B"))
        assert len(idx.get_blocks("doc.pdf")) == 1  # internal state unchanged


# ======================================================================
# CoordinateIndex find_quote
# ======================================================================


class TestCoordinateIndexFindQuote:
    """Tests for CoordinateIndex.find_quote substring matching."""

    def _build_index(self) -> CoordinateIndex:
        idx = CoordinateIndex()
        idx.add_file(
            "agreement.pdf",
            [
                TextBlock(page=1, x0=10, y0=100, x1=500, y1=120, text="This Agreement is entered into as of January 1"),
                TextBlock(page=1, x0=10, y0=130, x1=500, y1=150, text="CONFIDENTIALITY. The Parties agree to maintain"),
                TextBlock(page=2, x0=10, y0=50, x1=500, y1=70, text="Termination clause: either party may terminate"),
            ],
        )
        return idx

    def test_find_exact_substring(self) -> None:
        """Should find a block when the quote is an exact substring of block text."""
        idx = self._build_index()
        result = idx.find_quote("agreement.pdf", "entered into as of")
        assert result is not None
        assert result.page == 1
        assert result.y0 == 100

    def test_find_case_insensitive(self) -> None:
        """Quote matching should be case-insensitive."""
        idx = self._build_index()
        result = idx.find_quote("agreement.pdf", "confidentiality")
        assert result is not None
        assert "CONFIDENTIALITY" in result.text

    def test_find_returns_first_match(self) -> None:
        """When multiple blocks match, find_quote returns the first one."""
        idx = CoordinateIndex()
        idx.add_file(
            "doc.pdf",
            [
                TextBlock(page=1, x0=0, y0=0, x1=100, y1=20, text="The party of the first part"),
                TextBlock(page=2, x0=0, y0=0, x1=100, y1=20, text="The party of the second part"),
            ],
        )
        result = idx.find_quote("doc.pdf", "The party")
        assert result is not None
        assert result.page == 1

    def test_find_no_match_returns_none(self) -> None:
        """Should return None when no block contains the quote."""
        idx = self._build_index()
        assert idx.find_quote("agreement.pdf", "nonexistent phrase") is None

    def test_find_unknown_file_returns_none(self) -> None:
        """Should return None for an unindexed file path."""
        idx = self._build_index()
        assert idx.find_quote("other.pdf", "Agreement") is None

    def test_find_empty_quote_returns_none(self) -> None:
        """An empty quote string should return None."""
        idx = self._build_index()
        assert idx.find_quote("agreement.pdf", "") is None

    def test_find_whitespace_only_quote_returns_none(self) -> None:
        """A whitespace-only quote should return None, not match all blocks."""
        idx = self._build_index()
        assert idx.find_quote("agreement.pdf", "   ") is None
        assert idx.find_quote("agreement.pdf", "\t\n") is None


# ======================================================================
# Round-trip persistence
# ======================================================================


class TestCoordinateIndexPersistence:
    """Tests for save/load round-trip of CoordinateIndex."""

    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        """Saving and loading should produce an equivalent index."""
        idx = CoordinateIndex()
        idx.add_file(
            "contract.pdf",
            [
                TextBlock(page=1, x0=10.5, y0=20.3, x1=300.0, y1=40.7, text="Clause 1.1"),
                TextBlock(page=2, x0=10.5, y0=50.0, x1=300.0, y1=70.0, text="Clause 2.1"),
            ],
        )
        idx.add_file(
            "amendment.pdf",
            [TextBlock(page=1, x0=0, y0=0, x1=200, y1=30, text="Amendment to Clause 1.1")],
        )

        save_path = tmp_path / "coords" / "index.json"
        idx.save(save_path)

        loaded = CoordinateIndex.load(save_path)
        assert loaded.files == idx.files
        for fp in idx.files:
            orig_blocks = idx.get_blocks(fp)
            loaded_blocks = loaded.get_blocks(fp)
            assert len(loaded_blocks) == len(orig_blocks)
            for orig, loaded_b in zip(orig_blocks, loaded_blocks, strict=True):
                assert orig == loaded_b

    def test_save_creates_parent_directories(self, tmp_path: Path) -> None:
        """save() should create parent directories if they do not exist."""
        idx = CoordinateIndex()
        idx.add_file("f.pdf", [TextBlock(page=1, x0=0, y0=0, x1=1, y1=1, text="x")])
        deep_path = tmp_path / "a" / "b" / "c" / "index.json"
        idx.save(deep_path)
        assert deep_path.exists()

    def test_load_nonexistent_returns_empty(self, tmp_path: Path) -> None:
        """Loading from a nonexistent file should return an empty index."""
        loaded = CoordinateIndex.load(tmp_path / "missing.json")
        assert loaded.files == []

    def test_load_corrupt_json_returns_empty(self, tmp_path: Path) -> None:
        """Loading from a corrupt JSON file should return an empty index (not raise)."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("NOT VALID JSON {{{", encoding="utf-8")
        loaded = CoordinateIndex.load(bad_file)
        assert loaded.files == []

    def test_saved_json_structure(self, tmp_path: Path) -> None:
        """Verify the on-disk JSON has the expected structure."""
        idx = CoordinateIndex()
        idx.add_file("doc.pdf", [TextBlock(page=3, x0=1, y0=2, x1=3, y1=4, text="Hello")])
        path = tmp_path / "index.json"
        idx.save(path)

        raw = json.loads(path.read_text(encoding="utf-8"))
        assert "doc.pdf" in raw
        assert len(raw["doc.pdf"]) == 1
        block_data = raw["doc.pdf"][0]
        assert block_data["page"] == 3
        assert block_data["text"] == "Hello"
        assert block_data["x0"] == 1
        assert block_data["y1"] == 4


# ======================================================================
# BoundingBox model
# ======================================================================


class TestBoundingBox:
    """Tests for BoundingBox model validation."""

    def test_valid_bounding_box(self) -> None:
        """A well-formed BoundingBox should construct without errors."""
        bbox = BoundingBox(x0=10.0, y0=20.0, x1=200.0, y1=50.0, page=1)
        assert bbox.page == 1
        assert bbox.x0 == 10.0
        assert bbox.x1 == 200.0

    def test_bounding_box_serialization(self) -> None:
        """BoundingBox should round-trip through dict and back."""
        bbox = BoundingBox(x0=0.5, y0=1.5, x1=100.5, y1=200.5, page=5)
        data = bbox.model_dump()
        restored = BoundingBox.model_validate(data)
        assert restored == bbox

    def test_bounding_box_requires_page(self) -> None:
        """BoundingBox should fail validation when page is missing."""
        with pytest.raises(Exception):  # noqa: B017 — Pydantic ValidationError
            BoundingBox(x0=0, y0=0, x1=1, y1=1)  # type: ignore[call-arg]


# ======================================================================
# Citation backward compatibility (optional page_number and bounding_box)
# ======================================================================


class TestCitationVisualGrounding:
    """Tests for Citation optional page_number and bounding_box fields."""

    def test_citation_defaults_none_for_grounding_fields(self) -> None:
        """page_number and bounding_box should default to None for backward compat."""
        cit = Citation(
            source_type=SourceType.FILE,
            source_path="docs/agreement.pdf",
            location="Section 1",
            exact_quote="Sample quote",
        )
        assert cit.page_number is None
        assert cit.bounding_box is None

    def test_citation_with_page_number(self) -> None:
        """Citation should accept an explicit page_number."""
        cit = Citation(
            source_type=SourceType.FILE,
            source_path="docs/agreement.pdf",
            location="Section 2",
            exact_quote="Another quote",
            page_number=7,
        )
        assert cit.page_number == 7

    def test_citation_with_bounding_box(self) -> None:
        """Citation should accept a BoundingBox for visual grounding."""
        bbox = BoundingBox(x0=10, y0=20, x1=300, y1=50, page=3)
        cit = Citation(
            source_type=SourceType.FILE,
            source_path="docs/amendment.pdf",
            location="Clause 4",
            exact_quote="Termination clause text",
            page_number=3,
            bounding_box=bbox,
        )
        assert cit.bounding_box is not None
        assert cit.bounding_box.page == 3
        assert cit.bounding_box.x1 == 300

    def test_citation_serialization_excludes_none_grounding(self) -> None:
        """Serializing with exclude_none should omit absent grounding fields."""
        cit = Citation(
            source_type=SourceType.FILE,
            source_path="docs/file.pdf",
            exact_quote="text",
        )
        data = cit.model_dump(exclude_none=True)
        assert "page_number" not in data
        assert "bounding_box" not in data

    def test_citation_serialization_includes_present_grounding(self) -> None:
        """Serializing should include grounding fields when they are set."""
        bbox = BoundingBox(x0=0, y0=0, x1=100, y1=50, page=1)
        cit = Citation(
            source_type=SourceType.FILE,
            source_path="docs/file.pdf",
            exact_quote="text",
            page_number=1,
            bounding_box=bbox,
        )
        data = cit.model_dump()
        assert data["page_number"] == 1
        assert data["bounding_box"]["page"] == 1
        assert data["bounding_box"]["x1"] == 100
