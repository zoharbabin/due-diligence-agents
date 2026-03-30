"""Unit tests for the dd-agents auto-config command and cli_auto_config module."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from dd_agents.cli import main
from dd_agents.cli_auto_config import (
    BuyerContextIngester,
    DataRoomAnalyzer,
    IngestedContext,
    build_reference_file_summary,
    convert_document_to_markdown,
    get_tree_output,
    run_interactive_refinement,
    validate_and_fix_config,
)
from dd_agents.cli_init import DEFAULT_FOCUS_AREAS
from dd_agents.config import validate_deal_config

if TYPE_CHECKING:
    from pathlib import Path


# =========================================================================
# Helpers
# =========================================================================


def _create_data_room(tmp_path: Path) -> Path:
    """Create a minimal data room with groups and customers."""
    dr = tmp_path / "data_room"
    dr.mkdir()

    acme = dr / "GroupA" / "Acme_Corp"
    acme.mkdir(parents=True)
    (acme / "contract.pdf").write_text("content")
    (acme / "invoice.xlsx").write_text("content")

    beta = dr / "GroupA" / "Beta_Inc"
    beta.mkdir(parents=True)
    (beta / "agreement.pdf").write_text("content")

    gamma = dr / "GroupB" / "Gamma_LLC"
    gamma.mkdir(parents=True)
    (gamma / "license.docx").write_text("content")

    # Reference file at root
    (dr / "overview.pdf").write_text("reference content")
    (dr / "cap_table.xlsx").write_text("cap table data")

    return dr


def _create_empty_data_room(tmp_path: Path) -> Path:
    """Create an empty data room directory."""
    dr = tmp_path / "empty_room"
    dr.mkdir()
    return dr


def _make_scan_result(
    customer_names: list[str] | None = None,
    groups: list[str] | None = None,
    file_count: int = 5,
) -> dict:
    """Build a minimal scan_result dict for testing."""
    return {
        "groups": groups or ["GroupA", "GroupB"],
        "customers": [],
        "customer_names": customer_names or ["Acme_Corp", "Beta_Inc", "Gamma_LLC"],
        "file_count": file_count,
        "counts": None,
    }


def _make_valid_claude_response(
    buyer: str = "Apex Holdings, Inc.",
    target: str = "WidgetCo Inc.",
) -> dict:
    """Return a valid config dict as Claude would produce."""
    return {
        "config_version": "1.0.0",
        "buyer": {
            "name": buyer,
            "ticker": "APEX",
            "exchange": "NYSE",
            "notes": "Diversified technology holding company",
        },
        "target": {
            "name": target,
            "subsidiaries": ["WidgetCo Holdings LLC", "Sprocket Technologies Inc."],
            "previous_names": [
                {"name": "OldWidget", "period": "2012-2018", "notes": "Original name"},
            ],
            "acquired_entities": [
                {
                    "name": "GearHub",
                    "acquisition_date": "",
                    "deal_type": "acquisition",
                    "notes": "",
                },
            ],
            "entity_name_variants_for_contract_matching": [
                "WidgetCo Inc.",
                "WidgetCo",
                "WidgetCo Holdings LLC",
                "OldWidget",
                "Sprocket Technologies Inc.",
                "GearHub",
            ],
            "notes": "B2B widget intelligence platform",
        },
        "deal": {
            "type": "acquisition",
            "focus_areas": [
                "change_of_control_clauses",
                "ip_ownership",
                "data_privacy_compliance",
                "auto_renewal_terms",
            ],
            "notes": "Data room contains customer contracts organized by group.",
        },
        "entity_aliases": {
            "canonical_to_variants": {
                "WidgetCo": ["WidgetCo Inc.", "WidgetCo Holdings LLC"],
            },
        },
    }


def _make_buyer_strategy_response() -> dict:
    """Return a valid buyer_strategy dict as Claude would produce."""
    return {
        "buyer_strategy": {
            "thesis": "Acquire WidgetCo to expand Apex's platform into widget intelligence.",
            "key_synergies": [
                "Cross-sell widget analytics to Apex enterprise customers",
                "Integrate WidgetCo data engine with Apex platform",
            ],
            "integration_priorities": [
                "Unified analytics dashboard",
                "Customer migration program",
            ],
            "risk_tolerance": "moderate",
            "focus_areas": [
                "Customer overlap and CoC clause exposure",
                "IP ownership clarity for widget algorithms",
            ],
            "budget_range": "",
            "notes": "IMPORTANT: Acquirer Intelligence Agent should read buyer context at: _buyer/",
        },
    }


def _make_spa_extraction_response() -> dict:
    """Return a valid SPA extraction response."""
    return {
        "budget_range": "$50M base purchase price in cash.",
        "spa_notes": "Target is a ULC. 2-year non-compete. Escrow of $2M for 18 months.",
        "additional_entity_variants": ["WidgetCo ULC", "Widget Holdings Inc."],
        "key_executives": [
            {"name": "Jane Doe", "title": "CEO", "company": "WidgetCo Inc."},
        ],
    }


# =========================================================================
# get_tree_output tests
# =========================================================================


class TestGetTreeOutput:
    """Tests for get_tree_output."""

    def test_returns_non_empty_string(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        result = get_tree_output(dr)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_excludes_dd_directory(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        # Create a _dd directory that should be excluded
        (dr / "_dd").mkdir()
        (dr / "_dd" / "somefile.txt").write_text("hidden")
        result = get_tree_output(dr)
        # The _dd dir and its contents should not appear as tree entries.
        # (The root path itself may contain _dd as a substring, so check lines.)
        tree_lines = result.split("\n")
        # Filter to lines that represent tree entries (exclude the root path line)
        entry_lines = [line for line in tree_lines[1:] if line.strip()]
        for line in entry_lines:
            assert "somefile.txt" not in line, f"_dd contents should be excluded: {line}"

    def test_excludes_buyer_directory(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        (dr / "_buyer").mkdir()
        (dr / "_buyer" / "10k-business.md").write_text("buyer doc")
        result = get_tree_output(dr)
        tree_lines = result.split("\n")
        entry_lines = [line for line in tree_lines[1:] if line.strip()]
        for line in entry_lines:
            assert "10k-business.md" not in line, f"_buyer contents should be excluded: {line}"

    def test_fallback_when_tree_binary_missing(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        with patch("dd_agents.cli_auto_config._tree_via_binary", return_value=None):
            result = get_tree_output(dr)
        assert isinstance(result, str)
        assert len(result) > 0
        # Should contain some directory structure indicators
        assert "GroupA" in result

    def test_respects_max_depth(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        # Depth 1 should show top-level only
        result = get_tree_output(dr, max_depth=1)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_truncates_large_output(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        with patch("dd_agents.cli_auto_config._MAX_TREE_CHARS", 10):
            result = get_tree_output(dr)
        assert "truncated" in result


# =========================================================================
# build_reference_file_summary tests
# =========================================================================


class TestBuildReferenceFileSummary:
    """Tests for build_reference_file_summary."""

    def test_identifies_root_files(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        result = build_reference_file_summary(dr)
        filenames = [r["filename"] for r in result]
        assert "overview.pdf" in filenames
        assert "cap_table.xlsx" in filenames

    def test_excludes_customer_folder_files(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        result = build_reference_file_summary(dr)
        # Should only have root-level files, not files inside customer folders
        filenames = [r["filename"] for r in result]
        assert "contract.pdf" not in filenames
        assert "agreement.pdf" not in filenames

    def test_empty_dir_returns_empty(self, tmp_path: Path) -> None:
        dr = _create_empty_data_room(tmp_path)
        result = build_reference_file_summary(dr)
        assert result == []

    def test_returns_size_info(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        result = build_reference_file_summary(dr)
        for item in result:
            assert "filename" in item
            assert "size_kb" in item
            assert isinstance(item["size_kb"], int)
            assert item["size_kb"] >= 1


# =========================================================================
# Document conversion tests
# =========================================================================


class TestConvertDocumentToMarkdown:
    """Tests for convert_document_to_markdown."""

    def test_plain_text_file(self, tmp_path: Path) -> None:
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("Hello, world!")
        result = convert_document_to_markdown(txt_file)
        assert "Hello, world!" in result

    def test_markdown_file(self, tmp_path: Path) -> None:
        md_file = tmp_path / "test.md"
        md_file.write_text("# Title\n\nSome content.")
        result = convert_document_to_markdown(md_file)
        assert "Title" in result

    def test_nonexistent_file_returns_empty(self, tmp_path: Path) -> None:
        result = convert_document_to_markdown(tmp_path / "nonexistent.docx")
        assert result == ""

    def test_unsupported_extension_reads_as_text(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("a,b,c\n1,2,3")
        result = convert_document_to_markdown(csv_file)
        assert "a,b,c" in result

    def test_docx_with_mocked_markitdown(self, tmp_path: Path) -> None:
        docx_file = tmp_path / "test.docx"
        docx_file.write_text("fake docx content")

        with patch(
            "dd_agents.cli_auto_config._convert_via_markitdown",
            return_value="# Converted\n\nContent from markitdown",
        ):
            result = convert_document_to_markdown(docx_file)
        assert "Content from markitdown" in result

    def test_falls_back_to_pandoc_when_markitdown_fails(self, tmp_path: Path) -> None:
        docx_file = tmp_path / "test.docx"
        docx_file.write_text("fake")

        with (
            patch("dd_agents.cli_auto_config._convert_via_markitdown", return_value=""),
            patch(
                "dd_agents.cli_auto_config._convert_via_pandoc",
                return_value="# Pandoc output\n\nConverted via pandoc",
            ),
        ):
            result = convert_document_to_markdown(docx_file)
        assert "pandoc" in result.lower() or "Pandoc" in result

    def test_handles_both_converters_failing(self, tmp_path: Path) -> None:
        docx_file = tmp_path / "test.docx"
        docx_file.write_text("raw content")

        with (
            patch("dd_agents.cli_auto_config._convert_via_markitdown", return_value=""),
            patch("dd_agents.cli_auto_config._convert_via_pandoc", return_value=""),
        ):
            result = convert_document_to_markdown(docx_file)
        # Falls back to direct read
        assert "raw content" in result


class TestCleanMarkdown:
    """Tests for _clean_markdown."""

    def test_removes_html_comments(self) -> None:
        from dd_agents.cli_auto_config import _clean_markdown

        result = _clean_markdown("Hello <!-- comment --> World")
        assert "comment" not in result
        assert "Hello" in result
        assert "World" in result

    def test_removes_pandoc_markup_tags(self) -> None:
        from dd_agents.cli_auto_config import _clean_markdown

        result = _clean_markdown("Text{.mark} here")
        assert "{.mark}" not in result
        assert "Text" in result

    def test_fixes_escaped_quotes(self) -> None:
        from dd_agents.cli_auto_config import _clean_markdown

        result = _clean_markdown("it\\'s a test")
        assert "it's a test" in result

    def test_collapses_blank_lines(self) -> None:
        from dd_agents.cli_auto_config import _clean_markdown

        result = _clean_markdown("line1\n\n\n\n\nline2")
        assert result == "line1\n\nline2"


# =========================================================================
# BuyerContextIngester tests
# =========================================================================


class TestBuyerContextIngester:
    """Tests for BuyerContextIngester."""

    def test_creates_buyer_dir(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        buyer_doc = tmp_path / "10k.txt"
        buyer_doc.write_text("Annual report content")

        ingester = BuyerContextIngester()
        ctx = ingester.ingest(
            data_room_path=dr,
            buyer_docs=[buyer_doc],
        )
        buyer_dir = dr / "_buyer"
        assert buyer_dir.is_dir()
        assert len(ctx.buyer_doc_paths) == 1
        assert ctx.buyer_doc_paths[0].parent == buyer_dir

    def test_converts_buyer_doc_to_markdown(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        buyer_doc = tmp_path / "report.txt"
        buyer_doc.write_text("# Business Description\n\nOur company does things.")

        ingester = BuyerContextIngester()
        ctx = ingester.ingest(data_room_path=dr, buyer_docs=[buyer_doc])

        assert len(ctx.buyer_doc_contents) == 1
        assert "Business Description" in ctx.buyer_doc_contents[0]

    def test_custom_buyer_docs_dir(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        buyer_doc = tmp_path / "doc.txt"
        buyer_doc.write_text("content")

        ingester = BuyerContextIngester()
        ctx = ingester.ingest(
            data_room_path=dr,
            buyer_docs=[buyer_doc],
            buyer_docs_dir="_acquirer",
        )
        assert ctx.buyer_docs_dir == "_acquirer"
        assert (dr / "_acquirer").is_dir()

    def test_spa_not_placed_in_data_room(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        spa_file = tmp_path / "spa.txt"
        spa_file.write_text("SHARE PURCHASE AGREEMENT between parties...")

        ingester = BuyerContextIngester()
        ctx = ingester.ingest(data_room_path=dr, spa_path=spa_file)

        # SPA content extracted to memory
        assert "SHARE PURCHASE AGREEMENT" in ctx.spa_content
        # But no SPA file in data room
        assert not (dr / "_buyer" / "spa.md").exists()

    def test_press_release_extracted(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        pr_file = tmp_path / "press-release.txt"
        pr_file.write_text("FOR IMMEDIATE RELEASE: Apex acquires WidgetCo")

        ingester = BuyerContextIngester()
        ctx = ingester.ingest(data_room_path=dr, press_release_path=pr_file)

        assert "Apex acquires WidgetCo" in ctx.press_release_content

    def test_handles_missing_buyer_doc(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        missing = tmp_path / "nonexistent.docx"

        ingester = BuyerContextIngester()
        ctx = ingester.ingest(data_room_path=dr, buyer_docs=[missing])

        assert len(ctx.buyer_doc_paths) == 0
        assert len(ctx.buyer_doc_contents) == 0

    def test_handles_missing_spa(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        missing = tmp_path / "nonexistent.pdf"

        ingester = BuyerContextIngester()
        ctx = ingester.ingest(data_room_path=dr, spa_path=missing)

        assert ctx.spa_content == ""

    def test_no_docs_returns_empty_context(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)

        ingester = BuyerContextIngester()
        ctx = ingester.ingest(data_room_path=dr)

        assert ctx.buyer_doc_paths == []
        assert ctx.buyer_doc_contents == []
        assert ctx.spa_content == ""
        assert ctx.press_release_content == ""


# =========================================================================
# DataRoomAnalyzer tests
# =========================================================================


class TestDataRoomAnalyzer:
    """Tests for DataRoomAnalyzer (mocked Claude calls)."""

    @pytest.mark.asyncio
    async def test_successful_analysis(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)
        scan_result = _make_scan_result()
        mock_response = _make_valid_claude_response()

        mock_call = AsyncMock(return_value=json.dumps(mock_response))
        with patch.object(analyzer, "_call_claude", mock_call):
            result = await analyzer.analyze(
                tree_output="fake tree",
                scan_result=scan_result,
                reference_files=[],
                buyer="Apex Holdings",
                target="WidgetCo",
            )

        assert result["buyer"]["name"] == "Apex Holdings, Inc."
        assert result["target"]["name"] == "WidgetCo Inc."
        assert mock_call.call_count == 1

    @pytest.mark.asyncio
    async def test_system_prompt_mentions_buyer_and_target(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)

        prompt = analyzer._build_system_prompt("AcquireCo", "TargetCo")
        assert "AcquireCo" in prompt
        assert "TargetCo" in prompt

    @pytest.mark.asyncio
    async def test_user_prompt_includes_tree_and_refs(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)
        scan_result = _make_scan_result()
        refs = [{"filename": "overview.pdf", "size_kb": 42}]

        prompt = analyzer._build_user_prompt(
            tree_output="my-tree-output",
            scan_result=scan_result,
            reference_files=refs,
            buyer="BuyerCo",
            target="TargetCo",
        )
        assert "my-tree-output" in prompt
        assert "overview.pdf" in prompt
        assert "BuyerCo" in prompt
        assert "TargetCo" in prompt
        assert "Acme_Corp" in prompt  # customer names

    @pytest.mark.asyncio
    async def test_user_prompt_includes_deal_type_hint(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)
        scan_result = _make_scan_result()

        prompt = analyzer._build_user_prompt(
            tree_output="tree",
            scan_result=scan_result,
            reference_files=[],
            buyer="Buyer",
            target="Target",
            deal_type_hint="merger",
        )
        assert "merger" in prompt

    @pytest.mark.asyncio
    async def test_user_prompt_includes_spa_entities(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)
        scan_result = _make_scan_result()

        prompt = analyzer._build_user_prompt(
            tree_output="tree",
            scan_result=scan_result,
            reference_files=[],
            buyer="Buyer",
            target="Target",
            spa_entities="HOLDCO LLC owns 100% of shares",
        )
        assert "HOLDCO LLC" in prompt
        assert "SPA Entity Hints" in prompt

    @pytest.mark.asyncio
    async def test_claude_error_propagates(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)
        scan_result = _make_scan_result()

        mock_call = AsyncMock(side_effect=RuntimeError("Claude API error"))
        with patch.object(analyzer, "_call_claude", mock_call), pytest.raises(RuntimeError, match="Claude API error"):
            await analyzer.analyze(
                tree_output="tree",
                scan_result=scan_result,
                reference_files=[],
                buyer="Buyer",
                target="Target",
            )

    @pytest.mark.asyncio
    async def test_empty_response_raises(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)
        scan_result = _make_scan_result()

        mock_call = AsyncMock(return_value="")
        with patch.object(analyzer, "_call_claude", mock_call), pytest.raises(ValueError, match="empty response"):
            await analyzer.analyze(
                tree_output="tree",
                scan_result=scan_result,
                reference_files=[],
                buyer="Buyer",
                target="Target",
            )

    @pytest.mark.asyncio
    async def test_invalid_json_raises(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)
        scan_result = _make_scan_result()

        mock_call = AsyncMock(return_value="not valid json {{{")
        with patch.object(analyzer, "_call_claude", mock_call), pytest.raises(ValueError, match="Failed to parse"):
            await analyzer.analyze(
                tree_output="tree",
                scan_result=scan_result,
                reference_files=[],
                buyer="Buyer",
                target="Target",
            )

    @pytest.mark.asyncio
    async def test_markdown_fences_stripped(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)
        scan_result = _make_scan_result()
        mock_response = _make_valid_claude_response()

        fenced = f"```json\n{json.dumps(mock_response)}\n```"
        mock_call = AsyncMock(return_value=fenced)
        with patch.object(analyzer, "_call_claude", mock_call):
            result = await analyzer.analyze(
                tree_output="tree",
                scan_result=scan_result,
                reference_files=[],
                buyer="Apex Holdings",
                target="WidgetCo",
            )

        assert result["buyer"]["name"] == "Apex Holdings, Inc."


# =========================================================================
# Multi-turn analysis tests
# =========================================================================


class TestMultiTurnAnalysis:
    """Tests for multi-turn analysis with buyer context."""

    @pytest.mark.asyncio
    async def test_buyer_strategy_generated_when_docs_provided(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)
        scan_result = _make_scan_result()

        base_response = _make_valid_claude_response()
        strategy_response = _make_buyer_strategy_response()

        call_count = 0
        responses = [json.dumps(base_response), json.dumps(strategy_response)]

        async def mock_call(system: str, user: str) -> str:
            nonlocal call_count
            idx = min(call_count, len(responses) - 1)
            call_count += 1
            return responses[idx]

        ctx = IngestedContext(
            buyer_doc_contents=["Apex is a technology holding company."],
            buyer_docs_dir="_buyer",
        )

        with patch.object(analyzer, "_call_claude", side_effect=mock_call):
            result = await analyzer.analyze(
                tree_output="tree",
                scan_result=scan_result,
                reference_files=[],
                buyer="Apex Holdings",
                target="WidgetCo",
                ingested_context=ctx,
            )

        assert "buyer_strategy" in result
        assert result["buyer_strategy"]["thesis"]
        assert call_count == 2  # Turn 1 + Turn 2

    @pytest.mark.asyncio
    async def test_spa_extraction_runs_when_spa_provided(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)
        scan_result = _make_scan_result()

        base_response = _make_valid_claude_response()
        strategy_response = _make_buyer_strategy_response()
        spa_response = _make_spa_extraction_response()

        call_count = 0
        responses = [
            json.dumps(base_response),
            json.dumps(strategy_response),
            json.dumps(spa_response),
        ]

        async def mock_call(system: str, user: str) -> str:
            nonlocal call_count
            idx = min(call_count, len(responses) - 1)
            call_count += 1
            return responses[idx]

        ctx = IngestedContext(
            buyer_doc_contents=["Buyer business description."],
            spa_content="SHARE PURCHASE AGREEMENT... purchase price $50M...",
            buyer_docs_dir="_buyer",
        )

        with patch.object(analyzer, "_call_claude", side_effect=mock_call):
            result = await analyzer.analyze(
                tree_output="tree",
                scan_result=scan_result,
                reference_files=[],
                buyer="Apex Holdings",
                target="WidgetCo",
                ingested_context=ctx,
            )

        assert call_count == 3  # Turn 1 + Turn 2 + Turn 3
        assert "$50M" in result["buyer_strategy"]["budget_range"]
        assert "SPA STRUCTURE" in result["buyer_strategy"]["notes"]

    @pytest.mark.asyncio
    async def test_no_buyer_strategy_without_context(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)
        scan_result = _make_scan_result()
        base_response = _make_valid_claude_response()

        mock_call = AsyncMock(return_value=json.dumps(base_response))
        with patch.object(analyzer, "_call_claude", mock_call):
            result = await analyzer.analyze(
                tree_output="tree",
                scan_result=scan_result,
                reference_files=[],
                buyer="Apex Holdings",
                target="WidgetCo",
            )

        assert "buyer_strategy" not in result
        assert mock_call.call_count == 1

    @pytest.mark.asyncio
    async def test_spa_only_creates_buyer_strategy(self, tmp_path: Path) -> None:
        """SPA without buyer docs still creates buyer_strategy for budget info."""
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)
        scan_result = _make_scan_result()

        base_response = _make_valid_claude_response()
        spa_response = _make_spa_extraction_response()

        call_count = 0
        responses = [json.dumps(base_response), json.dumps(spa_response)]

        async def mock_call(system: str, user: str) -> str:
            nonlocal call_count
            idx = min(call_count, len(responses) - 1)
            call_count += 1
            return responses[idx]

        ctx = IngestedContext(
            spa_content="SHARE PURCHASE AGREEMENT...",
            buyer_docs_dir="_buyer",
        )

        with patch.object(analyzer, "_call_claude", side_effect=mock_call):
            result = await analyzer.analyze(
                tree_output="tree",
                scan_result=scan_result,
                reference_files=[],
                buyer="Apex Holdings",
                target="WidgetCo",
                ingested_context=ctx,
            )

        # Turn 2 skipped (no buyer docs), Turn 3 runs (SPA)
        assert call_count == 2
        assert "buyer_strategy" in result
        assert "$50M" in result["buyer_strategy"]["budget_range"]


class TestMergeSpaIntoConfig:
    """Tests for _merge_spa_into_config."""

    def test_merges_budget_range(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)
        config: dict[str, Any] = {"buyer_strategy": {"budget_range": "", "notes": ""}}
        spa_data = {"budget_range": "$10M cash", "spa_notes": "", "additional_entity_variants": []}

        analyzer._merge_spa_into_config(config, spa_data)
        assert config["buyer_strategy"]["budget_range"] == "$10M cash"

    def test_appends_to_existing_budget(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)
        config: dict[str, Any] = {"buyer_strategy": {"budget_range": "Existing info.", "notes": ""}}
        spa_data = {"budget_range": "Plus $5M escrow.", "spa_notes": "", "additional_entity_variants": []}

        analyzer._merge_spa_into_config(config, spa_data)
        assert "Existing info." in config["buyer_strategy"]["budget_range"]
        assert "Plus $5M escrow." in config["buyer_strategy"]["budget_range"]

    def test_merges_entity_variants(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)
        config: dict[str, Any] = {
            "target": {"entity_name_variants_for_contract_matching": ["Existing"]},
            "buyer_strategy": {"budget_range": "", "notes": ""},
        }
        spa_data = {
            "budget_range": "",
            "spa_notes": "",
            "additional_entity_variants": ["NewEntity", "Existing"],
        }

        analyzer._merge_spa_into_config(config, spa_data)
        variants = config["target"]["entity_name_variants_for_contract_matching"]
        assert "NewEntity" in variants
        assert variants.count("Existing") == 1  # no duplicates

    def test_merges_entity_variants_when_key_missing(self, tmp_path: Path) -> None:
        """Variants must be stored even when the target key doesn't exist yet."""
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)
        config: dict[str, Any] = {
            "target": {"name": "WidgetCo"},
            "buyer_strategy": {"budget_range": "", "notes": ""},
        }
        spa_data = {
            "budget_range": "",
            "spa_notes": "",
            "additional_entity_variants": ["WidgetCo ULC"],
        }

        analyzer._merge_spa_into_config(config, spa_data)
        variants = config["target"]["entity_name_variants_for_contract_matching"]
        assert "WidgetCo ULC" in variants

    def test_merges_key_executives(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)
        config: dict[str, Any] = {"buyer_strategy": {"budget_range": "", "notes": ""}}
        spa_data = {
            "budget_range": "",
            "spa_notes": "",
            "additional_entity_variants": [],
            "key_executives": [{"name": "John Smith", "title": "CFO", "company": "WidgetCo"}],
        }

        analyzer._merge_spa_into_config(config, spa_data)
        assert len(config["key_executives"]) == 1
        assert config["key_executives"][0]["name"] == "John Smith"

    def test_creates_buyer_strategy_if_absent(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)
        config: dict[str, Any] = {}
        spa_data = {"budget_range": "$50M", "spa_notes": "Delaware corp", "additional_entity_variants": []}

        analyzer._merge_spa_into_config(config, spa_data)
        assert config["buyer_strategy"]["budget_range"] == "$50M"
        assert "SPA STRUCTURE: Delaware corp" in config["buyer_strategy"]["notes"]


