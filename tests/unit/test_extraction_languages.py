"""Per-language OCR configuration and checks (Issue #263). No tesseract needed."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Any

import pytest
from click.testing import CliRunner
from pydantic import ValidationError

from dd_agents.extraction import languages as langs
from dd_agents.extraction.ocr import OCRExtractor
from dd_agents.extraction.ocr_registry import build_extraction_pipeline
from dd_agents.models.config import ExtractionConfig

if TYPE_CHECKING:
    from pathlib import Path


class TestCodes:
    @pytest.mark.parametrize("code", ["eng", "deu", "chi_sim", "srp_latn", "script/Cyrillic"])
    def test_valid(self, code: str) -> None:
        assert langs.validate_language_codes([code]) == [code]

    @pytest.mark.parametrize("code", ["", "en", "english", "DEU", "deu+fra", "a b", "../x", "deu;rm"])
    def test_invalid(self, code: str) -> None:
        with pytest.raises(ValueError, match="language"):
            langs.validate_language_codes([code])

    def test_empty_list_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            langs.validate_language_codes([])

    def test_duplicates_removed_in_order(self) -> None:
        assert langs.validate_language_codes(["deu", "eng", "deu"]) == ["deu", "eng"]


class TestConfig:
    def test_default_is_english(self) -> None:
        assert ExtractionConfig().ocr_languages == ["eng"]

    def test_accepts_list(self) -> None:
        assert ExtractionConfig(ocr_languages=["deu", "eng"]).ocr_languages == ["deu", "eng"]

    def test_rejects_bad_code(self) -> None:
        with pytest.raises(ValidationError):
            ExtractionConfig(ocr_languages=["english"])


class TestOcrWiring:
    def test_default_lang_string(self) -> None:
        assert OCRExtractor().lang == "eng"

    def test_lang_string_joins_with_plus(self) -> None:
        assert OCRExtractor(languages=["deu", "eng"]).lang == "deu+eng"

    def test_do_extract_passes_lang(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        class FakeTess:
            @staticmethod
            def image_to_string(img: object, lang: str) -> str:
                calls.append(lang)
                return "text"

        img_path = tmp_path / "a.png"
        img_path.write_bytes(b"x")
        monkeypatch.setattr(OCRExtractor, "_load_image", staticmethod(lambda _p: [object()]))
        text, _ = OCRExtractor(languages=["fra"])._do_extract(img_path, tmp_path, FakeTess(), "fra")
        assert calls == ["fra"]
        assert "text" in text

    @pytest.mark.parametrize("cfg", [{"extraction": {"ocr_languages": ["deu", "eng"]}}])
    def test_pipeline_uses_config_languages(self, cfg: dict[str, Any]) -> None:
        pipeline = build_extraction_pipeline(cfg)
        assert pipeline._ocr.lang == "deu+eng"

    def test_pipeline_default_languages(self) -> None:
        assert build_extraction_pipeline()._ocr.lang == "eng"


class TestInstalled:
    def test_none_when_tesseract_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(langs.shutil, "which", lambda _name: None)
        assert langs.installed_tesseract_languages() is None

    def test_parses_list_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(langs.shutil, "which", lambda _name: "/usr/bin/tesseract")

        def fake_run(*_a: Any, **_k: Any) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=[], returncode=0, stdout='List of available languages in "/x/" (3):\neng\nosd\ndeu\n', stderr=""
            )

        monkeypatch.setattr(langs.subprocess, "run", fake_run)
        assert langs.installed_tesseract_languages() == ["deu", "eng"]

    def test_none_on_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(langs.shutil, "which", lambda _name: "/usr/bin/tesseract")

        def boom(*_a: Any, **_k: Any) -> None:
            raise subprocess.TimeoutExpired("tesseract", 1)

        monkeypatch.setattr(langs.subprocess, "run", boom)
        assert langs.installed_tesseract_languages() is None


class TestSetup:
    def test_missing_packs(self) -> None:
        setup = langs.check_language_setup(["deu", "eng"], ["eng", "osd"])
        assert setup.missing == ["deu"]
        assert not setup.ok

    def test_all_present(self) -> None:
        assert langs.check_language_setup(["eng"], ["eng"]).ok

    def test_unknown_install_state(self) -> None:
        setup = langs.check_language_setup(["eng"], None)
        assert setup.installed is None
        assert not setup.ok
        assert setup.missing == []

    def test_script_model_counts_as_installed(self) -> None:
        assert langs.check_language_setup(["script/Cyrillic"], ["script/Cyrillic"]).ok


class TestScripts:
    def test_counts_letters_only(self) -> None:
        counts = langs.script_counts("Hello 123 мир 世界!")
        assert counts == {"LATIN": 5, "CYRILLIC": 3, "HAN": 2}

    def test_japanese_kana(self) -> None:
        counts = langs.script_counts("こんにちはカタカナ")
        assert counts["HIRAGANA"] == 5
        assert counts["KATAKANA"] == 4

    def test_warns_when_script_has_no_language(self) -> None:
        text = "Договор поставки между сторонами. " * 5
        warnings = langs.script_warnings(text, ["eng"])
        assert len(warnings) == 1
        assert "CYRILLIC" in warnings[0]
        assert "rus" in warnings[0]

    def test_no_warning_when_language_covers_script(self) -> None:
        text = "Договор поставки между сторонами. " * 5
        assert langs.script_warnings(text, ["rus", "eng"]) == []

    def test_script_model_covers(self) -> None:
        text = "合同 双方 协议 条款 " * 10
        assert langs.script_warnings(text, ["script/HanS"]) == []

    def test_japanese_needs_jpn(self) -> None:
        text = "契約書です。これは売買契約です。" * 5
        assert langs.script_warnings(text, ["chi_sim"]) != []
        assert langs.script_warnings(text, ["jpn"]) == []

    def test_small_share_ignored(self) -> None:
        text = "This contract is governed by English law. " * 10 + "мир"
        assert langs.script_warnings(text, ["eng"]) == []

    def test_latin_never_warns(self) -> None:
        assert langs.script_warnings("Gesellschaft mit beschränkter Haftung " * 5, ["eng"]) == []

    def test_empty_text(self) -> None:
        assert langs.script_warnings("", ["eng"]) == []


class TestCli:
    def _invoke(self, args: list[str]) -> Any:
        from dd_agents.cli import main

        return CliRunner().invoke(main, ["extraction", "check", *args])

    def test_reports_missing_pack(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("dd_agents.cli_extraction.installed_tesseract_languages", lambda: ["eng"])
        result = self._invoke(["--languages", "deu,eng"])
        assert result.exit_code == 1
        assert "deu" in result.output
        assert "missing" in result.output.lower()

    def test_ok_when_installed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("dd_agents.cli_extraction.installed_tesseract_languages", lambda: ["eng", "deu"])
        result = self._invoke(["--languages", "deu,eng"])
        assert result.exit_code == 0

    def test_bad_code_is_a_usage_error(self) -> None:
        result = self._invoke(["--languages", "english"])
        assert result.exit_code != 0
        assert "language" in result.output.lower()

    def test_reads_languages_from_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import json

        cfg = tmp_path / "deal.json"
        cfg.write_text(
            json.dumps(
                {
                    "config_version": "1.0.0",
                    "buyer": {"name": "Buyer A"},
                    "target": {"name": "Subject A"},
                    "deal": {"type": "acquisition", "focus_areas": ["change_of_control"]},
                    "extraction": {"ocr_languages": ["fra"]},
                }
            )
        )
        monkeypatch.setattr("dd_agents.cli_extraction.installed_tesseract_languages", lambda: ["eng"])
        result = self._invoke(["--config", str(cfg)])
        assert result.exit_code == 1
        assert "fra" in result.output

    def test_file_check_warns_on_script_mismatch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("dd_agents.cli_extraction.installed_tesseract_languages", lambda: ["eng"])
        sample = tmp_path / "sample.txt"
        sample.write_text("Договор поставки между сторонами. " * 10, encoding="utf-8")
        result = self._invoke(["--languages", "eng", str(sample)])
        assert result.exit_code == 1
        assert "CYRILLIC" in result.output


class TestCorpusScripts:
    """Script checks against the synthetic corpus (ground-truth phrases per language)."""

    @staticmethod
    def _text(language: str) -> str:
        import json
        from pathlib import Path

        truth = Path(__file__).parent.parent / "fixtures" / "extraction_corpus" / "ground_truth.json"
        files = json.loads(truth.read_text())["files"]
        pdfs = [e for e in files.values() if e["language"] == language and e["kind"] == "pdf"]
        return " ".join(p for e in pdfs for p in e["key_phrases"])

    @pytest.mark.parametrize(
        ("language", "good", "bad"),
        [("ja", ["jpn"], ["eng"]), ("zh", ["chi_sim"], ["eng"]), ("ko", ["kor"], ["eng"])],
    )
    def test_cjk_languages(self, language: str, good: list[str], bad: list[str]) -> None:
        text = self._text(language)
        assert text
        assert langs.script_warnings(text, good + ["eng"]) == []
        assert langs.script_warnings(text, bad)

    @pytest.mark.parametrize("language", ["en", "de", "fr", "es"])
    def test_latin_languages_never_warn(self, language: str) -> None:
        assert langs.script_warnings(self._text(language), ["eng"]) == []
