# Review-chat redesign — suggested solution

> The parallel to `docs/ux-fixes-plan.md`'s review-chat findings (R1–R14).
> This is a **proposal**, not a landed spec: the flow's redesign that resolves
> every finding from the 2026-08-08→09 walk. Landed decisions go in the PRD /
> UI.md / CHAT-UX.md layers once the user agrees.

## The problem in one line

The review was designed for a **fresh** import — it presents every proposed
record as an unknown stranger and forces a family-ness + kinship answer —
so against a draft that curation has already superseded it shows a phantom
backlog, re-asks what the archive already knows, never asks the decision
that actually matters (the *status*), and can't be resumed.

## Design principles

1. **Reconcile first.** Before the chat opens, the draft is compared with
   the current table. The queue is what's genuinely pending; what's already
   placed is listed, not re-asked.
2. **The review decides the disposition of a *proposed link*; it never
   re-confirms an existing one.** The word "confirm" belongs to the status
   vocabulary (confirmed = attested) and is **never used for the decision**.
   The decisions have their own words: *resolve*, *mark*, *keep*, *delete*.
3. **The exact fact is named.** Every question states the precise claim
   being verified — "the import proposes: **Quentin Whitlock is the brother of
   Pearl Whitlock**" — with the people by name. The reviewer verifies that
   claim, nothing vaguer.
4. **"I don't know" is a first-class answer**, never an input for the model
   to guess over.
5. **Estimated always carries its basis, in the reviewer's own words.**
   "I believe it" is followed by "what makes you think that?", and the
   answer is recorded verbatim, dated, and attributed by name.
6. **The model never invents relationships.** Relations are recorded from
   the reviewer's own words (or the import's guess). No AI-derived
   narrator-relative terms — the walk's "your ex-husband" failure came from
   exactly that.
7. **Off-topic answers are caught.** If the reviewer's answer addresses a
   different claim ("X was definitely in that house at the time"), the chat
   names the mismatch and re-asks the actual question.
8. **The conversation is a record.** The transcript and the decisions are
   persisted on the import session's page — resumable, reviewable, honest
   about what changed.
9. **Status is visible, and the copy names people.** Confirmed / estimated
   / proposed render differently everywhere a person or relationship
   appears; an estimated marker says "from **Nora's** recollection,
   9 Aug 2026: …" — never "the narrator", and never more than the dataset
   actually records.

## The two vocabularies (the "confirm" collision)

| Vocabulary | Words | Meaning |
|---|---|---|
| **Status** (the archive's state) | confirmed | the link is attested — by the record, or the owner's verified word |
| | estimated | a guess, with a recorded basis ("from Nora's recollection") |
| | proposed | the import's guess, awaiting review |
| **Decision** (what the review does) | resolve / mark | the reviewer decides a proposed link's fate |
| | mark attested → confirmed | the reviewer vouches the link is true — her own verified word |
| | mark estimated | the reviewer's recollection + the recorded basis |
| | keep pending → proposed | no information; the import's guess stays |
| | delete → dismissed | the proposed link is wrong |

A proposed link is **resolved**; it **becomes** confirmed/estimated/proposed
or is deleted. The review never asks anyone to "confirm" anything — that
word is the status, not the action.

## How each finding resolves

| # | Finding | Resolution |
|---|---|---|
| R1 | Phantom backlog | **Reconcile-first queue**: the opening message counts only the proposed links not already resolved — "3 proposed links need a decision; 26 are already in the archive — review the 3, or see what's already placed?" The already-placed are a section, not a queue. |
| R2 | Re-asks what it knows | The already-placed link is shown with its existing state: "The archive already records Quentin as brother of Pearl (confirmed)." Nothing to decide — it is not in the queue. |
| R3 | "Is she family?" wrong question | **Dropped entirely.** The review resolves the proposed link's disposition; family-ness never appears. A non-family associate (teacher, official) is recorded the same way — disposition with no kinship, landing in "Also in the archive". |
| R4 | Status decision never asked | The per-link question names the claim and offers the four decisions: "The import proposes: **Quentin Whitlock is the brother of Pearl Whitlock**. What do you know about that?" — [I know this is true] [I believe it — my recollection] [I don't know] [It's wrong — remove it]. The "I know this is true" is the reviewer's own verified word (an attestation) — never "from the record", which would misattribute the knowledge to an archive that already resolved the link. |
| R5 | No "I don't know" path | *I don't know* is a quick reply: "He stays as the import's guess (proposed) until we know more — or mark him estimated with what little you do know?" The model never sees "I don't know" as a claim to resolve. |
| R6 | Double-message echo | One message per decision: "Quentin's link is recorded — estimated." The preview-then-confirm pair is deleted. |
| R7 | No thinking indicator | The spec from the findings: animated dots / "Thinking…" in the assistant's message slot, shown the instant the reviewer sends, replaced by the reply in the same slot; polite live region + `prefers-reduced-motion` static; label escalates after ~2s. |
| R8 | Unsatisfying ending | A closing summary with what actually changed: "Review done: 3 marked attested, 2 marked estimated, 1 deleted, 23 were already in the archive — nothing changed for them." Plus a next action — "See the family tree →". |
| R9 | Transcript not resumable | The review session persists server-side (imports identity table): the transcript, the current link, and every decision. The import session's page renders it; a resumed review continues from the last undecided link. |
| R10 | Hardcoded "she" | The claim is always phrased with names: "Quentin Whitlock is the brother of Pearl Whitlock" — no pronoun to get wrong. |
| R11 | Header count never moves | The header reads the same reconciled queue the chat walks; it re-renders on every advance. |
| R12 | Estimated status invisible | Estimated renders distinctly: the person page and cast card carry "estimated — from **Nora's** recollection, 9 Aug 2026: *verbatim basis*"; the tree's estimated edges are dashed. The chip names the person and shows the basis only as the dataset recorded it — never "the narrator", never more than in evidence. |
| R13 | Generic failure line | Errors state the cause; deleting an already-resolved link is a state ("that link is already recorded — nothing to delete"), not the 400 path. |
| R14 | Completion claim oversells | The summary counts the already-in-the-archive separately and says "nothing changed for them." |

## The conversation, concretely

```
[opening, reconciled]  "The document import review — 3 proposed links need
                       a decision; 26 are already in the archive.
                       Review the 3, or see what's already placed?"

[per link, exact fact] "The import proposes: Quentin Whitlock is the brother
                       of Pearl Whitlock (and brother of Pearl).
                       What do you know about that?"
                       [I know this is true]
                       [I believe it — my recollection]
                       [I don't know]
                       [It's wrong — remove it]

[I know this is true] → the link is marked attested (confirmed) — the
                       reviewer's own verified word.

[I believe it]         "What makes you think that?"
                       [free text — recorded verbatim, dated, named;
                        the prompt never suggests a reason — the basis
                        is the reviewer's own, or it isn't an estimate]

[off-topic answer]     "That's about the house — I need the brother link
                       (Quentin Whitlock is the brother of Pearl Whitlock).
                       What do you know about that?"

[I don't know]         "He stays as the import's guess (proposed) until
                       we know more — or mark him estimated with what
                       little you do know?"
                       [Keep as proposed] [Mark estimated]

[one message, no echo] "Quentin's link is recorded — estimated, from
                       Nora's recollection: 'Grandma used to say…'."

[ending]               "Review done: 3 marked attested, 2 marked estimated,
                       1 deleted, 23 were already in the archive — nothing
                       changed for them."
                       [See the family tree →]
```

## Data-model changes

- **imports identity table** gains the review record: `{ session_id,
  transcript: [messages], current: link_id | null, decisions: [{link,
  disposition, status, basis?, when}] }` — written by the review
  endpoints, served on the session's page, the resume point.
- **People/relationships**: `estimated` gains the basis — the recorded
  verbatim text, the named person, the date — stored on the relationship
  (and person where the estimate is the person's existence). The chip
  renders only what the dataset carries: "from **X's** recollection,
  DATE: *basis*".
- **The server**: the review endpoints learn the disposition vocabulary
  (mark-attested / mark-estimated / keep-pending / delete). `/api/review/
  relate` is removed from the recording path — relations come from the
  reviewer's words or the import's guess, never AI-derived. The free-text
  basis and the free-text kinship answers are checked against the named
  claim (off-topic detection) before they are recorded.
- **The tree and the cast** render the estimated marker (dashed edges,
  named chip) — R12.

## Open questions for the user

1. The "keep as proposed" backlog: should a kept-proposed link reappear in
   the review on the *next* visit (resume), or sit quietly until the
   reviewer reopens the session?
2. The estimated chip's wording: "estimated — from Nora's recollection,
   9 Aug 2026: 'Grandma used to say…'" — correct length, or shorter?
3. Should the tree draw estimated edges dashed, or keep solid lines and
   mark only the person cards? (The dashed edge is the stronger signal.)
