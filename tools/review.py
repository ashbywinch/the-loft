"""The import review (user): the review resolves the
DISPOSITION of each proposed link in the chat — attested, estimated (with
the reviewer's own words recorded verbatim as the basis), pending, or
deleted. The model never invents relationships: ``check_relevance`` only
decides whether a free-text answer addresses the exact claim under review
(the walk's "your ex-husband" failure came from the old relation
inference — a random ancestor resolved to the narrator's own spouse). The
decision vocabulary is NOT the status vocabulary: "confirm" is a status,
never an action.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any, Protocol

from pipeline.model.ai_client import AIClientError, json_object
from tools.attested_args import AttestedArgs
from tools.decision_basis import DecisionBasis
from tools.item_hit import ItemHit
from tools.memory import ElicitationError
from tools.person_args import PersonArgs
from tools.person_hit import PersonHit
from tools.person_summary import PersonSummary
from tools.records import Message, Person, ReviewContext
from tools.relationships_args import RelationshipsArgs
from tools.review_verdict import ReviewVerdict
from tools.search_items_args import SearchItemsArgs
from tools.search_people_args import SearchPeopleArgs
from tools.tool_error import ToolError
from tools.tool_note import ToolNote
from tools.trace_step import TraceStep

MAX_RESOLVE_ATTEMPTS = 2

logger = logging.getLogger(__name__)


def _relevant_sentences(text: str, needles: tuple[str, ...], limit: int = 3) -> list[str]:
    """The sentences of a document that mention any needle — the RELEVANT
    part to quote, never the opening (user: the tools returned the
    document's first 200-300 characters, so the model could only quote
    the opening). Returns up to ``limit`` matching sentences, capped in
    length, or the first content sentence when nothing matches (a
    fallback, never silence)."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    # case-insensitive: search_items lowercases its query, so "Seascale"
    # must still match "seascale" — a case-sensitive match returns the
    # document's opening sentences instead of the relevant ones
    lower = [s.lower() for s in sentences]
    hits = [s for s, lowered in zip(sentences, lower, strict=True) if any(n.lower() in lowered for n in needles)]
    pool = hits or sentences
    return [s[:300] for s in pool[:limit]]


class _Chat(Protocol):
    # instance method using self

    def chat(self, system: str, user: str, *, thinking: bool = False) -> str: ...


def _known_facts(facts: ReviewContext) -> str:
    """The archive's attested facts for the contradiction check — the
    people (deaths + relations) and the recorded items' stories, read
    through the typed context (the Knowledge's converted models drop the
    dod and the stories, so the investigation reads the raw projection)."""
    lines = ["People:"]
    for p in facts.people:
        bits = [f"  {p.id} — {p.name}"]
        # proposed/estimated are guesses, never attested facts — the people
        # table handed to the review still holds the proposed person under
        # review, so their import relation must be marked, or the
        # contradiction check treats the guess as attested (the
        # never-an-unverified-import-guess rule)
        if p.status != "confirmed":
            bits.append(f"(status: {p.status})")
        if p.dob:
            bits.append(f"(born {p.dob.date})")
        if p.dod:
            bits.append(f"(died {p.dod.date})")
        if p.relation:
            bits.append(f"(relation: {p.relation})")
        lines.append(" ".join(bits))
    lines.append("Recorded items:")
    for it in facts.items:
        story = (it.get("story") or it.get("transcription") or "").strip()
        if story:
            # Rule L: a draft transcription is marked — the model must
            # know which texts are unverified so it never quotes one as
            # the document's own words
            draft = (
                " (DRAFT TRANSCRIPTION — machine-read, unverified)" if it.get("transcription_status") == "draft" else ""
            )
            lines.append(f"  {it.get('id')} — {it.get('title', '')}{draft}: {story[:200]}")
    return "\n".join(lines)


MAX_INVESTIGATE_STEPS = 6  # the digs plus room for a verdict correction
VERDICT_AND_CORRECTION_TURNS = 3  # the loop's turns beyond the digs: the verdict, a correction, and slack
MAX_TOOL_CALLS = 4  # the investigation's tool-call budget before the model must conclude

