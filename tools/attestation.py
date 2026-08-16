"""The attested-edge scanner (2026-08-06, user: edges must not get lost).

The family tree can only place people who have family edges — a person
whose *text* attests a family link ("married X", "X's son") but whose
relationships lack the edge is stranded in "Also in the archive". This
module finds those gaps in any people table; the archive eval and the
letter-import eval both refuse the build when it returns offenders.

Same-name people are resolved leniently: the edge exists if ANY person
with that name is linked. Unresolvable names (no cast match) are skipped —
the scanner checks what the table can name, never invents.
"""

from __future__ import annotations

import re
from typing import Any

# text patterns -> the edge kind the claim asserts. Parent links may name
# one or both parents ("son of ? Corbett and Harper Pryce") — the first named
# parent suffices for the check.
PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"married ([A-Z][\w' -]+?)(?:,|\.|\(|\b\d|$)"), "spouse"),
    (re.compile(r"([A-Z][\w' -]+?)'s husband"), "spouse"),
    (re.compile(r"([A-Z][\w' -]+?)'s wife"), "spouse"),
    (re.compile(r"husband of ([A-Z][\w' -]+)"), "spouse"),
    (re.compile(r"wife of ([A-Z][\w' -]+)"), "spouse"),
    (re.compile(r"son of ([A-Z?][\w' -]+?)(?: and |\.|$)"), "parent"),
    (re.compile(r"daughter of ([A-Z?][\w' -]+?)(?: and |\.|$)"), "parent"),
    (re.compile(r"child of ([A-Z?][\w' -]+?)(?: and |\.|$)"), "parent"),
    (re.compile(r"father of ([A-Z][\w' -]+?)(?: and |\.|$)"), "parent"),
    (re.compile(r"mother of ([A-Z][\w' -]+?)(?: and |\.|$)"), "parent"),
    (re.compile(r"sister-in-law of ([A-Z][\w' -]+)"), "inlaw"),
    (re.compile(r"brother-in-law of ([A-Z][\w' -]+)"), "inlaw"),
)


def _resolve_candidates(name: str, people: list[dict[str, Any]]) -> list[str]:
    """Every person the claimed name can denote — same-name people are
    common in a family archive, and the edge may link any of them.
    Possessive claims ("Pearl's husband") capture first names, so a name
    that starts with the claim or contains it as a word also matches."""
    wanted = name.strip().strip(".").strip().lower()
    if not wanted:
        return []
    single_word = " " not in wanted
    return [
        p["id"]
        for p in people
        if p.get("name", "").lower() == wanted
        or wanted in [a.lower() for a in p.get("aliases", [])]
        or p.get("name", "").lower().startswith(wanted + " ")
        or (single_word and wanted in p.get("name", "").lower().split())
    ]


def attested_edge_gaps(people: list[dict[str, Any]], relationships: list[dict[str, Any]]) -> list[str]:
    """Text-attested spouse/parent/inlaw links that lack the edge.

    Returns human-readable offenders ("<name> (<id>): text says '<claim>'
    but no <kind> edge links <targets>"), one per claim.
    """
    edges = [r for r in relationships if r.get("kind") in ("spouse", "parent", "inlaw")]

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
                    continue  # an unnameable claim — the table can't check it
                if person["id"] in targets:
                    continue  # "wife of X" where X is oneself — an artifact, not a link
                if not any(linked(person["id"], t, kind) for t in targets):
                    offenders.append(
                        f"{person.get('name')} ({person['id']}): text says '{match.group(0).strip()}' "
                        f"but no {kind} edge links {', '.join(targets)}"
                    )
    return sorted(set(offenders))
