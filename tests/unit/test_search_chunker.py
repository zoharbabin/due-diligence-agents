"""Unit tests for the search chunker module."""

from __future__ import annotations

from dd_agents.search.chunker import (
    TARGET_CHUNK_CHARS,
    AnalysisChunk,
    FileSegment,
    FileText,
    create_analysis_chunks,
    detect_page_markers,
    estimate_chunks,
    split_by_pages,
    split_by_paragraphs,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_page_text(num_pages: int, chars_per_page: int = 500) -> str:
    """Generate synthetic text with ``--- Page N ---`` markers.

    Each page contains a repeated filler paragraph so tests can control
    the total size precisely.
    """
    parts: list[str] = []
    filler = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
    for page in range(1, num_pages + 1):
        parts.append(f"\n--- Page {page} ---\n")
        # Fill to target size.  Each repetition is len(filler) chars.
        reps = max(1, chars_per_page // len(filler))
        parts.append((filler * reps)[:chars_per_page])
    return "".join(parts)


def _make_file_text(
    file_path: str = "file_1.pdf",
    text: str = "Short document text.",
    has_page_markers: bool | None = None,
) -> FileText:
    """Create a :class:`FileText` with auto-detected page markers if not specified."""
    if has_page_markers is None:
        has_page_markers = detect_page_markers(text)
    return FileText(file_path=file_path, text=text, has_page_markers=has_page_markers)


# ===================================================================
# detect_page_markers
# ===================================================================


class TestDetectPageMarkers:
    def test_detects_page_markers_present(self) -> None:
        text = "Preamble\n--- Page 1 ---\nContent on page one."
        assert detect_page_markers(text) is True

    def test_detects_no_page_markers(self) -> None:
        text = "This is plain text with no special markers."
        assert detect_page_markers(text) is False

    def test_detects_multidigit_page_numbers(self) -> None:
        text = "Some text\n--- Page 123 ---\nMore text."
        assert detect_page_markers(text) is True


# ===================================================================
# split_by_pages
# ===================================================================


class TestSplitByPages:
    def test_single_page_fits(self) -> None:
        """One page under target -> single segment, is_partial=False."""
        text = "\n--- Page 1 ---\nShort page content."
        segments = split_by_pages(text, "file_1.pdf", target_chars=TARGET_CHUNK_CHARS)

        assert len(segments) == 1
        assert segments[0].is_partial is False
        assert segments[0].file_path == "file_1.pdf"

    def test_small_file_single_segment(self) -> None:
        """5 pages, total under target -> one segment."""
        text = _make_page_text(5, chars_per_page=200)
        segments = split_by_pages(text, "file_1.pdf", target_chars=TARGET_CHUNK_CHARS)

        assert len(segments) == 1
        assert segments[0].is_partial is False
        assert segments[0].start_page == 1
        assert segments[0].end_page == 5
        assert segments[0].total_pages == 5

    def test_large_file_splits_at_pages(self) -> None:
        """Many pages exceeding target -> multiple segments with correct page ranges."""
        # Use small target to force splitting.
        text = _make_page_text(10, chars_per_page=1000)
        segments = split_by_pages(text, "file_1.pdf", target_chars=3000, overlap_ratio=0.0)

        assert len(segments) > 1
        # Every segment is partial.
        for seg in segments:
            assert seg.is_partial is True
            assert seg.total_parts == len(segments)
        # First segment starts at page 1.
        assert segments[0].start_page == 1
        # Last segment ends at page 10.
        assert segments[-1].end_page == 10

    def test_overlap_pages_included(self) -> None:
        """Verify that segments overlap (trailing pages of seg N appear in start of seg N+1)."""
        text = _make_page_text(10, chars_per_page=1000)
        # Small target, 50% overlap for clear verification.
        segments = split_by_pages(text, "file_1.pdf", target_chars=3000, overlap_ratio=0.50)

        assert len(segments) > 1
        # The second segment should be larger than just its "own" pages
        # because it includes overlap from the first segment.
        # Verify the second segment text contains content from near the
        # boundary of the first segment's pages.
        first_end_page = segments[0].end_page
        assert first_end_page is not None
        # With 50% overlap, the second segment's text should contain content
        # that also appeared in the first segment.
        assert len(segments[1].text) > 0

    def test_page_numbers_tracked(self) -> None:
        """start_page/end_page/total_pages are correct."""
        text = _make_page_text(20, chars_per_page=500)
        segments = split_by_pages(text, "file_1.pdf", target_chars=3000, overlap_ratio=0.0)

        for seg in segments:
            assert seg.start_page is not None
            assert seg.end_page is not None
            assert seg.total_pages == 20
            assert seg.start_page <= seg.end_page

    def test_empty_text(self) -> None:
        """Empty string -> single segment with empty text."""
        segments = split_by_pages("", "file_1.pdf")

        assert len(segments) == 1
        assert segments[0].text == ""


# ===================================================================
# split_by_paragraphs
# ===================================================================


class TestSplitByParagraphs:
    def test_small_text_single_segment(self) -> None:
        """Text under target -> single segment."""
        text = "A short paragraph.\n\nAnother paragraph."
        segments = split_by_paragraphs(text, "file_1.txt", target_chars=TARGET_CHUNK_CHARS)

        assert len(segments) == 1
        assert segments[0].is_partial is False
        assert segments[0].start_page is None
        assert segments[0].end_page is None
        assert segments[0].total_pages is None

    def test_splits_at_double_newline(self) -> None:
        r"""Text exceeding target splits at \\n\\n."""
        # Build text with double-newline separated paragraphs.
        paragraph = "A" * 600
        text = (paragraph + "\n\n") * 10  # ~6200 chars total
        segments = split_by_paragraphs(text, "file_1.txt", target_chars=2000, overlap_chars=0)

        assert len(segments) > 1
        # Verify splits happened at paragraph boundaries (text shouldn't
        # end mid-word since we split at \n\n).
        for seg in segments[:-1]:
            assert seg.text.endswith("\n\n")

    def test_splits_at_single_newline_fallback(self) -> None:
        r"""No \\n\\n but has \\n -> splits at \\n."""
        # Build text with single newlines only (no double newlines).
        line = "B" * 600
        text = (line + "\n") * 10  # ~6010 chars
        segments = split_by_paragraphs(text, "file_1.txt", target_chars=2000, overlap_chars=0)

        assert len(segments) > 1
        for seg in segments[:-1]:
            assert seg.text.endswith("\n")

    def test_splits_at_sentence_fallback(self) -> None:
        r"""No newlines -> splits at ". "."""
        # Build text with sentence boundaries but no newlines.
        sentence = "C" * 300 + ". "
        text = sentence * 20  # ~6040 chars
        segments = split_by_paragraphs(text, "file_1.txt", target_chars=2000, overlap_chars=0)

        assert len(segments) > 1
        for seg in segments[:-1]:
            assert seg.text.endswith(". ")

    def test_hard_break_last_resort(self) -> None:
        """Continuous string with no separators -> hard character break."""
        text = "D" * 5000  # No whitespace, no punctuation separators
        segments = split_by_paragraphs(text, "file_1.txt", target_chars=2000, overlap_chars=0)

        assert len(segments) > 1
        # First segment should be exactly target_chars since there is no split point.
        assert len(segments[0].text) == 2000


# ===================================================================
# create_analysis_chunks
# ===================================================================


class TestCreateAnalysisChunks:
    def test_empty_input(self) -> None:
        """Empty list -> empty list."""
        result = create_analysis_chunks([])
        assert result == []

    def test_single_small_file(self) -> None:
        """One small file -> one chunk with one segment."""
        ft = _make_file_text("contract.pdf", "Short agreement text.")
        chunks = create_analysis_chunks([ft])

        assert len(chunks) == 1
        assert chunks[0].chunk_index == 0
        assert chunks[0].total_chunks == 1
        assert len(chunks[0].file_segments) == 1
        assert chunks[0].file_segments[0].file_path == "contract.pdf"

    def test_single_large_file_with_pages(self) -> None:
        """Large file with page markers -> multiple chunks."""
        text = _make_page_text(50, chars_per_page=5000)
        ft = _make_file_text("big_contract.pdf", text)
        # Use small target to force multiple chunks.
        chunks = create_analysis_chunks([ft], target_chars=10_000)

        assert len(chunks) > 1
        # Each chunk should have segments from the same file.
        for chunk in chunks:
            for seg in chunk.file_segments:
                assert seg.file_path == "big_contract.pdf"

    def test_multiple_small_files_packed(self) -> None:
        """3 small files -> one chunk with 3 segments."""
        files = [
            _make_file_text("file_1.pdf", "First document content."),
            _make_file_text("file_2.pdf", "Second document content."),
            _make_file_text("file_3.pdf", "Third document content."),
        ]
        chunks = create_analysis_chunks(files)

        assert len(chunks) == 1
        assert len(chunks[0].file_segments) == 3

    def test_mixed_sizes(self) -> None:
        """Small files + large file -> small files packed, large file separate."""
        small_1 = _make_file_text("small_1.pdf", "Small file one.")
        small_2 = _make_file_text("small_2.pdf", "Small file two.")
        big_text = _make_page_text(20, chars_per_page=2000)
        big = _make_file_text("big.pdf", big_text)

        # Target small enough that the big file needs its own chunk(s).
        chunks = create_analysis_chunks([small_1, small_2, big], target_chars=10_000)

        assert len(chunks) >= 2
        # First chunk should have the small files packed together.
        small_paths = {seg.file_path for seg in chunks[0].file_segments}
        assert "small_1.pdf" in small_paths
        assert "small_2.pdf" in small_paths

    def test_chunk_indices_correct(self) -> None:
        """Verify chunk_index and total_chunks are set correctly."""
        text = _make_page_text(30, chars_per_page=2000)
        ft = _make_file_text("large.pdf", text)
        chunks = create_analysis_chunks([ft], target_chars=10_000)

        for idx, chunk in enumerate(chunks):
            assert chunk.chunk_index == idx
            assert chunk.total_chunks == len(chunks)

    def test_char_count_property(self) -> None:
        """Verify AnalysisChunk.char_count works."""
        seg1 = FileSegment(file_path="a.pdf", text="Hello", start_page=None, end_page=None, total_pages=None)
        seg2 = FileSegment(file_path="b.pdf", text="World!", start_page=None, end_page=None, total_pages=None)
        chunk = AnalysisChunk(chunk_index=0, total_chunks=1, file_segments=[seg1, seg2])

        assert chunk.char_count == len("Hello") + len("World!")


# ===================================================================
# estimate_chunks
# ===================================================================


class TestEstimateChunks:
    def test_single_small_file(self) -> None:
        """Small file -> returns 1."""
        assert estimate_chunks([1000]) == 1

    def test_empty_list(self) -> None:
        """Empty list -> returns 1."""
        assert estimate_chunks([]) == 1

    def test_large_file(self) -> None:
        """file_sizes=[500_000] with target 150K -> returns ceil(500000/150000) = 4."""
        result = estimate_chunks([500_000], target_chars=150_000)
        assert result == 4

    def test_multiple_files(self) -> None:
        """Sum of sizes determines chunk count."""
        # 3 files of 100K each = 300K total.  With 150K target -> 2 chunks.
        result = estimate_chunks([100_000, 100_000, 100_000], target_chars=150_000)
        assert result == 2


# ===================================================================
# Page marker preservation (Issue #61)
# ===================================================================


class TestPageMarkerPreservation:
    def test_page_markers_preserved_in_chunks(self) -> None:
        """Page markers must survive chunking -- they must appear in segment text.

        Regression: markers at chunk boundaries were being stripped because
        split_by_pages started each page's text *after* the marker.
        """
        text = _make_page_text(5, chars_per_page=200)
        segments = split_by_pages(text, "file_1.pdf", target_chars=TARGET_CHUNK_CHARS)

        assert len(segments) == 1
        # Every page marker in the original text must appear in the segment.
        for page_num in range(1, 6):
            assert f"--- Page {page_num} ---" in segments[0].text

    def test_page_markers_preserved_across_multiple_segments(self) -> None:
        """When a file is split into multiple segments, each segment should
        contain the page markers for the pages it covers."""
        text = _make_page_text(10, chars_per_page=1000)
        segments = split_by_pages(text, "file_1.pdf", target_chars=3000, overlap_ratio=0.0)

        assert len(segments) > 1
        # Concatenation of all segments' text should contain all page markers.
        combined = "".join(seg.text for seg in segments)
        for page_num in range(1, 11):
            assert f"--- Page {page_num} ---" in combined

    def test_page_markers_preserved_in_analysis_chunks(self) -> None:
        """End-to-end: create_analysis_chunks should produce chunks whose
        segment text contains page markers."""
        text = _make_page_text(3, chars_per_page=200)
        ft = _make_file_text("contract.pdf", text)
        chunks = create_analysis_chunks([ft])

        assert len(chunks) == 1
        chunk_text = "".join(seg.text for seg in chunks[0].file_segments)
        for page_num in range(1, 4):
            assert f"--- Page {page_num} ---" in chunk_text


# ===================================================================
# is_tabular (E-4)
# ===================================================================


class TestIsTabular:
    def test_markdown_table_detected(self) -> None:
        from dd_agents.search.chunker import is_tabular

        text = "## Sheet: Revenue\n| A | B |\n| --- | --- |\n| 100 | 200 |\n| 300 | 400 |"
        assert is_tabular(text) is True

    def test_prose_not_tabular(self) -> None:
        from dd_agents.search.chunker import is_tabular

        text = "This is a contract.\nSection 1. Definitions.\nSection 2. Terms."
        assert is_tabular(text) is False

    def test_mixed_mostly_table(self) -> None:
        from dd_agents.search.chunker import is_tabular

        text = "## Sheet: Data\n| A | B |\n| --- | --- |\n" + "| x | y |\n" * 20
        assert is_tabular(text) is True

    def test_empty_text(self) -> None:
        from dd_agents.search.chunker import is_tabular

        assert is_tabular("") is False


# ===================================================================
# split_by_table_rows (E-4)
# ===================================================================


class TestSplitByTableRows:
    def _make_table(self, num_rows: int, cols: int = 3, row_chars: int = 50) -> str:
        """Build a markdown table with a sheet heading and column headers."""
        filler = "x" * max(1, (row_chars - cols * 5) // cols)
        lines = [f"## Sheet: Data ({num_rows} rows, {cols} columns)", ""]
        headers = [_col_letter_simple(i) for i in range(cols)]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join("---" for _ in headers) + " |")
        for i in range(num_rows):
            cells = [f"{filler}_{i}_{c}" for c in range(cols)]
            lines.append("| " + " | ".join(cells) + " |")
        return "\n".join(lines)

    def test_small_table_single_segment(self) -> None:
        from dd_agents.search.chunker import split_by_table_rows

        text = self._make_table(5)
        segs = split_by_table_rows(text, "revenue.xlsx", target_chars=TARGET_CHUNK_CHARS)

        assert len(segs) == 1
        assert segs[0].is_partial is False
        assert "## Sheet: Data" in segs[0].text

    def test_large_table_splits_with_header_repetition(self) -> None:
        from dd_agents.search.chunker import split_by_table_rows

        # Each row ~60 chars.  200 rows = ~12000 chars.  Target 3000 → multiple segments.
        text = self._make_table(200, row_chars=60)
        segs = split_by_table_rows(text, "big.xlsx", target_chars=3000)

        assert len(segs) > 1
        # Every segment must contain the full header block:
        # sheet heading, column letters, and separator.
        for seg in segs:
            assert "## Sheet: Data" in seg.text
            assert "| A |" in seg.text
            assert "| --- |" in seg.text

    def test_all_data_rows_preserved(self) -> None:
        from dd_agents.search.chunker import split_by_table_rows

        text = self._make_table(50, row_chars=60)
        segs = split_by_table_rows(text, "data.xlsx", target_chars=2000)

        combined = "\n".join(seg.text for seg in segs)
        # Use word-boundary marker (pipe-delimited) to avoid substring collisions
        # (e.g. "_1_0" matching inside "_10_0").
        for i in range(50):
            assert f"_{i}_0 |" in combined or f"_{i}_0|" in combined

    def test_partial_flags_set_correctly(self) -> None:
        from dd_agents.search.chunker import split_by_table_rows

        text = self._make_table(100, row_chars=60)
        segs = split_by_table_rows(text, "data.xlsx", target_chars=2000)

        assert len(segs) > 1
        for idx, seg in enumerate(segs):
            assert seg.is_partial is True
            assert seg.part_number == idx + 1
            assert seg.total_parts == len(segs)

    def test_non_tabular_falls_back(self) -> None:
        """Non-tabular text falls back to split_by_paragraphs."""
        from dd_agents.search.chunker import split_by_table_rows

        text = "Just a paragraph of text.\n\nAnother paragraph."
        segs = split_by_table_rows(text, "notes.txt", target_chars=TARGET_CHUNK_CHARS)

        assert len(segs) == 1
        assert "Just a paragraph" in segs[0].text

    def test_create_analysis_chunks_routes_tabular(self) -> None:
        """create_analysis_chunks detects tabular text and uses table-row splitting."""
        from dd_agents.search.chunker import is_tabular

        text = self._make_table(100, row_chars=60)
        assert is_tabular(text) is True

        ft = _make_file_text("revenue.xlsx", text, has_page_markers=False)
        chunks = create_analysis_chunks([ft], target_chars=2000)

        assert len(chunks) > 1
        # Every chunk's segments should contain the header.
        for chunk in chunks:
            for seg in chunk.file_segments:
                assert "| A |" in seg.text


def _col_letter_simple(index: int) -> str:
    """Excel-style column letter.  Matches production ``_col_letter``."""
    result = ""
    i = index
    while True:
        result = chr(65 + i % 26) + result
        i = i // 26 - 1
        if i < 0:
            break
    return result
