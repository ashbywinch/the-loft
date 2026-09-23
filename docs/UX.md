# UX Spec — The Loft (usability-requirements baseline)

The UX requirements against the PRD. Each entry is a **user outcome or
behaviour** — what the user can do, experience, or never have to do — NOT
a UI specification. Labels, buttons, placements, components, and tokens
live in `docs/UI.md` (the pattern library); the review principles are
`docs/ux-standards.md`; the record of decisions from the UX loops is
`docs/PLAN/ux-fixes-plan.md` + the decision register
(`docs/PLAN/design-decisions.md`); the mechanisms are `docs/TECHSPEC.md`.
Per documentation-structure, this doc meets every PRD requirement (no PRD
requirement is left without a UX answer), lists the journeys to
usability-test, and is enforced with the code (P6: behaviour is automated
where checkable; acceptance is re-walking the scenarios — P13).

Status: current (2026-09-22). Changes land only with user agreement and
when a re-walk stops finding the targeted problems.

## 1. The posture (PRD §1–§3, §10, non-goals)

- The reader **walks a museum, not a grid**: exploring is chronological,
  serendipitous, and bounded — never a raw wall of items, never a dead
  end (§2, G1).
- The reader **is never interpreted to**: the app arranges evidence and
  never editorialises — no mood labels, no AI summaries, no "this is when
  it went wrong" (§10; **G-the-honesty-principles**).
- The app **does not nag**: no streaks, badges, leaderboards, or push
  notifications (§10).
- Nothing the user did not endorse is ever shown as fact, and the reader
  can **always tell attested from recollection from machine-guess** — the
  display rules are §5.
- Nothing is ever destroyed by the user's hand (§3 non-goals): corrections
  supersede, never delete; the UI has no destructive operation on an
  artifact.

## 2. The personas (PRD §4)
- **Any user** can achieve their goal without reading instructions and
  without a narrator to ask; one obvious path per screen; interaction
  never depends on hover (§4, P9).
- **The Curator**: captures an item in one short ritual with minimal
  typing, repeatedly, without losing flow (G4; §7).
- **The Elders** (possibly with dementia): can be prompted through
  familiar material with big imagery and one action per screen; they are
  never a dependency — the app's running state never assumes them (G6).
- **The Young Kids** (pre-readers): can wander and find something
  interesting without reading; nothing they tap is a dead end (G1, §4).
- **The Next Generation**: can meet a person they never knew — every
  person has a bio, every item a description line, every card dated and
  attributed; nothing requires a living narrator (§4, G5).

## 3. The key flows (PRD §9 — F1–F9)

- **F1 — on-this-day**: visiting on a date, the user meets what happened
  that week in family history; the user can stop any one date, person, or
  memory from resurfacing, and the stoppage is respected without touching
  the archive.
- **F2 — find "the letters from 1964"**: the user narrows the timeline to
  a person/type/period and sees the exact letters; finding an artifact is
  ≤ 3 taps from the right door.
- **F3 — show a grandkid the courtship**: the member of the family who
  knows the story can show it as a sequence (see Show mode, §4) without
  any navigation skill in the room.
- **F4 — find everything with Grandma**: every mention of a person is
  reachable from that person — items, letters, testimonies, relationships
  — nothing the archive holds about them is un-discoverable.
- **F5 — import a letter**: one item is captured in ≤ 30 s of effort (the
  ritual, §6); the item appears in the same session.
- **F6 — family-only**: only the family reaches anything; a family member
  signs in without friction, and a guest sees nothing (accounts §15).
- **F7 — a name in a letter becomes a person**: a name the reader taps
  leads to the person's page; when the machine proposed the link it is
  marked as proposed until a family member confirms (the alias resolver).
- **F8 — the map opens at the right time**: the Places door shows the
  archive's geography for the window the user set; an unverified coordinate
  is never presented as a fact.
