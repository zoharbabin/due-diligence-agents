# Exposing a dd-agents report as a network-addressable Bindu agent

`dd-agents` produces a rich, cited due-diligence report for a deal — 44 findings
across nine domains for the bundled Project Atlas sample alone. This directory
turns a *finished* report into a conversational agent you can ask questions over
the network: "How many P0 findings? What's the biggest customer-concentration
risk? Show me the exact clause." It's a small, self-contained example built with
[agno](https://github.com/agno-agi/agno) and [Bindu](https://github.com/GetBindu/Bindu).

> **Community-built example.** Not affiliated with or endorsed by the
> due-diligence-agents maintainers. The `dd_agents` package is the real engine
> and the source of truth, under its own Apache-2.0 LICENSE; this directory is
> example *glue* showing one way to serve a report it produced.

Contributed by the team at [Bindu](https://github.com/GetBindu/Bindu). The agent
reads a completed report through `dd-agents`' own finding index and answers in
plain language with citations. We link back to this repo as the canonical source
of the analysis from Bindu's examples index, so discovery flows both ways.

## Maintenance

The due-diligence engine (everything under `src/dd_agents/`) is maintained by the
dd-agents maintainers — file analysis/data issues there. For issues with **this
example** (the Bindu glue, the prompt, this README), open an issue on
[Bindu](https://github.com/GetBindu/Bindu) and tag it `[dd-agents example]`, or
reach the Bindu team on Discord. Please don't burden the upstream maintainers with
glue-specific questions.

## What the example does

The pipeline (`dd-agents run`) is the heavy, expensive part: it reads a data room
and writes merged findings to `…/runs/latest/findings/merged/*.json`. This agent
is the **light** part on the other side of that output. It:

1. Loads a completed report's merged findings through the upstream
   `dd_agents.query.FindingIndexer` — pure, deterministic Python, **no LLM**.
2. Exposes three tools to an agno agent: `report_overview`, `list_findings`,
   `get_finding`.
3. Lets the agno model (via OpenRouter) reason over those tools and answer
   conversationally, leading with the answer and citing the source document,
   section, and exact quote.

Because the retrieval is deterministic and the only model call is agno's, **this
example needs only an OpenRouter key — no Anthropic key**. (The dd-agents
*pipeline* still needs Anthropic/Bedrock; reading its output here does not.)

By default the agent reads the bundled, 100%-synthetic **Project Atlas** golden
report this repo ships at `docs/marketing/sample-report-atlas/` (real pipeline
output: 2 P0, 10 P1, 17 P2, 15 P3 findings — the hero being a customer worth
30.1% of ARR with a change-of-control termination right). Point `DD_REPORT_DIR`
at any `dd-agents run` output (its `runs/latest`) to analyze a real deal.

## The libraries it uses

- **[dd-agents](https://github.com/zoharbabin/due-diligence-agents)** — the
  upstream engine. We use its `query` finding index to load and slice a report.
- **[agno](https://github.com/agno-agi/agno)** — the agent loop: model call,
  tool-calling, and response synthesis.
- **[Bindu](https://github.com/GetBindu/Bindu)** — wraps the agent as an A2A
  service with a DID identity, a public agent card, and JSON-RPC endpoints.

## Setup

All commands run from the **repo root**, with [uv](https://docs.astral.sh/uv/).

```bash
uv venv                                                  # create a venv (Python 3.12+)
uv pip install -e .                                      # the dd-agents engine (this repo)
uv pip install -r examples/agno-bindu/requirements.txt   # agno + Bindu glue
cp examples/agno-bindu/.env.example examples/agno-bindu/.env
# edit examples/agno-bindu/.env and set OPENROUTER_API_KEY
```

## Run the CLI (one-shot)

The fastest way to try it — no server:

```bash
uv run python examples/agno-bindu/cli.py "How many P0 findings are there, and what are they?"
```

The agent calls `report_overview` / `list_findings` / `get_finding`, then answers from
the report (real output against the bundled Atlas report, trimmed):

```text
There are 2 P0 findings (deal-stoppers), and both concern the same risk:
Meridian Freight — representing 30.1% of ARR — holds an unconditional, immediate
change-of-control termination right that will be triggered by this acquisition.

1. Finance P0 — forensic-dd_finance_northwind_logistics_0001
   $12.4M ARR (30.1% of $41.2M) can terminate immediately on close, "sole and
   absolute discretion", no cure period; obligates a pro-rata refund of prepaid fees.
   Source: Northwind_Logistics/msa_meridian_freight.pdf.md, §12.3(c)–(d):
   "in the event of a Change of Control of Provider, Customer may terminate this
    Agreement, effective immediately … shall not … be subject to any cure period …"

2. Commercial P0 — forensic-dd_commercial_northwind_logistics_0002
   Same Meridian clause, commercial lens; the board deck (Slide 8) represented "No
   customer-termination, change-of-control … items are flagged" — contradicted here.

Sources: forensic-dd_finance_northwind_logistics_0001,
         forensic-dd_commercial_northwind_logistics_0002
```

## Run the A2A service

```bash
uv run python examples/agno-bindu/bindu_agent.py
```

This starts a Bindu agent on `http://localhost:3773` with:

- `GET /.well-known/agent.json` — the agent card. The DID is published under
  `capabilities.extensions[].uri` as `did:bindu:…`.
- `GET /.well-known/did.json` — the DID document.
- `GET /health` — health payload (look for `health: healthy` and
  `application.agent_did`).
- `POST /` — JSON-RPC 2.0: `message/send` (returns a task with `id` and state
  `submitted`) and `tasks/get` (poll with that id until `completed`).

Quick check:

```bash
curl -s localhost:3773/.well-known/agent.json | jq '.name, .capabilities.extensions[].uri'
curl -s localhost:3773/health | jq '.health, .application.agent_did'
```

## Try it out

`message/send` is asynchronous and the JSON-RPC `id` plus the three message ids
must be **real UUIDs** — this self-contained snippet generates them, sends one
question, and polls `tasks/get` until the task is terminal:

```bash
BASE=http://localhost:3773
Q="What is the single biggest risk to this deal, and which domains flag it?"
uuid() { uuidgen | tr 'A-Z' 'a-z'; }
RPC=$(uuid); MSG=$(uuid); CTX=$(uuid); TASK=$(uuid)

# message/send returns a task object; capture its id, then poll tasks/get for it.
SUBMIT=$(curl -s -X POST "$BASE" -H 'content-type: application/json' -d "{
  \"jsonrpc\":\"2.0\",\"id\":\"$RPC\",\"method\":\"message/send\",
  \"params\":{
    \"configuration\":{\"acceptedOutputModes\":[\"text/plain\"]},
    \"message\":{\"role\":\"user\",\"messageId\":\"$MSG\",\"contextId\":\"$CTX\",
      \"taskId\":\"$TASK\",\"kind\":\"message\",
      \"parts\":[{\"kind\":\"text\",\"text\":\"$Q\"}]}
  }
}")
echo "$SUBMIT" | jq -r '.result.status.state'   # -> submitted
TID=$(echo "$SUBMIT" | jq -r '.result.id')

# poll until terminal, then print the answer (tasks/get takes {"task_id": ...})
for i in $(seq 1 45); do
  R=$(curl -s -X POST "$BASE" -H 'content-type: application/json' -d "{
    \"jsonrpc\":\"2.0\",\"id\":\"$(uuid)\",\"method\":\"tasks/get\",
    \"params\":{\"task_id\":\"$TID\"}}")
  S=$(echo "$R" | jq -r '.result.status.state // "?"')
  [ "$S" = completed ] && { echo "$R" | jq -r '.result.artifacts[0].parts[0].text'; break; }
  [ "$S" = failed ] && { echo "task failed"; break; }
  sleep 2
done
```

The poll prints the agent's answer (real output against the bundled Atlas report, trimmed):

```text
# The single biggest risk: Meridian Freight's unconditional change-of-control termination right

Two P0 (deal-stopper) findings describe the same issue: Meridian Freight — the largest
customer at 30.1% of ARR ($12.4M) — holds an unconditional, immediate termination right
triggered by Summit's acquisition, with no cure period and no carve-outs.

Which domains flag it
- Finance (forensic-dd_finance_northwind_logistics_0001): quantifies 30.1% of ARR at risk,
  exceeding the 20%-revenue / no-cure CoC deal-stopper threshold.
- Commercial (forensic-dd_commercial_northwind_logistics_0002): the clause mechanics, and that
  the board deck (Slide 8) represented "No … change-of-control … items are flagged".

From Northwind_Logistics/msa_meridian_freight.pdf.md, §12.3(c)-(d):
> "in the event of a Change of Control of Provider, Customer may terminate this Agreement,
>  effective immediately … shall not … be subject to any cure period, transition period …"

Sources: forensic-dd_finance_northwind_logistics_0001, forensic-dd_commercial_northwind_logistics_0002
```

> **Sending documents:** ask questions about a report that already exists; this
> agent does not accept file uploads. To analyze new documents, run the
> `dd-agents` pipeline first, then point `DD_REPORT_DIR` at its `runs/latest`.

## Network exposure & dependencies

- **Local by default.** The agent binds to `localhost` and CORS is limited to a
  local dev origin. Setting `BINDU_EXPOSE=true` asks Bindu to open a **public,
  unauthenticated** tunnel to the agent, with your OpenRouter key on the billing
  path. Leave it off unless you understand that.
- **Opt-in deps.** The extra packages live in `examples/agno-bindu/requirements.txt`
  and are installed only if you set this example up. Nothing here changes the
  `dd-agents` package, its CLI, or its CI.

## Files

| File | Purpose |
|------|---------|
| `agent.py` | The agno agent + the three finding-index tools |
| `bindu_agent.py` | Primary entry point — handler, config, `bindufy(...)` |
| `cli.py` | One-shot local runner |
| `prompts.py` | Agent name, description, and system prompt |
| `requirements.txt` | agno + Bindu glue deps (the engine comes from the parent repo) |
| `.env.example` | `OPENROUTER_API_KEY` + `DD_REPORT_DIR` and other knobs |
