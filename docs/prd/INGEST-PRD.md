# The document-ingest review — requirements (INGEST-PRD)

Status: agreed direction (2026-08-10, user). Purpose: this doc is
requirements and user needs only — the mechanics live in
`docs/plans/INGEST-PLAN.md`. Related: the app's F9 + the review principles in
`docs/prd/PRD.md`; the artifact-import rules in `docs/prd/IMPORT-PRD.md`.

## The overarching goal

When a document (or the family's own telling) presents information that
might belong in the archive, the review resolves it into a correctly
populated record — by systematically working through the unknowns the
information presents, one question at a time, in a conversation with the
family. "Correctly populated" means:

- every person, place, item, event, story and fact the family wants kept
  is in the record, with its page adequately filled from the family's own
  words and the documents' evidence;
- nothing the family did not endorse is recorded;
- the review closes only when every unknown the conversation surfaced is
  resolved — populated, or explicitly excluded from relevance.

The telling is human and non-deterministic; the structure is not: every
unknown travels the same phases, and the conversation never loses an
unknown it has surfaced.

## Claims — the unit of work

A **claim** is an assertion the document or the conversation makes that
might need to be recorded. Claims are not only about the existence of a
person, place, item, event, story or memory — they are about **any piece
of data the store might hold**:

- an entity exists ("Dave", "the village church", "a wedding");
- a fact about an entity ("Bill was a doctor" — the occupation);
- a relationship or event ("they were married in the village church");
- any other assertion the store can represent.

A claim can be **compound**: "they were married in the village church" is
at least two claims — the marriage happened, and the village church exists
— and each raises its own further questions (where exactly was the church,
when was the marriage, who officiated). Compound claims decompose into
their components, and each component enters the review as its own claim.

Every claim carries **the evidence that makes it exist**: the document's
own words (a direct quote) that assert it, or — for something the family
themselves raise — the family's own words.

## The phases — every claim resolves through the same three, one question at a time

| Phase | The question (what the family sees) | The output |
|---|---|---|
| **Identity** | "Who is {name}?" — or "what is this place?", "what happened?" for the other kinds | the subject identified: an existing record, the family's description, or unresolved |
| **Disposition** | "Should {name} be recorded? The document says: {quote}" | attested / recorded as a guess (with the family's words as the basis) / left for later / excluded |
| **Population** | "What do you remember about {name}?" | the facts, dates, relations and story that fill the page |
| **Closed** | — | the claim's outputs are final |

## The rules

- **One question at a time; never re-ask what's already answered.** A claim
  whose identity and disposition arrived with the family's own first-hand
  words — "I remember going to work with my mum, she was a tree surgeon"
  attests that mum existed and was a tree surgeon — is not asked about
  those. The conversation asks only the first unanswered phase.
- **The conversation flows naturally — one claim and its fan-out are
  bottomed out before the next (2026-08-10).** When a claim's resolution
  surfaces new claims (Bill's marriage → Bill, and the marriage itself),
  they are worked immediately after the current claim is bottomed out —
  not deferred to the end of the queue. The family is not asked about
  Pearl, then Dave, then dragged back to Bill's marriage later: the
  current claim is finished, then Bill and his marriage are gone through
  right after it. Discovery is depth-first: the queue works a claim's
  consequences before the next pre-existing claim.
- **An unresolved identity still proceeds to disposition.** "I don't know
  who that is" does not end the claim: the document still attests the
  subject existed. The user then chooses add / leave / exclude — the
  user's choice, never the machine's — with the document's quote as the
  existence attestation.
- **Discovery.** New entities the family mentions during the conversation
  join the review as their own claims, pre-answered to the degree the
  family's words attest them ("my cousin Pearl" is identified; "Pearl
  wrote the letters" attests an activity). The walk never loses a mention.
- **Closure.** The review is done when every claim is resolved — populated
  or explicitly excluded. It cannot close while an unresolved claim is
  still in the queue.
- **The evidence discipline.** The family's words are recorded verbatim;
  the documents' evidence is quoted, never paraphrased; the machine's
  guesses are never presented as facts; the attestation is a human's words
  or a record — never "a note was made" (PRD R2).

## Non-goals (initially)

- The population phase's full page-filling — what goes into a page beyond
  the attestation (the user: "that's out of scope for now").
- Automatic capture — the review proposes; the family decides.
