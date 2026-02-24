"""Unit tests for the citation verifier (Issue #5, Issue #24).

Tests cover:
- Page splitting by ``--- Page N ---`` markers
- Exact and fuzzy quote matching
- Section reference verification
- Page-scoped verification
- Progressive search scope (Issue #24): page → adjacent → full doc → cross-file
- Whitespace normalization (Issue #24)
- Cross-file quote correction (Issue #24)
- Verification summary computation
- Integration with SearchCustomerResult
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dd_agents.models.search import (
    SearchCitation,
    SearchColumnResult,
    SearchCustomerResult,
)
from dd_agents.search.chunker import FileText
from dd_agents.search.citation_verifier import (
    QUOTE_MATCH_THRESHOLD,
    CitationVerifier,
    compute_verification_summary,
    split_by_pages,
)

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Test split_by_pages
# ---------------------------------------------------------------------------


class TestSplitByPages:
    """Tests for the page splitting helper."""

    def test_no_markers(self) -> None:
        """Text without page markers stores content as preamble under key '0'."""
        pages = split_by_pages("Just some text without markers.")
        # No page markers means regex splits into just the preamble.
        # The preamble is stored under key "0" only if text is non-empty
        # and the regex produces a non-empty first element — but since
        # there are no markers, the full text becomes parts[0].
        assert "0" in pages
        assert "Just some text" in pages["0"]

    def test_single_page(self) -> None:
        pages = split_by_pages("\n--- Page 1 ---\nFirst page content here.")
        assert "1" in pages
        assert "First page content" in pages["1"]

    def test_multiple_pages(self) -> None:
        text = (
            "\n--- Page 1 ---\nPage one content.\n"
            "\n--- Page 2 ---\nPage two content.\n"
            "\n--- Page 3 ---\nPage three content.\n"
        )
        pages = split_by_pages(text)
        assert len(pages) == 3
        assert "Page one content" in pages["1"]
        assert "Page two content" in pages["2"]
        assert "Page three content" in pages["3"]

    def test_preamble_text(self) -> None:
        text = "Preamble text before any page.\n--- Page 1 ---\nPage one."
        pages = split_by_pages(text)
        assert "0" in pages
        assert "Preamble" in pages["0"]
        assert "1" in pages

    def test_empty_text(self) -> None:
        assert split_by_pages("") == {}


# ---------------------------------------------------------------------------
# Test CitationVerifier
# ---------------------------------------------------------------------------


def _make_verifier(tmp_path: Path) -> CitationVerifier:
    """Create a CitationVerifier with a temp directory."""
    text_dir = tmp_path / "text"
    text_dir.mkdir()
    data_room = tmp_path / "data_room"
    data_room.mkdir()
    return CitationVerifier(text_dir=text_dir, data_room_path=data_room)


def _make_result_with_citation(
    file_path: str = "GroupA/Customer/msa.pdf",
    page: str = "5",
    section_ref: str = "Section 12.3",
    exact_quote: str = "Upon change of control, the agreement terminates.",
) -> SearchCustomerResult:
    """Create a SearchCustomerResult with a single citation."""
    return SearchCustomerResult(
        customer_name="Test Customer",
        group="GroupA",
        files_analyzed=1,
        total_files=1,
        columns={
            "Q1": SearchColumnResult(
                answer="YES",
                confidence="HIGH",
                citations=[
                    SearchCitation(
                        file_path=file_path,
                        page=page,
                        section_ref=section_ref,
                        exact_quote=exact_quote,
                    )
                ],
            )
        },
    )


class TestCitationVerifier:
    """Tests for the CitationVerifier class."""

    def test_exact_match_verified(self, tmp_path: Path) -> None:
        """Citation with exact quote match is verified."""
        verifier = _make_verifier(tmp_path)
        source_text = "\n--- Page 5 ---\nSection 12.3\nUpon change of control, the agreement terminates.\n"
        file_texts = [
            FileText(
                file_path="GroupA/Customer/msa.pdf",
                text=source_text,
                has_page_markers=True,
            )
        ]

        result = _make_result_with_citation()
        verifier.verify_result(result, file_texts=file_texts)

        cit = result.columns["Q1"].citations[0]
        assert cit.quote_verified is True
        assert cit.quote_match_score >= QUOTE_MATCH_THRESHOLD
        assert cit.section_verified is True

    def test_fuzzy_match_above_threshold(self, tmp_path: Path) -> None:
        """Citation with OCR-like typos still verifies above threshold."""
        verifier = _make_verifier(tmp_path)
        # Source has slight OCR differences from the citation.
        source_text = "\n--- Page 5 ---\nSection 12.3\nUpon change of controI, the agreernent terrninates.\n"
        file_texts = [
            FileText(
                file_path="GroupA/Customer/msa.pdf",
                text=source_text,
                has_page_markers=True,
            )
        ]

        result = _make_result_with_citation()
        verifier.verify_result(result, file_texts=file_texts)

        cit = result.columns["Q1"].citations[0]
        assert cit.quote_verified is True
        assert cit.quote_match_score >= QUOTE_MATCH_THRESHOLD

    def test_hallucinated_quote_fails(self, tmp_path: Path) -> None:
        """Citation with a fabricated quote fails verification."""
        verifier = _make_verifier(tmp_path)
        source_text = "\n--- Page 5 ---\nSection 12.3\nThis agreement is for the provision of consulting services.\n"
        file_texts = [
            FileText(
                file_path="GroupA/Customer/msa.pdf",
                text=source_text,
                has_page_markers=True,
            )
        ]

        result = _make_result_with_citation(
            exact_quote="The vendor shall provide 30 days written notice of any material breach."
        )
        verifier.verify_result(result, file_texts=file_texts)

        cit = result.columns["Q1"].citations[0]
        assert cit.quote_verified is False
        assert cit.quote_match_score < QUOTE_MATCH_THRESHOLD

    def test_missing_section_ref(self, tmp_path: Path) -> None:
        """Section reference not found in source is flagged."""
        verifier = _make_verifier(tmp_path)
        source_text = "\n--- Page 5 ---\nArticle 8\nUpon change of control, the agreement terminates.\n"
        file_texts = [
            FileText(
                file_path="GroupA/Customer/msa.pdf",
                text=source_text,
                has_page_markers=True,
            )
        ]

        result = _make_result_with_citation(section_ref="Section 12.3")
        verifier.verify_result(result, file_texts=file_texts)

        cit = result.columns["Q1"].citations[0]
        assert cit.section_verified is False

    def test_empty_section_ref_is_none(self, tmp_path: Path) -> None:
        """Empty section_ref results in None (nothing to verify)."""
        verifier = _make_verifier(tmp_path)
        file_texts = [
            FileText(
                file_path="GroupA/Customer/msa.pdf",
                text="Some content.",
                has_page_markers=False,
            )
        ]

        result = _make_result_with_citation(section_ref="", exact_quote="Some content")
        verifier.verify_result(result, file_texts=file_texts)

        cit = result.columns["Q1"].citations[0]
        assert cit.section_verified is None

    def test_empty_quote_is_none(self, tmp_path: Path) -> None:
        """Empty exact_quote results in None (nothing to verify)."""
        verifier = _make_verifier(tmp_path)
        file_texts = [
            FileText(
                file_path="GroupA/Customer/msa.pdf",
                text="Some content.",
                has_page_markers=False,
            )
        ]

        result = _make_result_with_citation(exact_quote="")
        verifier.verify_result(result, file_texts=file_texts)

        cit = result.columns["Q1"].citations[0]
        assert cit.quote_verified is None

    def test_missing_file_fails_all(self, tmp_path: Path) -> None:
        """Citation referencing a file not in extracted texts fails."""
        verifier = _make_verifier(tmp_path)
        # Provide no file texts at all.
        result = _make_result_with_citation()
        verifier.verify_result(result, file_texts=[])

        cit = result.columns["Q1"].citations[0]
        assert cit.quote_verified is False
        assert cit.section_verified is False

    def test_page_scoped_verification_wrong_page_full_doc_fallback(self, tmp_path: Path) -> None:
        """Quote on wrong page is found via full-document fallback (Issue #24)."""
        verifier = _make_verifier(tmp_path)
        source_text = (
            "\n--- Page 3 ---\n"
            "Upon change of control, the agreement terminates.\n"
            "\n--- Page 5 ---\n"
            "This section covers payment terms.\n"
        )
        file_texts = [
            FileText(
                file_path="GroupA/Customer/msa.pdf",
                text=source_text,
                has_page_markers=True,
            )
        ]

        # Citation claims page 5 but quote is actually on page 3.
        # Progressive search: page 5 fails → adjacent (4,5,6) fails →
        # full document succeeds.
        result = _make_result_with_citation(page="5")
        verifier.verify_result(result, file_texts=file_texts)

        cit = result.columns["Q1"].citations[0]
        assert cit.quote_verified is True
        assert cit.quote_match_score >= QUOTE_MATCH_THRESHOLD

    def test_no_page_markers_searches_full_text(self, tmp_path: Path) -> None:
        """Without page markers, verifier searches the full document text."""
        verifier = _make_verifier(tmp_path)
        source_text = "Upon change of control, the agreement terminates."
        file_texts = [
            FileText(
                file_path="GroupA/Customer/msa.pdf",
                text=source_text,
                has_page_markers=False,
            )
        ]

        result = _make_result_with_citation(page="1")
        verifier.verify_result(result, file_texts=file_texts)

        cit = result.columns["Q1"].citations[0]
        # No page markers means split_by_pages returns empty, so full text is used.
        assert cit.quote_verified is True

    def test_multiple_citations_verified(self, tmp_path: Path) -> None:
        """Multiple citations in one column are all verified."""
        verifier = _make_verifier(tmp_path)
        source_text = (
            "\n--- Page 3 ---\n"
            "Section 5.1: Consent required for assignment.\n"
            "\n--- Page 7 ---\n"
            "Section 12.3: Notice must be provided 30 days prior.\n"
        )
        file_texts = [
            FileText(
                file_path="GroupA/Customer/msa.pdf",
                text=source_text,
                has_page_markers=True,
            )
        ]

        result = SearchCustomerResult(
            customer_name="Test",
            group="GroupA",
            columns={
                "Q1": SearchColumnResult(
                    answer="YES",
                    confidence="HIGH",
                    citations=[
                        SearchCitation(
                            file_path="GroupA/Customer/msa.pdf",
                            page="3",
                            section_ref="Section 5.1",
                            exact_quote="Consent required for assignment.",
                        ),
                        SearchCitation(
                            file_path="GroupA/Customer/msa.pdf",
                            page="7",
                            section_ref="Section 12.3",
                            exact_quote="Notice must be provided 30 days prior.",
                        ),
                    ],
                )
            },
        )

        verifier.verify_result(result, file_texts=file_texts)

        for cit in result.columns["Q1"].citations:
            assert cit.quote_verified is True
            assert cit.section_verified is True


# ---------------------------------------------------------------------------
# Test compute_verification_summary
# ---------------------------------------------------------------------------


class TestVerificationSummary:
    """Tests for compute_verification_summary."""

    def test_all_verified(self) -> None:
        result = SearchCustomerResult(
            customer_name="Test",
            columns={
                "Q1": SearchColumnResult(
                    answer="YES",
                    citations=[
                        SearchCitation(quote_verified=True, quote_match_score=95.0),
                        SearchCitation(quote_verified=True, quote_match_score=90.0),
                    ],
                )
            },
        )
        summary = compute_verification_summary(result)
        assert summary == {"verified": 2, "failed": 0, "unverifiable": 0}

    def test_mixed_results(self) -> None:
        result = SearchCustomerResult(
            customer_name="Test",
            columns={
                "Q1": SearchColumnResult(
                    answer="YES",
                    citations=[
                        SearchCitation(quote_verified=True, quote_match_score=95.0),
                        SearchCitation(quote_verified=False, quote_match_score=30.0),
                        SearchCitation(quote_verified=None),
                    ],
                )
            },
        )
        summary = compute_verification_summary(result)
        assert summary == {"verified": 1, "failed": 1, "unverifiable": 1}

    def test_no_citations(self) -> None:
        result = SearchCustomerResult(
            customer_name="Test",
            columns={
                "Q1": SearchColumnResult(answer="NOT_ADDRESSED"),
            },
        )
        summary = compute_verification_summary(result)
        assert summary == {"verified": 0, "failed": 0, "unverifiable": 0}


# ---------------------------------------------------------------------------
# Test model changes (page field_validator)
# ---------------------------------------------------------------------------


class TestSearchCitationPageValidator:
    """Tests for the page field_validator on SearchCitation (Issue #4 Phase B)."""

    def test_int_page_coerced_to_str(self) -> None:
        cit = SearchCitation(page=5)  # type: ignore[arg-type]
        assert cit.page == "5"
        assert isinstance(cit.page, str)

    def test_none_page_coerced_to_empty(self) -> None:
        cit = SearchCitation(page=None)  # type: ignore[arg-type]
        assert cit.page == ""

    def test_str_page_unchanged(self) -> None:
        cit = SearchCitation(page="12")
        assert cit.page == "12"

    def test_float_page_coerced(self) -> None:
        cit = SearchCitation(page=3.0)  # type: ignore[arg-type]
        assert cit.page == "3.0"


# ---------------------------------------------------------------------------
# Test _normalize_whitespace (Issue #24)
# ---------------------------------------------------------------------------


class TestNormalizeWhitespace:
    """Tests for whitespace normalization before fuzzy matching."""

    def test_collapses_newlines(self) -> None:
        from dd_agents.search.citation_verifier import _normalize_whitespace

        assert _normalize_whitespace("hello\nworld") == "hello world"

    def test_collapses_multiple_spaces(self) -> None:
        from dd_agents.search.citation_verifier import _normalize_whitespace

        assert _normalize_whitespace("hello   world") == "hello world"

    def test_collapses_tabs(self) -> None:
        from dd_agents.search.citation_verifier import _normalize_whitespace

        assert _normalize_whitespace("hello\t\tworld") == "hello world"

    def test_strips_leading_trailing(self) -> None:
        from dd_agents.search.citation_verifier import _normalize_whitespace

        assert _normalize_whitespace("  hello  ") == "hello"

    def test_mixed_whitespace(self) -> None:
        from dd_agents.search.citation_verifier import _normalize_whitespace

        text = "  The agreement\nshall not be\r\nassigned  without   consent.  "
        assert _normalize_whitespace(text) == "The agreement shall not be assigned without consent."


# ---------------------------------------------------------------------------
# Test _get_adjacent_pages_text (Issue #24)
# ---------------------------------------------------------------------------


class TestGetAdjacentPagesText:
    """Tests for the ±1 page expansion helper."""

    def test_returns_three_pages(self) -> None:
        from dd_agents.search.citation_verifier import _get_adjacent_pages_text

        pages = {"1": "page1", "2": "page2", "3": "page3", "4": "page4"}
        result = _get_adjacent_pages_text(pages, "2")
        assert "page1" in result
        assert "page2" in result
        assert "page3" in result
        assert "page4" not in result

    def test_first_page_no_negative(self) -> None:
        from dd_agents.search.citation_verifier import _get_adjacent_pages_text

        pages = {"1": "page1", "2": "page2"}
        result = _get_adjacent_pages_text(pages, "1")
        assert "page1" in result
        assert "page2" in result

    def test_non_numeric_page_returns_empty(self) -> None:
        from dd_agents.search.citation_verifier import _get_adjacent_pages_text

        assert _get_adjacent_pages_text({"1": "text"}, "abc") == ""

    def test_none_page_returns_empty(self) -> None:
        from dd_agents.search.citation_verifier import _get_adjacent_pages_text

        assert _get_adjacent_pages_text({"1": "text"}, None) == ""  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Test progressive search scope (Issue #24)
# ---------------------------------------------------------------------------


class TestProgressiveSearchScope:
    """Tests for the progressive page → adjacent → full doc → cross-file search."""

    def test_adjacent_page_catches_off_by_one(self, tmp_path: Path) -> None:
        """Quote on page 2 with citation claiming page 3 is found via adjacent pages."""
        verifier = _make_verifier(tmp_path)
        source_text = (
            "\n--- Page 2 ---\n"
            "Upon change of control, the agreement terminates.\n"
            "\n--- Page 3 ---\n"
            "Payment terms are net 30 days.\n"
        )
        file_texts = [
            FileText(
                file_path="GroupA/Customer/msa.pdf",
                text=source_text,
                has_page_markers=True,
            )
        ]

        # Citation claims page 3, quote is on page 2 (adjacent).
        result = _make_result_with_citation(page="3")
        verifier.verify_result(result, file_texts=file_texts)

        cit = result.columns["Q1"].citations[0]
        assert cit.quote_verified is True
        assert cit.quote_match_score >= QUOTE_MATCH_THRESHOLD

    def test_whitespace_normalized_in_fuzzy_match(self, tmp_path: Path) -> None:
        """Line breaks in extracted text don't prevent quote verification."""
        verifier = _make_verifier(tmp_path)
        # Source text has line breaks mid-sentence (PDF column layout).
        source_text = "\n--- Page 5 ---\nSection 12.3\nUpon change of\ncontrol, the\nagreement terminates.\n"
        file_texts = [
            FileText(
                file_path="GroupA/Customer/msa.pdf",
                text=source_text,
                has_page_markers=True,
            )
        ]

        # Citation quote is a clean single-line string.
        result = _make_result_with_citation(exact_quote="Upon change of control, the agreement terminates.")
        verifier.verify_result(result, file_texts=file_texts)

        cit = result.columns["Q1"].citations[0]
        assert cit.quote_verified is True
        assert cit.quote_match_score >= QUOTE_MATCH_THRESHOLD

    def test_cross_file_correction(self, tmp_path: Path) -> None:
        """Quote in wrong file is found and file_path is corrected."""
        verifier = _make_verifier(tmp_path)

        # File A has the quote.
        file_a_text = "\n--- Page 2 ---\nUpon change of control, the agreement terminates.\n"
        # File B does NOT have the quote — LLM attributed it here incorrectly.
        file_b_text = "\n--- Page 1 ---\nThis purchase order is for consulting services.\n"
        file_texts = [
            FileText(file_path="GroupA/Customer/contract_a.pdf", text=file_a_text, has_page_markers=True),
            FileText(file_path="GroupA/Customer/contract_b.pdf", text=file_b_text, has_page_markers=True),
        ]

        # Citation incorrectly attributes the quote to contract_b.
        result = _make_result_with_citation(
            file_path="GroupA/Customer/contract_b.pdf",
            page="1",
        )
        verifier.verify_result(result, file_texts=file_texts)

        cit = result.columns["Q1"].citations[0]
        assert cit.quote_verified is True
        assert cit.file_path == "GroupA/Customer/contract_a.pdf"
        assert cit.quote_match_score >= QUOTE_MATCH_THRESHOLD

    def test_cross_file_correction_updates_page(self, tmp_path: Path) -> None:
        """Cross-file correction also finds the correct page number."""
        verifier = _make_verifier(tmp_path)

        file_a_text = (
            "\n--- Page 1 ---\n"
            "Introduction and definitions.\n"
            "\n--- Page 4 ---\n"
            "Upon change of control, the agreement terminates.\n"
        )
        file_b_text = "\n--- Page 1 ---\nUnrelated purchase order.\n"
        file_texts = [
            FileText(file_path="GroupA/Customer/msa.pdf", text=file_a_text, has_page_markers=True),
            FileText(file_path="GroupA/Customer/po.pdf", text=file_b_text, has_page_markers=True),
        ]

        result = _make_result_with_citation(
            file_path="GroupA/Customer/po.pdf",
            page="1",
        )
        verifier.verify_result(result, file_texts=file_texts)

        cit = result.columns["Q1"].citations[0]
        assert cit.file_path == "GroupA/Customer/msa.pdf"
        assert cit.page == "4"

    def test_truly_hallucinated_quote_fails_all_scopes(self, tmp_path: Path) -> None:
        """A completely fabricated quote fails at all search scopes."""
        verifier = _make_verifier(tmp_path)

        file_texts = [
            FileText(
                file_path="GroupA/Customer/msa.pdf",
                text="\n--- Page 1 ---\nThis is a standard consulting agreement.\n",
                has_page_markers=True,
            ),
            FileText(
                file_path="GroupA/Customer/sow.pdf",
                text="\n--- Page 1 ---\nStatement of work for project delivery.\n",
                has_page_markers=True,
            ),
        ]

        result = _make_result_with_citation(
            exact_quote="The vendor shall indemnify the customer for all losses arising from negligence."
        )
        verifier.verify_result(result, file_texts=file_texts)

        cit = result.columns["Q1"].citations[0]
        assert cit.quote_verified is False
        assert cit.quote_match_score < QUOTE_MATCH_THRESHOLD


# ---------------------------------------------------------------------------
# Test colon-in-filename fallback (Bug C)
# ---------------------------------------------------------------------------


class TestColonInFilenameFallback:
    """Tests for the colon → &#x3a_ filename fallback in _load_customer_texts."""

    def test_colon_in_path_resolved_via_encoded_fallback(self, tmp_path: Path) -> None:
        """LLM cites path with literal colon; filesystem stores &#x3a_ encoding."""
        from dd_agents.extraction.pipeline import ExtractionPipeline

        text_dir = tmp_path / "text"
        text_dir.mkdir()
        data_room = tmp_path / "data_room"
        data_room.mkdir()

        # The LLM cites this path (with literal colon):
        llm_cited_path = "Below-100K/WSPS/Order Form 2:3.pdf"
        # The filesystem stores the colon-encoded variant:
        encoded_path = "Below-100K/WSPS/Order Form 2&#x3a_3.pdf"

        # Write the extracted text file under the encoded variant.
        absolute_encoded = str(data_room / encoded_path)
        safe_name = ExtractionPipeline._safe_text_name(absolute_encoded)
        text_file = text_dir / safe_name
        text_file.write_text(
            "\n--- Page 1 ---\nThis agreement governs the purchase of services.\n",
            encoding="utf-8",
        )

        verifier = CitationVerifier(text_dir=text_dir, data_room_path=data_room)
        result = _make_result_with_citation(
            file_path=llm_cited_path,
            exact_quote="This agreement governs the purchase of services.",
            page="1",
            section_ref="",
        )
        verifier.verify_result(result)

        cit = result.columns["Q1"].citations[0]
        assert cit.quote_verified is True
        assert cit.quote_match_score >= QUOTE_MATCH_THRESHOLD

    def test_no_colon_path_unaffected(self, tmp_path: Path) -> None:
        """Paths without colons skip the fallback and still load normally."""
        from dd_agents.extraction.pipeline import ExtractionPipeline

        text_dir = tmp_path / "text"
        text_dir.mkdir()
        data_room = tmp_path / "data_room"
        data_room.mkdir()

        normal_path = "GroupA/Customer/msa.pdf"
        absolute = str(data_room / normal_path)
        safe_name = ExtractionPipeline._safe_text_name(absolute)
        text_file = text_dir / safe_name
        text_file.write_text(
            "\n--- Page 5 ---\nSection 12.3\nUpon change of control, the agreement terminates.\n",
            encoding="utf-8",
        )

        verifier = CitationVerifier(text_dir=text_dir, data_room_path=data_room)
        result = _make_result_with_citation(
            file_path=normal_path,
        )
        verifier.verify_result(result)

        cit = result.columns["Q1"].citations[0]
        assert cit.quote_verified is True

    def test_colon_path_no_encoded_file_fails_gracefully(self, tmp_path: Path) -> None:
        """Colon path with no matching encoded file still fails gracefully."""
        text_dir = tmp_path / "text"
        text_dir.mkdir()
        data_room = tmp_path / "data_room"
        data_room.mkdir()

        verifier = CitationVerifier(text_dir=text_dir, data_room_path=data_room)
        result = _make_result_with_citation(
            file_path="Below-100K/WSPS/Order Form 2:3.pdf",
            exact_quote="Some quote from the document.",
        )
        verifier.verify_result(result)

        cit = result.columns["Q1"].citations[0]
        # No file found → verification fails.
        assert cit.quote_verified is False
        assert cit.quote_match_score == 0.0


# ---------------------------------------------------------------------------
# Test caching optimizations (Issue #27 Phase 4)
# ---------------------------------------------------------------------------


class TestVerifierCaching:
    """Tests for citation verifier caching optimizations (Issue #27 Phase 4)."""

    def test_page_cache_populated(self, tmp_path: Path) -> None:
        """After verification, _page_cache contains the split pages."""
        verifier = _make_verifier(tmp_path)
        source_text = "\n--- Page 1 ---\nSection 12.3\nUpon change of control, the agreement terminates.\n"
        file_texts = [
            FileText(
                file_path="GroupA/Customer/msa.pdf",
                text=source_text,
                has_page_markers=True,
            )
        ]

        result = _make_result_with_citation(
            file_path="GroupA/Customer/msa.pdf",
            page="1",
            exact_quote="Upon change of control, the agreement terminates.",
        )
        verifier.verify_result(result, file_texts=file_texts)

        # The page cache should now contain the file's split pages.
        assert "GroupA/Customer/msa.pdf" in verifier._page_cache
        pages = verifier._page_cache["GroupA/Customer/msa.pdf"]
        assert "1" in pages
        assert "Upon change of control" in pages["1"]

    def test_norm_cache_populated(self, tmp_path: Path) -> None:
        """After verification, _norm_cache contains normalized text."""
        verifier = _make_verifier(tmp_path)
        source_text = "\n--- Page 5 ---\nSection 12.3\nUpon change of control, the agreement terminates.\n"
        file_texts = [
            FileText(
                file_path="GroupA/Customer/msa.pdf",
                text=source_text,
                has_page_markers=True,
            )
        ]

        result = _make_result_with_citation()
        verifier.verify_result(result, file_texts=file_texts)

        # At least the page-level normalization key should be cached.
        assert len(verifier._norm_cache) > 0
        # Check that a page-level key exists.
        assert "GroupA/Customer/msa.pdf:page:5" in verifier._norm_cache

    def test_exact_substring_short_circuits(self, tmp_path: Path) -> None:
        """Exact substring match returns 100.0 without calling fuzz."""
        verifier = _make_verifier(tmp_path)

        # When the quote is an exact substring, _match_score returns 100.0.
        score = verifier._match_score(
            "the agreement terminates",
            "Upon change of control, the agreement terminates immediately.",
        )
        assert score == 100.0

    def test_match_score_falls_back_to_fuzz(self, tmp_path: Path) -> None:
        """Non-exact match falls back to fuzz.partial_ratio."""
        verifier = _make_verifier(tmp_path)

        # Slightly different text (OCR-like typo) — not an exact substring.
        score = verifier._match_score(
            "the agreernent terrninates",
            "Upon change of control, the agreement terminates immediately.",
        )
        # Should still get a reasonable fuzzy score (not 100.0 exact, but > 0).
        assert score > 0.0
        assert score != 100.0  # Not an exact substring match.