- **F9 — the family reviews machine suggestions**: every machine proposal
  is reviewable in the flow — kept means confirmed, dropped means gone;
  nothing is asserted unreviewed (the review seams in §7/§9/§10).

## 4. The doors and screens (PRD §8)

Each surface's outcome:

- **Home** — arriving, the user knows whose archive this is and can enter
  any door without deciding what to do next.
- **Timeline** — the user can read the whole correspondence as a timeline
  at any density (year bands, decade bands), filter by type/person/place,
  and never see an unbounded wall of cards.
- **Item lens** — the user reads a letter like the letter: pinch-zoom,
  transcription toggle with mention links, connections, and one line that
  says what this item is.
- **Cast / Family Tree** — the user can tell two same-named people apart
  (life dates on cards), tap any card to move the tree, and open a person
  from an explicit affordance — never fight a link inside a link (walks
  1–3).
- **Places** — the user can watch a life's geography move (time slider,
  person filter) and can always tell where the pins are; no pin pretends
  to precision it lacks.
- **Stories** — the user enters a theme and reads its artifacts in order,
  swipe by swipe; a story takes minutes, not an afternoon (3–8 items).
- **Museum** — the user sees an heirloom as an object: imagery and its
  provenance narrative.
- **Show mode** — on tap, the archive becomes a full-screen slideshow
  with large type and auto-advance that anyone in the room can operate;
  it starts from any person or story (F3, §4 elders).
- **Search** — the user finds *that one letter* by any word the archive
  holds, and any result renders somewhere real.
- **Curator / import** — the capture surface carries the review with it:
  the user never moves between capture and curation as separate worlds
  (§6/§9).
- **The review hub** (pipeline-stages UR2) — the user sees exactly what
  needs them: "N pages to check", "N documents need review", "N
  people/places proposed"; each opens the right surface; nothing
  human-looping lives elsewhere.