# =========================================================================
# Buyer strategy prompt tests
# =========================================================================


class TestBuyerStrategyPrompts:
    """Tests for buyer strategy prompt building."""

    def test_buyer_strategy_system_prompt(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)

        prompt = analyzer._build_buyer_strategy_system_prompt("BuyerCo", "TargetCo")
        assert "BuyerCo" in prompt
        assert "TargetCo" in prompt
        assert "buyer_strategy" in prompt
        assert "thesis" in prompt

    def test_buyer_strategy_prompt_includes_docs(self, tmp_path: Path) -> None:
        from pathlib import Path as PathCls

        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)
        base_config = _make_valid_claude_response()
        ctx = IngestedContext(
            buyer_doc_contents=["Our company is a technology leader."],
            buyer_doc_paths=[PathCls("/data_room/_buyer/10k.md")],
            buyer_docs_dir="_buyer",
        )

        prompt = analyzer._build_buyer_strategy_prompt("BuyerCo", "TargetCo", base_config, ctx)
        assert "technology leader" in prompt
        assert "_buyer/10k.md" in prompt

    def test_buyer_strategy_prompt_includes_press_release(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)
        base_config = _make_valid_claude_response()
        ctx = IngestedContext(
            press_release_content="FOR IMMEDIATE RELEASE: Strategic acquisition announced",
            buyer_docs_dir="_buyer",
        )

        prompt = analyzer._build_buyer_strategy_prompt("BuyerCo", "TargetCo", base_config, ctx)
        assert "Strategic acquisition announced" in prompt

    def test_buyer_strategy_prompt_without_docs(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)
        base_config = _make_valid_claude_response()
        ctx = IngestedContext(buyer_docs_dir="_buyer")

        prompt = analyzer._build_buyer_strategy_prompt("BuyerCo", "TargetCo", base_config, ctx)
        assert "Deal Context" in prompt
        # No buyer documents section
        assert "Buyer Business Documents" not in prompt


