# Provider Coverage Matrix

Which dd-agents flows are verified on which providers. dd-agents is model- and
provider-agnostic by env config (see [Model Providers](model-providers.md)); this
page records what has been **exercised live**, so claims stay honest.

## How routing works (recap)

Every LLM call is built by one seam (`dd_agents.llm.build_agent_options`) and run
through `claude_agent_sdk`, which speaks the Anthropic Messages wire protocol.
Native providers (Anthropic API / Bedrock / Vertex) run Claude; an
Anthropic-compatible gateway (e.g. LiteLLM) fronts **any** model. Verify your own
setup with `dd-agents doctor --probe`.

## Flows

The seven LLM-calling flows (one per `build_agent_options` call site):

| Flow | CLI surface |
|------|-------------|
| Provider probe | `dd-agents doctor --probe` |
| Single-question query | `dd-agents query` |
| Contract search | `dd-agents search` |
| Full pipeline (9 specialists + synthesis + judge) | `dd-agents run` |
| Auto-config | `dd-agents auto-config` |
| Interactive chat | `dd-agents chat` |
| Vision/image extraction fallback | `dd-agents run` (scanned docs) |

## Verified live

Legend: ✅ verified live · ⚙️ exercised via the shared seam (same code path) ·
🔑 not run here (no credentials) · ⚠️ runs, output quality model-dependent.

| Flow | Native Bedrock (Claude) | Gateway → Bedrock-Claude | Gateway → DeepSeek (non-Claude) | Anthropic API / Vertex |
|------|:-----------------------:|:------------------------:|:-------------------------------:|:----------------------:|
| `doctor --probe` | ✅ | ✅ | ✅ | 🔑 |
| `query` | ✅ | ✅ | ✅ | 🔑 |
| `search` | ✅ | ✅ | ⚠️ | 🔑 |
| full `run` (38 steps) | ⚙️ | ✅ | ✅ | 🔑 |
| `auto-config` | ⚙️ | ⚙️ | ⚙️ | 🔑 |
| `chat` | ⚙️ | ⚙️ | ⚙️ | 🔑 |
| vision extraction | ⚙️ | ⚙️ | ⚙️ | 🔑 |

Notes:

- **Full `run` is proven end-to-end through a gateway on BOTH Claude and a
  non-Claude model (DeepSeek v3.2 on Bedrock):** 38/38 steps, all gates, real
  multi-domain findings (40+), HTML + Excel reports, and the audit receipt
  records the provider/model. The same engine drives native Bedrock, so that
  column is ⚙️ (identical code path, not separately driven end-to-end here).
- **`search` on a weak/non-Claude model (⚠️):** the command completes and
  degrades gracefully, but a model that ignores the JSON contract (e.g. DeepSeek
  emitting native tool-call markup) yields partial columns. dd-agents recovers
  JSON from prose and tool-markup where possible; final fidelity is the model's
  responsibility. Prefer a strong tool-calling model — validate with
  `dd-agents doctor --probe` and a trial `search` first.
- **Anthropic API direct / Vertex (🔑):** not run here for lack of credentials.
  Both ride the identical seam + wire protocol as the verified providers;
  Anthropic-direct is the SDK's default transport and Vertex is a native CLI
  routing flag.
- **`auto-config` / `chat` / vision (⚙️):** not separately driven end-to-end in
  this pass; each builds options through the same seam as the ✅ flows, so
  provider routing is identical. Drive them with `dd-agents doctor` first if you
  are bringing up a new provider.

## Model capability tiers

Which *backing model* you put behind the seam matters: the pipeline leans on
tool-use, structured (JSON-schema) output, and — for scanned docs — vision.
This matrix records what's been validated, so a BYO-model buyer can choose with
confidence instead of discovering gaps at runtime. Legend: ✅ validated ·
⚠️ partial / model-dependent · ❓ untested here.

| Model (family) | Tool-use | Structured output (JSON) | Vision | Full 38-step run |
|----------------|:--------:|:------------------------:|:------:|:----------------:|
| Claude (Anthropic API / Bedrock / Vertex / gateway) | ✅ | ✅ | ✅ | ✅ |
| DeepSeek v3.2 via gateway (non-Claude) | ⚠️ | ⚠️ | ❓ | ✅ |
| GPT / Gemini via gateway | ❓ | ❓ | ❓ | ❓ |

Notes:

- **Claude** is the reference tier — full fidelity on every flow, native or via a gateway.
- **DeepSeek (and weaker models)**: the full pipeline completes and produces
  substantive findings, but a model that ignores the JSON contract (e.g. emits
  native tool-call markup) yields partial `search` columns — handled gracefully,
  not a crash. The structured-output fallback (prompt-instructed JSON + a
  robust extractor) mitigates this; final fidelity is the model's responsibility.
- **GPT / Gemini via gateway**: reachable by construction (same wire protocol)
  but not validated live here — verify with `dd-agents doctor --probe` + a trial
  `search` before a production run.
- This matrix is a point-in-time validation record, not a guarantee. The
  authoritative, continuous check is the `-m gateway` test (run on every push to
  `main` via the **Gateway Provider Proof** CI job) plus your own
  `dd-agents doctor --probe`.

## Reproduce

Stand up a gateway and point dd-agents at it (the recipe in
[`examples/litellm-gateway/`](https://github.com/zoharbabin/due-diligence-agents/tree/main/examples/litellm-gateway)),
then:

```bash
export ANTHROPIC_BASE_URL=http://localhost:4011 ANTHROPIC_AUTH_TOKEN=sk-anything
dd-agents doctor --probe                 # confirm routing + a live round-trip
dd-agents run deal-config.json           # full pipeline through your provider
```

The gateway end-to-end test (`tests/e2e/test_gateway_provider.py -m gateway`) is
the automated version of the `doctor --probe` check. It runs continuously on
every push to `main` (the **Gateway Provider Proof** CI job stands up a LiteLLM
proxy in front of the Anthropic Messages API and round-trips a real query), and
you can run it against your own gateway by setting `DD_TEST_GATEWAY_URL`.
