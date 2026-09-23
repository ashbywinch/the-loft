# Story & Fact Capture — "Add your memory" (Feature PRD)

- **Status:** requirements (the flow shipped 2026-08-03 →; mechanics in
  `TECHSPEC.md` §3/§4/§16.9/§16.11/§16.12)
- **Companions:** `PRD.md` §19 (story harvest), `TECHSPEC.md` §16.9/
  §16.11/§16.12 (mechanics), `docs/PLAN/PLAN.md`
- **Requirements only.** This file states what the feature must do for the
  family — nothing about how it is built. Mechanics live in TECHSPEC.

## What this is

Browse-side capture (PRD §19, productized): every entity page — item, person,
place, story/theme — carries an **"Add your memory"** affordance. A
contributor tells their account; an AI assesses it — proposing
people/places/links under the standing certainty rules — then interviews:
**open-ended first** ("anything else?") until the narrator closes the
account, then **bounded targeted questions** for genuinely missing detail.
The narrator reviews before anything is stored. The AI's guesses — links,
dates, facts — are verified by whoever is operating the flow, in the same
flow's review: kept means confirmed, dropped means gone, nothing waits on a
separate confirmation gate. Nothing asserted unreviewed (P4); nothing told
is lost (§19.4).

## The narrator's experience

**Affordance placement** — one shared component, identical on all four page
types, obeying §19.7 (after the artifact/facts, before Connections):

| Page | Placement |
|---|---|
| Item lens | after story/provenance/metadata → "Your memories": attributed responses, then the button |
| Person page | after bio/known-as → "Add a memory of Nora" |
| Place page | after the note → "Add a memory of Marlock" |
| Story/theme page | after the arranged items → "Add your story to this theme" |

