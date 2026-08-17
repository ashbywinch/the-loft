"""Mechanical standards checks (docs/coding-standards.md,
docs/testing-standards.md): rules that are stated as house convention and
are cheaply verifiable in code. The shape/behaviour rules (fail-fast
patterns, UX conventions, no backward-compat shims) stay with the LLM
reviewer — the reviewer is the right tool for judgement, these for fact."""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# vendored — the .venv-htr-only stage, foreign-interpreter code not subject
# to this repo's module contract; the same set ruff and pyrefly exclude.
# (The code-health tools were vendored here but are now served by lucidlint
# from its own repo — deleted 2026-08-16.)
VENDORED = {"layout_detect.py"}


def test_every_tools_module_has_a_docstring() -> None:
    """docs/coding-standards.md: every public module gets a docstring
    stating its contract — a module that can't say what it does is a
    candidate for deletion, not a comment."""

    missing = [
        path.name
        for path in sorted((REPO / "tools").glob("*.py"))
        if path.name not in VENDORED and not path.read_text(encoding="utf-8").lstrip().startswith(('"""', "'''"))
    ]
    assert not missing, f"tools modules missing a docstring: {missing}"


def test_no_runtime_dependencies() -> None:
    """docs/TECH-SPEC.md §2 / coding-standards.md: no framework, no build
    step, no runtime npm deps — the app ships as files. A "dependencies"
    entry in package.json is a decision point, never a silent addition."""

    package = json.loads((REPO / "package.json").read_text(encoding="utf-8"))
    assert "dependencies" not in package, "runtime dependencies are a standards change — discuss first"
