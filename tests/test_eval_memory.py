"""Tests for the eval entry surface: the fail-fast contract — an eval that
cannot run must say so loudly (2026-08-05). The evals now run under pytest
(2026-08-10, user: use the framework's selection, not custom CLI flags), so
the contract is pinned through that surface: ``pytest -m eval`` with no API
key must fail with the message, never skip silently."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(
    not (REPO / "app" / "data" / "people.json").exists(),
    reason="app/data not bootstrapped yet (the public tree ships no dataset)",
)
def test_eval_fails_fast_without_api_key() -> None:
    """pytest -m eval with no API key must exit non-zero — a silent SKIP
    hides an eval that never ran (2026-08-05). The env is scrubbed of every
    key source (OPENAI_*, LOFT_AI_*) so the eval cannot find a key."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OPENAI_", "LOFT_AI_"))}
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-m", "eval", "-k", "arc", "-q", "--no-header"],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO,
        timeout=180,
    )
    assert result.returncode != 0, f"eval exited 0 without a key — output: {result.stdout}"
    assert "API key" in result.stdout + result.stderr