_TOOLS_DESC = """You can investigate the archive with these READ-ONLY tools:

- search_people({"query": "<name or relation text>"}): people whose name
  matches, with their ids.
- person({"id": "<person id>"}): one person's record — dates, relation,
  status.
- relationships({"id": "<person id>"}): the recorded family edges touching
  that person.
- attested({"id": "<person id>"}): the recorded items (letters, records,
  stories) that mention the person — their attested facts.
- search_items({"query": "<a place, a town, an event, a phrase>"}): the
  recorded items whose text mentions it — follow a place or an event the
  reviewer brings up (a visit, a town, a death).

To call a tool, return ONLY JSON: {"tool": "<name>", "args": {...}}.
The tool's result will be appended and you may call another. When you have
enough to answer, return the verdict JSON.

Deliberate in ONE short pass: at most four tool calls in one round, and
each of the four decisions (leads, search, relevance, contradiction)
made exactly once. After each tool call a "Facts already gathered"
ledger is appended — it is deduplicated and last-value-wins: consult it
and NEVER re-fetch a fact it already lists, and once it covers your
planned leads, stop deliberating about further calls and emit the
verdict. The ledger is only an INDEX of the tool results — it changes
nothing about what counts as a finding: relationship/person lines in it
are not evidence (the person-record rule), and a document the tools
surfaced is STILL a finding to report even when the ledger lists it.
Never re-analyse a decision
you have already made, never re-plan a search you have already planned,
and never restate the reviewer's statement back to yourself. If you
catch yourself repeating a step, stop and emit the verdict."""


def _facts_ledger(trace: Sequence[TraceStep], limit: int = 400) -> str:
    """The deduplicated facts ledger — one line per (tool, args), last
    value wins — placed at the END of the prompt so the model consults
    what it already gathered instead of re-deriving or re-querying it.
    The analysis-paralysis stall circles on exactly that: the model
    re-reads tool results buried in the growing transcript and debates
    further queries (arXiv:2502.08235's Analysis Paralysis; the
    deduplicated-ledger fix from the tool-loop practice literature).
    Each line truncates to ``limit`` characters; the full result stays
    in the transcript above."""
    lines: dict[tuple[str, str], str] = {}
    for step in trace:
        if not step.tool:
            continue
        args = json.dumps(step.args or {}, sort_keys=True)
        # default=repr: an unserializable tool result serializes as its
        # repr instead of raising — the ledger must never crash the
        # investigation on an exotic payload (lucidlint: no swallow to
        # flag, the fallback is declarative)
        result = json.dumps(step.result, ensure_ascii=True, default=repr)
        if len(result) > limit:
            result = result[:limit] + "…"
        lines[(step.tool, args)] = f"- {step.tool}({args}) -> {result}"
    return "\n".join(lines.values())


# The tool-call arguments the model may send, one record per tool — the
# harness parses the model's wire into the tool's own record and dispatches
# on the name.
ToolArgs = SearchPeopleArgs | PersonArgs | RelationshipsArgs | AttestedArgs | SearchItemsArgs

# The results the read-only tools answer with: the records the model reads,
# or the archive's own relationship edges verbatim (the people table already
# holds them as its wire records, so the harness passes them through).
ToolHit = PersonHit | PersonSummary | ItemHit
# One entry of a tool's LIST result: a hit record, or an archive edge's own
# wire record.
ToolEntry = ToolHit | dict[str, Any]
ToolResult = ToolError | ToolNote | ToolHit | list[ToolEntry]


