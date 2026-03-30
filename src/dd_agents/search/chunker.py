"""Page-aware chunking of extracted text files for the search analyzer.

Pure logic module -- receives text and returns chunks.  No file I/O.

Implements the Addleshaw Goddard RAG Report (2024) recommendation of
splitting oversized context at natural document boundaries (page breaks,
paragraph breaks) with configurable overlap so the LLM never loses
cross-boundary context.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PAGE_MARKER_RE = re.compile(r"\n--- Page (\d+) ---\n")
TARGET_CHUNK_CHARS = 150_000  # ~37-50K tokens -- well within 200K window
MAX_CHUNK_CHARS = 400_000  # Hard ceiling
OVERLAP_RATIO = 0.15  # 15% overlap (AG report optimal)
MAX_OVERLAP_CHARS = 60_000  # Cap overlap

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FileText:
    """Immutable container for a single file's extracted text.

    Parameters
    ----------
    file_path:
        Original file path (for provenance tracking).
    text:
        Extracted text content.
    has_page_markers:
        Auto-detected via :data:`PAGE_MARKER_RE`.
    """

    file_path: str
    text: str
    has_page_markers: bool  # Auto-detected via PAGE_MARKER_RE


@dataclass
class FileSegment:
    """A contiguous slice of a file's text, optionally with page metadata.

    When a file is too large for a single analysis chunk it is split into
    multiple segments.  Each segment records which pages it covers so the
    downstream prompt can tell the LLM "you are reading pages 15-30 of 80".
    """

    file_path: str
    text: str
    start_page: int | None
    end_page: int | None
    total_pages: int | None
    is_partial: bool = False
    part_number: int = 1
    total_parts: int = 1


@dataclass
class AnalysisChunk:
    """A group of :class:`FileSegment` objects that fit within one LLM call.

    After bin-packing, :attr:`chunk_index` and :attr:`total_chunks` are set
    so the orchestrator can build progress messages like "chunk 2/5".
    """

    chunk_index: int
    total_chunks: int
    file_segments: list[FileSegment] = field(default_factory=list)

    @property
    def char_count(self) -> int:
        """Total character count across all segments in this chunk."""
        return sum(len(seg.text) for seg in self.file_segments)


# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------


def detect_page_markers(text: str) -> bool:
    """Return ``True`` if *text* contains at least one ``--- Page N ---`` marker."""
    return PAGE_MARKER_RE.search(text) is not None


# ---------------------------------------------------------------------------
# Page-based splitting
# ---------------------------------------------------------------------------


def split_by_pages(
    text: str,
    file_path: str,
    target_chars: int = TARGET_CHUNK_CHARS,
    overlap_ratio: float = OVERLAP_RATIO,
) -> list[FileSegment]:
    """Split *text* at ``--- Page N ---`` boundaries into :class:`FileSegment` objects.

    Pages are grouped together until approaching *target_chars*.  An overlap
    of *overlap_ratio* * *target_chars* worth of trailing pages from the
    previous segment is prepended to the next segment (capped at
    :data:`MAX_OVERLAP_CHARS`).

    If the entire file fits in one segment, a single :class:`FileSegment`
    with ``is_partial=False`` is returned.
    """
    if not text:
        return [FileSegment(file_path=file_path, text="", start_page=None, end_page=None, total_pages=None)]

    # --- Parse pages ---
    # Each page is (page_number, page_text).
    pages: list[tuple[int, str]] = []
    matches = list(PAGE_MARKER_RE.finditer(text))

    if not matches:
        # No page markers at all -- treat as a single page.
        return [FileSegment(file_path=file_path, text=text, start_page=None, end_page=None, total_pages=None)]

    # Text before the first marker (preamble).
    preamble = text[: matches[0].start()]
    if preamble.strip():
        pages.append((0, preamble))

    for i, match in enumerate(matches):
        page_num = int(match.group(1))
        # Preserve the page marker itself as part of the page text so
        # downstream consumers (LLM prompts, citation verifier) can see
        # which page they are reading.  Issue #61.
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        pages.append((page_num, text[start:end]))

    total_pages = len(pages)

    # --- Group pages into segments ---
    overlap_chars = min(int(target_chars * overlap_ratio), MAX_OVERLAP_CHARS)

    groups: list[list[int]] = []  # Each group is a list of indices into `pages`.
    current_group: list[int] = []
    current_size = 0

    for idx, (_page_num, page_text) in enumerate(pages):
        page_len = len(page_text)
        if current_group and current_size + page_len > target_chars:
            groups.append(current_group)
            current_group = []
            current_size = 0
        current_group.append(idx)
        current_size += page_len

    if current_group:
        groups.append(current_group)

    # Single group -- entire file fits.
    if len(groups) == 1:
        first_page = pages[groups[0][0]][0]
        last_page = pages[groups[0][-1]][0]
        return [
            FileSegment(
                file_path=file_path,
                text=text,
                start_page=first_page,
                end_page=last_page,
                total_pages=total_pages,
                is_partial=False,
            )
        ]

    # Multiple groups -- add overlap from previous group to next group.
    segments: list[FileSegment] = []
    for group_idx, group in enumerate(groups):
        # Build overlap from previous group's trailing pages.
        overlap_pages: list[int] = []
        if group_idx > 0:
            prev_group = groups[group_idx - 1]
            overlap_size = 0
            for pidx in reversed(prev_group):
                page_len = len(pages[pidx][1])
                if overlap_size + page_len > overlap_chars:
                    break
                overlap_pages.insert(0, pidx)
                overlap_size += page_len

        all_page_indices = overlap_pages + group
        segment_text = "".join(pages[pidx][1] for pidx in all_page_indices)

        # Page numbers for metadata: use the group's pages (not overlap).
        first_page = pages[group[0]][0]
        last_page = pages[group[-1]][0]

        segments.append(
            FileSegment(
                file_path=file_path,
                text=segment_text,
                start_page=first_page,
                end_page=last_page,
                total_pages=total_pages,
                is_partial=True,
                part_number=group_idx + 1,
                total_parts=len(groups),
            )
        )

    return segments


# ---------------------------------------------------------------------------
# Paragraph-based splitting (fallback)
# ---------------------------------------------------------------------------


def split_by_paragraphs(
    text: str,
    file_path: str,
    target_chars: int = TARGET_CHUNK_CHARS,
    overlap_chars: int | None = None,
) -> list[FileSegment]:
    """Split *text* at paragraph boundaries (fallback for text without page markers).

    Split priority: ``\\n\\n`` > ``\\n`` > ``". "`` > hard character break.

    Parameters
    ----------
    text:
        Raw text to split.
    file_path:
        Original file path for provenance.
    target_chars:
        Target size per segment.
    overlap_chars:
        Character overlap between segments.  Defaults to
        ``min(target_chars * OVERLAP_RATIO, MAX_OVERLAP_CHARS)``.
    """
    if overlap_chars is None:
        overlap_chars = min(int(target_chars * OVERLAP_RATIO), MAX_OVERLAP_CHARS)

    if not text or len(text) <= target_chars:
        return [
            FileSegment(
                file_path=file_path,
                text=text,
                start_page=None,
                end_page=None,
                total_pages=None,
            )
        ]

    segments: list[FileSegment] = []
    pos = 0
    text_len = len(text)

    while pos < text_len:
        end = min(pos + target_chars, text_len)

        split_pos = _find_split_point(text, pos, end) if end < text_len else end

        segment_text = text[pos:split_pos]
        segments.append(
            FileSegment(
                file_path=file_path,
                text=segment_text,
                start_page=None,
                end_page=None,
                total_pages=None,
            )
        )

        # Advance with overlap.
        next_pos = split_pos - overlap_chars
        if next_pos <= pos:
            # Overlap is larger than what we consumed -- avoid infinite loop.
            next_pos = split_pos
        pos = next_pos

    # Tag partial segments.
    if len(segments) > 1:
        for idx, seg in enumerate(segments):
            seg.is_partial = True
            seg.part_number = idx + 1
            seg.total_parts = len(segments)

    return segments


def _find_split_point(text: str, start: int, end: int) -> int:
    """Find the best natural split point in ``text[start:end]``.

    Looks backwards from *end* for (in order of preference):
    ``\\n\\n``, ``\\n``, ``". "``, then falls back to *end* (hard break).
    """
    # Search window: look back from end within a reasonable range.
    search_start = max(start, end - min(end - start, 10_000))
    window = text[search_start:end]

    # 1. Double newline.
    idx = window.rfind("\n\n")
    if idx != -1:
        return search_start + idx + 2  # After the double newline.

    # 2. Single newline.
    idx = window.rfind("\n")
    if idx != -1:
        return search_start + idx + 1

    # 3. Sentence boundary.
    idx = window.rfind(". ")
    if idx != -1:
        return search_start + idx + 2

    # 4. Hard character break.
    return end


# ---------------------------------------------------------------------------
# Orchestration: split + bin-pack
# ---------------------------------------------------------------------------


def create_analysis_chunks(
    file_texts: list[FileText],
    target_chars: int = TARGET_CHUNK_CHARS,
) -> list[AnalysisChunk]:
    """Split files into segments and bin-pack them into :class:`AnalysisChunk` objects.

    For each :class:`FileText`:
    - If ``has_page_markers`` is ``True``, uses :func:`split_by_pages`.
    - Otherwise, falls back to :func:`split_by_paragraphs`.

    Segments are then greedily packed into chunks up to *target_chars*.
    A single segment that exceeds *target_chars* gets its own chunk.

    Returns
    -------
    list[AnalysisChunk]
        Ordered list with ``chunk_index`` and ``total_chunks`` set.
    """
    if not file_texts:
        return []

    # --- Phase 1: split every file into segments ---
    all_segments: list[FileSegment] = []
    for ft in file_texts:
        if ft.has_page_markers:
            segs = split_by_pages(ft.text, ft.file_path, target_chars=target_chars)
        else:
            segs = split_by_paragraphs(ft.text, ft.file_path, target_chars=target_chars)
        all_segments.extend(segs)

    # --- Phase 2: greedy bin-packing ---
    chunks: list[AnalysisChunk] = []
    current_chunk = AnalysisChunk(chunk_index=0, total_chunks=0)

    for seg in all_segments:
        seg_len = len(seg.text)

        if not current_chunk.file_segments:
            # Chunk is empty -- always add the first segment.
            current_chunk.file_segments.append(seg)
        elif current_chunk.char_count + seg_len <= target_chars:
            current_chunk.file_segments.append(seg)
        else:
            # Current chunk is full.  Finalise it and start a new one.
            chunks.append(current_chunk)
            current_chunk = AnalysisChunk(chunk_index=0, total_chunks=0)
            current_chunk.file_segments.append(seg)

    if current_chunk.file_segments:
        chunks.append(current_chunk)

    # --- Phase 3: assign indices ---
    total = len(chunks)
    for idx, chunk in enumerate(chunks):
        chunk.chunk_index = idx
        chunk.total_chunks = total

    return chunks


# ---------------------------------------------------------------------------
# Quick estimation (no text reading)
# ---------------------------------------------------------------------------


def estimate_chunks(file_sizes: list[int], target_chars: int = TARGET_CHUNK_CHARS) -> int:
    """Estimate the number of analysis chunks from character counts alone.

    Returns ``max(1, ceil(total_chars / target_chars))``.  Useful for
    progress bars and cost estimates before the actual text is loaded.
    """
    total = sum(file_sizes)
    if total <= 0:
        return 1
    return max(1, math.ceil(total / target_chars))
