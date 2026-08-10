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

from tools.ai_client import AIClient
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


class ReviewFlow:
    """One named review scenario — the reviewer's statement against the
    claim. The session fixture in tests/test_evals.py runs each flow ONCE
    and caches the output; the condition tests are independent, unaware
    they share the run, and each verifies the output against one condition
    declared here (2026-08-10, user: "name all the flows… have a fixture
    that caches the results of running the flow. The individual tests can
    remain independent and not be aware that they share flow outputs"). A
    condition a flow does not pin keeps its default."""

    name = ""
    text = ""
    relevant = "true"
    contradiction = "false"
    detail_mentions: str | None = None
    confidence: tuple[str, ...] = ()  # the accepted confidence values
    findings_mention: str | None = None
    findings_quote: str | None = None
    no_findings = False
    no_term = False
    question_concludes = False
    has_question = False


class OnTopicFlow(ReviewFlow):
    """A positive recollection with no documents: relevant, and no
    fabricated attestation (R2 — a robot's note is never evidence). One
    run, two conditions — the merge of the old on-topic + R2 cases
    (2026-08-10, user: never two evals covering the same thing)."""

    name = "on-topic is relevant, and no fabricated attestation (R2)"
    text = "Grandma used to say that Quentin was Pearl's brother."
    no_findings = True


class OffTopicFlow(ReviewFlow):
    name = "off-topic answer is flagged"
    text = "We visited that house every summer — I remember the garden well."
    relevant = "false"


class WrongPersonContradictionFlow(ReviewFlow):
    name = "the user is wrong — a contradiction with the attested war record is surfaced"
    text = "It was Nora who died in the war, I remember that clearly."
    contradiction = "true"
    detail_mentions = "Walter"


class NeverDerivesFlow(ReviewFlow):
    name = "the model never derives a relationship from the answer"
    text = "He was her brother, I think."
    confidence = ("think_so",)
    no_term = True


class PlaceLeadFlow(ReviewFlow):
    name = "the model follows a place lead and reports what the records show"
    text = (
        "I don't remember the relationship. But Mum did know a Walter — we visited him once "
        "in Seascale when I was young, and he has died since."
    )
    findings_mention = "Seascale"
    has_question = True


class ImportGuessNotContradictionFlow(ReviewFlow):
    name = "the model never treats an unverified import guess as a contradiction"
    text = "I'm fairly sure the import has it right — he was Pearl's brother, that fits."
    confidence = ("think_so", "definitely")


class DigsToDeathFlow(ReviewFlow):
    name = "the model digs into the statement and surfaces the attested death"
    text = (
        "Not sure about the brother link. But I remember Mum saying one of Nora's siblings "
        "died in the war — I think it was Walter."
    )
    findings_mention = "Walter"
    findings_quote = "died on 15 September 1916"
    has_question = True


class ExhaustedUncertaintyFlow(ReviewFlow):
    name = "exhausted uncertainty concludes instead of re-asking"
    text = "I've no idea whether Quentin was Pearl's brother — I never met him."
    confidence = ("dont_know",)
    question_concludes = True


