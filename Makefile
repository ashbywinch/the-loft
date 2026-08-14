# Makefile for The Loft — family history museum web app.
# Single dev entry point: every dev action goes through make.
# CI runs exactly: make setup && make lint-github && make coverage — the
# suites run ONCE (inside coverage), never twice (2026-08-11: make test +
# make coverage both re-ran pytest and vitest in CI). make test stays as
# the local fast gate.

PYTHON := .venv/bin/python
RUFF := .venv/bin/ruff
PYREFLY := .venv/bin/pyrefly
NPM := npm

GREEN := \033[0;32m
YELLOW := \033[0;33m
RED := \033[0;31m
NC := \033[0m

help:
	@echo "The Loft — available commands:"
	@echo "  ${GREEN}make setup${NC}        Create venv, install deps (Python + JS) + pre-commit hooks"
	@echo "  ${GREEN}make serve${NC}        Serve app/ on the LAN — open the printed address on any device"
	@echo "  ${GREEN}make lint${NC}         Check code quality (ruff + eslint)"
	@echo "  ${GREEN}make typecheck${NC}    Static type check (pyrefly, Python tools)"
	@echo "  ${GREEN}make test${NC}         Run tests (lint + typecheck gate; pytest + vitest)"
	@echo "  ${GREEN}make format${NC}       Auto-fix formatting issues"
	@echo "  ${GREEN}make coverage${NC}     Run tests with coverage report"
	@echo "  ${GREEN}make evals${NC}        Run the real-model evals (pytest -m eval — needs the API key; select pieces with -k)"
	@echo "  ${GREEN}make verify${NC}       Run the archive-quality data checks (pytest -m archive — the drift guard, completeness, no-PII)"
	@echo "  ${GREEN}make eval-changed${NC} Run only the evals the current changes affect"
	@echo "  ${GREEN}make clean${NC}        Remove .venv, node_modules and generated files"

setup:
	@uv --version >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh
	@uv sync --locked
	@if [ ! -d node_modules ] || [ ! -f node_modules/.package-lock.json ] || [ package-lock.json -nt node_modules/.package-lock.json ]; then $(NPM) ci --no-audit --no-fund; fi  # ci stays reproducible; skipped when the lock is unchanged (2026-08-13: a full reinstall on every make call was the suite's fixed 3 s tax)
	@uv run pre-commit install
	@[ -f .env ] || cp .env.example .env

serve: setup
	@./loft serve --host 0.0.0.0 --port 8000


lint: setup
	@$(RUFF) check tools/ tests/
	@$(PYTHON) -m compileall -q tools/  # a parse error survives ruff/pyrefly — compile it (2026-08-06)
	@$(NPM) run lint

lint-github: setup
	@$(RUFF) check tools/ tests/ --output-format=github
	@$(NPM) run lint

typecheck: setup
	@$(PYREFLY) check

test: setup lint typecheck
	@$(PYTHON) -m pytest
	@$(NPM) run test

coverage: setup lint typecheck
	@$(PYTHON) -m pytest --cov=tools --cov-report=term-missing --cov-report=xml
	@$(NPM) run coverage

evals: setup
	@$(PYTHON) -m pytest -m eval -q

eval: evals

verify: setup
	@$(PYTHON) -m pytest -m archive -q  # the archive-quality data checks (drift guard, completeness, descriptions, no-PII, …) — skipped in CI, no archive there

eval-changed: setup
	@MARKERS=$$($(PYTHON) tools/affected_evals.py); \
	if [ "$$MARKERS" = "none" ]; then \
		echo "no evals affected by the current changes"; \
	else \
		echo "running the affected evals ($$MARKERS)"; \
		$(PYTHON) -m pytest -m "eval and ($$MARKERS)" -q; \
	fi

format: setup
	@$(RUFF) check --fix tools/ tests/
	@$(RUFF) format tools/ tests/
	@$(NPM) run format

	@$(PYTHON) tools/scan.py docs $(ARGS)

	@$(PYTHON) tools/scan.py photos $(ARGS)




clean:
	@rm -rf .venv node_modules htmlcov/ app/coverage/
	@rm -f .coverage coverage.xml
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete
