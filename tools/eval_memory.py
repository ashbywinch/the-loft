"""Eval for the elicitation assessment — run against the real model.

Not part of `make test` (tests never hit the network): this needs a network
and a configured key (LOFT_AI_KEY / OPENCODE_API_KEY / opencode auth.json).
Run with `loft eval-memory` (tools/cli.py).

The cases cover the family's own stories AND a fictional family (the
Kowalskis of Gdańsk), so the assessment cannot be tuned to one household's
data: the fictional cases assert the model never over-matches to this
family's cast/places, and the adversarial case pins the about-vs-mention
rule. The dob cases pin the age/date behaviour (docs/CONTRIBUTIONS.md).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tools.ai_client import AIClient, AIClientError
from tools.memory import BUCKETS, KINDS, MAX_QUESTIONS, MAX_SUGGESTIONS, Knowledge, assess

REPO = Path(__file__).resolve().parent.parent

AssertFn = Callable[[dict[str, Any]], list[str]]


def load_projection() -> dict[str, list[dict[str, Any]]]:
    data = REPO / "app" / "data"
    return {
        "people": json.loads((data / "people.json").read_text(encoding="utf-8"))["people"],
        "places": json.loads((data / "places.json").read_text(encoding="utf-8"))["places"],
        "themes": json.loads((data / "themes.json").read_text(encoding="utf-8"))["themes"],
        "items": json.loads((data / "index.json").read_text(encoding="utf-8"))["items"],
    }


# The elicitation speaks the family's language, never the process's — the
# hired genealogist's voice (PRD: "the assistant reads as a hired
# genealogist, not a computer", 2026-08-09; user: "make sure the
# requirement is in all relevant evals").
_PROCESS_JARGON = (
    "session",
    "interview",
    "elicitation",
    "draft",
    "the system",
    "the app",
    "question 1",
    "input",
)


def _persona_errors(result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for q in result.get("questions", []):
        text = str(q.get("text", "")).lower()
        for word in _PROCESS_JARGON:
            if word in text:
                errors.append(f"question echoes the process ('{word}'): {q.get('text', '')[:80]}")
    return errors


def contract_errors(result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    errors.extend(_persona_errors(result))
    if not isinstance(result.get("title"), str) or not result["title"].strip():
        errors.append("missing title")
    for ex in result.get("extractions", []):
        if ex.get("kind") not in KINDS:
            errors.append(f"extraction kind not in {KINDS}: {ex!r}")
        if ex.get("bucket") not in BUCKETS:
            errors.append(f"extraction bucket not in {BUCKETS}: {ex!r}")
        if not (ex.get("match") is None or isinstance(ex.get("match"), str)):
            errors.append(f"extraction match must be str|null: {ex!r}")
    questions = result.get("questions", [])
    if len(questions) > MAX_QUESTIONS:
        errors.append(f"more than {MAX_QUESTIONS} questions")
    for q in questions:
        if q.get("skippable") is not True:
            errors.append(f"question not skippable: {q!r}")
        suggestions = q.get("suggestions", [])
        if len(suggestions) > MAX_SUGGESTIONS or not all(isinstance(s, str) for s in suggestions):
            errors.append(f"bad suggestions: {suggestions!r}")
    return errors


def _matches(result: dict[str, Any]) -> list[str]:
    return [ex["match"] for ex in result.get("extractions", []) if ex.get("match")]


def _extraction_names(result: dict[str, Any]) -> list[str]:
    return [ex.get("name", "") for ex in result.get("extractions", [])]


def _question_texts(result: dict[str, Any]) -> str:
    return " ".join(q.get("text", "") for q in result.get("questions", [])).lower()


def _facts_of_kind(result: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [f for f in result.get("facts", []) if f.get("kind") == kind]


# date-seeking phrasing ("when you moved" inside another question is not one)
_DATE_ASK = (
    "what year",
    "which year",
    "in what year",
    "in which year",
    "date of birth",
    "born",
    "how old",
    "your age",
    "what date",
    "when did",
    "when was",
    "when do",
    "when were",
)


def _real_knowledge_with_dob() -> dict[str, list[dict[str, Any]]]:
    """Fictional narrator for the dob cases — the rule must not depend on
    which real people happen to be in the projection (no person is
    special-cased in code)."""
    return {
        "people": [{"id": "p-marek", "name": "Marek Kowalski", "aliases": ["Marek"], "dob": "1982-05-01"}],
        "places": [],
        "themes": [],
        "items": [],
    }


# ---------------------------------------------------------------------------
# Cases: the family's own stories and a fictional family
# ---------------------------------------------------------------------------

CASES: list[dict[str, Any]] = [
    {
        "name": "real-boats-links-the-artifacts",
        "anchor": {"kind": "place", "id": "pl-farndale-wharf", "name": "Iron Wharf, Farndale"},
        "who": "Alex",
        "account": "The boats were built on Iron Wharf — Sunlight first in 1980. The yard had a "
        + "slipway into the creek.",
        "assert": lambda r: (
            []
            if any(m in {"t-the-boats", "object-sunlight"} for m in _matches(r))
            else ["the boats/Sunlight were not linked — expected a theme or artifact extraction"]
        ),
    },
    {
        "name": "real-sheppey-extracts-about-entities",
        "anchor": {"kind": "place", "id": "pl-seagate", "name": "Seagate"},
        "who": "Alex",
        "account": "We used to sail around the Isle of Seagate and under the old ford, not the new one. "
        "Dad built the boats on Iron Wharf and Mum came along sometimes.",
        "assert": lambda r: (
            []
            if any(m in {"pl-seagate", "pl-farndale-wharf", "p-owen", "p-nora", "t-the-boats"} for m in _matches(r))
            else ["no about-entity from the story was matched"]
        ),
    },
    {
        "name": "fictional-family-no-overmatch",
        "knowledge": {
            "people": [
                {"id": "p-helena", "name": "Helena Kowalski", "aliases": ["Grandma", "Babcia"]},
                {"id": "p-jan", "name": "Jan Kowalski", "aliases": ["Janek"]},
            ],
            "places": [{"id": "pl-gdansk", "name": "Gdańsk"}, {"id": "pl-dluga", "name": "Ulica Długa"}],
            "themes": [],
            "items": [],
        },
        "anchor": {"kind": "place", "id": "pl-gdansk", "name": "Gdańsk"},
        "who": "Marek",
        "account": "Grandma Helena ran a bakery on Ulica Długa in Gdańsk. We used to visit after school and she "
        "always gave us fresh poppy-seed cake. Janek helped behind the counter.",
        "assert": lambda r: (
            []
            if any(p in n for n in _extraction_names(r) for p in ("Helena", "Janek", "Jan"))
            and any(p in n for n in _extraction_names(r) for p in ("Gdańsk", "Długa", "Ulica"))
            else [f"expected the fictional people and places extracted, got {_extraction_names(r)}"]
        ),
    },
    {
        "name": "fictional-mention-is-not-a-link",
        "anchor": {"kind": "theme", "id": "t-the-boats", "name": "The boats"},
        "who": "Marek",
        "account": "Aunt Nora from next door brought her famous plum cake to our wedding. It rained, but "
        "nobody minded, and Dad played the accordion all evening.",
        "assert": lambda r: (
            [] if "p-nora" not in _matches(r) else ['"Nora" in a fictional story matched p-nora — about ≠ mention']
        ),
    },
    {
        "name": "kinship-term-not-an-archive-alias",
        "knowledge": {
            "people": [
                {"id": "p-marek", "name": "Marek Kowalski", "aliases": ["Marek"]},
                {"id": "p-otto", "name": "Otto Nowak", "aliases": ["Dad"]},
            ],
            "places": [],
            "themes": [],
            "items": [],
        },
        "anchor": {"kind": "theme", "id": "t-kowalski-house", "name": "The house"},
        "who": "Marek",
        "account": "Dad came with me to see the house we wanted to buy. He said nothing, which is his way.",
        "assert": lambda r: (
            []
            if "p-otto" not in _matches(r)
            else [
                "'Dad' defaulted to p-otto — a kinship term is the writer's own "
                "relative, never an archive-wide alias (2026-08-05)"
            ]
        ),
    },
    {
        "name": "age-with-known-dob-is-not-asked",
        "knowledge": _real_knowledge_with_dob(),
        "anchor": {"kind": "item", "id": "letter-1990-03-01", "name": "A letter"},
        "who": "Marek",
        "account": "I was eight when we moved to the new house.",
        "assert": lambda r: (
            []
            if not any(w in _question_texts(r) for w in _DATE_ASK)
            else [f"asked for a date despite a known dob + given age: {_question_texts(r)}"]
        ),
    },
    {
        "name": "age-without-dob-asks-politely",
        "knowledge": {
            "people": [{"id": "p-marek", "name": "Marek Kowalski", "aliases": ["Marek"]}],
            "places": [],
            "themes": [],
            "items": [],
        },
        "anchor": {"kind": "item", "id": "letter-1990-03-01", "name": "A letter"},
        "who": "Marek",
        "account": "I was eight when we moved to the new house.",
        "assert": lambda r: (
            []
            if any(w in _question_texts(r) for w in _DATE_ASK)
            else ["no date question asked despite an unknown dob and only an age given"]
        ),
    },
    {
        "name": "dob-stated-in-account-is-asserted",
        "knowledge": {
            "people": [{"id": "p-marek", "name": "Marek Kowalski", "aliases": ["Marek"]}],
            "places": [],
            "themes": [],
            "items": [],
        },
        "anchor": {"kind": "item", "id": "letter-1990-03-01", "name": "A letter"},
        "who": "Marek",
        "account": "I was eight when we moved. My DOB is 15/09/1981.",
        "assert": lambda r: (
            []
            if _facts_of_kind(r, "dob") and not any(w in _question_texts(r) for w in _DATE_ASK)
            else ["expected an asserted dob fact and no date question when dob + age are computable"]
        ),
    },
    {
        "name": "new-narrator-connection-asked",
        "knowledge": {
            "people": [{"id": "p-helena", "name": "Helena Kowalski", "aliases": ["Grandma", "Babcia"]}],
            "places": [],
            "themes": [],
            "items": [],
        },
        "anchor": {"kind": "theme", "id": "t-kowalski-wedding", "name": "The wedding"},
        "who": "Zofia Kowalski",
        "account": "The wedding was lovely, the cake was poppy seed.",
        "assert": lambda r: (
            []
            if any(w in _question_texts(r) for w in ("connect", "related", "relationship", "family"))
            else ["no question asks how the new narrator is connected to the family"]
        ),
    },
    {
        "name": "new-artifact-asked-about",
        "knowledge": {
            "people": [{"id": "p-marek", "name": "Marek Kowalski", "aliases": ["Marek"]}],
            "places": [],
            "themes": [],
            "items": [],
        },
        "anchor": {"kind": "theme", "id": "t-kowalski-boats", "name": "The boats"},
        "who": "Marek",
        "account": "We sailed on the Kasia, a little yacht Dad rebuilt in the garden.",
        "assert": lambda r: (
            []
            if "kasia" in _question_texts(r)
            else ["no 'tell me more' question about the newly named artifact (Kasia)"]
        ),
    },
]


def run_case(
    client: AIClient,
    case: dict[str, Any],
    default_knowledge: dict[str, list[dict[str, Any]]],
) -> tuple[bool, list[str]]:
    knowledge = case.get("knowledge", default_knowledge)
    result = assess(
        client,
        anchor=case["anchor"],
        who=case["who"],
        account=case["account"],
        knowledge=Knowledge(
            people=knowledge["people"],
            places=knowledge["places"],
            themes=knowledge["themes"],
            items=knowledge["items"],
        ),
    )
    errors = contract_errors(result) + case["assert"](result)
    if errors:
        return False, errors
    return True, []


def main() -> int:
    default_knowledge = load_projection()
    try:
        client = AIClient()
    except AIClientError as e:
        # fail fast, never a silent skip: an eval that cannot run must say so
        # loudly (2026-08-05) — a zero exit would green a CI that never ran it
        print(f"FAIL — no API key: {e}")
        return 1
    # one shot per case: the production call self-corrects internally
    # (assess -> review -> redo), so the eval must run it exactly once
    failures = 0
    for case in CASES:
        ok, errors = run_case(client, case, default_knowledge)
        if ok:
            print(f"PASS {case['name']}")
        else:
            failures += 1
            print(f"FAIL {case['name']}")
            for error in errors:
                print(f"  - {error}")
    print(f"{len(CASES) - failures}/{len(CASES)} cases passing")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
