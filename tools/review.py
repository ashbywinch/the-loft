"""The import review (2026-08-09, user): the review resolves the
DISPOSITION of each proposed link in the chat — attested, estimated (with
the reviewer's own words recorded verbatim as the basis), pending, or
deleted. The model never invents relationships: ``check_relevance`` only
decides whether a free-text answer addresses the exact claim under review
(the walk's "your ex-husband" failure came from the old relation
inference — a random ancestor resolved to the narrator's own spouse). The
decision vocabulary is NOT the status vocabulary: "confirm" is a status,
never an action (user, 2026-08-09).
"""

from __future__ import annotations

from typing import Any, Protocol

from tools.ai_client import AIClientError, json_object
from tools.memory import ElicitationError
from tools.records import Message, Person, ReviewContext

MAX_RESOLVE_ATTEMPTS = 2


def _relevant_sentences(text: str, needles: tuple[str, ...], limit: int = 3) -> list[str]:
    """The sentences of a document that mention any needle — the RELEVANT
    part to quote, never the opening (2026-08-09, user: the model was
    "extremely bad at identifying the relevant part of the document to
    quote when explaining the attestation" — the tools returned the
    document's first 200-300 characters, so the model could only quote the
    opening). Returns up to ``limit`` matching sentences, capped in length,
    or the first content sentence when nothing matches (a fallback, never
    silence)."""
    import re

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    hits = [s for s in sentences if any(n in s for n in needles)]
    pool = hits or sentences
    return [s[:300] for s in pool[:limit]]


class _Chat(Protocol):
    def chat(self, system: str, user: str) -> str: ...


def _known_facts(facts: ReviewContext) -> str:
    """The archive's attested facts for the contradiction check — the
    people (deaths + relations) and the recorded items' stories, read
    through the typed context (the Knowledge's converted models drop the
    dod and the stories, so the investigation reads the raw projection)."""
    lines = ["People:"]
    for p in facts.people:
        bits = [f"  {p.id} — {p.name}"]
        if p.dob:
            bits.append(f"(born {p.dob.get('date')})")
        if p.dod:
            bits.append(f"(died {p.dod.get('date')})")
        if p.relation:
            bits.append(f"(relation: {p.relation})")
        lines.append(" ".join(bits))
    lines.append("Recorded items:")
    for it in facts.items:
        story = (it.get("story") or it.get("transcription") or "").strip()
        if story:
            lines.append(f"  {it.get('id')} — {it.get('title', '')}: {story[:200]}")
    return "\n".join(lines)


MAX_INVESTIGATE_STEPS = 6  # the digs plus room for a verdict correction

_TOOLS_DESC = """You can investigate the archive with these READ-ONLY tools:

- search_people({"query": "<name or relation text>"}): people whose name or
  import record matches, with their ids.
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
enough to answer, return the verdict JSON."""


def _run_tool(tool: str, args: dict[str, Any], facts: ReviewContext) -> Any:
    """The read-only tool harness — the model can look things up but never
    change them (2026-08-09, user: give the AI the API so it can find out
    the existing situation — the ad-hoc digging conversation)."""
    people = facts.people
    if tool == "search_people":
        q = str(args.get("query", "")).strip().lower()
        if not q:
            return {"error": "query required"}
        hits = [
            {"id": p.id, "name": p.name, "relation": p.relation}
            for p in people
            if q in p.name.lower() or q in p.relation.lower()
        ]
        return hits[:10] or {"note": "no matches"}
    if tool == "person":
        pid = str(args.get("id", ""))
        p = next((x for x in people if x.id == pid), None)
        return (
            {"id": p.id, "name": p.name, "relation": p.relation, "status": p.status}
            if p
            else {"error": f"no person {pid}"}
        )
    if tool == "relationships":
        pid = str(args.get("id", ""))
        return [r for r in facts.relationships if r.get("a") == pid or r.get("b") == pid] or {
            "note": "no recorded relationships"
        }
    if tool == "attested":
        pid = str(args.get("id", ""))
        p = next((x for x in people if x.id == pid), None)
        # the sentences that MENTION the person — the part that attests
        # the fact, quotable verbatim (2026-08-09, user) — with the
        # person's name and first name as the needles. The item's
        # structured involvement (its people ids) or the prose naming the
        # person both count — real transcriptions mention names, never ids
        needles = (p.name, p.name.split()[0]) if p else (pid,)
        results = []
        for it in facts.items:
            text = it.get("story") or it.get("transcription") or ""
            involved = pid in it.get("people", [])
            if involved or any(n in text for n in needles):
                results.append({"id": it["id"], "title": it["title"], "quotes": _relevant_sentences(text, needles)})
        return results or {"note": "no recorded items mention this person"}
    if tool == "search_items":
        q = str(args.get("query", "")).strip().lower()
        if not q:
            return {"error": "query required"}
        hits = []
        for it in facts.items:
            text = it.get("story") or it.get("transcription") or ""
            if q in text.lower():
                hits.append({"id": it["id"], "title": it["title"], "quotes": _relevant_sentences(text, (q,))})
        return hits[:5] or {"note": f"no recorded items mention {q!r}"}
    return {"error": f"unknown tool {tool}"}