class _ReviewTools:
    """The review's read-only tool harness — owns the ReviewContext (the
    facts) every tool reads, the (args, facts) data clump the tool functions
    used to thread. The model can look things up but never change them."""

    # the read-only tools the model may call — method names, dispatched by
    # lookup (a chain of five identical-shaped branches is duplication)
    _TOOLS = ("search_people", "person", "relationships", "attested", "search_items")

    def __init__(self, facts: ReviewContext) -> None:
        self._facts = facts

    def run(self, tool: str, args: ToolArgs | None) -> ToolResult:
        """One tool call — the tool's own method with its own argument
        record, or the error result for a tool this harness does not have
        (the model's mistake, never a crash)."""
        if args is None or tool not in self._TOOLS:
            return ToolError(f"unknown tool {tool}")
        return getattr(self, tool)(args)

    def search_people(self, args: SearchPeopleArgs) -> ToolResult:
        if not args.query:
            return ToolError("query required")
        hits: list[ToolEntry] = [
            PersonHit(id=p.id, name=p.name, relation=p.relation)
            for p in self._facts.people
            if args.query in p.name.lower() or args.query in (p.relation or "").lower()
        ]
        return hits[:10] or ToolNote("no matches")

    def person(self, args: PersonArgs) -> ToolResult:
        p = next((x for x in self._facts.people if x.id == args.id), None)
        return (
            PersonSummary(id=p.id, name=p.name, relation=p.relation, status=p.status)
            if p
            else ToolError(f"no person {args.id}")
        )

    def relationships(self, args: RelationshipsArgs) -> ToolResult:
        edges: list[ToolEntry] = [
            edge for edge in self._facts.relationships if edge.get("a") == args.id or edge.get("b") == args.id
        ]
        return edges or ToolNote("no recorded relationships")

    def attested(self, args: AttestedArgs) -> ToolResult:
        """The recorded items that mention the person — their attested facts.
        The sentences that MENTION the person are the part that attests the
        fact, quotable verbatim — with the person's name
        and first name as the needles. The item's structured involvement (its
        people ids) or the prose naming the person both count — real
        transcriptions mention names, never ids. Case-insensitive: OCR and
        captured text frequently differ in case, so an item whose only
        mention is lowercased must not be silently dropped at the door."""
        p = next((x for x in self._facts.people if x.id == args.id), None)
        needles = (p.name, p.name.split()[0]) if p else (args.id,)
        lowered = [n.lower() for n in needles]
        results: list[ToolEntry] = []
        for it in self._facts.items:
            text = it.get("story") or it.get("transcription") or ""
            involved = args.id in it.get("people", [])
            if involved or any(n in text.lower() for n in lowered):
                results.append(
                    ItemHit(
                        id=it["id"],
                        title=it["title"],
                        draft=it.get("transcription_status") == "draft",
                        quotes=tuple(_relevant_sentences(text, needles)),
                    )
                )
        return results or ToolNote("no recorded items mention this person")

    def search_items(self, args: SearchItemsArgs) -> ToolResult:
        """The recorded items whose text mentions the query — follow a place
        or an event the reviewer brings up (a visit, a town, a death)."""
        if not args.query:
            return ToolError("query required")
        hits: list[ToolEntry] = []
        for it in self._facts.items:
            text = it.get("story") or it.get("transcription") or ""
            if args.query in text.lower():
                hits.append(
                    ItemHit(
                        id=it["id"],
                        title=it["title"],
                        draft=it.get("transcription_status") == "draft",
                        quotes=tuple(_relevant_sentences(text, (args.query,))),
                    )
                )
        return hits[:5] or ToolNote(f"no recorded items mention {args.query!r}")


def _wire_result(result: ToolResult | ToolEntry) -> Any:
    """A tool result as the model's wire form — a record's own dict, a list
    of them, or the archive's relationship edges verbatim (the facts table
    already holds them as its wire records)."""
    if isinstance(result, list):
        return [_wire_result(item) for item in result]
    if isinstance(result, dict):
        return result
    return result.to_dict()


def _tool_args(tool: str, raw: Mapping[str, Any]) -> ToolArgs | None:
    """The model's tool-call arguments as the tool's own record — None for a
    tool this harness does not have (the model's mistake, answered with the
    error result)."""
    match tool:
        case "search_people":
            return SearchPeopleArgs.from_dict(raw)
        case "person":
            return PersonArgs.from_dict(raw)
        case "relationships":
            return RelationshipsArgs.from_dict(raw)
        case "attested":
            return AttestedArgs.from_dict(raw)
        case "search_items":
            return SearchItemsArgs.from_dict(raw)
    return None


def run_tool(tool: str, args: ToolArgs | None, facts: ReviewContext) -> ToolResult:
    """The read-only tool harness — the model can look things up but never
    change them: the model digs up the existing situation, never edits it.
    ``args`` is the tool's own argument record — None for a tool the harness
    does not have, answered with the error result. Public and documented so
    the tests exercise the real harness, never a private symbol."""
    return _ReviewTools(facts).run(tool, args)


def assistant_message(verdict: ReviewVerdict, person: Person) -> str:
    """The assistant's rendered words for one investigation response — what
    the family sees, verbatim. The server builds the words;
    the app shows them unmodified; the record stores them. The model's
    internal note never surfaces."""
    parts: list[str] = []
    if verdict.findings:
        parts.append("The documents show: " + " ".join(finding.text for finding in verdict.findings))
    if verdict.question:
        parts.append(verdict.question)
    return " ".join(parts)


