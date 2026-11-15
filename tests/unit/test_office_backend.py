"""Tests for the optional anydoc Office backend (``extraction.office_backend``, Issue #272).

Real conversions use the synthetic corpus and skip when ``anydoc`` is not installed.
Fallback paths use mocks so they run everywhere.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from dd_agents.extraction import anydoc_backend
from dd_agents.extraction.markitdown import MarkitdownExtractor
from dd_agents.extraction.ocr_registry import build_extraction_pipeline
from dd_agents.extraction.pipeline import ExtractionPipeline
from dd_agents.models.config import ExtractionConfig

CORPUS = Path(__file__).resolve().parent.parent / "fixtures" / "extraction_corpus"
HAS_ANYDOC = importlib.util.find_spec("anydoc") is not None
needs_anydoc = pytest.mark.skipif(not HAS_ANYDOC, reason="anydoc is not installed")

GOOD_TEXT = "# Agreement\n\nThis agreement is made between Subject A Ltd and Subject B Ltd. " * 3


def _phrases(name: str) -> list[str]:
    data = json.loads((CORPUS / "ground_truth.json").read_text(encoding="utf-8"))
    return list(data["files"][name]["key_phrases"])


def _fake_markitdown(text: str = GOOD_TEXT) -> Any:
    md = MagicMock(spec=MarkitdownExtractor)
    md.extract.return_value = (text, 0.9)
    return md


def _pipeline(backend: str, md: Any = None) -> ExtractionPipeline:
    return ExtractionPipeline(markitdown=md or _fake_markitdown(), office_backend=backend)


def _copy(name: str, tmp_path: Path) -> Path:
    dest = tmp_path / name
    dest.write_bytes((CORPUS / name).read_bytes())
    return dest


@pytest.fixture(autouse=True)
def _reset_warning_flag() -> None:
    anydoc_backend._reset_warning_for_tests()


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestConfig:
    def test_default_is_markitdown(self) -> None:
        assert ExtractionConfig().office_backend == "markitdown"

    def test_anydoc_is_accepted(self) -> None:
        assert ExtractionConfig(office_backend="anydoc").office_backend == "anydoc"

    @pytest.mark.parametrize("bad", ["Anydoc", "libreoffice", "", "auto"])
    def test_unknown_value_is_rejected(self, bad: str) -> None:
        with pytest.raises(ValidationError):
            ExtractionConfig(office_backend=bad)  # type: ignore[arg-type]


class TestBuildPipeline:
    def test_default(self) -> None:
        assert build_extraction_pipeline()._office_backend == "markitdown"

    def test_from_dict(self) -> None:
        pipeline = build_extraction_pipeline({"extraction": {"office_backend": "anydoc"}})
        assert pipeline._office_backend == "anydoc"

    def test_from_typed_config(self) -> None:
        cfg = MagicMock()
        cfg.extraction = ExtractionConfig(office_backend="anydoc")
        assert build_extraction_pipeline(cfg)._office_backend == "anydoc"

    def test_bad_dict_value_raises(self) -> None:
        with pytest.raises(ValueError, match="office_backend"):
            build_extraction_pipeline({"extraction": {"office_backend": "nope"}})

    def test_pipeline_rejects_unknown_backend(self) -> None:
        with pytest.raises(ValueError, match="office_backend"):
            ExtractionPipeline(office_backend="nope")


# ---------------------------------------------------------------------------
# Real conversions (need anydoc)
# ---------------------------------------------------------------------------


@needs_anydoc
class TestRealConversion:
    @pytest.mark.parametrize(
        "name",
        [
            "office_contract_en.docx",
            "office_contract_ja.docx",
            "office_tracked_changes_en.docx",
            "people_officers_en.docx",
            "office_board_deck_en.pptx",
        ],
    )
    def test_office_file_uses_anydoc_and_keeps_phrases(self, name: str, tmp_path: Path) -> None:
        md = _fake_markitdown()
        entry = _pipeline("anydoc", md).extract_single(_copy(name, tmp_path), tmp_path / "out")
        assert entry.fallback_chain == ["anydoc"]
        assert entry.method == "primary"
        assert entry.confidence > 0
        md.extract.assert_not_called()
        text = (tmp_path / "out" / ExtractionPipeline._safe_text_name(str(tmp_path / name))).read_text(encoding="utf-8")
        flat = " ".join(text.split())
        missing = [p for p in _phrases(name) if " ".join(p.split()) not in flat]
        assert not missing, f"anydoc lost phrases: {missing}"

    def test_xlsx_openpyxl_stays_primary(self, tmp_path: Path) -> None:
        md = _fake_markitdown()
        entry = _pipeline("anydoc", md).extract_single(_copy("office_arr_schedule_en.xlsx", tmp_path), tmp_path / "out")
        assert entry.fallback_chain == ["openpyxl"]
        md.extract.assert_not_called()

    def test_xlsx_fallback_uses_anydoc_before_markitdown(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ExtractionPipeline, "_read_xlsx", staticmethod(lambda _p: (None, 0.0)))
        md = _fake_markitdown()
        entry = _pipeline("anydoc", md).extract_single(_copy("office_arr_schedule_en.xlsx", tmp_path), tmp_path / "out")
        assert entry.fallback_chain == ["anydoc"]
        md.extract.assert_not_called()

    def test_html_is_unsupported_and_stays_on_markitdown(self, tmp_path: Path) -> None:
        md = _fake_markitdown()
        entry = _pipeline("anydoc", md).extract_single(_copy("office_terms_en.html", tmp_path), tmp_path / "out")
        assert entry.fallback_chain == ["markitdown"]
        md.extract.assert_called_once()

    def test_default_backend_never_calls_anydoc(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        boom = MagicMock(side_effect=AssertionError("anydoc must not run"))
        monkeypatch.setattr(anydoc_backend, "extract", boom)
        md = _fake_markitdown()
        entry = _pipeline("markitdown", md).extract_single(_copy("office_contract_en.docx", tmp_path), tmp_path / "out")
        assert entry.fallback_chain == ["markitdown"]
        boom.assert_not_called()

    def test_corrupt_docx_falls_back_to_markitdown(self, tmp_path: Path) -> None:
        bad = tmp_path / "broken.docx"
        bad.write_bytes(b"PK\x03\x04not really a zip")
        md = _fake_markitdown()
        entry = _pipeline("anydoc", md).extract_single(bad, tmp_path / "out")
        assert entry.fallback_chain[:2] == ["anydoc", "markitdown"]
        assert entry.method == "fallback_markitdown"


# ---------------------------------------------------------------------------
# Fallback paths (mocked)
# ---------------------------------------------------------------------------


def _docx(tmp_path: Path) -> Path:
    path = tmp_path / "a.docx"
    path.write_bytes(b"PK\x03\x04" + b"\x00" * 600)
    return path


class TestFallbackWithMocks:
    def test_anydoc_raising_falls_back(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(anydoc_backend, "extract", MagicMock(return_value=("", 0.0)))
        md = _fake_markitdown()
        entry = _pipeline("anydoc", md).extract_single(_docx(tmp_path), tmp_path / "out")
        assert entry.fallback_chain == ["anydoc", "markitdown"]
        assert entry.method == "fallback_markitdown"
        assert any(r.startswith("anydoc:") for r in entry.failure_reasons)

    def test_anydoc_text_failing_quality_gate_falls_back(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        garbage = ("\x00\x01\x02\x03" * 60) + "x" * 40
        monkeypatch.setattr(anydoc_backend, "extract", MagicMock(return_value=(garbage, 0.9)))
        md = _fake_markitdown()
        entry = _pipeline("anydoc", md).extract_single(_docx(tmp_path), tmp_path / "out")
        assert entry.fallback_chain == ["anydoc", "markitdown"]
        assert entry.method == "fallback_markitdown"

    def test_anydoc_success_skips_markitdown(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(anydoc_backend, "extract", MagicMock(return_value=(GOOD_TEXT, 0.9)))
        md = _fake_markitdown()
        entry = _pipeline("anydoc", md).extract_single(_docx(tmp_path), tmp_path / "out")
        assert entry.fallback_chain == ["anydoc"]
        md.extract.assert_not_called()

    def test_unsupported_suffix_never_asks_anydoc(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        probe = MagicMock(return_value=(GOOD_TEXT, 0.9))
        monkeypatch.setattr(anydoc_backend, "extract", probe)
        html = tmp_path / "page.html"
        html.write_text("<html><body>" + GOOD_TEXT + "</body></html>", encoding="utf-8")
        entry = _pipeline("anydoc").extract_single(html, tmp_path / "out")
        assert entry.fallback_chain == ["markitdown"]
        probe.assert_not_called()


# ---------------------------------------------------------------------------
# The backend module itself
# ---------------------------------------------------------------------------


class TestBackendModule:
    def test_supported_extensions(self) -> None:
        assert frozenset({".docx", ".pptx", ".xlsx"}) == anydoc_backend.ANYDOC_EXTENSIONS

    def test_missing_package_warns_once_and_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setitem(sys.modules, "anydoc", None)
        caplog.set_level(logging.WARNING, logger="dd_agents.extraction.anydoc_backend")
        target = tmp_path / "a.docx"
        target.write_bytes(b"PK")
        assert anydoc_backend.extract(target) == ("", 0.0)
        assert anydoc_backend.extract(target) == ("", 0.0)
        warnings = [r for r in caplog.records if "pip install" in r.getMessage()]
        assert len(warnings) == 1
        assert "office-fast" in warnings[0].getMessage()

    def test_pipeline_survives_missing_package(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "anydoc", None)
        md = _fake_markitdown()
        entry = _pipeline("anydoc", md).extract_single(_docx(tmp_path), tmp_path / "out")
        assert entry.fallback_chain == ["anydoc", "markitdown"]
        assert entry.method == "fallback_markitdown"

    def test_conversion_error_returns_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake: Any = MagicMock()
        fake.to_markdown.side_effect = RuntimeError("boom")
        monkeypatch.setitem(sys.modules, "anydoc", fake)
        assert anydoc_backend.extract(tmp_path / "a.docx") == ("", 0.0)

    def test_never_uses_hosted_ocr(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Hosted OCR uploads the file to a third-party API. It must never be requested."""
        fake: Any = MagicMock()
        fake.to_markdown.return_value = GOOD_TEXT
        monkeypatch.setitem(sys.modules, "anydoc", fake)
        text, conf = anydoc_backend.extract(tmp_path / "a.docx")
        assert text == GOOD_TEXT
        assert conf > 0
        _, kwargs = fake.to_markdown.call_args
        assert kwargs.get("ocr") == "reject"
        assert "api_key" not in kwargs
        assert "api_url" not in kwargs

    def test_blank_output_is_failure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake: Any = MagicMock()
        fake.to_markdown.return_value = "   \n"
        monkeypatch.setitem(sys.modules, "anydoc", fake)
        assert anydoc_backend.extract(tmp_path / "a.docx") == ("", 0.0)
