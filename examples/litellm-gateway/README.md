# Run dd-agents on any model via a LiteLLM gateway

dd-agents speaks the **Anthropic Messages** wire protocol through the Claude
Agent SDK. [LiteLLM](https://github.com/BerriAI/litellm) exposes that exact
protocol (`/v1/messages`) in front of 100+ providers — so pointing dd-agents'
`ANTHROPIC_BASE_URL` at a LiteLLM gateway lets the **entire pipeline** run on
GPT, Gemini, DeepSeek, a local model, etc., with **no code change**.

This is an opt-in example. It does not change the `dd-agents` package or its
dependencies.

## Steps

```bash
# 1. install LiteLLM (separate from dd-agents)
uv pip install 'litellm[proxy]'

# 2. set the backend's key (matches config.yaml), then start the gateway
export OPENAI_API_KEY=sk-...                       # pragma: allowlist secret
litellm --config examples/litellm-gateway/config.yaml --port 4011

# 3. point dd-agents at the gateway (in another shell) and run as usual
export ANTHROPIC_BASE_URL=http://localhost:4011
export ANTHROPIC_AUTH_TOKEN=sk-anything            # pragma: allowlist secret
export DD_MAX_OUTPUT_TOKENS=4096                    # see "max_tokens" note below
dd-agents run deal-config.json
```

Edit [`config.yaml`](config.yaml) to map the model dd-agents requests to your
chosen backend (OpenAI / Gemini / a non-Claude Bedrock model / local).

## Verify it works

First, a quick pre-flight that prints the active routing and round-trips one query:

```bash
ANTHROPIC_BASE_URL=http://localhost:4011 ANTHROPIC_AUTH_TOKEN=sk-anything \
  dd-agents doctor --probe          # pragma: allowlist secret
```

The repo also ships an opt-in end-to-end check (skipped in the standard CI
matrix, which has no proxy — run it manually against your gateway):

```bash
DD_TEST_GATEWAY_URL=http://localhost:4011 \
DD_TEST_GATEWAY_KEY=sk-anything \
DD_TEST_GATEWAY_MODEL=claude-sonnet-4-6 \
DD_MAX_OUTPUT_TOKENS=4096 \
pytest tests/e2e/test_gateway_provider.py -m gateway
```

It runs a real `claude_agent_sdk` query through the gateway and asserts a
non-error completion — confirming your gateway is wired correctly.

## Notes & caveats

- **`max_tokens` / `DD_MAX_OUTPUT_TOKENS`** — the Claude CLI requests a large
  `max_tokens`; some backing models cap lower (e.g. Amazon Nova at 10k) and will
  return a 400. Set `DD_MAX_OUTPUT_TOKENS` to a value within the backing model's
  output limit (dd-agents forwards it to the CLI), or pick a higher-limit model.
- **Cost accuracy** — set `DD_MODEL_PRICING` (JSON) so non-Claude usage is costed
  correctly; otherwise estimates use default rates and say so.
- **Capability** — tool-use, streaming, and structured-output fidelity are the
  gateway's/backing model's responsibility. Validate with the `-m gateway` test
  before a production run, and prefer a strong tool-calling model.
- **Trust guarantees** — dd-agents' safety floor, citation mandate, and
  per-subject finding contract are prompt/tool-enforced and apply to any model,
  but smaller models follow them less reliably.

See [docs/user-guide/model-providers.md](../../docs/user-guide/model-providers.md)
for the full reference (native providers + the gateway path).
