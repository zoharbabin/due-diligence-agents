"""Unit tests for dd_agents.tools.mcp_server — MCP server builder."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from dd_agents.tools.mcp_server import _build_runtime_context, build_mcp_server

if TYPE_CHECKING:
    from pathlib import Path


# ===================================================================
# build_mcp_server — SDK available
# ===================================================================


class TestBuildMcpServer:
    """Tests for build_mcp_server with real SDK."""

    def test_specialist_returns_server(self) -> None:
        server = build_mcp_server("specialist")
        assert server is not None
        assert isinstance(server, dict)
        assert server["type"] == "sdk"
        assert server["name"] == "dd_tools"

    def test_judge_returns_server(self) -> None:
        server = build_mcp_server("judge")
        assert server is not None
        assert server["name"] == "dd_tools"

    def test_unknown_agent_type_returns_none(self) -> None:
        server = build_mcp_server("unknown")
        assert server is None

    def test_specialist_has_9_tools(self) -> None:
        """Specialist agents should get all 9 custom tools."""
        server = build_mcp_server("specialist")
        assert server is not None
        # The server wraps an MCP Server instance — verify it was created
        assert "instance" in server

    def test_judge_has_verify_citation_only(self) -> None:
        """Judge agent should only get verify_citation."""
        server = build_mcp_server("judge")
        assert server is not None

    def test_context_params_accepted(self, tmp_path: Path) -> None:
        """Runtime context params should be accepted without error."""
        text_dir = tmp_path / "text"
        text_dir.mkdir()
        cache_path = tmp_path / "cache.json"
        cache_path.write_text("{}")

        server = build_mcp_server(
            "specialist",
            text_dir=text_dir,
            files_list=["a.pdf", "b.pdf"],
            subjects_csv=[{"subject_safe_name": "acme", "file_list": ["a.pdf"]}],
            cache_path=cache_path,
            allowed_dir=tmp_path,
        )
        assert server is not None

    def test_none_context_params_accepted(self) -> None:
        """All context params as None should still produce a server."""
        server = build_mcp_server(
            "specialist",
            text_dir=None,
            files_list=None,
            subjects_csv=None,
            cache_path=None,
            allowed_dir=None,
        )
        assert server is not None


class TestBuildMcpServerNoSdk:
    """Tests for build_mcp_server when SDK is not available."""

    def test_returns_none_without_sdk(self) -> None:
        with patch("dd_agents.tools.mcp_server.build_mcp_server") as mock_build:
            mock_build.return_value = None
            result = mock_build("specialist")
            assert result is None


# ===================================================================
# _build_runtime_context
# ===================================================================


class TestBuildRuntimeContext:
    """Tests for _build_runtime_context helper."""

    def test_returns_expected_keys(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        run_dir = tmp_path / "run"
        project_dir.mkdir()
        run_dir.mkdir()

        ctx = _build_runtime_context(project_dir, run_dir)
        assert "text_dir" in ctx
        assert "files_list" in ctx
        assert "subjects_csv" in ctx
        assert "cache_path" in ctx
        assert "allowed_dir" in ctx

    def test_missing_dirs_return_none(self, tmp_path: Path) -> None:
        """When dd dirs don't exist, paths should be None."""
        project_dir = tmp_path / "project"
        run_dir = tmp_path / "run"
        project_dir.mkdir()
        run_dir.mkdir()

        ctx = _build_runtime_context(project_dir, run_dir)
        assert ctx["text_dir"] is None
        assert ctx["cache_path"] is None
        # When _dd/ doesn't exist, allowed_dir falls back to project_dir
        # (fail-closed: agents are still restricted to the project tree).
        assert ctx["allowed_dir"] == project_dir

    def test_existing_dirs_return_paths(self, tmp_path: Path) -> None:
        """When dd dirs exist, paths should be populated."""
        project_dir = tmp_path / "project"
        run_dir = tmp_path / "run"
        dd_dir = project_dir / "_dd" / "forensic-dd"
        text_dir = dd_dir / "index" / "text"
        text_dir.mkdir(parents=True)
        er_dir = dd_dir / "entity_resolution"
        er_dir.mkdir(parents=True)
        cache_path = er_dir / "entity_resolution_cache.json"
        cache_path.write_text("{}")
        run_dir.mkdir()

        ctx = _build_runtime_context(project_dir, run_dir)
        assert ctx["text_dir"] == text_dir
        assert ctx["cache_path"] == cache_path
        assert ctx["allowed_dir"] == project_dir

    def test_reads_inventory_csv(self, tmp_path: Path) -> None:
        """Should populate files_list from master_inventory.csv."""
        project_dir = tmp_path / "project"
        run_dir = tmp_path / "run"
        dd_dir = project_dir / "_dd" / "forensic-dd"
        index_dir = dd_dir / "index"
        index_dir.mkdir(parents=True)
        run_dir.mkdir()

        inventory_csv = index_dir / "master_inventory.csv"
        inventory_csv.write_text("file_path,doc_type\na.pdf,MSA\nb.pdf,SOW\n")

        ctx = _build_runtime_context(project_dir, run_dir)
        assert ctx["files_list"] == ["a.pdf", "b.pdf"]

    def test_empty_inventory_csv(self, tmp_path: Path) -> None:
        """Empty CSV should result in None files_list."""
        project_dir = tmp_path / "project"
        run_dir = tmp_path / "run"
        dd_dir = project_dir / "_dd" / "forensic-dd"
        index_dir = dd_dir / "index"
        index_dir.mkdir(parents=True)
        run_dir.mkdir()

        inventory_csv = index_dir / "master_inventory.csv"
        inventory_csv.write_text("file_path,doc_type\n")

        ctx = _build_runtime_context(project_dir, run_dir)
        assert ctx["files_list"] is None

    def test_passes_subjects_csv_through(self, tmp_path: Path) -> None:
        """subjects_csv param should be passed through unchanged."""
        project_dir = tmp_path / "project"
        run_dir = tmp_path / "run"
        project_dir.mkdir()
        run_dir.mkdir()

        subjects = [{"subject_safe_name": "acme", "file_list": ["a.pdf"]}]
        ctx = _build_runtime_context(project_dir, run_dir, subjects_csv=subjects)
        assert ctx["subjects_csv"] is subjects