Navigation (P9, the "Back" research): the user's back press always returns
to the view they last saw (the app's back IS the system back); a user who
arrived by deep link can always go Up to a named parent; back never loses
in-progress work; opening a zoom or filter never creates a history entry.

## 5. Content and honesty surfaces (PRD §6, §9 F7/F9, §10 rulings)

- **Display order**: the artifact and its facts first; the reader's own
  testimony next; other people's testimony last (§19.7) — every entity
  page.
- A told account is read as a **Memory** with a "told by / told <date>"
  stamp — never "Story" (which reads like another scanned document).
- A **clarification** appears only on the pages it attests; a
  **reflection** only on the pages it mentions — never on the timeline.
- Dates show their **honest precision**; a year-only date is never shown
  as exact; a vague place never claims to be located (Rule P; §19 reqs
  5–7).
- A machine guess is always distinguishable at rest (proposed markers);
  an **estimated** record carries its basis in the family's own words
  ("from **X's** recollection, DATE: …"); the tree draws estimated edges
  differently (R12 of the review-chat walk).
- A statement whose source matters carries **provenance in the narrator's
  own words** ("Pete: 'Mum used to tell us this all the time'") — the
  provenance is asked, never inferred (§19 req 2, resolved 2026-09-22).
- The user can always tell what the machine is unsure of: uncertain words
  are visibly marked and every line remains correctable (VR4, §8).

## 6. Capture and multi-document intake (PRD §7, F5; MULTI-DOC-IMPORT R1–R14)

- **The ritual**: Import → 3 fields → one line of story → done; the item
  is on the timeline in the same session (F5). Nothing blocks capture;
  curation debt is deferred, never a wall.
- **Capture sessions**: capturing many items back-to-back, the user enters
  just the date each time; the app suggests date+7 for weekly letters; the
  title and story line accept speech-to-text; people/places tagging
  happens later, in batch (G4).
- **Scanners**: output from the family's scanner enters the archive with
  auto-naming; tagging happens on the phone — no filename typing ever
  (R1–R4: any arrival enters the same pipeline, in order, without the
  user re-driving it).
- **Duplicates** are detected and surfaced, never destroyed (R5): the
  user only ever chooses which copy is better, never loses one.
- **Nothing the pipeline does surprises destructively**: the user's scan
  folders are never modified; drawers/folders can be rearranged freely
  (R1, R11).
- **Handwriting is transcribed, not guessed**: the machine proposes; the
  family confirms; a draft is always marked draft (R10, P4).
- A multi-page letter **stays one letter** through the review (R9/R12):
  the reviewer sees which pages belong together and can fix the grouping.
- The tooling **runs lightly on the household laptop** while the family
  works (R14 ↔ VR16): heavy work never blocks the review.

## 7. Story capture ("Add your memory" — MEMORIES; PRD §19, §9 F10)

- **Capture rides the browse** (F10, the fireside principle): exploring
  an item, a place, a person is itself the prompt — surfaced subtly,
  never an interruption, never an interview to start. The user can start
  telling wherever a memory surfaces.
- The user's **tangents are the flow**: any detour, any length; the flow
  returns them to their starting point, and nothing they said is lost.
- An **unfinished memory is a first-class state** (P7): the user can stop
  mid-telling, and the memory joins the work queue — **the same queue
  that carries the proposed identities from imports, since resuming is
  the same conversation** (§10: identity → disposition → population) —
  visibly unfinished, to complete on another visit, resuming without
  re-asking what was already told.
- The session is a **fireside chat, not an interrogation**: the narrator's
  voice leads; nothing is forced, nothing is required (PRD §19 req 11).
- From any entity page, the user can tell their account in their own
  words, and nothing is interposed: **open-ended first** ("Anything
  else?") with no cap until the narrator taps **"That's everything"**
  (§19: capture fully, then review).
- Targeted questions are genuinely about missing detail — one at a time,
  each skippable, each with its *why*, with visible progress; "I'd rather
  not say" is always on the table.
- Before anything is stored, the narrator reviews: the assembled account
  verbatim and editable (redaction), each proposed link a keep/drop
  decision — nothing waits on a separate confirmation gate (req 1, P4).
- The narrator's identity is the signed-in identity, never typed; a name
  that matches nobody becomes a new proposed person, and the flow asks how
  they are connected (§19.2).
- When the family cites a source, the flow asks how they know — "Did she
  say that to you personally?" / "What did you see that made you think
  that?" — and records the answer verbatim as provenance (req 2, resolved).
- The flow **politely** discovers dates, presence (who was actually
  there), places ("the old ford — which one?"), dob/pronouns — nothing is
  required, and uncertainty is recorded honestly (reqs 5–10).
- Without the household server, the affordance stays and explains
  honestly that contributions are collected when it is running — the
  user's words are never silently dropped (P3, P12).

## 8. Transcription review (TRANSCRIPTION-REVIEW-PRD VR1–VR25)

- The reviewer **never hunts**: every page arrives with text, boxes, and
  draft transcription (VR1, VR14); what needs checking is visible (VR4).
- Fixing is **precise and effortless**: exactly the word changes; struck
  words render struck (VR2); every line is correctable, flags are entry
  points not limits (VR20's spirit).
- The review is **fast, never at accuracy's expense**: fluid on the
  laptop, no layout task ever blocks the flow (VR3, VR16).
- **Confirmation is the only gate** and proceeds page by page in any
  order (VR5, VR11); fully reviewed work leaves the pending pile and is
  visibly done — nothing is redone (VR12, VR13); partial work is bounded
  and resumable (VR9).
- Rotated or multi-orientation text is **read upright for validation**
  while its position stays honest (VR15, VR18); marginal notes and
  insertions survive as themselves (VR6, VR7, VR19).
- **Reorientation is the reviewer's act**, immediate and reliable — never
  an automated replay (VR10).
- The reviewer can look at the document in any order without getting lost:
  scrolling the text moves the image to match; tapping a box scrolls to
  the line (VR17, the focus model).
- Segments are faithful and **a box shows what it claims** (VR19); the
  reviewer can correct structure — split/merge/extract with the text
  visibly re-validated (VR20, VR25); an insertion point's state is never
  disguised (VR21).
- **Human work supersedes the machine**, always: nothing a re-run
  overwrites; what the reviewer validated stays validated, and
  re-structured pieces come back un-ticked honestly (VR22, S11).
- Problem detection is the gate: a page arrives nearly clean (a few
  flagged fixes) or is refused — never silently bad (VR23). The reviewer
  always knows exactly what they are checking, in what part of the letter,
  and whether structure is settled before words are judged (VR24).

## 9. The artifact import review (IMPORT-PRD — rules A–S, §2.2 stages)

- Review is the gate: proposals for people, orgs, places, dates, and
  memorabilia are presented one stage at a time; kept = confirmed,
  dropped = gone; an abandoned session stays a visible draft (2.1).
- To/from is proposed **as assumptions** with accept / pick a different
  existing entity / create a new one (Rule B, stage 1) — identity is
  never guessed (Rule A, Q1).
- A household question is asked **before** household proposals are made
  (Rule C; care-of triggers its own residency question first — Rule D).
- Coordinates are proposed for the reviewer's eyes — "near X", accept /
  adjust / drop — before anything renders on the map (Rule O); a place
  that cannot be pinned enters research, never a silent fallback (Rules
  S, R); precision comes from what was actually matched, never from the
  place's type (Rule P).
- Dates carry honest precision; the item's date is the earliest
  attestation, asked as "where did this come from?" (Rule K, Q7).
- The reviewer is never asked "is this the whole item?" (Rule I/Never):
  a missing page is simply the next scan.
- The transcript is checked and fixed **before** any proposal is built on
  it (Rule L) — a transcription is the document's words, verbatim;
  structure (tables, lines) is preserved (Rule M).
- The story line is encouraged, never blocking (Q5); the whole flow works
  on the phone with speech-to-text (§2.6 UI stage).

## 10. The ingest review chat (INGEST-PRD; F9)

- The review **reconciles first**: what the draft proposes against what
  the archive already holds — the user is never shown a phantom backlog or
  re-asked what is already placed (R1/R2 of the walk; "3 proposed links,
  26 already in the archive").
- The conversation works **one question at a time, never re-asking what
  is answered**: identity first ("Who is {name}?" with the document's
  words as evidence), then disposition ("Should {name} be recorded? The
  document says: …" → attested / a recollection with the family's words
  as the basis / left for later / excluded), then the page-filling
  population — and a claim whose identity and disposition arrived with
  the family's own words is never re-asked (§ claims/phases).
- The exact claim is always named ("The import proposes: Quentin Whitlock
  is the brother of Pearl Whitlock"); **"I don't know" is a first-class
  answer** — never fuel for the model to guess over.
- New people/places the conversation surfaces join the queue; **nothing
  mentioned is ever lost**; the walk closes only when every claim is
  resolved or explicitly excluded (§ rules: discovery/closure).
- The session is a **record**: resumable from any device later, with what
  changed summarised at the end and a next action offered (R8/R9).
- Statuses are visible and the copy names people — confirmed / estimated
  (with its basis) / proposed render differently everywhere (R12).

## 11. The portal (pipeline-stages UR1–UR3)

- The user sees every pending human item in **one place** with honest
  counts and routing: rows to check, documents to review, identities
  proposed — nothing human-looping lives outside it (UR2).
- New scans arrive without any manual step: the pages land in the
  check-rows queue, draft rows already built from the words (UR3), and the
  user decides whether any line-drawing is needed at all — an incomplete
  set merges live with the draft rows as they draw (UR1.4) — a wrong line
  is deleted and redrawn, instantly.

## 12. Engagement (PRD §10)

- Serendipity has boundaries: raw dates stay raw until the user says
  otherwise; the controls to hide/filter/exclude emotionally loaded
  material are visible and first-class (the "controls are the trust
  layer" rule).
- Presentation is warm without being editorial ("explorable, not
  editorial"); stories are snackable; the tone may be funny or sad, never
  flattened.
- The recall loop is respected: the emotionally loaded artifacts surface
  without being told twice (G3) — and are dismissible per the user's own
  dates/people/memories (F1).

## 13. Ergonomics and environment (PRD §11)

- The whole browsable archive works **offline after one visit**; the site
  keeps working when the household machine is off, and any degraded
  surface says so honestly (P3).
- Performance is UX: an artifact renders from the first meaningful paint
  on 4G; scrolling stays at frame rate; images lazy-load; nothing waits
  on one giant fetch (G6 no-bottleneck).
- Touch targets are usable with a finger; every interaction works without
  hover; focus is visible; reduced motion is honoured; movement that
  follows the user's own manipulation tracks 1:1 and synchronised
  movements ease (P18).
- A screen that renders is not a screen that works: the walkthrough
  exercises every interactive surface with the persona's real input, and
  a flow is accepted only by what the user could perceive and complete
  (P14/P15) — the repository rule for every UX change.

## 14. Legibility in 2060 (PRD §18, G5)

- The archive's own README reads for a reader in 2060 who has never seen
  the app; the app itself is self-explanatory to a stranger in ten years
  — every person a bio, every item a line, every card dated and
  attributed, no process vocabulary on any user-facing surface.

## Journeys to usability-test (the walkthrough scenarios)

Each is a fake-user walk per `skill://ux-process` with a PRD persona, on
the phone viewport; the loop converges when a re-walk finds none of the
targeted problems:

1. **A phone curator captures a letter** (F5, §6): ritual, date+7 session,
   speech-to-text, the item appears this session.
2. **An elder is shown familiar photos** (§4 elders, F3): Show mode from
   a person — no one in the room needs the app explained.
3. **A child wanders** (§4 kids): no reading required; nothing dead-ends;
   something interesting is found.
4. **A teenager's first encounter** (§4 next generation, F4): meets a
   grandparent they never knew — the tree, same-name disambiguation,
   the person's story in ≤ 3 taps.
5. **A document import is reviewed** (IMPORT-PRD §4 acceptance): stages
   walked on a real batch; transcripts checked before proposals; a
   geocoded point verified before it renders.
6. **A transcription is reviewed** (§8): flagged words fixed, anything
   else correctable, confirmed, resumable, re-runs don't overwrite.
7. **A memory is told** (§7): open-ended closure, bounded questions, the
   review as the gate, provenance asked when a source is cited.
8. **The ingest review chat** (§10): a draft already partly handled shows
   no phantom backlog; "I don't know" works; the summary and next action
   close the walk.
9. **A gathering** (§12, F3): Show mode drives it; the site works offline
   and with the home machine off.
10. **The trust ritual** (F6, PRD §18): the annual export runs end to end
    and a sensitive item never appears where it should not.
11. **A memory surfaces while browsing** (F10): a letter triggers a
    memory; the narrator follows a tangent and stops mid-telling; the
    unfinished memory appears in the work queue; a later visit resumes
    and completes it — the whole session felt like a chat, not an
    interview.

PRD §9's acceptance criteria and the feature-PRD acceptances are the
objective anchors for these walks; a walk that contradicts an acceptance
criterion is a PRD finding, not a UX opinion.

## Enforcement

- Implementation conforms to the TECH-SPEC **and** this document (the
  review bot checks PRs against it, with `docs/UI.md` for the pattern
  library and `docs/ux-standards.md` for the principles).
- A behaviour that is checkable gets an automated test (P6); the
  walkthrough proves the experience (P13) — a UX change lands only when
  the targeted confusions no longer reproduce.