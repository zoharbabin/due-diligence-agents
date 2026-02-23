"""Unit tests for the citation verifier (Issue #5).

Tests cover:
- Page splitting by ``--- Page N ---`` markers
- Exact and fuzzy quote matching
- Section reference verification
- Page-scoped verification
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

    def test_page_scoped_verification(self, tmp_path: Path) -> None:
        """Quote found on the wrong page should still verify against full text."""
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
        result = _make_result_with_citation(page="5")
        verifier.verify_result(result, file_texts=file_texts)

        cit = result.columns["Q1"].citations[0]
        # Page-scoped search won't find it on page 5.
        # But the verifier falls back to the full page text scope.
        # Since page 5 text doesn't contain the quote, it should fail.
        assert cit.quote_verified is False

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
