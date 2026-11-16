"""The single seam for building Claude Agent SDK model calls.

Every reasoning-LLM call site in dd-agents builds its ``ClaudeAgentOptions``
through :func:`build_agent_options` rather than constructing options by hand.
That gives one place to:

- always resolve the CLI binary (``resolve_sdk_cli_path``),
- set an explicit ``model`` when one is resolved (a deal/env override),
  otherwise intentionally inherit the provider/CLI default,
- honor an output-token clamp for gateways whose backing model has a lower
  cap than the CLI's default request (``DD_MAX_OUTPUT_TOKENS`` ->
  ``CLAUDE_CODE_MAX_OUTPUT_TOKENS``), and
- snapshot the active provider routing for diagnostics
  (:func:`resolve_provider` — logged once at pipeline start).

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
    for diagnostics (logged once at pipeline start, see
    :meth:`ProviderInfo.describe`); it does not itself change behavior.
    """

    #: One of: ``anthropic`` | ``bedrock`` | ``vertex`` | ``gateway``.
    provider: str
    #: The ``ANTHROPIC_BASE_URL`` when a gateway/proxy is configured, else None.
    base_url: str | None
    #: Output-token clamp in effect (None when unset).
    max_output_tokens: int | None

    @property
    def safe_base_url(self) -> str | None:
        """``base_url`` with any embedded credentials stripped.

        ``ANTHROPIC_BASE_URL`` can legitimately carry secrets in userinfo
        (``https://token@host``) or a query string (``?api-key=...``). This
        keeps only scheme + host[:port] + path so the value is safe to log and
        persist. Returns None when no base_url is set.
        """
        if not self.base_url:
            return None
        from urllib.parse import urlsplit, urlunsplit

        parts = urlsplit(self.base_url)
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
        # Drop userinfo (netloc → host only), query, and fragment.
        return urlunsplit((parts.scheme, host, parts.path, "", "")) or None

    def describe(self) -> str:
        """One-line, secret-free summary for startup logging."""
        parts = [f"provider={self.provider}"]
        safe = self.safe_base_url
        if safe:
            parts.append(f"base_url={safe}")
        if self.max_output_tokens is not None:
            parts.append(f"max_output_tokens={self.max_output_tokens}")
        return " ".join(parts)

    def as_receipt(self) -> dict[str, str | int | None]:
        """Secret-free routing receipt for persistence into the run audit trail."""
        return {
            "provider": self.provider,
            "base_url": self.safe_base_url,
            "max_output_tokens": self.max_output_tokens,
        }

    def fingerprint(self) -> str:
        """Stable, secret-free identity of the active routing.

        Folded into the provenance hash so a resume under a different
        provider/gateway/clamp is rejected by the fail-closed gate. Uses the
        redacted base_url (host only), so no secret enters the hash.

        Also includes ``DD_VISION_MODEL`` (Issue #248): the vision fallback is the
        one aux model knob that drives a real reasoning call inside a ``run`` (its
        text feeds every downstream specialist), so swapping it across a
        checkpoint must bust the gate too. It is a model id, not a secret. Other
        aux paths (search/auto-config) are separate commands, not part of a run.
        """
        return "|".join(
            (
                self.provider,
                self.safe_base_url or "",
                str(self.max_output_tokens if self.max_output_tokens is not None else ""),
                os.getenv("DD_VISION_MODEL", "").strip(),
            )
        )


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


# Built-in tools no dd-agents call may use. Shell, network and sub-agent tools
# are never part of the pipeline's contract; denying them here (the one place
# options are built) holds even when a caller runs with bypassPermissions.
DENIED_BUILTIN_TOOLS: tuple[str, ...] = ("Bash", "WebFetch", "WebSearch", "Agent", "Task", "NotebookEdit")


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

    denied = list(dict.fromkeys([*(kwargs.get("disallowed_tools") or []), *DENIED_BUILTIN_TOOLS]))
    kwargs["disallowed_tools"] = denied

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


# Credential env vars each provider needs. Bedrock/Vertex accept a profile or explicit keys,
# so the common ones are listed. Names only: values are never read into a response.
PROVIDER_CREDENTIAL_HINTS: dict[str, tuple[str, ...]] = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "bedrock": ("AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_BEARER_TOKEN_BEDROCK"),
    "vertex": ("ANTHROPIC_VERTEX_PROJECT_ID", "GOOGLE_APPLICATION_CREDENTIALS"),
    "gateway": ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"),
}

_SECRET_ENV = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_BEARER_TOKEN_BEDROCK",
    "ANTHROPIC_BASE_URL",
)


def credential_present(info: ProviderInfo) -> bool:
    """True when at least one credential env var for the active provider is set."""
    return any(os.getenv(name) for name in PROVIDER_CREDENTIAL_HINTS.get(info.provider, ()))


def scrub_secrets(text: str) -> str:
    """Replace any configured secret value found in ``text`` with ``***``."""
    for name in _SECRET_ENV:
        value = os.getenv(name, "").strip()
        if len(value) >= 6:
            text = text.replace(value, "***")
    return text


def probe_provider() -> tuple[bool, str]:
    """Issue one minimal query through the seam. Returns ``(ok, detail)``. Calls the provider."""
    import asyncio

    async def _run() -> tuple[bool, str]:
        try:
            from claude_agent_sdk import query

            options = build_agent_options(max_turns=1, tools=[], allowed_tools=[])
            text = ""
            async for message in query(prompt="Reply with the single word: OK", options=options):
                for attr in ("content", "result", "text"):
                    val = getattr(message, attr, None)
                    if isinstance(val, str):
                        text += val
            return (bool(text.strip()), f"response chars: {len(text.strip())}")
        except Exception as exc:  # noqa: BLE001 - diagnostic surface, report any failure
            return (False, scrub_secrets(f"{type(exc).__name__}: {exc}"))

    return asyncio.run(_run())