# =========================================================================
# SPA extraction prompt tests
# =========================================================================


class TestSpaExtractionPrompts:
    """Tests for SPA extraction prompt building."""

    def test_spa_system_prompt(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)

        prompt = analyzer._build_spa_system_prompt()
        assert "Share Purchase Agreement" in prompt
        assert "budget_range" in prompt

    def test_spa_extraction_prompt(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)
        base_config = _make_valid_claude_response()

        prompt = analyzer._build_spa_extraction_prompt(
            "BuyerCo",
            "TargetCo",
            base_config,
            "This SPA is between BuyerCo and TargetCo for $50M...",
        )
        assert "BuyerCo" in prompt
        assert "$50M" in prompt

    def test_spa_content_truncated_when_too_long(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)
        base_config = _make_valid_claude_response()

        long_spa = "A" * 100_000
        prompt = analyzer._build_spa_extraction_prompt(
            "BuyerCo",
            "TargetCo",
            base_config,
            long_spa,
        )
        assert "truncated" in prompt


# =========================================================================
# validate_and_fix_config tests
# =========================================================================


class TestValidateAndFixConfig:
    """Tests for validate_and_fix_config."""

    def test_valid_config_passes_through(self) -> None:
        config = _make_valid_claude_response()
        scan_result = _make_scan_result()
        result = validate_and_fix_config(config, scan_result)
        assert result["config_version"] == "1.0.0"
        assert result["buyer"]["name"] == "Apex Holdings, Inc."

    def test_missing_config_version_fixed(self) -> None:
        config = _make_valid_claude_response()
        del config["config_version"]
        scan_result = _make_scan_result()
        result = validate_and_fix_config(config, scan_result)
        assert result["config_version"] == "1.0.0"

    def test_missing_focus_areas_fixed(self) -> None:
        config = _make_valid_claude_response()
        del config["deal"]["focus_areas"]
        scan_result = _make_scan_result()
        result = validate_and_fix_config(config, scan_result)
        assert result["deal"]["focus_areas"] == list(DEFAULT_FOCUS_AREAS[:4])

    def test_invalid_deal_type_fixed(self) -> None:
        config = _make_valid_claude_response()
        config["deal"]["type"] = "hostile_takeover"
        scan_result = _make_scan_result()
        result = validate_and_fix_config(config, scan_result)
        assert result["deal"]["type"] == "acquisition"

    def test_empty_buyer_raises(self) -> None:
        config = _make_valid_claude_response()
        config["buyer"]["name"] = ""
        scan_result = _make_scan_result()
        with pytest.raises(ValueError, match="buyer.name is empty"):
            validate_and_fix_config(config, scan_result)

    def test_empty_target_raises(self) -> None:
        config = _make_valid_claude_response()
        config["target"]["name"] = ""
        scan_result = _make_scan_result()
        with pytest.raises(ValueError, match="target.name is empty"):
            validate_and_fix_config(config, scan_result)

    def test_customer_names_merged_into_entity_aliases(self) -> None:
        config = _make_valid_claude_response()
        scan_result = _make_scan_result(customer_names=["Acme_Corp", "Beta_Inc"])
        result = validate_and_fix_config(config, scan_result)
        c2v = result["entity_aliases"]["canonical_to_variants"]
        assert "Acme Corp" in c2v
        assert "Acme_Corp" in c2v["Acme Corp"]

    def test_target_name_added_to_entity_variants(self) -> None:
        config = _make_valid_claude_response()
        config["target"]["entity_name_variants_for_contract_matching"] = []
        scan_result = _make_scan_result()
        result = validate_and_fix_config(config, scan_result)
        variants = result["target"]["entity_name_variants_for_contract_matching"]
        assert config["target"]["name"] in variants

    def test_target_name_inserted_if_missing_from_variants(self) -> None:
        config = _make_valid_claude_response()
        config["target"]["entity_name_variants_for_contract_matching"] = ["SomeOther"]
        scan_result = _make_scan_result()
        result = validate_and_fix_config(config, scan_result)
        variants = result["target"]["entity_name_variants_for_contract_matching"]
        assert variants[0] == config["target"]["name"]

    def test_result_passes_pydantic_validation(self) -> None:
        config = _make_valid_claude_response()
        scan_result = _make_scan_result()
        result = validate_and_fix_config(config, scan_result)
        validated = validate_deal_config(result)
        assert validated.buyer.name == "Apex Holdings, Inc."
        assert validated.target.name == "WidgetCo Inc."

    def test_buyer_strategy_invalid_risk_tolerance_fixed(self) -> None:
        config = _make_valid_claude_response()
        config["buyer_strategy"] = {
            "thesis": "Test thesis",
            "risk_tolerance": "very_risky",
        }
        scan_result = _make_scan_result()
        result = validate_and_fix_config(config, scan_result)
        assert result["buyer_strategy"]["risk_tolerance"] == "moderate"

    def test_buyer_strategy_defaults_applied(self) -> None:
        config = _make_valid_claude_response()
        config["buyer_strategy"] = {"thesis": "Test"}
        scan_result = _make_scan_result()
        result = validate_and_fix_config(config, scan_result)
        bs = result["buyer_strategy"]
        assert bs["key_synergies"] == []
        assert bs["integration_priorities"] == []
        assert bs["focus_areas"] == []
        assert bs["budget_range"] == ""
        assert bs["notes"] == ""
        assert bs["risk_tolerance"] == "moderate"

    def test_config_with_buyer_strategy_passes_pydantic(self) -> None:
        config = _make_valid_claude_response()
        config["buyer_strategy"] = _make_buyer_strategy_response()["buyer_strategy"]
        scan_result = _make_scan_result()
        result = validate_and_fix_config(config, scan_result)
        validated = validate_deal_config(result)
        assert validated.buyer_strategy is not None
        assert validated.buyer_strategy.thesis

    def test_config_without_buyer_strategy_passes_pydantic(self) -> None:
        config = _make_valid_claude_response()
        scan_result = _make_scan_result()
        result = validate_and_fix_config(config, scan_result)
        validated = validate_deal_config(result)
        assert validated.buyer_strategy is None