def confirmation_message(name: str, decision: str, basis: DecisionBasis | None) -> str:
    """The assistant's rendered confirmation — the receipt the family sees,
    in the genealogist's voice, naming the consequence (the vocabulary is
    the family's, never the statuses': fact / guess / left for later /
    delete — user)."""
    if decision == "attested":
        return f"Done — {name} joins the tree as a fact."
    if decision == "estimated":
        text = (basis.text if basis else "") or "a guess"
        return f"Done — I've recorded {name} as a guess: '{text}'."
    if decision == "delete":
        return f"Done — {name} is not recorded after all."
    return f"{name} stays out of the tree for now — we can pick it up later."


def steer_message(person: Person, note: str) -> str:
    """The off-topic steer — the genealogist's words, never the model's
    internal note."""
    return (
        f"That's about {note or 'something else'} — let's come back to {person.name}: does that fit what you remember?"
    )


def render_history(messages: tuple[Message, ...]) -> str:
    """The conversation so far, verbatim — the family's words and the
    assistant's reasoning and speech, in order — so the model sees the
    whole arc (user: the model needs its own history to do its job)."""
    lines: list[str] = []
    # branching append: user vs assistant, and the assistant also emits a conditional
    # reasoning line — a comprehension would need sentinel tuples
    # lucidlint: ignore loop-pipeline branching append with a conditional second line
    for m in messages:
        if m.role == "user":
            lines.append(f"[family] {m.text}")
        else:
            if m.thinking:
                lines.append(f"[assistant reasoning] {m.thinking}")
            lines.append(f"[assistant] {m.text}")
    return "\n".join(lines)


