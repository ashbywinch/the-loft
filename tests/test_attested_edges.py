"""The attested-edges eval (2026-08-06, user: make sure edges don't get
lost again).

The family tree can only place people who have family edges — a person
whose *text* attests a family link ("married X", "X's son") but whose
relationships lack the edge is stranded in "Also in the archive". Ernie,
Walter and Quentin were exactly that. This eval scans the live archive's
relation/bio text for attested spouse/parent/inlaw links and refuses the
build if any lacks the corresponding edge — a text claim with no edge is
a lost edge, wherever it happens.

Same-name people are resolved leniently: the edge exists if ANY person
with that name is linked. Unresolvable names (no cast match) are skipped —
the eval checks what the archive can name, never invents.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parent.parent

# text patterns -> the edge kind the claim asserts. Parent links may name
# one or both parents ("son of ? Corbett and Harper Pryce") — the first named
# parent suffices for the check.
PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"married ([A-Z][\w' -]+?)(?:,|\.|\(|\b\d|$)"), "spouse"),
    (re.compile(r"([A-Z][\w' -]+?)'s husband"), "spouse"),
    (re.compile(r"([A-Z][\w' -]+?)'s wife"), "spouse"),
    (re.compile(r"husband of ([A-Z][\w' -]+)"), "spouse"),
    (re.compile(r"wife of ([A-Z][\w' -]+)"), "spouse"),
    (re.compile(r"son of ([A-Z?][\w' -]+?)(?: and |\.|$)"), "parent"),
    (re.compile(r"daughter of ([A-Z?][\w' -]+?)(?: and |\.|$)"), "parent"),
    (re.compile(r"child of ([A-Z?][\w' -]+?)(?: and |\.|$)"), "parent"),
    (re.compile(r"sister-in-law of ([A-Z][\w' -]+)"), "inlaw"),
    (re.compile(r"brother-in-law of ([A-Z][\w' -]+)"), "inlaw"),
]


def _latest(paths: list[Path]) -> Path:
    best: tuple[int, Path] | None = None
    for p in paths:
        m = re.search(r"(\d+)\.json$", p.name)
        version = int(m.group(1)) if m else 1
        if best is None or version > best[0]:
            best = (version, p)
    assert best is not None
    return best[1]


def _resolve_candidates(name: str, people: list[dict[str, Any]]) -> list[str]:
    """Every person whose name or alias matches — same-name people are
    common in a family archive, and the edge may link any of them."""
    wanted = name.strip().strip(".").strip().lower()
    if not wanted:
        return []
    return [
        p["id"] for p in people if p["name"].lower() == wanted or wanted in [a.lower() for a in p.get("aliases", [])]
    ]


@pytest.mark.skipif(not (REPO / "archive" / "people.json").exists(), reason="archive not bootstrapped yet")
def test_attested_family_links_have_edges() -> None:
    paths = sorted((REPO / "archive").glob("people*.json"))
    table: dict[str, Any] = json.loads(_latest(paths).read_text(encoding="utf-8"))
    people = table.get("people", [])
    edges = [r for r in table.get("relationships", []) if r.get("kind") in ("spouse", "parent", "inlaw")]

    def linked(a: str, b: str, kind: str) -> bool:
        return any(
            e.get("kind") == kind and ((e["a"] == a and e["b"] == b) or (e["a"] == b and e["b"] == a)) for e in edges
        )

    offenders: list[str] = []
    for person in people:
        text = f"{person.get('relation', '')} {person.get('bio', '')}"
        for pattern, kind in PATTERNS:
            for match in pattern.finditer(text):
                targets = _resolve_candidates(match.group(1), people)
                if not targets:
                    continue  # an unnameable claim — the archive can't check it
                if person["id"] in targets:
                    continue  # "wife of X" where X is oneself — an artifact, not a link
                if not any(linked(person["id"], t, kind) for t in targets):
                    offenders.append(
                        f"{person.get('name')} ({person['id']}): text says '{match.group(0).strip()}' "
                        f"but no {kind} edge links {', '.join(targets)}"
                    )
    assert not offenders, "text-attested family links with no edge — the tree cannot place them:\n" + "\n".join(
        sorted(set(offenders))
    )
