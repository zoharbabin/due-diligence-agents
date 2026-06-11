"""Tests for DD_VISION_MODEL provenance + completeness/integrity KB compounding (#248)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from dd_agents.knowledge.base import DealKnowledgeBase
from dd_agents.knowledge.compiler import KnowledgeCompiler
from dd_agents.llm import resolve_provider

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


class TestVisionModelInFingerprint:
    def test_fingerprint_busts_on_vision_model_change(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
        monkeypatch.setenv("DD_VISION_MODEL", "claude-sonnet-4-6")
        fp1 = resolve_provider().fingerprint()
        monkeypatch.setenv("DD_VISION_MODEL", "some-other-vision-model")
        fp2 = resolve_provider().fingerprint()
        assert fp1 != fp2

    def test_fingerprint_stable_when_vision_model_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
        monkeypatch.setenv("DD_VISION_MODEL", "claude-sonnet-4-6")
        assert resolve_provider().fingerprint() == resolve_provider().fingerprint()

    def test_fingerprint_secret_free(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The vision model id is not a secret; the fingerprint must still carry no URL creds.
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://tok:pw@gw.example/v1")  # pragma: allowlist secret
        monkeypatch.setenv("DD_VISION_MODEL", "m")
        fp = resolve_provider().fingerprint()
        assert "pw@" not in fp and "tok:" not in fp


class TestCompletenessSignalsKB:
    def _kb(self, tmp_path: Path) -> DealKnowledgeBase:
        kb = DealKnowledgeBase(tmp_path)
        kb.ensure_dirs()
        return kb

    def _write_inventory(self, tmp_path: Path, request_list: dict | None, formula: dict | None) -> None:  # type: ignore[type-arg]
        inv = tmp_path / "_dd" / "forensic-dd" / "inventory"
        inv.mkdir(parents=True, exist_ok=True)
        if request_list is not None:
            (inv / "request_list.json").write_text(json.dumps(request_list))
        if formula is not None:
            (inv / "formula_audit.json").write_text(json.dumps(formula))

    def _run_dir(self, tmp_path: Path) -> Path:
        rd = tmp_path / "_dd" / "forensic-dd" / "runs" / "r1"
        (rd / "findings" / "merged").mkdir(parents=True, exist_ok=True)
        return rd

    def test_compiles_deal_signal_article(self, tmp_path: Path) -> None:
        self._write_inventory(
            tmp_path,
            {"received": ["MSA"], "missing_required": ["Audited Financials"], "missing_optional": []},
            {"total_issues": 2, "by_kind": {"hardcoded_override": 2}, "files_with_formulas": 1},
        )
        kb = self._kb(tmp_path)
        KnowledgeCompiler(kb).compile_from_run(self._run_dir(tmp_path), "r1")
        article = kb.get_article("deal_completeness_integrity")
        assert article is not None
        assert article.content["latest_missing_required_docs"] == 1
        assert article.content["latest_formula_issues_total"] == 2
        assert len(article.content["cross_run_history"]) == 1

    def test_compounds_across_runs(self, tmp_path: Path) -> None:
        self._write_inventory(tmp_path, {"received": [], "missing_required": ["A"]}, None)
        kb = self._kb(tmp_path)
        KnowledgeCompiler(kb).compile_from_run(self._run_dir(tmp_path), "r1")
        # Second run: another missing doc.
        self._write_inventory(tmp_path, {"received": ["A"], "missing_required": ["B"]}, None)
        KnowledgeCompiler(kb).compile_from_run(self._run_dir(tmp_path), "r2")
        article = kb.get_article("deal_completeness_integrity")
        assert article is not None
        assert len(article.content["cross_run_history"]) == 2

    def test_noop_when_no_inventory_artifacts(self, tmp_path: Path) -> None:
        kb = self._kb(tmp_path)
        KnowledgeCompiler(kb).compile_from_run(self._run_dir(tmp_path), "r1")
        assert kb.get_article("deal_completeness_integrity") is None