# the reviewer identity, the facts context, the history — a parameter object would add ceremony at the DI boundary
# lucidlint: ignore long-param-list the investigation's inputs — the client seam, the answer, the person under review,
def investigate(
    client: _Chat,
    *,
    text: str,
    person: Person,
    who: str,
    facts: ReviewContext,
    history: tuple[Message, ...] = (),
) -> ReviewVerdict:
    """The tool-using review of a free-text answer (user): the
    model can call the archive's read-only lookups to dig into the
    reviewer's statement — follow the leads and surface what the archive
    already attests — then return the ReviewVerdict: the check's answers,
    the findings the tools surfaced, and the genealogist's question. *history* is the
    conversation so far (the messages, including the model's own previous
    reasoning), rendered verbatim into the prompt — the model always sees
    its own history, so a message that re-answers an earlier question is
    recognised as such. The findings are the digging's results — shown to
    the reviewer. The tools are read-only: the decisions stay in the app's
    flow. The never-derive rule holds — the model reports what it finds,
    it never invents a kinship. ``raw`` is the model's final raw output,
    stored verbatim as the turn's thinking."""
    text = str(text or "").strip()
    if not text:
        raise ElicitationError("no answer given")
    # The claim is the APP's question about the document the family uploaded:
    # the app has read it and is checking what it says. "The family is
    # checking" would read as the family asking, and a statement about the
    # document's own subject — a death in the war — would look like a
    # different question entirely.
    claim = f"whether {person.name} was related to the family"
    if person.relation:
        # family language, never the system's — the model echoes the claim's
        # own words, and the persona rule forbids 'the import'/'proposes'/
        # 'link' (the prompt must not model the jargon it forbids)
        claim += f" — the record under review says: {person.relation}"
    # the conversation renders uniformly and sits LAST in the prompt — the
    # static (the reviewer, the claim, the facts, the instructions) comes
    # before it, so the previous prompt's exact text is the current prompt's
    # prefix and the model's prompt-cache reuses the whole thing
    # (user: 'the exact same text goes back… cheaper if so,
    # because of caching'). The latest line is part of the same render, so
    # a message that re-answers an earlier question is seen in context.
    conversation = render_history(history + (Message(role="user", text=text, when=""),))
    user = "\n\n".join(
        [
            f"Reviewer: {who or 'unknown'}",
            # the conversation's frame: the family uploaded a document, the app
            # read it, and it is the app that is checking
            "The family have uploaded a document to the archive; the app has read "
            "it and is asking them to confirm what it says against what they know.",
            f"The claim under review: {claim}.",
            "Known family (the archive's attested facts):\n" + _known_facts(facts),
            "Decide in this order, once each, and write no alternatives. Decide a "
            "thing, write it, move on: never re-word a sentence you have decided, "
            "never list candidate questions ('Or ask: …' or 'But we need to say …'), "
            "and never re-read your own draft. The JSON is the answer, not a draft "
            "of one — produce it as soon as the last decision is made. "
            "1. FIND THE LEADS. A lead is anything the statement names "
            "concretely: a person, a place, a town, an event, a death, a "
            "marriage, or a relationship/kinship claim ('Pearl's brothers', "
            "'a cousin of Grandma', 'that house in Seascale'). A bare "
            "recollection that names nothing concrete ('Grandma used to say "
            "so', 'I vaguely remember') has no lead. "
            "2. SEARCH EVERY LEAD FIRST — before judging relevance or "
            "answering: search_items for places and events, "
            "person/relationships/attested for named people. Report what the "
            "archive holds: a lead is answered whatever the verdict. "
            "3. DECIDE RELEVANCE. The statement is RELEVANT when it bears on "
            "the claim — the claim's person, the family, or an attested family "
            "event. That covers agreement, disagreement, uncertainty, 'I don't "
            "know', a recollection about the family (the claim's person or any "
            "other family member — 'I don't remember the relationship, but we "
            "visited Walter in Seascale' IS relevant), and a wrong person for "
            "an attested family event ('it was Nora who died in the war' when "
            "the record says Walter bears on the claim: the error is surfaced "
            "as a contradiction, NEVER as irrelevance). The statement is NOT "
            "relevant ONLY when it is about something else entirely — a house, "
            "a holiday, an unrelated person with no connection to the claim, "
            "the family, or an attested family event. Judge by what the "
            "statement NAMES, not by what a search can be made to match: "
            "relevance needs a PERSON or a FAMILY EVENT in the statement "
            "itself. A place alone — 'that house every summer', 'the garden' "
            "— is not enough, and an archive record sharing the place's word "
            "does not make it so: never bridge a house or a holiday memory to "
            "a visit record on the place alone. A place joins the claim only "
            "through a person or an event the statement also names ('we "
            "visited Walter in Seascale' — the relative is named). "
            "4. DECIDE CONTRADICTION. An attested event carries its SUBJECT: the "
            "war record attesting that Walter died in 1916 is a fact ABOUT Walter, "
            "so a statement that gives that death to someone else — 'it was Nora "
            "who died in the war' — contradicts it, even though the archive holds "
            "no death record for Nora. Silence about the other person is not "
            "permission to move an attested event onto them: the conflict is with "
            "the record's subject, never with a fact the archive lacks. A "
            "same-name ambiguity buys no pass either — if a second person shares "
            "the name, ask which one they mean in your question AND still flag "
            "the conflict the record states. "
            "Flag it when the statement asserts something the attested facts "
            "deny: the wrong person for an attested death, disputing a confirmed "
            "relationship. Never flag a different version of an UNVERIFIED import "
            "guess — the import's guess is not attested; only genuine conflicts "
            "with the attested facts. "
            "When you have ALREADY spoken in this conversation, the "
            "reviewer's latest line is a NEW statement — it may not answer "
            "your earlier question: follow ITS leads and NEVER repeat your "
            "own earlier question verbatim (a past stall: the reviewer "
            "answered with a visit and the assistant re-asked the identical "
            "question). "
            "Your own previous reply is history, not a template: do NOT "
            "continue this turn in the previous reply's shape, do NOT ask "
            "again what you already asked, in substance or in reworded "
            "form, and do NOT mimic your own prior verdict's question — the "
            "reviewer's new line is the matter to answer now. ",
            "5. CONCLUDE WHEN THE REVIEWER IS EXHAUSTED. When the reviewer has said "
            "they don't know and cannot recall (no memory, never met the person), "
            "do NOT ask them to remember again in any form: state what you will do "
            "with the claim instead — keep the guess as it stands, or record what "
            "they remember — then end. The conclusion is a STATEMENT, never a "
            "question: write no '?' in it, and let NOTHING follow it — no follow-up "
            "question, no new lead to chase, no second sentence: the reviewer has "
            "told you what they know. Offering the alternative is still a statement "
            "— 'I'll leave it as Nora's brother unless you tell me otherwise' — "
            "never an offer put as a question ('shall I leave it…?'), which is a "
            "re-ask in another costume. ",
            "Then answer.",
            _TOOLS_DESC,
            # the conversation — the growing part — sits LAST so the
            # previous prompt's exact text is this prompt's prefix (the
            # prompt-cache reuses it). The family's latest line is part of
            # the same render: a message that re-answers an earlier
            # question is seen in the whole arc.
            "The conversation (verbatim — the family's words and your own previous "
            "reasoning and replies; the family's latest line may be re-answering an "
            "EARLIER question of yours that misunderstood them, so consider the whole "
            f"arc):\n{conversation}",
        ]
    )
    prompt = (
        "You are the family's genealogist — a friendly but professional researcher the family "
        "has hired, talking to them about their own archive. You NEVER speak in the system's "
        "voice: no 'the import', no statuses (proposed/estimated/confirmed), no 'link', no "
        "'the archive has a record for' — say what the records say in plain family language "
        "('the records list X as…', 'the war record says…'). The rule is never to introduce "
        "the process vocabulary yourself — if the REVIEWER uses a word like 'the import', you "
        "may use it back: echoing the family's own word is how they understand you, not a "
        "violation. You may "
        "investigate with the read-only tools, then return the verdict. You NEVER derive "
        "relationships, NEVER guess a kinship, NEVER infer who the reviewer is related to — "
        "the reviewer's own words are recorded verbatim or nothing is. Every word the family "
        "READS — each finding, the note, the question — is in the language the family writes "
        "in (this archive's family writes English), and a quotation stays in the document's "
        "own words: never translated. "
        "The contradiction "
        "check flags ONLY genuine conflicts with the archive's attested facts — never a "
        "different version of an unverified import guess, and never a fact the archive "
        "simply doesn't have. But an attested event's subject is not a fact the archive "
        "lacks: a statement that hands that event to the wrong person contradicts the "
        "record. When the record is silent AND no attested event is displaced, no "
        "contradiction."
    )
    verdict = (
        '{"relevant": true|false, "contradiction": {"found": true|false, '
        '"detail": "<the attested fact that conflicts, or empty>"}, "confidence": '
        "\"<definitely|think_so|dont_know|think_not|definitely_not|unclear> — the REVIEWER's "
        'own certainty, never your assessment: a hedged "I think" is think_so, never '
        'definitely. The reviewer\'s words map: "fairly sure", "pretty sure", "I think", '
        '"probably" → think_so; "I know", "confident", "positive", "sure", "certain" → '
        'definitely; "maybe", '
        '"not sure" → unclear; ONLY a bare "I don\'t know" / "no idea" / "can\'t recall" '
        "→ dont_know. The reviewer's words ALWAYS decide — a reviewer sure of something "
        'the archive cannot attest is still "sure", never dont_know.", '
        '"note": "<when relevant, one short sentence — the reason the answer seems right, in '
        'the family\'s own terms (e.g. "Grandma always said so"). When NOT relevant, the note '
        "is ONLY the topic the answer was about — a short phrase ('the house on Victoria "
        "Avenue'). NEVER the reasoning, NEVER the third person ('the reviewer'), NEVER an "
        'explanation of why it is off-topic>", "findings": '
        '[{"text": "<the family reads these words: the family member is ALWAYS "you"/"your" — '
        '"your recollection", "what you said" — never "the reviewer", never "the participant", '
        'never "the user". One short sentence per '
        "meaningful thing the tools surfaced, naming the "
        "SPECIFIC document (its title from the tool results) and the fact — with the EXACT "
        "sentence from the document's quotes that attests it, verbatim in quotation marks "
        "(e.g. \"in the Whitlock family history email, Pearl is described as a cousin: 'Pearl "
        "was always the clever one.'\"). Quote the relevant sentence — the one that mentions "
        "the fact — never the document's opening, never a paraphrase. NEVER \"the "
        'records\\", \\"the archive\\", a generic \\"the war record\\", and NEVER the import '
        "itself (the import is not a document — only the tool results list real items; "
        "if the tools found no document for the point, do not make a finding about it — "
        "and NEVER an empty findings array after a search surfaced a document bearing on "
        "the statement: that document IS a finding — "
        'and NEVER a bare absence like \\"no record connects X to Y\\": the findings report '
        "what the records DO show, not what they do not. A recollection is the family's "
        '— "Mum\'s recollection", "the recollection" — NEVER "the reviewer\'s". A PERSON '
        "record is not evidence either: its relation field is the import's guess, never a "
        "finding (R2: a robot's note is never an attestation — only items "
        "with a transcription or story are documents. A DRAFT transcription "
        "(the tool results mark drafts with 'draft': true) is machine-read and "
        "UNVERIFIED: its sentences are never quoted as the document's own words — "
        "quote only verified text, or say plainly that the reading is unverified "
        "(IMPORT-PRD Rule L). When the "
        "reviewer mentions a PLACE "
        "or an EVENT and the tools surface an item matching their statement, REPORT it — "
        "quote the item and ASK whether it is the same visit or person: the archive "
        "answers the family's lead even when the item does not settle the claim under "
        'review)">", '
        '"item_id": "<the document id from the tool results>"}, ...], '
        '"question": '
        '"<the genealogist next question to the reviewer, spoken to the family in their '
        'own words — never the process vocabulary: no "the import", no "the archive", no '
        '"the records", no statuses, no "awaiting". Asked the way '
        "a hired researcher "
        'would — the provenance when the reviewer cited a source ("did she tell you that '
        'personally?"), the follow-up that would firm up the connection; or a short conclusion '
        "when no question is needed. When the reviewer expresses NO knowledge and has NO "
        "lead to follow (confidence dont_know), offer the conclusion rather than asking "
        "again: \"I'll leave her as she stands unless you'd like to record what you remember "
        'as a guess.">"}'
    )
    # the verdict shape must be in the INITIAL prompt — the schema was only
    # revealed in the correction branch, so every first call was rejected
    # once before the shape appeared, doubling the cost of every exchange
    prompt = prompt + "\n\nReturn ONLY the verdict JSON, in exactly this shape:\n" + verdict
    prompt += (
        "\n\nThe verdict MUST contain ALL of these keys, spelled exactly as written — "
        "relevant, contradiction, confidence, note, findings, question — no others, "
        "no misspellings, no missing keys (a misspelled key is a failed verdict)."
    )
    tool_calls = 0
    trace: list[TraceStep] = []
    # the stable prompt — the static plus the conversation before the
    # loop's tool dynamics — is the caching prefix: the next call's stable
    # prompt starts with this one (the tool results are logged in the
    # trace, not in the prefix)
    base_prompt = user
    for _ in range(MAX_INVESTIGATE_STEPS + VERDICT_AND_CORRECTION_TURNS):  # the digs, plus the verdict and a correction
        try:
            raw = client.chat(prompt, user, thinking=True)
            parsed = json_object(raw)
        except AIClientError as e:
            raise ElicitationError(f"investigation failed: {e}") from e
        parsed_dict = parsed if isinstance(parsed, dict) else {}
        tool = str(parsed_dict.get("tool", "") or "").strip()
        reasoning = getattr(client, "last_reasoning", "")
        if tool:
            tool_calls += 1
            if tool_calls > MAX_TOOL_CALLS:
                # an over-budget tool-shaped turn is still the model's own
                # words — logged in the trace AND fed back verbatim, never
                # discarded (the completeness property — everything the model
                # produced is fed back and logged)
                trace.append(TraceStep(model=raw, reasoning=reasoning))
                user += (
                    "\n\n[your previous answer] "
                    + raw
                    + "\n\nNo more tool calls are allowed — conclude with the verdict JSON now."
                )
                continue
            raw_args = parsed_dict.get("args")
            wire_args: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}
            args = _tool_args(tool, wire_args)
            wire = _wire_result(run_tool(tool, args, facts))
            trace.append(TraceStep(model=raw, reasoning=reasoning, tool=tool, args=wire_args, result=wire))
            user += f"\n\nTool result ({tool}): {wire!r}"
            # the facts ledger sits LAST — the most salient position — and
            # is deduplicated/last-value-wins: the model consults what it
            # has instead of re-deriving it or debating further queries
            user += (
                "\n\nFacts already gathered (deduplicated, last value wins — "
                "consult this, never re-fetch a fact you have):\n" + _facts_ledger(trace)
            )
            continue
        trace.append(TraceStep(model=raw, reasoning=reasoning))
        turn = ReviewVerdict.from_dict(parsed_dict)
        if turn.complete:
            return replace(turn, raw=raw, trace=tuple(trace), prompt=base_prompt, final_prompt=user)
        user += (
            "\n\n[your previous answer] "
            + raw
            + "\n\nThat was neither a tool call nor the complete verdict. Keep the reasoning "
            "above and return the complete verdict JSON now: " + verdict
        )
    # pragma: no cover  # defensive: the bounded loop must conclude
    raise ElicitationError("investigation did not conclude")
