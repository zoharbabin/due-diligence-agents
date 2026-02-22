.PHONY: install-dev test test-unit test-integration test-e2e lint typecheck format verify clean

# Install all development dependencies (including type stubs for mypy)
install-dev:
	pip install -e ".[dev,vector,ocr]" types-openpyxl types-networkx
	pre-commit install

# Run all tests (unit + integration, excludes e2e)
test: test-unit test-integration

# Run unit tests only (no API calls, fast)
test-unit:
	pytest tests/unit/ -v --tb=short

# Run integration tests (no API calls by default)
test-integration:
	pytest tests/integration/ -v --tb=short -k "not test_agent_spawning"

# Run end-to-end tests (requires ANTHROPIC_API_KEY, slow, costs money)
test-e2e:
	pytest tests/e2e/ -v --tb=long -m "e2e"

# Lint check with ruff
lint:
	ruff check src/ tests/
	ruff format --check src/ tests/

# Type check with mypy
typecheck:
	mypy src/ --strict

# Auto-format code with ruff
format:
	ruff check --fix src/ tests/
	ruff format src/ tests/

# Run all verification gates (lint + typecheck + tests) — must all pass before merge
verify: lint typecheck test

# Clean build artifacts, caches, and temp files
clean:
	rm -rf build/ dist/ *.egg-info .eggs/
	rm -rf .mypy_cache/ .pytest_cache/ .ruff_cache/
	rm -rf results/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
