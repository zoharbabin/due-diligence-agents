# Model Providers

Run dd-agents on **any provider** — Anthropic API, AWS Bedrock, Google Vertex AI — and on **any model**, including non-Claude models (GPT, Gemini, DeepSeek, local), through an Anthropic-compatible gateway. Selection is entirely by environment; no code change, no vendor hardcoded.

## Quick config (pick one)

```bash
# Anthropic API (default)
export ANTHROPIC_API_KEY=sk-ant-...

# AWS Bedrock — data stays in your AWS account
export CLAUDE_CODE_USE_BEDROCK=1
export AWS_PROFILE=default AWS_REGION=us-east-1

# Google Vertex AI
export CLAUDE_CODE_USE_VERTEX=1
export ANTHROPIC_VERTEX_PROJECT_ID=your-gcp-project CLOUD_ML_REGION=us-east5

# Any model via an Anthropic-compatible gateway (e.g. LiteLLM → GPT/Gemini/…)
export ANTHROPIC_BASE_URL=http://localhost:4011
export ANTHROPIC_AUTH_TOKEN=sk-anything            # pragma: allowlist secret
export DD_MAX_OUTPUT_TOKENS=4096                    # clamp if the backing model caps lower
```

## Verify before you run

```bash
dd-agents doctor            # show the active provider/model routing + credential check
dd-agents doctor --probe    # also issue one minimal live query to confirm the endpoint answers
dd-agents doctor --json     # machine-readable routing receipt (exit 1 if misconfigured)
```

`doctor` is the fast pre-flight: it prints which provider/gateway will answer
(secret-free — credentials in `ANTHROPIC_BASE_URL` are stripped), confirms a
credential is present, and with `--probe` round-trips a real query. Use it to
validate a Bedrock / Vertex / gateway setup before committing to a full run.

## How it works (the contract)

Every reasoning-LLM call in dd-agents is built by one seam —
`dd_agents.llm.build_agent_options()` (`src/dd_agents/llm/provider.py`) — then
run through `claude_agent_sdk`. dd-agents writes **no provider code**: the SDK
forwards your environment to the bundled Claude CLI, which natively routes to
Anthropic / Bedrock / Vertex, and the SDK speaks the **Anthropic Messages wire
protocol**. Anything that answers that protocol works — so an Anthropic-compatible
gateway lets you reach models from any vendor without changing dd-agents.

## Design rules (mechanical)

- **Native providers** (Anthropic / Bedrock / Vertex): set the matching env vars above. Model family is Claude.
- **Other models** (GPT, Gemini, DeepSeek, local, …): run an Anthropic-compatible gateway and point `ANTHROPIC_BASE_URL` at it. The model family is whatever the gateway serves.
- **If a query 400s on token limits** behind a gateway, set `DD_MAX_OUTPUT_TOKENS` (the seam exports it as `CLAUDE_CODE_MAX_OUTPUT_TOKENS`) to a value within the backing model's output cap.
- **Cost accuracy for non-Claude models**: set `DD_MODEL_PRICING` (JSON: `{"<model-id>": {"input": <usd_per_mtok>, "output": <…>}}`). Unknown models are estimated at default rates and logged as such, never silently presented as exact.
- **Pin a model per call path** (optional): `agent_models.overrides` in the deal config (specialists/synthesis), and `DD_QUERY_MODEL` / `DD_SEARCH_MODEL` / `DD_AUTOCONFIG_MODEL` / `DD_VISION_MODEL` for the auxiliary reasoning paths. Use the id form your endpoint expects. CLI `--model-profile` / `--model-override` apply to a `run` and are folded into the run's provenance hash.

## Auxiliary (local) model paths

Beyond the reasoning LLM, two extraction paths use **local** models — independent of your provider choice, no remote calls:

- **OCR** (scanned PDFs): selected by `extraction.ocr_backend` in the deal config (`auto` | `glm_ocr` | `pytesseract`); the local GLM-OCR model tag is overridable via `DD_OCR_MODEL_MLX` / `DD_OCR_MODEL_OLLAMA`.
- **Transcription** (audio/video): `DD_TRANSCRIPTION_BACKEND` (`mlx` | `whisperx` | `openai`-local-whisper) and `DD_TRANSCRIPTION_MODEL`.

Entity resolution and the knowledge base use no remote model (local TF-IDF / no embedding RAG).

## Resume is provider-locked

The fail-closed resume gate folds the active provider/gateway routing into the run's provenance hash. A checkpoint is only resumable under the **same** provider/model routing it was created with; switching transport (e.g. Anthropic API → a gateway, or flipping Bedrock) between the original run and a `--resume-from` is rejected rather than silently stitching findings from two backends into one report. Start a fresh run to change providers.

## Auditability

Every run records a secret-free **routing receipt** — the active provider, the gateway base URL (host only, credentials stripped), and the distinct model ids actually used. It is persisted to the run's `metadata.json` (`llm_provider` / `llm_base_url` / `llm_models`) and `cost_summary.json` (`routing`), and surfaced in the HTML report's *Generation Provenance* section and the Excel `_Metadata` sheet. So an auditor can later prove which provider/model produced the findings.

## Use any model via a LiteLLM gateway (recipe)

A copy-paste recipe lives in [`examples/litellm-gateway/`](https://github.com/zoharbabin/due-diligence-agents/tree/main/examples/litellm-gateway) — a LiteLLM config mapping a model name to your chosen backend, plus the exact env to point dd-agents at it. The repo ships an **opt-in** gateway end-to-end test (`tests/e2e/test_gateway_provider.py`, `-m gateway`) that runs a real query through a gateway you stand up; it is skipped in the standard CI matrix (no proxy) and is run manually to validate your own gateway.

## Caveats

- The vision/multimodal extraction fallback needs a multimodal model; a text-only gateway model returns no image description (handled gracefully — text extraction still runs).
- Tool-use, streaming, and structured-output fidelity through a gateway are the gateway's responsibility; validate your gateway against `-m gateway` before a production run.
- The code-enforced safety floor, citation mandate, and per-subject finding contract are prompt/tool-level and apply regardless of model — but smaller models may follow them less reliably. Prefer a strong tool-calling model.

## Reference

| Read | When |
|------|------|
| `.env.example` | The full, current env var set (provider routing, clamps, overrides) |
| [Deal Configuration](deal-configuration.md) | `agent_models` profiles/overrides and budget cap |
| `src/dd_agents/llm/provider.py` | The seam — `resolve_provider()` and `build_agent_options()` |
| `examples/litellm-gateway/` | A tested gateway recipe for non-Claude models |
| [Provider Coverage](provider-coverage.md) | Which flows are verified live on which providers |