FLOWS: list[ReviewFlow] = [
    OnTopicFlow(),
    OffTopicFlow(),
    WrongPersonContradictionFlow(),
    NeverDerivesFlow(),
    PlaceLeadFlow(),
    ImportGuessNotContradictionFlow(),
    DigsToDeathFlow(),
    ExhaustedUncertaintyFlow(),
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


def run_flow(client: AIClient, flow: ReviewFlow) -> dict[str, Any]:
    """Run the flow ONCE — the reviewer's statement through investigate.
    The condition tests evaluate the single output; the run is never
    repeated for a condition (2026-08-10, user: one run, many
    conditions)."""
    return investigate(client, text=flow.text, person=PERSON, who="Alex", facts=_facts())


def condition_relevant(flow: ReviewFlow, result: dict[str, Any]) -> str | None:
    if result.get("relevant") != flow.relevant:
        return f"relevant: expected {flow.relevant}, got {result.get('relevant')}"
    return None


def condition_contradiction(flow: ReviewFlow, result: dict[str, Any]) -> str | None:
    contradiction = result.get("contradiction", {})
    if contradiction.get("found") != flow.contradiction:
        return f"contradiction: expected {flow.contradiction}, got {contradiction.get('found')}"
    if flow.detail_mentions and flow.detail_mentions not in str(contradiction.get("detail", "")):
        return f"contradiction detail should name {flow.detail_mentions}: {contradiction}"
    return None


def condition_confidence(flow: ReviewFlow, result: dict[str, Any]) -> str | None:
    if flow.confidence and result.get("confidence") not in flow.confidence:
        return f"confidence: expected one of {flow.confidence}, got {result.get('confidence')}"
    return None


def condition_findings(flow: ReviewFlow, result: dict[str, Any]) -> str | None:
    findings = result.get("findings", [])
    texts = [f.get("text", "") if isinstance(f, dict) else str(f) for f in findings]
    if flow.no_findings and findings:
        return (
            "no evidence surfaced, but a finding was offered anyway — a robot's note is "
            f"never attestation (R2): {findings}"
        )
    if flow.findings_mention and not any(flow.findings_mention in t for t in texts):
        return f"findings should mention {flow.findings_mention}: {findings}"
    if flow.findings_quote and not any(flow.findings_quote in t for t in texts):
        return (
            f"findings should QUOTE the relevant sentence verbatim ({flow.findings_quote!r} — "
            f"the document's own words, not a paraphrase): {findings}"
        )
    return None


def condition_no_term(flow: ReviewFlow, result: dict[str, Any]) -> str | None:
    if flow.no_term and "term" in result:
        return f"the check returned a derived term — it must never: {result['term']}"
    return None


def condition_question(flow: ReviewFlow, result: dict[str, Any]) -> str | None:
    question = str(result.get("question", ""))
    if flow.has_question and not question:
        return f"the genealogist should ask a follow-up question: {question!r}"
    if flow.question_concludes and not any(word in question for word in ("leave", "guess", "record", "unless")):
        return (
            "the exhausted 'I don't know' must offer the conclusion (keep the guess / "
            f"record what they remember), not ask again: {question!r}"
        )
    return None


def condition_persona(flow: ReviewFlow, result: dict[str, Any]) -> str | None:
    errors = persona_errors(result)
    return "\n".join(errors) if errors else None


def condition_feedback(flow: ReviewFlow, result: dict[str, Any]) -> str | None:
    errors = _feedback_errors(result)
    return "\n".join(errors) if errors else None


# every condition, in the order the condition tests run them
REVIEW_CONDITIONS: list[tuple[str, Any]] = [
    ("relevance", condition_relevant),
    ("contradiction", condition_contradiction),
    ("confidence", condition_confidence),
    ("findings", condition_findings),
    ("no derived term", condition_no_term),
    ("the question", condition_question),
    ("the persona guard", condition_persona),
    ("the feedback property", condition_feedback),
]


class MultiTurnArcFlow:
    """The Seascale stall (R3/R4, 2026-08-10): two turns — the assistant
    asks, the reviewer answers with a place lead. The response must name
    the lead; the assistant's own question must never be repeated. The
    single-message flows cannot catch this — the failure was a
    turn-transition, only reachable with history."""

    name = "multi-turn arc (the Seascale stall)"
    turn1 = "I think Mum said he was Pearl's brother."
    turn2 = (
        "I'm not sure who it was — but we visited an older relative in Seascale once when "
        "I was young, and he's died since."
    )
    lead = "Seascale"


def run_arc(client: AIClient) -> dict[str, Any]:
    """Run the two-turn arc ONCE; the condition tests verify the output."""
    t1 = investigate(client, text=MultiTurnArcFlow.turn1, person=PERSON, who="Alex", facts=_facts())
    history = (
        Message(role="user", text=MultiTurnArcFlow.turn1, when=""),
        Message(
            role="assistant",
            text=assistant_message(t1, PERSON),
            when="",
            thinking=_json.dumps(t1.get("trace"), ensure_ascii=False),
        ),
    )
    t2 = investigate(
        client,
        text=MultiTurnArcFlow.turn2,
        person=PERSON,
        who="Alex",
        facts=_facts(),
        history=history,
    )
    return {"t1": t1, "t2": t2, "q1": str(t1.get("question", ""))}


def condition_arc_lead(result: dict[str, Any]) -> str | None:
    """The lead is FOLLOWED when the assistant's response names it — in the
    findings (the tool path) or in the question (the known-facts path):
    "Is the Seascale visit you remember the same one recorded in the
    archive…?" is the genealogist's move, either way (R3: the tools — and
    the archive's facts — inform the conversation). The live stall repeated
    the question and never acknowledged the visit."""
    t2 = result["t2"]
    response_text = " ".join(
        [(f.get("text", "") if isinstance(f, dict) else str(f)) for f in t2.get("findings", [])]
        + [str(t2.get("question", ""))]
    )
    if MultiTurnArcFlow.lead not in response_text:
        return (
            "the reviewer answered with a PLACE lead (Seascale) and the model's response "
            f"never names it — the lead went unanswered (R3): {response_text or '(empty)'}"
        )
    return None


def condition_arc_no_repeat(result: dict[str, Any]) -> str | None:
    q1 = str(result.get("q1", ""))
    q2 = str(result["t2"].get("question", ""))
    if q1 and q2 and q2 == q1:
        return f"the model repeated its own question verbatim — the walk stalled (R4): {q2!r}"
    return None


class CachingFlow:
    """The prefix contract (2026-08-09, user: "have ALL our evals cross
    check this at the end"): a short conversation runs as one accumulating
    history, and every turn's prompt must start with the previous turn's
    exact text — the conversation renders verbatim and grows at the end."""

    name = "caching cross-check"
    turns = (
        "I think Mum said she was a cousin, via one of Pearl's brothers.",
        "I don't remember more than that.",
        "That's all I know.",
    )


def run_caching(client: AIClient) -> dict[str, Any]:
    """Run the three-turn caching conversation ONCE; the condition test
    verifies the prompts' prefix property."""
    history: tuple[Message, ...] = ()
    prompts: list[str] = []
    for text in CachingFlow.turns:
        result = investigate(client, text=text, person=PERSON, who="Alex", facts=_facts(), history=history)
        prompts.append(str(result.get("prompt", "")))
        history = history + (
            Message(role="user", text=text, when=""),
            Message(
                role="assistant",
                text=assistant_message(result, PERSON),
                when="",
                thinking=_json.dumps(result.get("trace"), ensure_ascii=False),
            ),
        )
    return {"prompts": prompts}


def condition_caching_prefix(result: dict[str, Any]) -> str | None:
    prompts = result.get("prompts", [])
    for prev, current in zip(prompts, prompts[1:], strict=False):
        if not current.startswith(prev):
            return (
                "the previous prompt is not this prompt's prefix — the caching contract is "
                "broken (the conversation must render verbatim and grow at the end)"
            )
    return None
