"""The single seam for building Claude Agent SDK model calls.

Every reasoning-LLM call site in dd-agents builds its ``ClaudeAgentOptions``
through :func:`build_agent_options` rather than constructing options by hand.
That gives one place to:

- always resolve the CLI binary (``resolve_sdk_cli_path``),
- always set an explicit ``model`` (never silently ride the CLI default),
- honor an output-token clamp for gateways whose backing model has a lower
  cap than the CLI's default request (``DD_MAX_OUTPUT_TOKENS`` ->
  ``CLAUDE_CODE_MAX_OUTPUT_TOKENS``), and
- report the active provider for audit/provenance (:func:`resolve_provider`).

Provider/model selection is environment-driven (see
``docs/user-guide/model-providers.md`` and ``.env.example``); this module reads
that environment but never hardcodes a vendor.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from claude_agent_sdk import ClaudeAgentOptions


@dataclass(frozen=True)
class ProviderInfo:
    """Audit-friendly snapshot of the active LLM provider routing.

    Derived purely from environment — the same env the Claude CLI reads. Used
    for provenance/diagnostics; it does not itself change behavior.
    """

    #: One of: ``anthropic`` | ``bedrock`` | ``vertex`` | ``gateway``.
    provider: str
    #: The ``ANTHROPIC_BASE_URL`` when a gateway/proxy is configured, else None.
    base_url: str | None
    #: Output-token clamp in effect (None when unset).
    max_output_tokens: int | None


def _max_output_tokens() -> int | None:
    """Resolve the optional output-token clamp from ``DD_MAX_OUTPUT_TOKENS``.

    Some gateway-backed models accept a lower ``max_tokens`` than the Claude
    CLI's default request, which otherwise 400s. Setting this exports
    ``CLAUDE_CODE_MAX_OUTPUT_TOKENS`` for the CLI. Returns None when unset or
    invalid (no clamp).
    """
    raw = os.getenv("DD_MAX_OUTPUT_TOKENS", "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def resolve_provider() -> ProviderInfo:
    """Snapshot the active provider routing from the environment.

    Precedence mirrors the Claude CLI: an explicit ``ANTHROPIC_BASE_URL`` means
    a gateway/proxy (any model); otherwise the ``CLAUDE_CODE_USE_BEDROCK`` /
    ``CLAUDE_CODE_USE_VERTEX`` flags select the native cloud provider; the
    default is the direct Anthropic API.
    """
    base_url = os.getenv("ANTHROPIC_BASE_URL", "").strip() or None

    def _truthy(name: str) -> bool:
        return os.getenv(name, "").strip().lower() in {"1", "true", "yes"}

    if base_url:
        provider = "gateway"
    elif _truthy("CLAUDE_CODE_USE_BEDROCK"):
        provider = "bedrock"
    elif _truthy("CLAUDE_CODE_USE_VERTEX"):
        provider = "vertex"
    else:
        provider = "anthropic"

    return ProviderInfo(provider=provider, base_url=base_url, max_output_tokens=_max_output_tokens())


def build_agent_options(
    *,
    model: str | None = None,
    extra_env: dict[str, str] | None = None,
    **kwargs: Any,
) -> ClaudeAgentOptions:
    """Build a :class:`ClaudeAgentOptions`, applying dd-agents' shared policy.

    This is the ONE place options are constructed. It always sets ``cli_path``
    (when resolvable) and applies the output-token clamp; callers pass the same
    keyword arguments they would give ``ClaudeAgentOptions`` directly
    (``system_prompt``, ``max_turns``, ``allowed_tools``, ``permission_mode``,
    ``hooks``, ``mcp_servers``, ``cwd``, ``max_buffer_size`` …).

    Parameters
    ----------
    model:
        Model id to request. Pass the per-deal resolved id; ``None`` falls back
        to the CLI default (kept for the few callers that intentionally inherit
        it). Any id the configured endpoint serves is valid — Claude on
        Anthropic/Bedrock/Vertex, or any model behind an Anthropic-compatible
        gateway.
    extra_env:
        Extra environment forwarded to the CLI (merged with the token clamp).
    **kwargs:
        Forwarded verbatim to ``ClaudeAgentOptions``.
    """
    from claude_agent_sdk import ClaudeAgentOptions

    from dd_agents.utils import resolve_sdk_cli_path

    if model is not None:
        kwargs["model"] = model

    cli_path = resolve_sdk_cli_path()
    if cli_path is not None:
        kwargs.setdefault("cli_path", cli_path)

    # Forward the output-token clamp to the CLI so a gateway model with a lower
    # cap than the CLI's default request does not 400. Merge with caller env.
    env: dict[str, str] = dict(kwargs.pop("env", {}) or {})
    if extra_env:
        env.update(extra_env)
    clamp = _max_output_tokens()
    if clamp is not None:
        env.setdefault("CLAUDE_CODE_MAX_OUTPUT_TOKENS", str(clamp))
    if env:
        kwargs["env"] = env

    return ClaudeAgentOptions(**kwargs)
