"""Atlas DD Analyst exposed as a Bindu A2A agent (synchronous — no MCP, no loop).

The handler reads a completed dd-agents report through the upstream finding index
and lets the agno agent answer over it. Tools are deterministic and need no
Anthropic key; only the agno model call (via OpenRouter) needs OPENROUTER_API_KEY.

Run:  uv run python examples/agno-bindu/bindu_agent.py
"""

from __future__ import annotations

import os
from pathlib import Path

from bindu.penguin.bindufy import bindufy
from dotenv import load_dotenv
from prompts import AGENT_DESCRIPTION

# Load the example's .env before importing `agent`, which builds the model at
# import time and needs OPENROUTER_API_KEY.
load_dotenv(Path(__file__).with_name(".env"))

from agent import agent  # noqa: E402  (after load_dotenv, by design)


def handler(messages):
    """Sync Bindu handler. ``messages`` is OpenAI-style [{role, content}, ...]."""
    user_content = " ".join((m.get("content") or "") for m in (messages or []) if m.get("role") == "user").strip()
    if not user_content:
        return (
            "Send me a question about the loaded due-diligence report — e.g. "
            '"How many P0 findings are there?" or "What\'s the biggest '
            'customer-concentration risk?"'
        )
    result = agent.run(input=user_content)
    return getattr(result, "content", None) or str(result)


config = {
    "author": os.getenv("BINDU_AGENT_AUTHOR", "bindu-examples@example.com"),
    "name": os.getenv("BINDU_AGENT_NAME", "bindu-dd-analyst"),
    "description": AGENT_DESCRIPTION,
    "deployment": {
        "url": os.getenv("BINDU_AGENT_URL", "http://localhost:3773"),
        # expose=true opens a PUBLIC, unauthenticated tunnel with your model key
        # on the billing path. Off by default; read the README before enabling.
        "expose": os.getenv("BINDU_EXPOSE", "false").lower() == "true",
        "cors_origins": ["http://localhost:5173"],
    },
    "capabilities": {"streaming": False},
}


if __name__ == "__main__":
    bindufy(config, handler)
