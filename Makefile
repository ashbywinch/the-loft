# Makefile for The Loft — family history museum web app.
# Single dev entry point: every dev action goes through make.
# CI runs exactly: make setup && make lint-github && make coverage && make
# verify — then make lucidlint (the code-health gate, from its own repo) — the
# suites run ONCE (inside coverage), never twice (2026-08-11: make test + make
# coverage both re-ran pytest and vitest in CI). make test stays as the local
# fast gate.
.PHONY: help setup serve lint lint-github typecheck test coverage format clean eval evals eval-changed verify scan-docs scan-photos adopt ingest confirm

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
	@echo "  ${GREEN}make scan-docs${NC}    Scan documents from the FF-680W into ~/loft/inbox (ARGS=\"--job …\")"
	@echo "  ${GREEN}make scan-photos${NC}  Scan photos from the FF-680W into ~/loft/inbox (ARGS=\"--job …\")"
	@echo "  ${GREEN}make adopt${NC}        Register a user scan folder in the registry in place (ARGS=\"<folder> --label …\")"
	@echo "  ${GREEN}make ingest${NC}       Orient + raw OCR + model guess for a batch (ARGS=\"<batch-id>\")"
	@echo "  ${GREEN}make confirm${NC}      User confirmation gate for a batch's guessed text (ARGS=\"<batch-id>\")"
	@echo "  ${GREEN}make clean${NC}        Remove .venv, node_modules and generated files"

# The gate's system-tool contract (coding-standards): a test that needs a
# system tool gets it from a make target, into the project — never sudo, never
# a ci.yml step. The OCR/evals tests run the real tesseract + ImageMagick, so
# this installs them into a micromamba env at .conda-tools (a sibling of .venv):
# same binary versions on every machine, CI == developer == anyone. Both are
# real file targets, so make's own timestamp rule does the "already installed"
# check — the env is rebuilt only when environment.yml (or micromamba) changes.
CONDA_TOOLS := .conda-tools
MICROMAMBA := $(HOME)/.local/bin/micromamba
CONDA_COMPLETE := $(CONDA_TOOLS)/.complete

$(MICROMAMBA):
	@os=$$(uname -s | tr 'A-Z' 'a-z'); arch=$$(uname -m); \
	case "$$os-$$arch" in \
		linux-x86_64) plat=linux-64;; linux-aarch64) plat=linux-aarch64;; \
		darwin-x86_64) plat=osx-64;; darwin-arm64) plat=osx-arm64;; \
		*) echo "error: unsupported platform $$os-$$arch for the project tools env"; exit 1;; \
	esac; \
	mkdir -p "$(HOME)/.local"; \
	curl -LsSf "https://micro.mamba.pm/api/micromamba/$$plat/latest" | tar -xj -C "$(HOME)/.local" bin/micromamba \
		|| { echo "error: micromamba bootstrap failed — re-run make setup"; exit 1; }

$(CONDA_COMPLETE): environment.yml $(MICROMAMBA)
	@$(MICROMAMBA) create -y -q -p "$(CURDIR)/$(CONDA_TOOLS)" -c conda-forge --file environment.yml \
		|| { echo "error: the project tools env (tesseract + magick) failed to create — see the output above"; exit 1; }
	@for tool in tesseract magick; do [ -x "$(CONDA_TOOLS)/bin/$$tool" ] || { echo "error: $$tool not in the project env after the install"; exit 1; }; done
	@touch $@

.PHONY: install-tools
install-tools: $(CONDA_COMPLETE)

# The project tools come first, so every make target (tests and the runtime
# scan/confirm flows alike) uses the pinned versions, not whatever OS/brew
# happens to be on PATH.
PATH := $(CURDIR)/$(CONDA_TOOLS)/bin:$(PATH)

setup: install-tools
	@uv --version >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh
	@uv sync --locked
	@if [ ! -d node_modules ] || [ ! -f node_modules/.package-lock.json ] || [ package-lock.json -nt node_modules/.package-lock.json ]; then $(NPM) ci --no-audit --no-fund; fi  # ci stays reproducible; skipped when the lock is unchanged (2026-08-13: a full reinstall on every make call was the suite's fixed 3 s tax)
	@uv run pre-commit install
	@[ -f .env ] || cp .env.example .env

serve: setup
	@./loft serve --host 0.0.0.0 --port 8000 --reload