# =========================================================================
# Interactive refinement tests
# =========================================================================


class TestInteractiveRefinement:
    """Tests for run_interactive_refinement."""

    def test_accepts_thesis(self) -> None:
        from unittest.mock import MagicMock

        config = _make_valid_claude_response()
        config["buyer_strategy"] = _make_buyer_strategy_response()["buyer_strategy"]
        mock_console = MagicMock()

        with patch("dd_agents.cli_auto_config._prompt_user", return_value="Y"):
            result = run_interactive_refinement(config, mock_console)

        assert result["buyer_strategy"]["thesis"] == config["buyer_strategy"]["thesis"]

    def test_edits_risk_tolerance(self) -> None:
        from unittest.mock import MagicMock

        config = _make_valid_claude_response()
        config["buyer_strategy"] = _make_buyer_strategy_response()["buyer_strategy"]
        mock_console = MagicMock()

        responses = iter(["Y", "aggressive", "", ""])

        with patch("dd_agents.cli_auto_config._prompt_user", side_effect=responses):
            result = run_interactive_refinement(config, mock_console)

        assert result["buyer_strategy"]["risk_tolerance"] == "aggressive"

    def test_adds_focus_areas(self) -> None:
        from unittest.mock import MagicMock

        config = _make_valid_claude_response()
        config["buyer_strategy"] = _make_buyer_strategy_response()["buyer_strategy"]
        original_count = len(config["buyer_strategy"]["focus_areas"])
        mock_console = MagicMock()

        responses = iter(["Y", "moderate", "new_risk_1, new_risk_2", ""])

        with patch("dd_agents.cli_auto_config._prompt_user", side_effect=responses):
            result = run_interactive_refinement(config, mock_console)

        assert len(result["buyer_strategy"]["focus_areas"]) == original_count + 2

    def test_no_buyer_strategy_returns_unchanged(self) -> None:
        from unittest.mock import MagicMock

        config = _make_valid_claude_response()
        mock_console = MagicMock()

        result = run_interactive_refinement(config, mock_console)
        assert "buyer_strategy" not in result


# =========================================================================
# print_auto_config_summary tests
# =========================================================================


class TestPrintAutoConfigSummary:
    """Tests for print_auto_config_summary."""

    def test_includes_buyer_strategy_when_present(self) -> None:
        from unittest.mock import MagicMock

        from dd_agents.cli_auto_config import print_auto_config_summary

        config = _make_valid_claude_response()
        config["buyer_strategy"] = _make_buyer_strategy_response()["buyer_strategy"]
        scan_result = _make_scan_result()
        mock_console = MagicMock()

        print_auto_config_summary(mock_console, config, scan_result)

        # Verify Table was printed
        mock_console.print.assert_called()

    def test_works_without_buyer_strategy(self) -> None:
        from unittest.mock import MagicMock

        from dd_agents.cli_auto_config import print_auto_config_summary

        config = _make_valid_claude_response()
        scan_result = _make_scan_result()
        mock_console = MagicMock()

        print_auto_config_summary(mock_console, config, scan_result)
        mock_console.print.assert_called()


# =========================================================================
# Reference file classification tests
# =========================================================================


class TestBuyerContextClassification:
    """Tests for buyer context file classification and routing."""

    def test_buyer_context_files_classified_correctly(self) -> None:
        from dd_agents.inventory.reference_files import ReferenceFileClassifier
        from dd_agents.models.enums import ReferenceFileCategory
        from dd_agents.models.inventory import FileEntry

        classifier = ReferenceFileClassifier()
        files = [
            FileEntry(path="_buyer/10-k-business.md", text_path="_buyer/10-k-business.md"),
        ]

        result = classifier.classify(files, customer_dirs=[])
        assert len(result) == 1
        assert result[0].category == ReferenceFileCategory.BUYER_CONTEXT.value

    def test_buyer_context_routed_to_acquirer_agent(self) -> None:
        from dd_agents.inventory.reference_files import ReferenceFileClassifier
        from dd_agents.models.enums import ReferenceFileCategory

        classifier = ReferenceFileClassifier()
        agents = classifier.route_to_agents(ReferenceFileCategory.BUYER_CONTEXT)
        assert "acquirer_intelligence" in agents
        assert len(agents) == 1  # Only acquirer intelligence

    def test_10k_pattern_matches_buyer_context(self) -> None:
        from dd_agents.inventory.reference_files import ReferenceFileClassifier
        from dd_agents.models.inventory import FileEntry

        classifier = ReferenceFileClassifier()
        files = [
            FileEntry(path="ref/annual-report-2024.pdf", text_path="ref/annual-report-2024.txt"),
        ]

        result = classifier.classify(files, customer_dirs=[])
        assert len(result) == 1
        assert result[0].category == "Buyer Context"

    def test_buyer_dir_takes_precedence_over_financial(self) -> None:
        """Files in _buyer/ should be classified as buyer context even if they match financial patterns."""
        from dd_agents.inventory.reference_files import ReferenceFileClassifier
        from dd_agents.models.inventory import FileEntry

        classifier = ReferenceFileClassifier()
        files = [
            FileEntry(path="_buyer/revenue-summary.md", text_path="_buyer/revenue-summary.md"),
        ]

        result = classifier.classify(files, customer_dirs=[])
        assert len(result) == 1
        assert result[0].category == "Buyer Context"