def assistant_message(result: dict[str, Any], person: Person) -> str:
    """The assistant's rendered words for one investigation response — what
    the family sees, verbatim (2026-08-09, user: "when you load a given
    transcript, you see exactly what I saw"). The server builds the words;
    the app shows them unmodified; the record stores them. The model's
    internal note never surfaces."""
    parts: list[str] = []
    if result.get("findings"):
        parts.append("The documents show: " + " ".join(f["text"] for f in result["findings"]))
    if result.get("question"):
        parts.append(result["question"])
    return " ".join(parts)


def confirmation_message(name: str, decision: str, basis: dict[str, Any] | None) -> str:
    """The assistant's rendered confirmation — the receipt the family sees,
    in the genealogist's voice, naming the consequence (2026-08-09; the
    vocabulary is the family's, never the statuses': fact / guess / left
    for later / delete — user, 2026-08-10)."""
    if decision == "attested":
        return f"Done — {name} joins the tree as a fact."
    if decision == "estimated":
        text = (basis or {}).get("text") or "a guess"
        return f"Done — I've recorded {name} as a guess: '{text}'."
    if decision == "delete":
        return f"Done — {name} is not recorded after all."
    return f"{name} stays out of the tree for now — we can pick it up later."


def steer_message(person: Person, note: str) -> str:
    """The off-topic steer — the genealogist's words, never the model's
    internal note (the note was leaking into the parens, 2026-08-09)."""
    return (
        f"That's about {note or 'something else'} — let's come back to {person.name}: does that fit what you remember?"
    )


def render_history(messages: tuple[Message, ...]) -> str:
    """The conversation so far, verbatim — the family's words and the
    assistant's reasoning and speech, in order — so the model sees the
    whole arc (2026-08-09, user: the flow misunderstood because the model
    couldn't see that an answer was re-answering an earlier question; the
    model needs its own history to do its job)."""
    lines: list[str] = []
    for m in messages:
        if m.role == "user":
            lines.append(f"[family] {m.text}")
        else:
            if m.thinking:
                lines.append(f"[assistant reasoning] {m.thinking}")
            lines.append(f"[assistant] {m.text}")
    return "\n".join(lines)