lint: setup
	@$(RUFF) check tools/ tests/
	@$(PYTHON) -m compileall -q tools/  # a parse error survives ruff/pyrefly — compile it (2026-08-06)
	@$(PYTHON) -c "from pathlib import Path; css = Path('app/styles.css').read_text(); a, b = css.count('{'), css.count('}'); assert a == b, f'app/styles.css has {a} open and {b} close braces — an unclosed block swallows everything after it (2026-08-16: a mangled .rv-txa block hid the portrait media query and most review styles)'"
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

# lucidlint (github.com/ashbywinch/lucidlint) — the deterministic code-health
# gate, wired from its own repo per the project decision (2026-08-16, user):
# the in-repo code-health tools were deleted in its favour. The gate
# provisions its own environment — this target downloads the self-contained
# release bundle (SHA256SUMS-verified) into lucidlint-dist/ (gitignored), so
# CI == developer on the same compiled binary.
.PHONY: install-lucidlint lucidlint
LUCIDLINT_VERSION ?= 0.1.0
LUCIDLINT_ARCH ?= x86_64-unknown-linux-musl
LUCIDLINT_DIST := lucidlint-dist
LUCIDLINT_BUNDLE := $(LUCIDLINT_DIST)/lucidlint.py

install-lucidlint: $(LUCIDLINT_BUNDLE)

$(LUCIDLINT_BUNDLE):
	@mkdir -p $(LUCIDLINT_DIST)
	@curl -fsSLo $(LUCIDLINT_DIST)/lucidlint-v$(LUCIDLINT_VERSION)-$(LUCIDLINT_ARCH).tar.gz https://github.com/ashbywinch/lucidlint/releases/download/v$(LUCIDLINT_VERSION)/lucidlint-v$(LUCIDLINT_VERSION)-$(LUCIDLINT_ARCH).tar.gz
	@curl -fsSLo $(LUCIDLINT_DIST)/SHA256SUMS https://github.com/ashbywinch/lucidlint/releases/download/v$(LUCIDLINT_VERSION)/SHA256SUMS
	@cd $(LUCIDLINT_DIST) && grep "lucidlint-v$(LUCIDLINT_VERSION)-$(LUCIDLINT_ARCH).tar.gz" SHA256SUMS | sha256sum --check --status
	@tar -xzf $(LUCIDLINT_DIST)/lucidlint-v$(LUCIDLINT_VERSION)-$(LUCIDLINT_ARCH).tar.gz -C $(LUCIDLINT_DIST) --strip-components=1
	@rm -f $(LUCIDLINT_DIST)/lucidlint-v$(LUCIDLINT_VERSION)-$(LUCIDLINT_ARCH).tar.gz $(LUCIDLINT_DIST)/SHA256SUMS

lucidlint: install-lucidlint
	@echo "== lucidlint gate =="
	# NO baseline (user, 2026-08-29): the gate fails on EVERY finding —
	# a gate failure means the finding gets fixed, never locked
	@$(PYTHON) $(LUCIDLINT_BUNDLE) --repo .

eval: evals

verify: setup
	@$(PYTHON) -m pytest -m archive -q || [ $$? -eq 5 ]  # exit 5 = nothing selected (pre-B, the markers land later); real failures still fail

eval-changed: setup
	@MARKERS=$$($(PYTHON) tools/affected_evals.py); \
	if [ "$$MARKERS" = "none" ]; then \
		echo "no evals affected by the current changes"; \
	else \
		echo "running the affected evals ($$MARKERS)"; \
		$(PYTHON) -m pytest -m "(eval or archive) and ($$MARKERS)" -q; \
	fi

format: setup
	@$(RUFF) check --fix tools/ tests/
	@$(RUFF) format tools/ tests/
	@$(NPM) run format

scan-docs: setup
	@$(PYTHON) tools/scan.py docs $(ARGS)

scan-photos: setup
	@$(PYTHON) tools/scan.py photos $(ARGS)

adopt: setup
	@$(PYTHON) tools/adopt.py $(ARGS)

ingest: setup
	@$(PYTHON) tools/pipeline.py process $(ARGS)

confirm: setup
	@$(PYTHON) tools/pipeline.py review $(ARGS)

pipeline: setup
	@$(PYTHON) tools/pipeline.py $(ARGS)
clean:
	@rm -rf .venv node_modules htmlcov/ app/coverage/
	@rm -f .coverage coverage.xml
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete
