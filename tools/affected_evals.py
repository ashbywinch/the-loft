"""Change-aware eval selection (2026-08-10, user: an incremental option for
regular use — the neighbour project's pattern, an explicit conservative
mapping instead of a graph). Prints the pytest marker expression for the
suites the current changes affect, or ``none``:

    python tools/affected_evals.py        # -> "eval_review" | "eval_review or eval_transcription" | "none"

A change to a shared module (tools/ai_client.py) runs every suite that
imports it. `make eval-changed` turns the expression into
`pytest -m "eval and (…)"`.
"""

from __future__ import annotations

import subprocess
import sys

# The marker expression per changed file — "or" joins the suites the file
# feeds (a shared module is imported by several).
CHANGED_TO_MARKERS: dict[str, str] = {
    "tools/review.py": "eval_review",
    "tools/eval_review.py": "eval_review",
    "tools/records.py": "eval_review or eval_memory",
    "tools/archive.py": "eval_review",
    "tools/server.py": "eval_review",
    "tools/ai_client.py": "eval_review or eval_memory",
    "app/views/import.js": "eval_review",
    "tools/memory.py": "eval_memory",
    "tools/eval_memory.py": "eval_memory",
    "tools/ocr.py": "eval_transcription",
    "tools/eval_transcription.py": "eval_transcription",
    "tests/fixtures/": "eval_transcription",
}


def _git_base() -> str:
    for ref in ("loft/main", "origin/main"):
        result = subprocess.run(["git", "rev-parse", "--verify", "-q", ref], capture_output=True, text=True)
        if result.returncode == 0:
            return ref
    return "HEAD"


def affected_markers() -> str:
    """The pytest marker expression for the suites the current changes
    affect — committed since the base branch, staged, and unstaged."""
    files: list[str] = []
    for spec in ("", "--cached"):
        args = ["git", "diff", "--name-only"] + ([spec] if spec else [])
        result = subprocess.run(args, capture_output=True, text=True)
        files += result.stdout.splitlines()
    result = subprocess.run(["git", "diff", "--name-only", _git_base()], capture_output=True, text=True)
    files += result.stdout.splitlines()
    markers: set[str] = set()
    for f in files:
        if f in CHANGED_TO_MARKERS:
            markers.update(CHANGED_TO_MARKERS[f].split(" or "))
        elif f.startswith("tests/fixtures/"):
            markers.update(CHANGED_TO_MARKERS["tests/fixtures/"].split(" or "))
    return " or ".join(sorted(markers)) or "none"


if __name__ == "__main__":
    print(affected_markers())
    sys.exit(0)
