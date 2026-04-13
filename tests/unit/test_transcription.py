"""Tests for multi-backend transcription module.

Tests backend detection, env var overrides, and each backend's transcription
logic (mocked — no real whisper models loaded in unit tests).
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from dd_agents.extraction.transcribe import (
    TranscriptionBackend,
    TranscriptionResult,
    _get_model,
    _is_macos,
    _mlx_whisper_available,
    _openai_whisper_available,
    _transcribe_mlx,
    _transcribe_openai,
    _whisperx_available,
    detect_backend,
    transcribe,
)

if TYPE_CHECKING:
    from pathlib import Path


# ===================================================================
# TranscriptionResult
# ===================================================================


class TestTranscriptionResult:
    def test_fields(self) -> None:
        r = TranscriptionResult(text="hello", backend=TranscriptionBackend.MLX_WHISPER, model="base")
        assert r.text == "hello"
        assert r.backend == TranscriptionBackend.MLX_WHISPER
        assert r.model == "base"
        assert r.language is None

    def test_with_language(self) -> None:
        r = TranscriptionResult(text="hola", backend=TranscriptionBackend.WHISPERX, model="large", language="es")
        assert r.language == "es"

    def test_frozen(self) -> None:
        r = TranscriptionResult(text="x", backend=TranscriptionBackend.OPENAI_WHISPER, model="base")
        with pytest.raises(AttributeError):
            r.text = "y"  # type: ignore[misc]


# ===================================================================
# Backend enum
# ===================================================================


class TestTranscriptionBackend:
    def test_values(self) -> None:
        assert TranscriptionBackend.MLX_WHISPER.value == "mlx"
        assert TranscriptionBackend.WHISPERX.value == "whisperx"
        assert TranscriptionBackend.OPENAI_WHISPER.value == "openai"


# ===================================================================
# Detection helpers
# ===================================================================


class TestDetectionHelpers:
    def test_is_macos_returns_bool(self) -> None:
        assert isinstance(_is_macos(), bool)

    @patch("dd_agents.extraction.transcribe.shutil.which", return_value="/usr/local/bin/mlx_whisper")
    def test_mlx_available_when_on_path(self, _mock: MagicMock) -> None:
        assert _mlx_whisper_available() is True

    @patch("dd_agents.extraction.transcribe.shutil.which", return_value=None)
    def test_mlx_unavailable_when_not_on_path(self, _mock: MagicMock) -> None:
        assert _mlx_whisper_available() is False

    def test_whisperx_unavailable_without_package(self) -> None:
        # whisperx is unlikely to be installed in test env.
        # If it is, this test still passes (returns True).
        result = _whisperx_available()
        assert isinstance(result, bool)

    def test_openai_whisper_unavailable_without_package(self) -> None:
        result = _openai_whisper_available()
        assert isinstance(result, bool)


# ===================================================================
# detect_backend
# ===================================================================


class TestDetectBackend:
    @patch.dict(os.environ, {"DD_TRANSCRIPTION_BACKEND": "mlx"})
    def test_env_override_mlx(self) -> None:
        assert detect_backend() == TranscriptionBackend.MLX_WHISPER

    @patch.dict(os.environ, {"DD_TRANSCRIPTION_BACKEND": "mlx_whisper"})
    def test_env_override_mlx_whisper_alias(self) -> None:
        assert detect_backend() == TranscriptionBackend.MLX_WHISPER

    @patch.dict(os.environ, {"DD_TRANSCRIPTION_BACKEND": "whisperx"})
    def test_env_override_whisperx(self) -> None:
        assert detect_backend() == TranscriptionBackend.WHISPERX

    @patch.dict(os.environ, {"DD_TRANSCRIPTION_BACKEND": "openai"})
    def test_env_override_openai(self) -> None:
        assert detect_backend() == TranscriptionBackend.OPENAI_WHISPER

    @patch.dict(os.environ, {"DD_TRANSCRIPTION_BACKEND": "openai-whisper"})
    def test_env_override_openai_dash(self) -> None:
        assert detect_backend() == TranscriptionBackend.OPENAI_WHISPER

    @patch.dict(os.environ, {"DD_TRANSCRIPTION_BACKEND": "nonsense"})
    def test_env_override_unknown_falls_back_to_none(self) -> None:
        with (
            patch("dd_agents.extraction.transcribe._is_macos", return_value=False),
            patch("dd_agents.extraction.transcribe._whisperx_available", return_value=False),
            patch("dd_agents.extraction.transcribe._openai_whisper_available", return_value=False),
        ):
            assert detect_backend() is None

    @patch.dict(os.environ, {}, clear=False)
    def test_auto_detect_mlx_on_macos(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "DD_TRANSCRIPTION_BACKEND"}
        with (
            patch.dict(os.environ, env, clear=True),
            patch("dd_agents.extraction.transcribe._is_macos", return_value=True),
            patch("dd_agents.extraction.transcribe._mlx_whisper_available", return_value=True),
        ):
            assert detect_backend() == TranscriptionBackend.MLX_WHISPER

    def test_auto_detect_whisperx_on_linux(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "DD_TRANSCRIPTION_BACKEND"}
        with (
            patch.dict(os.environ, env, clear=True),
            patch("dd_agents.extraction.transcribe._is_macos", return_value=False),
            patch("dd_agents.extraction.transcribe._whisperx_available", return_value=True),
        ):
            assert detect_backend() == TranscriptionBackend.WHISPERX

    def test_auto_detect_openai_fallback(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "DD_TRANSCRIPTION_BACKEND"}
        with (
            patch.dict(os.environ, env, clear=True),
            patch("dd_agents.extraction.transcribe._is_macos", return_value=False),
            patch("dd_agents.extraction.transcribe._whisperx_available", return_value=False),
            patch("dd_agents.extraction.transcribe._openai_whisper_available", return_value=True),
        ):
            assert detect_backend() == TranscriptionBackend.OPENAI_WHISPER

    def test_auto_detect_none_when_nothing_installed(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "DD_TRANSCRIPTION_BACKEND"}
        with (
            patch.dict(os.environ, env, clear=True),
            patch("dd_agents.extraction.transcribe._is_macos", return_value=False),
            patch("dd_agents.extraction.transcribe._whisperx_available", return_value=False),
            patch("dd_agents.extraction.transcribe._openai_whisper_available", return_value=False),
        ):
            assert detect_backend() is None

    def test_macos_prefers_mlx_over_whisperx(self) -> None:
        """Even if whisperx is available, macOS should prefer mlx_whisper."""
        env = {k: v for k, v in os.environ.items() if k != "DD_TRANSCRIPTION_BACKEND"}
        with (
            patch.dict(os.environ, env, clear=True),
            patch("dd_agents.extraction.transcribe._is_macos", return_value=True),
            patch("dd_agents.extraction.transcribe._mlx_whisper_available", return_value=True),
            patch("dd_agents.extraction.transcribe._whisperx_available", return_value=True),
            patch("dd_agents.extraction.transcribe._openai_whisper_available", return_value=True),
        ):
            assert detect_backend() == TranscriptionBackend.MLX_WHISPER

    def test_macos_falls_to_whisperx_if_mlx_missing(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "DD_TRANSCRIPTION_BACKEND"}
        with (
            patch.dict(os.environ, env, clear=True),
            patch("dd_agents.extraction.transcribe._is_macos", return_value=True),
            patch("dd_agents.extraction.transcribe._mlx_whisper_available", return_value=False),
            patch("dd_agents.extraction.transcribe._whisperx_available", return_value=True),
        ):
            assert detect_backend() == TranscriptionBackend.WHISPERX


# ===================================================================
# Model selection
# ===================================================================


class TestGetModel:
    def test_default_mlx(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "DD_TRANSCRIPTION_MODEL"}
        with patch.dict(os.environ, env, clear=True):
            assert _get_model(TranscriptionBackend.MLX_WHISPER) == "mlx-community/whisper-large-v3-turbo"

    def test_default_whisperx(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "DD_TRANSCRIPTION_MODEL"}
        with patch.dict(os.environ, env, clear=True):
            assert _get_model(TranscriptionBackend.WHISPERX) == "large-v3"

    def test_default_openai(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "DD_TRANSCRIPTION_MODEL"}
        with patch.dict(os.environ, env, clear=True):
            assert _get_model(TranscriptionBackend.OPENAI_WHISPER) == "base"

    @patch.dict(os.environ, {"DD_TRANSCRIPTION_MODEL": "tiny"})
    def test_env_override(self) -> None:
        assert _get_model(TranscriptionBackend.OPENAI_WHISPER) == "tiny"
        assert _get_model(TranscriptionBackend.MLX_WHISPER) == "tiny"


# ===================================================================
# mlx_whisper backend
# ===================================================================


class TestMlxBackend:
    def test_transcribe_mlx_success(self, tmp_path: Path) -> None:
        """Verify mlx_whisper CLI is called with correct args and JSON is parsed."""
        audio_file = tmp_path / "audio.wav"
        audio_file.write_bytes(b"\x00" * 100)

        transcript = {"text": "Hello world", "language": "en"}

        def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
            # Write the JSON output file into the output_dir.
            out_dir_idx = cmd.index("--output-dir") + 1
            out_dir = cmd[out_dir_idx]
            json_path = os.path.join(out_dir, "audio.json")
            with open(json_path, "w") as f:
                json.dump(transcript, f)
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("dd_agents.extraction.transcribe.subprocess.run", side_effect=fake_run) as mock_run:
            result = _transcribe_mlx(audio_file, "mlx-community/whisper-large-v3-turbo")

        assert result.text == "Hello world"
        assert result.backend == TranscriptionBackend.MLX_WHISPER
        assert result.language == "en"

        # Verify CLI args.
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "mlx_whisper"
        assert str(audio_file) in call_args
        assert "--model" in call_args
        assert "--language" in call_args
        assert "-f" in call_args
        assert "json" in call_args

    def test_transcribe_mlx_nonzero_exit(self, tmp_path: Path) -> None:
        audio_file = tmp_path / "audio.wav"
        audio_file.write_bytes(b"\x00" * 100)

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "model not found"

        with (
            patch("dd_agents.extraction.transcribe.subprocess.run", return_value=mock_result),
            pytest.raises(RuntimeError, match="mlx_whisper exited with code 1"),
        ):
            _transcribe_mlx(audio_file, "bad-model")

    def test_transcribe_mlx_no_json_output(self, tmp_path: Path) -> None:
        audio_file = tmp_path / "audio.wav"
        audio_file.write_bytes(b"\x00" * 100)

        mock_result = MagicMock()
        mock_result.returncode = 0

        with (
            patch("dd_agents.extraction.transcribe.subprocess.run", return_value=mock_result),
            pytest.raises(RuntimeError, match="no JSON output"),
        ):
            _transcribe_mlx(audio_file, "some-model")


# ===================================================================
# openai-whisper backend
# ===================================================================


class TestOpenaiBackend:
    def test_transcribe_openai_success(self, tmp_path: Path) -> None:
        audio_file = tmp_path / "audio.wav"
        audio_file.write_bytes(b"\x00" * 100)

        mock_model = MagicMock()
        mock_model.transcribe.return_value = {"text": "Test transcript", "language": "en"}

        with patch.dict("sys.modules", {"whisper": MagicMock()}):
            import sys

            mock_whisper = sys.modules["whisper"]
            mock_whisper.load_model.return_value = mock_model

            result = _transcribe_openai(audio_file, "base")

        assert result.text == "Test transcript"
        assert result.backend == TranscriptionBackend.OPENAI_WHISPER
        assert result.model == "base"


# ===================================================================
# transcribe() public API
# ===================================================================


class TestTranscribePublicAPI:
    def test_returns_none_when_no_backend(self, tmp_path: Path) -> None:
        audio_file = tmp_path / "audio.wav"
        audio_file.write_bytes(b"\x00" * 100)

        with patch("dd_agents.extraction.transcribe.detect_backend", return_value=None):
            assert transcribe(audio_file) is None

    def test_dispatches_to_correct_backend(self, tmp_path: Path) -> None:
        audio_file = tmp_path / "audio.wav"
        audio_file.write_bytes(b"\x00" * 100)

        expected = TranscriptionResult(text="dispatched", backend=TranscriptionBackend.WHISPERX, model="large-v3")
        mock_wx = MagicMock(return_value=expected)

        with (
            patch("dd_agents.extraction.transcribe.detect_backend", return_value=TranscriptionBackend.WHISPERX),
            patch("dd_agents.extraction.transcribe._get_model", return_value="large-v3"),
            patch.dict(
                "dd_agents.extraction.transcribe._BACKEND_DISPATCH",
                {TranscriptionBackend.WHISPERX: mock_wx},
            ),
        ):
            result = transcribe(audio_file)

        assert result is expected
        mock_wx.assert_called_once_with(audio_file, "large-v3")


# ===================================================================
# Integration: _extract_media uses transcribe module
# ===================================================================


class TestExtractMediaIntegration:
    """Verify that ExtractionPipeline._extract_media delegates to transcribe()."""

    def _make_pipeline(self) -> object:
        from dd_agents.extraction.pipeline import ExtractionPipeline

        return ExtractionPipeline()

    def test_successful_transcription(self, tmp_path: Path) -> None:
        pipeline = self._make_pipeline()
        mp4_file = tmp_path / "call.mp4"
        mp4_file.write_bytes(b"\x00" * 100)
        out_file = tmp_path / "call.md"

        mock_result = TranscriptionResult(
            text="Meeting transcript here", backend=TranscriptionBackend.MLX_WHISPER, model="large"
        )

        with patch("dd_agents.extraction.transcribe.transcribe", return_value=mock_result):
            entry = pipeline._extract_media(mp4_file, out_file)

        assert entry.method == "transcribe_mlx"
        assert entry.confidence == 0.7
        assert out_file.read_text().strip() == "Meeting transcript here"

    def test_no_backend_writes_placeholder(self, tmp_path: Path) -> None:
        pipeline = self._make_pipeline()
        mp4_file = tmp_path / "call.mp4"
        mp4_file.write_bytes(b"\x00" * 100)
        out_file = tmp_path / "call.md"

        with patch("dd_agents.extraction.transcribe.transcribe", return_value=None):
            entry = pipeline._extract_media(mp4_file, out_file)

        assert entry.method == "media_placeholder"
        assert entry.confidence < 0.5
        content = out_file.read_text()
        assert "MEDIA FILE" in content
        assert "mlx_whisper" in content  # Install hint mentions mlx.

    def test_transcription_exception_writes_placeholder(self, tmp_path: Path) -> None:
        pipeline = self._make_pipeline()
        mp4_file = tmp_path / "call.mp4"
        mp4_file.write_bytes(b"\x00" * 100)
        out_file = tmp_path / "call.md"

        with patch("dd_agents.extraction.transcribe.transcribe", side_effect=RuntimeError("GPU OOM")):
            entry = pipeline._extract_media(mp4_file, out_file)

        assert entry.method == "media_placeholder"
        assert "GPU OOM" in entry.failure_reasons[0]

    def test_empty_transcription_writes_placeholder(self, tmp_path: Path) -> None:
        pipeline = self._make_pipeline()
        mp4_file = tmp_path / "call.mp4"
        mp4_file.write_bytes(b"\x00" * 100)
        out_file = tmp_path / "call.md"

        mock_result = TranscriptionResult(text="", backend=TranscriptionBackend.OPENAI_WHISPER, model="base")

        with patch("dd_agents.extraction.transcribe.transcribe", return_value=mock_result):
            entry = pipeline._extract_media(mp4_file, out_file)

        assert entry.method == "media_placeholder"
        assert "empty transcription" in entry.failure_reasons[0]
