"""System-wide model/provider-agnosticism contracts (audit follow-up).

Covers the fixes that make agnosticism work end-to-end, not just in the
reasoning seam:

- CLI ``--model-profile`` / ``--model-override`` reach the engine and the
  effective config (the high-severity "silently dropped" bug).
- Specialist/synthesis runners receive the typed deal config so model
  selection is honored and cost is attributed to a real model.
- One shared OCR-pipeline factory (no per-call-site drift).
- ``ProviderInfo`` redacts credentials and exposes a persistable receipt.
- The run's audit trail records the active provider/model.
- Search cost estimation routes through the single pricing seam.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# ProviderInfo: secret redaction + persistable receipt
# ---------------------------------------------------------------------------


class TestProviderReceipt:
    def test_safe_base_url_strips_userinfo_and_query(self) -> None:
        from dd_agents.llm.provider import ProviderInfo

        info = ProviderInfo(
            provider="gateway",
            base_url="https://tok:s3cret@host.example.com:4011/v1?api-key=abc",  # pragma: allowlist secret
            max_output_tokens=4096,
        )
        safe = info.safe_base_url
        assert safe == "https://host.example.com:4011/v1"
        assert "s3cret" not in (safe or "")
        assert "api-key" not in (safe or "")

    def test_describe_is_secret_free(self) -> None:
        from dd_agents.llm.provider import ProviderInfo

        info = ProviderInfo(
            provider="gateway",
            base_url="https://user:pw@gw.internal/v1",  # pragma: allowlist secret
            max_output_tokens=None,
        )
        text = info.describe()
        assert "pw@" not in text
        assert "gw.internal" in text

    def test_safe_base_url_none_when_unset(self) -> None:
        from dd_agents.llm.provider import ProviderInfo

        info = ProviderInfo(provider="anthropic", base_url=None, max_output_tokens=None)
        assert info.safe_base_url is None

    def test_fingerprint_changes_with_routing(self) -> None:
        from dd_agents.llm.provider import ProviderInfo

        anthropic = ProviderInfo(provider="anthropic", base_url=None, max_output_tokens=None)
        bedrock = ProviderInfo(provider="bedrock", base_url=None, max_output_tokens=None)
        gateway = ProviderInfo(provider="gateway", base_url="https://gw/v1", max_output_tokens=4096)
        fps = {anthropic.fingerprint(), bedrock.fingerprint(), gateway.fingerprint()}
        assert len(fps) == 3  # each routing is distinct
        # Secret-free: a credentialed base_url never leaks into the fingerprint.
        creds = ProviderInfo(
            provider="gateway",
            base_url="https://tok:sneaky@gw/v1",  # pragma: allowlist secret
            max_output_tokens=4096,
        )
        assert "sneaky" not in creds.fingerprint()

    def test_provenance_hash_folds_routing(self) -> None:
        from dd_agents.persistence.provenance import compute_provenance_hash

        base = compute_provenance_hash("cfg", "1.0.0", {"legal": "abc"}, "anthropic||")
        swapped = compute_provenance_hash("cfg", "1.0.0", {"legal": "abc"}, "gateway|https://gw/v1|4096")
        assert base != swapped  # a provider swap busts the resume gate
        # Empty fingerprint preserves the legacy 3-input hash for back-compat.
        legacy = compute_provenance_hash("cfg", "1.0.0", {"legal": "abc"})
        legacy_explicit = compute_provenance_hash("cfg", "1.0.0", {"legal": "abc"}, "")
        assert legacy == legacy_explicit

    def test_as_receipt_is_secret_free_dict(self) -> None:
        from dd_agents.llm.provider import ProviderInfo

        info = ProviderInfo(
            provider="gateway",
            base_url="https://k@h.example/v1?token=zzz",  # pragma: allowlist secret
            max_output_tokens=2048,
        )
        receipt = info.as_receipt()
        assert receipt == {
            "provider": "gateway",
            "base_url": "https://h.example/v1",
            "max_output_tokens": 2048,
        }
        assert "zzz" not in json.dumps(receipt)


# ---------------------------------------------------------------------------
# CostTracker: distinct models + routing in to_dict
# ---------------------------------------------------------------------------


class TestCostRoutingReceipt:
    def test_models_used_distinct_sorted_nonempty(self) -> None:
        from dd_agents.agents.cost_tracker import CostTracker

        t = CostTracker()
        t.record("legal", "16_spawn", 100, 50, "claude-opus-4-8")
        t.record("finance", "16_spawn", 100, 50, "claude-sonnet-4-6")
        t.record("hr", "16_spawn", 100, 50, "")  # blank ignored
        t.record("tax", "16_spawn", 100, 50, "claude-opus-4-8")  # dup
        assert t.models_used() == ["claude-opus-4-8", "claude-sonnet-4-6"]

    def test_to_dict_includes_routing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from dd_agents.agents.cost_tracker import CostTracker

        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_USE_BEDROCK", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_USE_VERTEX", raising=False)
        t = CostTracker()
        t.record("legal", "16_spawn", 100, 50, "claude-opus-4-8")
        d = t.to_dict()
        assert "routing" in d
        assert d["routing"]["provider"] == "anthropic"
        assert d["routing"]["models_used"] == ["claude-opus-4-8"]


# ---------------------------------------------------------------------------
# Shared OCR factory: one seam, config-aware
# ---------------------------------------------------------------------------


class TestOcrFactory:
    def test_pytesseract_preference_yields_no_glm(self) -> None:
        from dd_agents.extraction.ocr_registry import build_extraction_pipeline

        pipeline = build_extraction_pipeline({"extraction": {"ocr_backend": "pytesseract"}})
        # GLM-OCR backend must not be wired when pytesseract is requested.
        assert pipeline._glm_ocr is None

    def test_preference_from_typed_config(self) -> None:
        from dd_agents.extraction.ocr_registry import _ocr_preference_from_config

        class _Extraction:
            ocr_backend = "pytesseract"

        class _Cfg:
            extraction = _Extraction()

        assert _ocr_preference_from_config(_Cfg()) == "pytesseract"

    def test_preference_defaults_to_auto(self) -> None:
        from dd_agents.extraction.ocr_registry import _ocr_preference_from_config

        assert _ocr_preference_from_config(None) == "auto"
        assert _ocr_preference_from_config({}) == "auto"


# ---------------------------------------------------------------------------
# Engine: CLI model selection reaches the effective config + provenance
# ---------------------------------------------------------------------------


def _write_min_config(tmp_path: Path) -> Path:
    cfg = {
        "config_version": "1.0.0",
        "buyer": {"name": "Buyer Co"},
        "target": {"name": "Target Co"},
        "deal": {"type": "acquisition", "focus_areas": ["ip_ownership"]},
        "data_room": {"path": str(tmp_path)},
    }
    path = tmp_path / "deal-config.json"
    path.write_text(json.dumps(cfg))
    return path


class TestModelSelectionPlumbing:
    @pytest.mark.asyncio
    async def test_model_overrides_applied_to_effective_config_and_hash(self, tmp_path: Path) -> None:
        from dd_agents.orchestrator.engine import PipelineEngine
        from dd_agents.orchestrator.state import PipelineState
        from dd_agents.persistence.provenance import compute_config_hash

        cfg_path = _write_min_config(tmp_path)

        # Baseline hash with no overrides.
        engine0 = PipelineEngine(project_dir=tmp_path, deal_config_path=cfg_path)
        state0 = await engine0._step_01_validate_config(PipelineState(project_dir=tmp_path))
        base_hash = state0.config_hash

        # With overrides plumbed through run_options.
        engine = PipelineEngine(project_dir=tmp_path, deal_config_path=cfg_path)
        engine._run_options = {
            "model_profile": "economy",
            "model_overrides": {"legal": "claude-haiku-4-5-20251001"},
        }
        state = await engine._step_01_validate_config(PipelineState(project_dir=tmp_path))

        # Effective in-memory config carries the overrides.
        assert state.deal_config["agent_models"]["profile"] == "economy"
        assert state.deal_config["agent_models"]["overrides"]["legal"] == "claude-haiku-4-5-20251001"

        # Provenance hash reflects the effective config (busts a stale checkpoint).
        assert state.config_hash != base_hash
        assert state.config_hash == compute_config_hash(state.deal_config)

        # Typed config resolves the pinned model for the overridden agent.
        typed = engine._typed_deal_config(state)
        assert typed is not None
        assert typed.agent_models.resolve_model("legal") == "claude-haiku-4-5-20251001"


# ---------------------------------------------------------------------------
# doctor command: pre-run provider verification
# ---------------------------------------------------------------------------


class TestDoctorCommand:
    def _invoke(self, monkeypatch: pytest.MonkeyPatch, env: dict[str, str], args: list[str]):
        from click.testing import CliRunner

        from dd_agents.cli import main

        for key in (
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_AUTH_TOKEN",
            "CLAUDE_CODE_USE_BEDROCK",
            "CLAUDE_CODE_USE_VERTEX",
            "AWS_PROFILE",
            "AWS_ACCESS_KEY_ID",
        ):
            monkeypatch.delenv(key, raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        return CliRunner().invoke(main, ["doctor", *args])

    def test_fails_without_credential(self, monkeypatch: pytest.MonkeyPatch) -> None:
        result = self._invoke(monkeypatch, {}, ["--json"])
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["provider"] == "anthropic"
        assert payload["credential_present"] is False

    def test_passes_with_credential(self, monkeypatch: pytest.MonkeyPatch) -> None:
        result = self._invoke(monkeypatch, {"ANTHROPIC_API_KEY": "sk-ant-x"}, ["--json"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["credential_present"] is True

    def test_gateway_routing_is_secret_free(self, monkeypatch: pytest.MonkeyPatch) -> None:
        result = self._invoke(
            monkeypatch,
            {
                "ANTHROPIC_BASE_URL": "https://tok:secret@gw.example/v1",  # pragma: allowlist secret
                "ANTHROPIC_AUTH_TOKEN": "sk-x",  # pragma: allowlist secret
            },
            ["--json"],
        )
        payload = json.loads(result.output)
        assert payload["provider"] == "gateway"
        assert payload["base_url"] == "https://gw.example/v1"
        assert "secret" not in result.output