class TestDDOutputClassification:
    """Tests for DD output / buyer work product exclusion from specialist analysis."""

    def test_readout_deck_excluded_from_reference_files(self) -> None:
        """DD readout decks must not be routed to any specialist agent."""
        from dd_agents.inventory.reference_files import ReferenceFileClassifier
        from dd_agents.models.inventory import FileEntry

        classifier = ReferenceFileClassifier()
        files = [
            FileEntry(
                path="DD readout decks/draft_readout.pptx",
                text_path="DD readout decks/draft_readout.pptx",
            ),
        ]
        result = classifier.classify(files, customer_dirs=[])
        assert len(result) == 0, "DD readout deck should be excluded from reference files"

    def test_dd_output_routed_to_no_agents(self) -> None:
        from dd_agents.inventory.reference_files import ReferenceFileClassifier
        from dd_agents.models.enums import ReferenceFileCategory

        classifier = ReferenceFileClassifier()
        agents = classifier.route_to_agents(ReferenceFileCategory.DD_OUTPUT)
        assert agents == []

    def test_internal_analysis_excluded_from_reference_files(self) -> None:
        from dd_agents.inventory.reference_files import ReferenceFileClassifier
        from dd_agents.models.inventory import FileEntry

        classifier = ReferenceFileClassifier()
        files = [
            FileEntry(
                path="3. Internal analysis/synergy_model.xlsx",
                text_path="3. Internal analysis/synergy_model.xlsx",
            ),
        ]
        result = classifier.classify(files, customer_dirs=[])
        assert len(result) == 0, "Internal analysis should be excluded from reference files"

    def test_dd_report_excluded_from_reference_files(self) -> None:
        from dd_agents.inventory.reference_files import ReferenceFileClassifier
        from dd_agents.models.inventory import FileEntry

        classifier = ReferenceFileClassifier()
        files = [
            FileEntry(path="dd-report-draft.docx", text_path="dd-report-draft.docx"),
        ]
        result = classifier.classify(files, customer_dirs=[])
        assert len(result) == 0, "DD report draft should be excluded from reference files"

    def test_synergy_model_excluded_from_reference_files(self) -> None:
        from dd_agents.inventory.reference_files import ReferenceFileClassifier
        from dd_agents.models.inventory import FileEntry

        classifier = ReferenceFileClassifier()
        files = [
            FileEntry(path="synergy_model_v2.xlsx", text_path="synergy_model_v2.xlsx"),
        ]
        result = classifier.classify(files, customer_dirs=[])
        assert len(result) == 0, "Synergy model should be excluded from reference files"

    def test_internal_analysis_takes_precedence_over_financial(self) -> None:
        """Files in 'internal analysis' dirs should be excluded even if they match financial patterns."""
        from dd_agents.inventory.reference_files import ReferenceFileClassifier
        from dd_agents.models.inventory import FileEntry

        classifier = ReferenceFileClassifier()
        files = [
            FileEntry(
                path="3. Internal analysis/Long-term income statement/financial_model.xlsx",
                text_path="3. Internal analysis/Long-term income statement/financial_model.xlsx",
            ),
        ]
        result = classifier.classify(files, customer_dirs=[])
        assert len(result) == 0, "Financial model in internal analysis dir should be excluded"

    def test_non_dd_output_still_classified(self) -> None:
        """Ensure normal reference files are still classified when DD output files are excluded."""
        from dd_agents.inventory.reference_files import ReferenceFileClassifier
        from dd_agents.models.inventory import FileEntry

        classifier = ReferenceFileClassifier()
        files = [
            FileEntry(
                path="DD readout decks/draft_readout.pptx",
                text_path="DD readout decks/draft_readout.pptx",
            ),
            FileEntry(path="revenue_summary.xlsx", text_path="revenue_summary.xlsx"),
        ]
        result = classifier.classify(files, customer_dirs=[])
        assert len(result) == 1, "Only the revenue file should remain"
        assert result[0].category == "Financial"