Bottom-of-page, not topbar: the artifact is the anchor on a browse-first
surface; capture is the secondary act. Same 44px-touch, scrapbook-warm
language as the existing doors. A global "tell us a story" door on Home is
out of scope (the requirement starts from the thing's page) — candidate for
later.

**The gathering flow** — a full-screen chat with the assistant (phone-first):

1. **Who**: the narrator IS the signed-in identity — the capture flow never
   asks for a name; signed out, it asks the narrator to sign in.
2. **The account**: "What do you remember about X?" — the story, then
   "Anything else?" **with no cap** — the assistant keeps asking until the
   narrator taps "That's everything". Nothing is forced; nothing is lost.
3. **Questions**: the AI's targeted questions one at a time, each with
   quick-reply suggestion buttons, "Skip", and "I'd rather not say". The
   current question is always above the fold (no long transcript pushes it
   off-screen).
4. **Review**: the AI-suggested title, the assembled verbatim account
   (editable — redaction), and the proposed links as **toggles** (tap to keep
   or drop) plus an "add a person or place" field. Save as told.
5. **Saved**: confirmation — a draft, marked not confirmed.

**Degradation:** when the household server is unreachable, the sheet
explains contributions are collected while it is running (the same card
language as the import admin view); the affordance stays visible.

**Browse-driven capture — the fireside principle (PRD §19 req 11, §9
F10).** Capture lives where a memory is born: the browse itself prompts,
subtly — never an interruption, never an interrogation. The narrator
follows whatever tangents they wish, at whatever length, and the flow
returns them to their starting point without losing anything they said.
A memory left unfinished is not lost: it joins the work queue — the same
queue that carries the proposed identities from imports (PRD §19 req 11:
an unfinished memory may simply have more to tell, but the task is the
same conversation) — visibly unfinished, and resumes without re-asking
what was already told. The
session is a fireside chat — the narrator's voice leads; nothing is
forced, nothing is required.

## The elicitation (what the AI must do)

**Phase A — open-ended closure.** After the initial account: "Anything else?" —
up to two rounds, then a soft "anything else before we go on?". The narrator
closes with a one-tap **"That's everything"** in the UI, so open-endedness
never becomes a wall. The account is only finished when the narrator says so —
never cut short by structured questions (§19: capture fully, then review).

**Phase B — targeted gaps.** Given the account + the thing it's about +
standing knowledge, ask *only* questions that meet the certainty rules —
never filler, never what's already known:

- dates: prod, record precision honestly when the narrator can't say (req 5)
- who was actually present (req 8), with the date-bounded presence check
- identity: "which Harper?" — never guessed (worked-example lesson 5)
- place identification/precision: "the old ford — which one?" (reqs 6–7)
- dob/pronouns only when they'd disambiguate presence, politely, nothing required (reqs 9–10)
- provenance: when the family cites a source ("Mum said…"), ask directly how they know — "Did she say that to you personally?" / "What did you see that made you think that?" — and record the answer verbatim, attributed, as the statement's provenance (e.g. `Pete: "Mum used to tell us this all the time"`), never an inferred status (PRD §19 req 2)

Every question is skippable ("Don't know / Skip"); the set is bounded (~5,
progress shows "2 of 5"). Ambiguity → a question, never a proposal; every
proposal is proposed.

The assessment **self-corrects**: genuine violations (mentions linked,
impossible matches, redundant questions, missing polite date questions) are
fed back for a bounded redo; a date computed from an age + a known date of
birth is derived deterministically, never asked of the model. The evals
cover a fictional family as well as the real one, so nothing is overfit to
one household. **No person is special-cased** — the narrator resolves like
anyone else; curation is a role anyone can hold, not a person record.

## What a memory is (content rules)

- **A memory is a story, not a new kind of thing** — a story item like any
  other artifact (user, 2026-08-03). It can respond to an artifact or to
  another story. The page the narrator started from becomes a proposed
  link — the narrator's own aboutness evidence.
- **`date` = the events, `recorded` = when told** (user, 2026-08-03): the
  timeline places the memory with its subject matter. Precision is honest
  when the narrator cannot say (PRD req 5). **The date is never defaulted
  to the telling day** — the flow always asks for the events' date
  (non-skippable) and never lets the telling day stand in for it (2026-08-05:
  fabricated telling-day dates shipped and the moment card served "0 years
  ago this week"; enforced in elicitation and guarded by tests).
- **A story is the narrator's own words, verbatim — never generated
  testimony** (PRD §10, user, 2026-08-03). No generated content is ever
  attributed to a person; an AI's summary is curation prose, never narrator
  testimony.
- **Facts are stories too** (user, 2026-08-03): a terse fact ("her birthday
  was 12 March 1928") is a verbatim story item; the AI's extraction proposes
  entity-field updates (dates of birth, aliases, relationships, place
  precision) that the review confirms or drops.
- **Clarification fragments and reflections** are story-shaped records with
  a flag, not a new type (2026-08-06). A clarification asserts an identity
  fact ("Lex is an alias of Alex") and renders **only on the pages it
  attests** — never on the timeline. A reflection is the narrator's
  perspective, has no events' date other than its telling day, and renders
  **only on the pages it mentions** — never on the timeline. A story is one
  or the other, never both; each must reference its target.
- **Verification is the review, not a later gate** (user, 2026-08-03):
  every AI guess enters proposed and the operator flips it in the same
  flow's review — kept = confirmed, dropped = gone. A completed, reviewed
  save is live immediately; an abandoned one stays a draft with proposed
  refs (nothing asserted unreviewed, P4).
- **Attribution** (2026-08-06): the narrator IS the signed-in identity;
  signed out, the flow asks them to sign in. The contributor names
  themselves — autocomplete over the cast (names + aliases) — and a name
  that matches nobody is a **new proposed person**: the assistant says so
  and asks how they are connected to the family, unless the story already
  makes it obvious.
- **Organisations and memorabilia are story links too** (2026-08-05): a
  story may reference organisations and objects, with the same
  propose/confirm refs — one content model, two capture flows (IMPORT-PRD
  §2.5).
- **A known object family is disambiguated, never guessed** (2026-08-06):
  when an account references a family of known objects without naming one
  ("we were on the boat"), the flow asks which — "Which boat?" — rather
  than assuming. An object link is an assertion; the name comes from the
  narrator, not the model. Every object must be attested by an artifact
  that names it.
- **Display:** a told account reads as **"Memory"** with its "told by /
  told <date>" stamp on every card — never "Story", which reads like
  another scanned document to a visitor (user, 2026-08-03).
- **Privacy:** the AI's reading never happens on the reader's device;
  family content leaves the household machine only for the explicitly
  requested AI call (house rule; §7 — no third-party cloud processing of
  family content). The family chooses the posture — cloud by default or
  local-only.
- **Append-only:** a memory lands wherever the app stores its info —
  local archive today, hosted later — under the archive's append-only rule
  (PRD §3 non-goal; mechanics in `TECHSPEC.md` §3).

## Acceptance

On any entity page, tell a 60-second story → open-ended closure → targeted
questions → review (the AI's guesses verified in-flow) → saved → rendered
as an attributed response. A new place named in the story ("the old ford")
enters as proposed with a follow-up question, never a guessed link — and
the operator's review confirms or drops it.

## Decisions (requirement rulings)

- **Type:** a memory is not a new type — it is a story item (user).
- **Dates:** the events' date with honest precision; the telling day
  recorded separately (user).
- **Anchor:** a story responds to an artifact or another story (user).
- **Facts:** terse facts are verbatim story items; extraction proposes
  entity-field updates the review confirms or drops (user).
- **Identity:** attributed to the named contributor; strangers create
  proposed person records (attribution is a Must, §19.2; proposed keeps P4).
- **Capture kinds:** text v1; voice/audio defers to Slice 4's
  testimony-at-scale.