def investigate(
    client: _Chat,
    *,
    text: str,
    person: Person,
    who: str,
    facts: ReviewContext,
    history: tuple[Message, ...] = (),
) -> dict[str, Any]:
    """The tool-using review of a free-text answer (2026-08-09, user): the
    model can call the archive's read-only lookups to dig into the
    reviewer's statement — follow the leads and surface what the archive
    already attests — then return the verdict: {relevant, contradiction,
    confidence, note, findings, question, raw}. *history* is the
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
    claim = f"the import proposes adding '{person.name}'"
    if person.relation:
        claim += f" — import record: '{person.relation}'"
    # the conversation renders uniformly and sits LAST in the prompt — the
    # static (the reviewer, the claim, the facts, the instructions) comes
    # before it, so the previous prompt's exact text is the current prompt's
    # prefix and the model's prompt-cache reuses the whole thing
    # (2026-08-09, user: 'the exact same text goes back… cheaper if so,
    # because of caching'). The latest line is part of the same render, so
    # a message that re-answers an earlier question is seen in context.
    conversation = render_history(history + (Message(role="user", text=text, when=""),))
    user = "\n\n".join(
        [
            f"Reviewer: {who or 'unknown'}",
            f"The claim under review: {claim}.",
            "Known family (the archive's attested facts):\n" + _known_facts(facts),
            "The reviewer's statement may carry leads worth checking — follow them with the "
            "tools before concluding. ONLY dig when the statement names people or mentions "
            "events the archive may attest (a death, a marriage, a place); a statement without "
            "leads — 'Grandma used to say so', 'I vaguely remember' — needs no tool calls: "
            "answer directly. When the reviewer mentions a PLACE or an EVENT (a visit, a "
            "town, a death), search the items for it — do not stop at the people. "
            "When you have ALREADY spoken in this conversation, the reviewer's latest line "
            "is a NEW statement — it may not answer your earlier question at all: follow "
            "ITS leads, acknowledge what they said, and NEVER repeat your own earlier "
            "question verbatim (2026-08-10, the Seascale stall: the reviewer answered "
            "with a visit to Seascale and the assistant re-asked the identical question). "
            "An answer that "
            "AGREES or DISAGREES with the claim, expresses "
            "uncertainty about it, or brings in the family facts the reviewer connects to it "
            "(who died, who married whom) IS relevant — the reviewer is answering the question. "
            "A statement that opens 'I don't remember' and then brings in what they DO remember "
            "about the person IS relevant — the uncertainty and the recollection are both "
            "answers to the claim. "
            'An answer about a person\'s WHEREABOUTS or a place ("he was in that house", '
            '"she lived in Marlock") without bearing on the claim is NOT relevant, however '
            "confident — the reviewer has answered a different question. BUT a place or a "
            "visit the reviewer mentions is still a LEAD first: search the archive for it "
            "and report what it holds, asking whether it is the same visit — the lead is "
            "answered even though the disposition is unaffected (2026-08-10, the Seascale "
            "arc: the model judged the visit 'not relevant' and never searched, so the "
            "family's lead went unanswered). "
            "And: does the statement CONTRADICT anything the archive attests? The reviewer "
            "names the wrong person for an attested event — e.g. the record says Walter "
            "Whitlock died in 1916 and the reviewer says 'it was Nora who died in the war': "
            "that contradicts the attested death. Or the reviewer disputes a confirmed "
            "relationship or asserts something the recorded facts deny. Flag the "
            "contradiction EVEN when the answer is otherwise off-topic — the reviewer has "
            "asserted something the record denies and must resolve it. Never flag a different "
            "version of an UNVERIFIED import guess (the import's guess is not attested) — "
            "only genuine conflicts with the attested facts. Then answer.",
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
        "('the records list X as…', 'the war record says…'). You may "
        "investigate with the read-only tools, then return the verdict. You NEVER derive "
        "relationships, NEVER guess a kinship, NEVER infer who the reviewer is related to — "
        "the reviewer's own words are recorded verbatim or nothing is. The contradiction "
        "check flags ONLY genuine conflicts with the archive's attested facts — never a "
        "different version of an unverified import guess, never a new fact the archive "
        "simply doesn't have. When in doubt, no contradiction."
    )
    verdict = (
        '{"relevant": true|false, "contradiction": {"found": true|false, '
        '"detail": "<the attested fact that conflicts, or empty>"}, "confidence": '
        '"<definitely|think_so|dont_know|think_not|definitely_not|unclear>", '
        '"note": "<when relevant, one short sentence — the reason the answer seems right, in '
        'the family\'s own terms (e.g. "Grandma always said so"). When NOT relevant, the note '
        "is ONLY the topic the answer was about — a short phrase ('the house on Victoria "
        "Avenue'). NEVER the reasoning, NEVER the third person ('the reviewer'), NEVER an "
        'explanation of why it is off-topic>", "findings": '
        '[{"text": "<one short sentence per meaningful thing the tools surfaced, naming the '
        "SPECIFIC document (its title from the tool results) and the fact — with the EXACT "
        "sentence from the document's quotes that attests it, verbatim in quotation marks "
        "(e.g. \"in the Whitlock family history email, Pearl is described as a cousin: 'Pearl "
        "was always the clever one.'\"). Quote the relevant sentence — the one that mentions "
        "the fact — never the document's opening, never a paraphrase. NEVER \"the "
        'records\\", \\"the archive\\", a generic \\"the war record\\", and NEVER the import '
        "itself (the import is not a document — only the tool results list real items; "
        "if the tools found no document for the point, do not make a finding about it — "
        'and NEVER a bare absence like \\"no record connects X to Y\\": the findings report '
        "what the records DO show, not what they do not. A recollection is the family's "
        '— "Mum\'s recollection", "the recollection" — NEVER "the reviewer\'s". A PERSON '
        "record is not evidence either: its relation field is the import's guess, never a "
        "finding (2026-08-10, R2: a robot's note is never an attestation — only items "
        "with a transcription or story are documents. A DRAFT transcription "
        "(transcription_status 'draft') is machine-read and UNVERIFIED: its sentences "
        "are never quoted as the document's own words — quote only verified text, or "
        "say plainly that the reading is unverified (IMPORT-PRD Rule L). When the "
        "reviewer mentions a PLACE "
        "or an EVENT and the tools surface an item matching their statement, REPORT it — "
        "quote the item and ASK whether it is the same visit or person: the archive "
        "answers the family's lead even when the item does not settle the claim under "
        "review (2026-08-10, the Seascale arc: the model searched, found the visit, and "
        "dropped it because it concerned a different person than the claim — the family's "
        'lead went unanswered)">", '
        '"item_id": "<the document id from the tool results>"}, ...], '
        '"question": '
        '"<the genealogist next question to the reviewer, asked the way a hired researcher '
        'would — the provenance when the reviewer cited a source ("did she tell you that '
        'personally?"), the follow-up that would firm up the link; or a short conclusion '
        "when no question is needed. When the reviewer expresses NO knowledge and has NO "
        "lead to follow (confidence dont_know), offer the conclusion rather than asking "
        "again: \"I'll leave her as she stands unless you'd like to record what you remember "
        'as a guess.">"}'
    )
    # the verdict shape must be in the INITIAL prompt — the schema was only
    # revealed in the correction branch, so every first call was rejected
    # once before the shape appeared, doubling the cost of every exchange
    # (2026-08-11 review)
    prompt = prompt + "\n\nReturn ONLY the verdict JSON, in exactly this shape:\n" + verdict
    tool_calls = 0
    trace: list[dict[str, Any]] = []
    # the stable prompt — the static plus the conversation before the
    # loop's tool dynamics — is the caching prefix: the next call's stable
    # prompt starts with this one (the tool results are logged in the
    # trace, not in the prefix)
    base_prompt = user
    for _ in range(MAX_INVESTIGATE_STEPS + 3):  # the digs, plus the verdict and a correction
        try:
            raw = client.chat(prompt, user)
            parsed = json_object(raw)
        except AIClientError as e:
            raise ElicitationError(f"investigation failed: {e}") from e
        parsed_dict = parsed if isinstance(parsed, dict) else {}
        tool = str(parsed_dict.get("tool", "") or "").strip()
        if tool:
            tool_calls += 1
            if tool_calls > 4:
                user += "\n\nNo more tool calls are allowed — conclude with the verdict JSON now."
                continue
            raw_args = parsed_dict.get("args")
            args: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}
            result = _run_tool(tool, args, facts)
            # the tool call and its deterministic result are part of the
            # model's reasoning — logged verbatim, never discarded
            # (2026-08-09: 'why would that stop you logging them correctly?'
            # — nothing does; the gap was that we didn't)
            trace.append({"model": raw, "tool": tool, "args": args, "result": result})
            user += f"\n\nTool result ({tool}): {result!r}"
            continue
        trace.append({"model": raw})
        relevant = str(parsed_dict.get("relevant", "")).strip().lower()
        raw_contradiction = parsed_dict.get("contradiction")
        contradiction: dict[str, Any] = raw_contradiction if isinstance(raw_contradiction, dict) else {}
        found = str(contradiction.get("found", "")).strip().lower()
        confidence = str(parsed_dict.get("confidence", "")).strip().lower()
        if (
            relevant in ("true", "false")
            and found in ("true", "false")
            and confidence in ("definitely", "think_so", "dont_know", "think_not", "definitely_not", "unclear")
        ):
            findings = parsed_dict.get("findings")
            normalized = []
            for f in findings if isinstance(findings, list) else []:
                if isinstance(f, dict):
                    normalized.append(
                        {"text": str(f.get("text", "")).strip(), "item_id": str(f.get("item_id", "")).strip() or None}
                    )
                else:
                    normalized.append({"text": str(f).strip(), "item_id": None})
            return {
                "relevant": relevant,
                "contradiction": {"found": found, "detail": str(contradiction.get("detail", ""))},
                "confidence": confidence,
                "note": str(parsed_dict.get("note", "")).strip(),
                "findings": [f for f in normalized if f["text"]],
                "question": str(parsed_dict.get("question", "")).strip(),
                "raw": raw,
                "trace": trace,
                "prompt": base_prompt,
                # the final user string after the loop's appends — the
                # completeness property: everything the model produced is
                # fed back (2026-08-09, user)
                "final_prompt": user,
            }
        user += (
            "\n\n[your previous answer] "
            + raw
            + "\n\nThat was neither a tool call nor the complete verdict. Keep the reasoning "
            "above and return the complete verdict JSON now: " + verdict
        )
    raise ElicitationError("investigation did not conclude")  # pragma: no cover