# =========================================================================
# CLI integration tests
# =========================================================================


class TestCliAutoConfig:
    """Tests for dd-agents auto-config CLI command."""

    def test_generates_valid_config_file(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        output = tmp_path / "out.json"
        mock_response = _make_valid_claude_response()

        runner = CliRunner()
        with patch(
            "dd_agents.cli_auto_config.DataRoomAnalyzer._call_claude",
            new_callable=AsyncMock,
            return_value=json.dumps(mock_response),
        ):
            result = runner.invoke(
                main,
                [
                    "auto-config",
                    "Apex Holdings",
                    "WidgetCo",
                    "--data-room",
                    str(dr),
                    "--output",
                    str(output),
                    "--force",
                ],
            )

        assert result.exit_code == 0, result.output
        assert output.exists()
        config = json.loads(output.read_text())
        validated = validate_deal_config(config)
        assert validated.buyer.name == "Apex Holdings, Inc."

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        output = tmp_path / "out.json"
        mock_response = _make_valid_claude_response()

        runner = CliRunner()
        with patch(
            "dd_agents.cli_auto_config.DataRoomAnalyzer._call_claude",
            new_callable=AsyncMock,
            return_value=json.dumps(mock_response),
        ):
            result = runner.invoke(
                main,
                [
                    "auto-config",
                    "Apex Holdings",
                    "WidgetCo",
                    "--data-room",
                    str(dr),
                    "--output",
                    str(output),
                    "--dry-run",
                ],
            )

        assert result.exit_code == 0, result.output
        assert not output.exists()
        # Should print the JSON to stdout
        assert "config_version" in result.output

    def test_output_path_respected(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        custom_output = tmp_path / "subdir" / "custom.json"
        mock_response = _make_valid_claude_response()

        runner = CliRunner()
        with patch(
            "dd_agents.cli_auto_config.DataRoomAnalyzer._call_claude",
            new_callable=AsyncMock,
            return_value=json.dumps(mock_response),
        ):
            result = runner.invoke(
                main,
                [
                    "auto-config",
                    "Apex Holdings",
                    "WidgetCo",
                    "--data-room",
                    str(dr),
                    "--output",
                    str(custom_output),
                ],
            )

        assert result.exit_code == 0, result.output
        assert custom_output.exists()

    def test_force_overwrites(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        output = tmp_path / "out.json"
        output.write_text("{}")
        mock_response = _make_valid_claude_response()

        runner = CliRunner()
        with patch(
            "dd_agents.cli_auto_config.DataRoomAnalyzer._call_claude",
            new_callable=AsyncMock,
            return_value=json.dumps(mock_response),
        ):
            result = runner.invoke(
                main,
                [
                    "auto-config",
                    "Apex Holdings",
                    "WidgetCo",
                    "--data-room",
                    str(dr),
                    "--output",
                    str(output),
                    "--force",
                ],
            )

        assert result.exit_code == 0, result.output
        config = json.loads(output.read_text())
        assert config["buyer"]["name"] == "Apex Holdings, Inc."

    def test_buyer_and_target_appear_in_output(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        mock_response = _make_valid_claude_response()

        runner = CliRunner()
        with patch(
            "dd_agents.cli_auto_config.DataRoomAnalyzer._call_claude",
            new_callable=AsyncMock,
            return_value=json.dumps(mock_response),
        ):
            result = runner.invoke(
                main,
                [
                    "auto-config",
                    "Apex Holdings",
                    "WidgetCo",
                    "--data-room",
                    str(dr),
                    "--dry-run",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "Apex Holdings" in result.output
        assert "WidgetCo" in result.output

    def test_nonexistent_data_room_fails(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "auto-config",
                "Buyer",
                "Target",
                "--data-room",
                str(tmp_path / "nonexistent"),
            ],
        )
        assert result.exit_code != 0

    def test_help_shows_buyer_and_target(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["auto-config", "--help"])
        assert result.exit_code == 0
        assert "BUYER" in result.output
        assert "TARGET" in result.output
        assert "acquiring company" in result.output

    def test_help_shows_new_options(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["auto-config", "--help"])
        assert result.exit_code == 0
        assert "--buyer-docs" in result.output
        assert "--spa" in result.output
        assert "--press-release" in result.output
        assert "--buyer-docs-dir" in result.output
        assert "--interactive" in result.output

    def test_backward_compatible_no_buyer_docs(self, tmp_path: Path) -> None:
        """Without --buyer-docs, no buyer_strategy is generated (same as before)."""
        dr = _create_data_room(tmp_path)
        output = tmp_path / "compat.json"
        mock_response = _make_valid_claude_response()

        runner = CliRunner()
        with patch(
            "dd_agents.cli_auto_config.DataRoomAnalyzer._call_claude",
            new_callable=AsyncMock,
            return_value=json.dumps(mock_response),
        ):
            result = runner.invoke(
                main,
                [
                    "auto-config",
                    "Apex Holdings",
                    "WidgetCo",
                    "--data-room",
                    str(dr),
                    "--output",
                    str(output),
                    "--force",
                ],
            )

        assert result.exit_code == 0, result.output
        assert output.exists()
        output_config = json.loads(output.read_text())
        assert "buyer_strategy" not in output_config

    def test_with_buyer_docs_generates_strategy(self, tmp_path: Path) -> None:
        """With --buyer-docs, buyer_strategy is generated."""
        dr = _create_data_room(tmp_path)
        buyer_doc = tmp_path / "10k.txt"
        buyer_doc.write_text("Annual report: We are a technology company.")

        base_response = _make_valid_claude_response()
        strategy_response = _make_buyer_strategy_response()

        call_count = 0
        responses = [json.dumps(base_response), json.dumps(strategy_response)]

        async def mock_call(system: str, user: str) -> str:
            nonlocal call_count
            idx = min(call_count, len(responses) - 1)
            call_count += 1
            return responses[idx]

        runner = CliRunner()
        with patch(
            "dd_agents.cli_auto_config.DataRoomAnalyzer._call_claude",
            side_effect=mock_call,
        ):
            result = runner.invoke(
                main,
                [
                    "auto-config",
                    "Apex Holdings",
                    "WidgetCo",
                    "--data-room",
                    str(dr),
                    "--buyer-docs",
                    str(buyer_doc),
                    "--dry-run",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "buyer_strategy" in result.output
        # Buyer doc should be converted and placed in _buyer/
        assert (dr / "_buyer" / "10k.md").exists()
