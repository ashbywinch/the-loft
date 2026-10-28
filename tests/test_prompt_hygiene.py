"""Prompt modules carry no history lessons.

`docs/writing-documentation.md` § "No history lessons — docs, comments, or
prompts": a rule states the constraint, never the story of the failure that
produced it. The prompt text is the strictest case — an agent reads it to act,
and a dated anecdote spends that attention on the past — so the modules that
build prompts are checked here: no date in their source, comments and
docstrings included.

Docs are not scanned: a plan's dated status stamp ("done 2026-10-26") is a
record, not a lesson, and telling the two apart is a judgement the review bot
makes from the standard, not a regex.
"""

from __future__ import annotations

import re
from pathlib import Path


def test_no_prompt_module_carries_a_dated_lesson() -> None:
    """Every string in these modules can reach a model: the review's
    investigator, the memory capture's assessor, the transcription's reader,
    the VLM client."""
    repo = Path(__file__).parent.parent
    prompt_modules = (
        "tools/review.py",
        "tools/memory.py",
        "pipeline/model/vlm.py",
        "pipeline/transcribe/transcripts.py",
    )
    date = re.compile(r"\b20\d\d-\d\d\b")
    offenders = [
        f"{module}:{number}: {line.strip()}"
        for module in prompt_modules
        for number, line in enumerate((repo / module).read_text(encoding="utf-8").splitlines(), start=1)
        if date.search(line)
    ]
    assert not offenders, "a date in a prompt module is a history lesson — state the rule instead:\n" + "\n".join(
        offenders
    )
