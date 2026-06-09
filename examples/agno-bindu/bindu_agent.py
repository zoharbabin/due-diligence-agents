"""Atlas DD Analyst exposed as a Bindu A2A agent (synchronous — no MCP, no loop).

The handler reads a completed dd-agents report through the upstream finding index
and lets the agno agent answer over it. The tools are deterministic and need no
key; only the agno model call needs your chosen provider's credentials
(BINDU_AGENT_PROVIDER; see .env.example).

Run:  uv run python examples/agno-bindu/bindu_agent.py
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from agent import get_agent
from bindu.penguin.bindufy import bindufy
from dotenv import load_dotenv
from prompts import AGENT_DESCRIPTION

# Load the example's .env so the provider credentials are present before the
# model is built. The agent is built lazily inside get_agent(), so importing
# `agent` above is key-free; the key is only needed on the first request.
load_dotenv(Path(__file__).with_name(".env"))

logger = logging.getLogger(__name__)


def handler(messages):
    """Sync Bindu handler. ``messages`` is OpenAI-style [{role, content}, ...]."""
    user_content = " ".join((m.get("content") or "") for m in (messages or []) if m.get("role") == "user").strip()
    if not user_content:
        return (
            "Send me a question about the loaded due-diligence report — e.g. "
            '"How many P0 findings are there?" or "What\'s the biggest '
            'customer-concentration risk?"'
        )
    # Guard the model call: a network-exposed handler must return a deliverable
    # string on transient model/key errors rather than leak a raw traceback.
    try:
        result = get_agent().run(input=user_content)
    except Exception as exc:  # noqa: BLE001 — surface a clean message over A2A
        logger.exception("Atlas DD Analyst run failed")
        return f"Sorry — I could not complete that request: {exc}"
    return getattr(result, "content", None) or str(result)


# Optional bearer token for the A2A endpoint. Strongly recommended before
# exposing publicly (BINDU_EXPOSE=true) — without it, every accepted request
# spends your provider key and returns full report contents.
_AUTH_TOKEN = os.getenv("BINDU_AUTH_TOKEN", "").strip()
_EXPOSE = os.getenv("BINDU_EXPOSE", "false").lower() == "true"
if _EXPOSE and not _AUTH_TOKEN:
    logger.warning(
        "BINDU_EXPOSE=true but BINDU_AUTH_TOKEN is unset: the agent will be "
        "publicly reachable with NO application-layer auth — every call bills "
        "your provider key and returns report contents. Set BINDU_AUTH_TOKEN "
        "or keep BINDU_EXPOSE=false for local use."
    )

config = {
    "author": os.getenv("BINDU_AGENT_AUTHOR", "bindu-examples@example.com"),
    "name": os.getenv("BINDU_AGENT_NAME", "bindu-dd-analyst"),
    "description": AGENT_DESCRIPTION,
    "deployment": {
        "url": os.getenv("BINDU_AGENT_URL", "http://localhost:3773"),
        # expose=true opens a PUBLIC tunnel with your model key on the billing
        # path. Off by default; set BINDU_AUTH_TOKEN and read the README first.
        "expose": _EXPOSE,
        # CORS origins for browser clients; override for your own front-end.
        "cors_origins": [
            o.strip() for o in os.getenv("BINDU_CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()
        ],
    },
    "capabilities": {"streaming": False},
}


if __name__ == "__main__":
    bindufy(config, handler)
