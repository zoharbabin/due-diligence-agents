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


class TestDoctorConfigPreflight:
    """doctor --config pre-flight validation (Issue #239)."""

    def _write_config(self, tmp_path: Path, extra: dict) -> Path:  # type: ignore[type-arg]
        base = {
            "config_version": "1.0.0",
            "buyer": {"name": "B"},
            "target": {"name": "T"},
            "deal": {"type": "acquisition", "focus_areas": ["ip_ownership"]},
        }
        base.update(extra)
        p = tmp_path / "deal-config.json"
        p.write_text(json.dumps(base))
        return p

    def _invoke(self, monkeypatch: pytest.MonkeyPatch, config_path: Path, env: dict[str, str] | None = None):
        from click.testing import CliRunner

        from dd_agents.cli import main

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
        for k, v in (env or {}).items():
            monkeypatch.setenv(k, v)
        return CliRunner().invoke(main, ["doctor", "--config", str(config_path), "--json"])

    def test_valid_config_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = self._write_config(
            tmp_path,
            {"precedence": {"vdr_overrides": {"contracts": "legal"}}},
        )
        result = self._invoke(monkeypatch, cfg)
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        cv = payload["config_validation"]
        assert cv["ok"] is True
        names = {c["name"] for c in cv["checks"]}
        assert "vdr_overrides" in names

    def test_missing_auth_token_env_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MY_GW_TOKEN", raising=False)
        cfg = self._write_config(
            tmp_path,
            {"agent_models": {"routes": {"legal": {"base_url": "http://gw", "auth_token_env": "MY_GW_TOKEN"}}}},
        )
        result = self._invoke(monkeypatch, cfg)
        assert result.exit_code == 1
        cv = json.loads(result.output)["config_validation"]
        assert cv["ok"] is False
        assert any("MY_GW_TOKEN" in e for e in cv["errors"])

    def test_invalid_vdr_domain_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = self._write_config(tmp_path, {"precedence": {"vdr_overrides": {"contracts": "not_a_domain"}}})
        result = self._invoke(monkeypatch, cfg)
        assert result.exit_code == 1
        cv = json.loads(result.output)["config_validation"]
        assert any("vdr_overrides" in e for e in cv["errors"])

    def test_unavailable_ocr_backend_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import dd_agents.extraction.ocr_registry as ocr_mod

        monkeypatch.setattr(ocr_mod.OCRBackendRegistry, "detect_available", staticmethod(lambda: []))
        cfg = self._write_config(tmp_path, {"extraction": {"ocr_backend": "glm_ocr"}})
        result = self._invoke(monkeypatch, cfg)
        assert result.exit_code == 1
        cv = json.loads(result.output)["config_validation"]
        assert any("ocr_backend" in e for e in cv["errors"])

    def test_no_config_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from click.testing import CliRunner

        from dd_agents.cli import main

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
        result = CliRunner().invoke(main, ["doctor", "--json"])
        assert result.exit_code == 0
        assert "config_validation" not in json.loads(result.output)


# ---------------------------------------------------------------------------
# Audit receipt: agent result carries the resolved model id
# ---------------------------------------------------------------------------


class TestModelAttribution:
    @pytest.mark.asyncio
    async def test_run_stamps_resolved_model_into_result(self, tmp_path: Path) -> None:
        """BaseAgentRunner.run() stamps result['model'] so cost/audit attribute it.

        Guards the audit-receipt fix: every cost entry + metadata.json llm_models
        must reflect the model the agent actually resolved, not "".
        """
        from unittest.mock import patch

        from dd_agents.agents.base import BaseAgentRunner

        class _Agent(BaseAgentRunner):
            def get_agent_name(self) -> str:
                return "legal"

            def get_model_id(self) -> str:
                return "claude-haiku-4-5-20251001"

            def get_system_prompt(self) -> str:
                return "x"

            def get_tools(self) -> list[str]:
                return []

            def build_prompt(self, state: dict) -> str:
                return "p"

        runner = _Agent(project_dir=tmp_path, run_dir=tmp_path, run_id="r")
        with patch.object(_Agent, "_spawn_agent", return_value="some output"):
            result = await runner.run({"prompt": "p", "subjects": []})
        assert result["model"] == "claude-haiku-4-5-20251001"

    @pytest.mark.asyncio
    async def test_run_stamps_empty_when_inheriting_default(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        from dd_agents.agents.base import BaseAgentRunner

        class _Agent(BaseAgentRunner):
            def get_agent_name(self) -> str:
                return "legal"

            def get_system_prompt(self) -> str:
                return "x"

            def get_tools(self) -> list[str]:
                return []

            def build_prompt(self, state: dict) -> str:
                return "p"

        # No deal_config → get_model_id() returns None → model stamped as "".
        runner = _Agent(project_dir=tmp_path, run_dir=tmp_path, run_id="r")
        with patch.object(_Agent, "_spawn_agent", return_value="out"):
            result = await runner.run({"prompt": "p", "subjects": []})
        assert result["model"] == ""
