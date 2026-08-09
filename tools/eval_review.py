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

import json as _json
from typing import Any

from tools.ai_client import AIClient, AIClientError
from tools.records import Message, Person, ReviewContext
from tools.review import assistant_message, investigate

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
        "story": "We visited Walter in Seascale once when the children were young; he has died since.",
    },
]

PERSON: Person = Person.from_dict(
    {"id": "p-quentin", "name": "Quentin Whitlock", "relation": "brother of Pearl Whitlock"}
)

CASES: list[dict[str, Any]] = [
    {
        "name": "on-topic answer is relevant and clear",
        "text": "Grandma used to say that Quentin was Pearl's brother.",
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
        "text": "I don't remember the relationship. But Mum did know a Walter — we visited him once "
        "in Seascale when I was young, and he has died since.",
        "expects": {"relevant": "true", "contradiction": "false", "findings_mention": "Seascale", "has_question": True},
    },
    {
        "name": "the model never treats an unverified import guess as a contradiction",
        "text": "I'm fairly sure the import has it right — he was Pearl's brother, that fits.",
        "expects": {
            "relevant": "true",
            "contradiction": "false",
            "confidence": ("think_so", "definitely"),
        },
    },
    {
        "name": "the model digs into the statement and surfaces the attested death",
        "text": "Not sure about the brother link. But I remember Mum saying one of Nora's siblings "
        "died in the war — I think it was Walter.",
        "expects": {
            "relevant": "true",
            "contradiction": "false",
            "findings_mention": "Walter",
            "findings_quote": "died on 15 September 1916",
            "has_question": True,
        },
    },
    {
        "name": "exhausted uncertainty concludes instead of re-asking",
        "text": "I've no idea whether Quentin was Pearl's brother — I never met him.",
        "expects": {
            "relevant": "true",
            "contradiction": "false",
            "confidence": "dont_know",
            "question_concludes": True,
        },
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
    # the third-person and the dead-ends the transcript showed (2026-08-09):
    # the assistant never speaks about the family as "the reviewer", and
    # never reports a bare absence
    "the reviewer",
    "no record connects",
    "no record of",
    "cannot confirm",
    "does not remember",
)


def persona_errors(result: dict[str, Any]) -> list[str]:
    """The genealogist's voice guard: the assistant's words (the question,
    the findings — and the note, which flows into the steer ONLY when the
    answer is off-topic) never contain the process vocabulary, the
    third-person, or a bare absence. For a relevant answer the note is
    internal reasoning and never surfaces; for an off-topic one it becomes
    the steer's topic, so it must be clean there (2026-08-09, user: the
    note-as-analysis read as "That's about the reviewer has no idea…")."""
    errors: list[str] = []
    fields: list[tuple[str, str]] = [("question", result.get("question", ""))]
    if result.get("relevant") != "true":
        fields.append(("note", result.get("note", "")))
    for i, f in enumerate(result.get("findings", [])):
        text = f.get("text", "") if isinstance(f, dict) else str(f)
        fields.append((f"findings[{i}]", text))
    for field, text in fields:
        for word in PERSONA_JARGON:
            if word in text:
                errors.append(f"{field} echoes the system ('{word}'): {text[:80]}")
    return errors


def _feedback_errors(result: dict[str, Any]) -> list[str]:
    """The intra-turn completeness property (2026-08-09, user: "how can it
    be that you wrote comprehensive evals to make sure our transcript went
    back verbatim, and now you've found that things were missing"): the
    transcript-going-back principle has a second surface — INSIDE an
    investigation, every answer the model produces (a partial response, a
    verdict) must be fed back into the prompt verbatim, so a re-answer
    happens in the context of the model's own reasoning. Tool calls are
    the exception: their deterministic results are the fed-back content,
    and they are logged in the trace."""
    errors: list[str] = []
    final = result.get("final_prompt", "")
    steps = result.get("trace", [])
    # the LAST step is the final verdict — the end of the conversation,
    # fed forward to the reviewer, not back into a prompt
    for i, step in enumerate(steps[:-1]):
        raw = str(step.get("model", ""))
        if raw and "tool" not in step and raw not in final:
            errors.append(f"trace step {i}'s answer was not fed back into the prompt: {raw[:80]}")
    return errors


def _run_once(client: AIClient, case: dict[str, Any]) -> list[str]:
    """One independent run of the case — the classification checks from
    the case's expectations plus the two absolute invariants (the persona
    guard, the intra-turn feedback)."""
    errors: list[str] = []
    try:
        result = investigate(client, text=case["text"], person=PERSON, who="Alex", facts=_facts())
    except Exception as e:  # noqa: BLE001 — the eval reports every failure mode
        return [f"investigate raised: {e}"]
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
    if wants.get("findings_quote") and not any(
        wants["findings_quote"] in (f.get("text", "") if isinstance(f, dict) else str(f))
        for f in result.get("findings", [])
    ):
        errors.append(
            f"findings should QUOTE the relevant sentence verbatim ({wants['findings_quote']!r} "
            f"— the document's own words, not a paraphrase): {result.get('findings')}"
        )
    want_conf = wants.get("confidence")
    if want_conf and result.get("confidence") not in (want_conf if isinstance(want_conf, tuple) else (want_conf,)):
        errors.append(f"confidence: expected {want_conf}, got {result.get('confidence')}")
    if wants.get("question_concludes") and not any(
        word in result.get("question", "")
        for word in ("leave", "leave her", "leave him", "guess", "estimate", "record", "unless")
    ):
        errors.append(
            "the exhausted 'I don't know' must offer the conclusion (keep the guess / record "
            f"an estimate), not ask again: {result.get('question')}"
        )
    if wants.get("no_term") and "term" in result:
        errors.append(f"the check returned a derived term — it must never: {result['term']}")
    errors.extend(persona_errors(result))
    errors.extend(_feedback_errors(result))
    return errors


def run_case(client: AIClient, case: dict[str, Any]) -> tuple[bool, int, list[str]]:
    """The case runs THREE times (2026-08-09, user: "how can it be that
    you wrote comprehensive evals… and now you've found that things were
    missing"): the model's judgment is stochastic even at temperature 0 —
    a single run's classification is an observation, not a pin. The two
    invariants (the persona guard, the feedback property) are ABSOLUTE —
    any run violating one fails the case, because they are write-seam
    contracts, not judgment. The classification checks pass on a majority
    of runs. Returns (ok, passes, errors)."""
    runs = [_run_once(client, case) for _ in range(3)]
    invariant = [
        e
        for run in runs
        for e in run
        if e.startswith(("question echoes", "note echoes", "findings[", "trace step", "investigate raised"))
    ]
    if invariant:
        return False, 0, sorted(set(invariant))
    passes = sum(1 for run in runs if not run)
    if passes >= 2:
        return True, passes, []
    seen: set[str] = set()
    flat = [e for run in runs for e in run if not (e in seen or seen.add(e))]
    return False, passes, flat[:6]


def check_caching_prefix(client: AIClient) -> list[str]:
    """The caching cross-check (2026-08-09, user: "have ALL our evals cross
    check this at the end and fail if there's no match"): a short dedicated
    conversation runs as one accumulating history, and every turn's prompt
    must start with the previous turn's exact text — the conversation
    renders verbatim and grows at the end, so the model's prompt-cache can
    reuse the prefix. The eval's behavioural cases stay independent — they
    are separate scenarios, not one conversation."""
    errors: list[str] = []
    history: tuple[Message, ...] = ()
    prev_prompt: str | None = None
    for text in (
        "I think Mum said she was a cousin, via one of Pearl's brothers.",
        "I don't remember more than that.",
        "That's all I know.",
    ):
        result = investigate(client, text=text, person=PERSON, who="Alex", facts=_facts(), history=history)
        prompt = result.get("prompt", "")
        if prev_prompt is not None and not prompt.startswith(prev_prompt):
            errors.append(
                "the previous prompt is not this prompt's prefix — the caching contract is "
                "broken (the conversation must render verbatim and grow at the end)"
            )
        prev_prompt = prompt
        history = history + (
            Message(role="user", text=text, when=""),
            Message(
                role="assistant",
                text=assistant_message(result, PERSON),
                when="",
                thinking=_json.dumps(result.get("trace"), ensure_ascii=False),
            ),
        )
    return errors


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
        ok, passes, errors = run_case(client, case)
        if ok:
            print(f"PASS {case['name']} ({passes}/3)")
        else:
            failures += 1
            print(f"FAIL {case['name']} ({passes}/3)")
            for error in errors:
                print(f"  - {error}")
    print(f"{len(CASES) - failures}/{len(CASES)} cases passing")

    # the caching cross-check — the whole suite verifies the prefix
    # contract at the end (2026-08-09, user)
    cache_errors = check_caching_prefix(client)
    if cache_errors:
        failures += 1
        print("FAIL caching cross-check")
        for error in cache_errors:
            print(f"  - {error}")
    else:
        print("PASS caching cross-check (every prompt is the next one's prefix)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
