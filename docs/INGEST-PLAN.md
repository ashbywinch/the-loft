# The document-ingest review — implementation plan (INGEST-PLAN)

Status: agreed direction (2026-08-10, user). Mechanics for
`docs/INGEST-PRD.md`; the requirements doc is authoritative. Each slice
lands with its evals (the flow-per-phase shape of `tests/test_evals.py`),
and no eval covers another's ground.

## The object model (the whole shape, built slice by slice)

```python
@dataclass
class Evidence:
    """What makes a claim exist — the document's own words, or the
    family's own words for something they raised."""
    kind: Literal["document", "family"]
    item_id: str | None      # the document, when kind == "document"
    quote: str               # the direct quote that asserts the claim

@dataclass
class Assertion:
    """What the claim asserts — any piece of data the store can hold."""
    kind: Literal["existence", "fact", "relation", "event", "story"]
    subject: EntityRef | None        # the entity the fact/relation attaches to
    predicate: str | None            # "was a doctor", "was married in…"
    objects: tuple[EntityRef, ...]   # the other entities the assertion references

@dataclass
class Claim:
    id: str
    assertion: Assertion
    source: Evidence
    phase: ClaimPhase                # identity | disposition | population | closed
    identification: Identification | None   # may arrive pre-answered
    disposition: Disposition | None         # may arrive pre-answered (first-hand)
    details: list[Detail] | None            # the population output

    def next_question(self) -> str | None:
        """Ask the first unanswered phase — never what's already answered.
        The flow's one rule."""

@dataclass
class Identification:
    kind: Literal["resolved", "described", "unresolved"]
    record_id: str | None
    description: str | None

@dataclass
class Disposition:
    decision: Literal["attested", "estimated", "pending", "excluded"]
    basis: dict[str, str] | None   # {text, by, when} — the family's words, verbatim
```

The conversation is the queue: `claims: list[Claim]` + `current`. The
queue is **depth-first** (2026-08-10, user: "we should finish bottoming
out the current claim but then go through Bill and his marriage right
after that"): a claim's fan-out — the claims its resolution surfaces —
is worked immediately after the current claim, before the next
pre-existing claim. The discovered claims push onto the front of the
queue (a stack); the seeded document claims follow behind. The existing
`Session`/`Attempt`/`Message` in `tools/records.py` stays the
transcript; these classes are the flow.

## Slice 1 — the claim model + identity-first walk

- `Claim`/`Evidence`/`Assertion`/`Identification`/`Disposition` in
  `tools/records.py` (or a new `tools/claims.py` — the domain nouns
  decision).
- `Claim.next_question()`: identity → disposition → population → closed.
- The app's walk re-wires: each proposed person's claim asks **identity
  first** ("Who is {name}?" + the surfacing quote), then disposition
  ("Should {name} be recorded? The document says: {quote}") — replacing
  the current jump straight to the disposition chips.
- The quote selection is fixed at the same time: the surfacing quote is
  the document's own sentence that names the subject (page-marker-robust;
  a routing header counts when the subject appears only there — "From:
  Robert & Judith Armstrong" is the evidence Judith exists).
- The AI-generated notes are demoted out of the claim's framing — they are
  never presented as evidence.
- Evals: the review flows become claims walking their phases; a flow per
  phase (identity question asked first; disposition offered only after
  identity; the unresolved path reaches disposition).

## Slice 2 — unresolved identity → disposition; embedded attestation skips

- An unresolved identification proceeds to disposition: the document's
  quote attests existence; the user chooses add / leave / exclude.
- A claim whose identity and disposition arrived with the family's own
  first-hand words is pre-answered: `next_question()` skips the answered
  phases ("I went to work with my mum, she was a tree surgeon" — no
  identity or disposition question for mum's existence/occupation).
- Evals: the unresolved-to-disposition flow; the embedded-attestation
  skip flow.

## Slice 3 — discovery (the queue grows)

- New entities the family mentions during the conversation join the queue
  as claims (source: the family's words), pre-answered to the degree the
  words attest them.
- The walk never loses a mention; closure cannot happen while a
  discovered claim is unresolved.
- Evals: a mention mid-conversation produces a new claim; the discovered
  claim's phase state matches what the words attested.

## Slice 4 — compound-claim decomposition

- "They were married in the village church" decomposes: the marriage event
  claim + the church's existence claim; each raises its own questions
  (where exactly, when).
- A fact claim ("Bill was a doctor") presupposes its subject's existence —
  the subject's identity claim precedes the fact's disposition.
- Evals: the decomposition produces the component claims; the ordering.

## Slice 5 — population (the page-filling phase)

- "What do you remember about {name}?" — the facts, dates, relations and
  story that fill the page (the user's non-goal, now in scope).
- The details are recorded verbatim, attributed to the narrator.
- Evals: a populated claim's details fill the page shape.

## Slice 6 — closure + the completeness check

- The walk closes only when every claim is resolved (populated or
  explicitly excluded).
- The completeness check: no mentioned entity is left unclaimed; nothing
  unendorsed is recorded.
- Evals: the closure conditions; a stranded claim keeps the walk open.

## Dependencies and notes

- Slice 1 depends on nothing new; it replaces the app's current
  disposition-first walk and the quote selection.
- Slices 2–4 extend the phase machine; 5–6 complete it.
- Every slice's evals follow the flow-per-phase shape: one run per flow,
  cached outputs, independent condition tests (testing-standards
  Definitions).
