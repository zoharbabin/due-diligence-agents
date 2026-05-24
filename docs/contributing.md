# Contributing

See [CONTRIBUTING.md](https://github.com/zoharbabin/due-diligence-agents/blob/main/CONTRIBUTING.md) on GitHub for the full contribution guide.

## Quick Start for Contributors

```bash
git clone https://github.com/zoharbabin/due-diligence-agents.git
cd due-diligence-agents
pip install -e ".[dev,pdf]"
pre-commit install
```

## Quality Gates

```bash
pytest tests/unit/ -x -q && mypy src/ --strict && ruff check src/ tests/
```

## Pull Request Process

1. Branch from `main`
2. Write tests first, then implement
3. Ensure quality gates pass locally
4. Open a PR with a clear description
