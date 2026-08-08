"""Tests for the eval-memory runner (tools/eval_memory): the entry
point's fail-fast contract — an eval that cannot run must say so loudly."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_eval_fails_fast_without_api_key() -> None:
    """make eval with no API key must exit non-zero — a silent SKIP hides an
    eval that never ran (2026-08-05). The env is scrubbed of every key source
    (LOFT_AI_*, OPENCODE_API_KEY) and the opencode auth file is made
    unreachable via an empty XDG_DATA_HOME."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LOFT_AI_", "OPENCODE_API_KEY"))}
    env["XDG_DATA_HOME"] = str(REPO / ".eval-empty-xdg")
    result = subprocess.run(
        [sys.executable, "-m", "tools.eval_memory"],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO,
        timeout=60,
    )
    assert result.returncode != 0, f"eval exited 0 without a key — output: {result.stdout}"
    assert "API key" in result.stdout + result.stderr
