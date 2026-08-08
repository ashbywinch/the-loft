"""The family tree's membership (2026-08-06, user): people the archive
attests as family must have family edges — Ernie Draper (married Marta
Voss), Quentin Whitlock (Pearl's husband), and Walter Lionel
Draper (Ernie's child, per the user) were confirmed people with no edges, so
the tree listed them as 'Also in the archive' when they are family."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from tools.document_capture import record_confirmed_family

REPO = Path(__file__).resolve().parent.parent


FAMILY_KINDS = {"spouse", "parent", "sibling", "inlaw"}


def _latest(paths: list[Path]) -> Path:
    best: tuple[int, Path] | None = None
    for p in paths:
        m = re.search(r"(\d+)\.json$", p.name)
        version = int(m.group(1)) if m else 1
        if best is None or version > best[0]:
            best = (version, p)
    assert best is not None
    return best[1]


@pytest.mark.skipif(not (REPO / "archive" / "people.json").exists(), reason="archive not bootstrapped yet")
def test_confirmed_family_members_have_family_edges() -> None:
    paths = sorted((REPO / "archive").glob("people*.json"))
    table: dict[str, Any] = json.loads(_latest(paths).read_text(encoding="utf-8"))
    edges = [r for r in table.get("relationships", []) if r.get("kind") in FAMILY_KINDS]
    linked = {e["a"] for e in edges} | {e["b"] for e in edges}
    confirmed = set(record_confirmed_family())
    missing = sorted(confirmed - linked)
    assert not missing, (
        f"confirmed family members have no family edge and appear in 'Also in the archive': {missing} "
        f"— Ernie↔Marta spouse, Ernie→Walter parent, Quentin↔Pearl spouse (user, 2026-08-06)"
    )
