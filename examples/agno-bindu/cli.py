"""One-shot CLI for the Atlas DD Analyst.

Usage:
    uv run python examples/agno-bindu/cli.py "How many P0 findings are there?"
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule

# Load the example's .env before importing `agent`, which builds the model at
# import time and needs OPENROUTER_API_KEY.
load_dotenv(Path(__file__).with_name(".env"))

from agent import agent, report_path  # noqa: E402  (after load_dotenv, by design)

console = Console()
err = Console(stderr=True)


def main() -> int:
    if len(sys.argv) < 2:
        err.print("[bold red]Error:[/bold red] pass a question as an argument.")
        return 2
    question = " ".join(sys.argv[1:])
    console.print(Panel.fit(question, title="Question", border_style="cyan"))
    err.print(f"[dim]report: {report_path()}[/dim]")
    try:
        with err.status("[bold cyan]Analyzing the report…[/bold cyan]", spinner="dots"):
            result = agent.run(input=question)
    except Exception as exc:  # noqa: BLE001 — surface any failure to the user
        err.print(f"[bold red]Error:[/bold red] {exc}")
        return 1
    answer = getattr(result, "content", None) or str(result)
    console.print(Rule(style="dim"))
    console.print(Markdown(answer))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
