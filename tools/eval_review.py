"""Eval for the import-review relevance check — run against the real model.

Not part of `make test` (tests never hit the network): this needs a network
and a configured key (LOFT_AI_KEY / OPENCODE_API_KEY / opencode auth.json).
Run with `loft eval-review` (tools/cli.py).

The cases cover the review flow's model behaviours (2026-08-09, user):
- the relevance verdict (an answer about the exact claim is on-topic);
- the off-topic steer (an answer about something else is never recorded);
- the contradiction gate — especially the case where the USER IS WRONG:
  the reviewer names the wrong person for an attested event (the
  wrong-person-for-the-attested-event shape — we don't confirm until contradictions with the
  existing data are resolved);
- the never-derive rule (the model never turns words into a relationship —
  the walk's "your ex-husband" failure).

The cast is fictional (the Whitlocks) so the eval cannot be tuned to one
household's data, and the PII guard never sees a real name.
"""

from __future__ import annotations

from typing import Any

from tools.ai_client import AIClient, AIClientError
from tools.records import Person, ReviewContext
from tools.review import investigate

PEOPLE: list[dict[str, Any]] = [
    {"id": "p-quentin", "name": "Quentin Whitlock", "relation": "brother of Pearl Whitlock"},
    {"id": "p-pearl", "name": "Pearl Whitlock"},
    {"id": "p-nora", "name": "Nora Whitlock"},
    {"id": "p-walter", "name": "Walter Whitlock", "dod": {"date": "1916-09-15", "precision": "exact"}},
]
PLACES: list[dict[str, Any]] = []
THEMES: list[dict[str, Any]] = []
RELATIONSHIPS: list[dict[str, Any]] = [
    {"a": "p-walter", "b": "p-nora", "kind": "sibling", "label_a": "sibling", "label_b": "sibling"},
]

ITEMS: list[dict[str, Any]] = [
    {
        "id": "item-war-record",
        "title": "The war record",
        "type": "document",
        "story": "Walter Whitlock died on 15 September 1916, aged 21 — the Commonwealth war record.",
    },
    {
        "id": "item-seascale",
        "title": "The Seascale visit",
        "type": "story",
        "story": "We visited the Cecil in Seascale once when the children were young; he has died since.",
    },
]

PERSON: Person = Person.from_dict(
    {"id": "p-quentin", "name": "Quentin Whitlock", "relation": "brother of Pearl Whitlock"}
)

CASES: list[dict[str, Any]] = [
    {
        "name": "on-topic answer is relevant and clear",
        "text": "Grandma used to say this was the case.",
        "expects": {"relevant": "true", "contradiction": "false"},
    },
    {
        "name": "off-topic answer is flagged",
        "text": "We visited that house every summer — I remember the garden well.",
        "expects": {"relevant": "false", "contradiction": "false"},
    },
    {
        "name": "the user is wrong — a contradiction with the attested war record is surfaced",
        "text": "It was Nora who died in the war, I remember that clearly.",
        "expects": {"relevant": "true", "contradiction": "true", "detail_mentions": "Walter"},
    },
    {
        "name": "the model never derives a relationship from the answer",
        "text": "He was her brother, I think.",
        "expects": {"relevant": "true", "contradiction": "false", "no_term": True, "confidence": "think_so"},
    },
    {
        "name": "the model follows a place lead and reports what the records show",
        "text": "I don't remember the relationship. But Mum did know a Cecil — we visited him once "
        "in Seascale when I was young, and he has died since.",
        "expects": {"relevant": "true", "contradiction": "false", "findings_mention": "Seascale", "has_question": True},
    },
    {
        "name": "the model never treats an unverified import guess as a contradiction",
        "text": "I'm fairly sure the import has it right — he was Pearl's brother, that fits.",
        "expects": {"relevant": "true", "contradiction": "false", "confidence": "think_so"},
    },
    {
        "name": "the model digs into the statement and surfaces the attested death",
        "text": "Not sure about the brother link. But I remember Mum saying one of Nora's siblings "
        "died in the war — I think it was Walter.",
        "expects": {"relevant": "true", "contradiction": "false", "findings_mention": "Walter", "has_question": True},
    },
]


def _facts() -> ReviewContext:
    return ReviewContext(
        people=tuple(Person.from_dict(p) for p in PEOPLE),
        items=tuple(ITEMS),
        relationships=tuple(RELATIONSHIPS),
    )


# The assistant's words never echo the system's — the hired genealogist's
# voice (PRD: "the assistant reads as a hired genealogist, not a computer",
# 2026-08-09; user: "make sure the requirement is in all relevant evals").
# The family never meets the process vocabulary: no third-person "the user",
# no "the import", no statuses or internal states, no "link" or "awaiting".
PERSONA_JARGON = (
    "the user's recollection",
    "the import",
    "import's record",
    "import proposes",
    "the archive has a record for",
    "awaiting",
    "link",
    "status",
    "estimated",
    "proposed",
)


def persona_errors(result: dict[str, Any]) -> list[str]:
    """The genealogist's voice guard: the assistant's words (the question,
    the note, the findings) never contain the process vocabulary."""
    errors: list[str] = []
    fields: list[tuple[str, str]] = [("question", result.get("question", ""))]
    for i, f in enumerate(result.get("findings", [])):
        text = f.get("text", "") if isinstance(f, dict) else str(f)
        fields.append((f"findings[{i}]", text))
    for field, text in fields:
        for word in PERSONA_JARGON:
            if word in text:
                errors.append(f"{field} echoes the system ('{word}'): {text[:80]}")
    return errors


def run_case(client: AIClient, case: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    try:
        result = investigate(client, text=case["text"], person=PERSON, who="Alex", facts=_facts())
    except Exception as e:  # noqa: BLE001 — the eval reports every failure mode
        return False, [f"investigate raised: {e}"]
    wants = case["expects"]
    if result.get("relevant") != wants["relevant"]:
        errors.append(f"relevant: expected {wants['relevant']}, got {result.get('relevant')}")
    if result.get("contradiction", {}).get("found") != wants["contradiction"]:
        errors.append(f"contradiction: expected {wants['contradiction']}, got {result.get('contradiction')}")
    detail = (result.get("contradiction") or {}).get("detail", "")
    if wants.get("detail_mentions") and wants["detail_mentions"] not in detail:
        errors.append(f"contradiction detail should name {wants['detail_mentions']}: {result.get('contradiction')}")
    if wants.get("has_question") and not result.get("question"):
        errors.append(f"the genealogist should ask a follow-up question: {result.get('question')}")
    if wants.get("findings_mention") and not any(
        wants["findings_mention"] in (f.get("text", "") if isinstance(f, dict) else str(f))
        for f in result.get("findings", [])
    ):
        errors.append(f"findings should mention {wants['findings_mention']}: {result.get('findings')}")
    if wants.get("confidence") and result.get("confidence") != wants["confidence"]:
        errors.append(f"confidence: expected {wants['confidence']}, got {result.get('confidence')}")
    if wants.get("no_term") and "term" in result:
        errors.append(f"the check returned a derived term — it must never: {result['term']}")
    errors.extend(persona_errors(result))
    return (not errors), errors


def main() -> int:
    try:
        client = AIClient()
    except AIClientError as e:
        # fail fast, never a silent skip: an eval that cannot run must say so
        # loudly (2026-08-05) — a zero exit would green a CI that never ran it
        print(f"FAIL — no API key: {e}")
        return 1
    failures = 0
    for case in CASES:
        ok, errors = run_case(client, case)
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
    raise SystemExit(main())
