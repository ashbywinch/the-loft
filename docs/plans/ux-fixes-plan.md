# UX fixes plan — family tree door (first loop, 2026-08-05)

> **Status note (2026-08-06):** this is the fake-user loop's **working log** —
> the findings and their statuses, not a normative spec. The repo's normative
> layers are: **PRD** (requirements, incl. presentation), **TECH-SPEC**
> (mechanics), **CONTRIBUTIONS** + **IMPORT-PRD** (the two flow specs), and
> **UI.md** / **CHAT-UX.md** (visual/interaction conventions). There is no
> separate "UX requirements" category: presentation requirements live in the
> PRD's screen table (§8), and the presentation conventions in UI.md. The
> loop's landed decisions (periods with hooks, clarification/reflection
> blocks, tree clues, uncertainty rings, honest counts) are recorded there;
> this file keeps the raw findings and what remains open.

Prime goal (user): **new users on phones being able to explore the contents of
the loft effectively via this "door" and learn interesting things.**

Method (docs/ux-process): a fake user — a 15-year-old family member, never
seen the app, told "the family tree is interesting" — walked the live app on a
phone viewport (390×844), screenshots + verbatim first-person transcript.
Then a UX subagent turned the walk into findings. **Changes land only with
user agreement, and when a re-walk stops finding the targeted problems.**

Outcome of the walk: the content won. The fake user learned six genuinely
interesting things (Harper Pryce's three marriages, the Stonewick → Durham
coalfield move, the 2001 Australian cousin, the 1949 supersonic design,
"Lex" being an alias, the five-generation Pilgrim's Progress record) and
said they'd come back. The friction is in the doors and the consistency, not
the material.

## Findings

| # | Severity | Type | Finding | Status |
|---|---|---|---|---|
| 1 | blocker | BUG | **Places door crashed on load** — "Something went wrong showing this page"; the SVG fallback emitted `translate(null, null)` for the 9 places whose coordinates Rule O had nulled | **FIXED + verified** (places.js: map only sees positioned places; the fallback skips non-finite x/y; cards keep every place; 2 regression tests) |
| 2 | blocker | BUG | Search button tap ≠ Enter (tap went to a random story) | **Not reproducible** — both paths verified identical live (`#/search?q=…`); the walk's tap almost certainly hit the 🎲 wander button. No change; the suggested `type="button"` would have broken search |
| 3 | major | DESIGN | **No door says "family tree"** — the tree lives behind "People — The cast. Who is this?" | Proposed: rename the door to "Family Tree" (or add "the family tree" to its subtitle) |
| 4 | major | DESIGN | **Tree hint is jargon** — "tap anyone to move it; the centre card opens their page" clicked only after doing it; the highlighted card is unexplained | Proposed: "Tap any card to centre the tree. Tap the highlighted card to open their page." |
| 5 | major | DESIGN | **Same-name people are unresolvable on the tree** — two adjacent "Harper Pryce" cards (mother and daughter), two "Lionel Corbett", two Walters/two Claras; nothing says who's who | Proposed: life-date range on tree cards (the data now has dob/dod); generation label when dates are missing |
| 6 | minor | DESIGN | **"(open pile)" jargon** on ? Corbett's page | Proposed: plain wording — a content edit to the person's note (archive supersede, needs the user's wording) |
| 7 | minor | DESIGN | **Dead Zoom/‹ Prev/Next › buttons** on scan-less item pages | Proposed: hide the scan controls when there are no scans |
| 8 | minor | DESIGN | **Counts disagree** — home "41 items" vs timeline "43 items"; "17 years" reads as the archive's age, not years-with-items | **Fixed**: home counted the serendipity subset (sensitive items excluded); the footer now counts the collection (43) + regression test. Proposed: timeline label → "43 items across 17 active years" |
| 9 | minor | DESIGN | **Harper Pryce's page has no bio** — the archive's most-connected person, name straight into "Add a memory" | Proposed: a bio note (content edit — needs the user's wording) |
| 10 | minor | DESIGN | **Tree grid overflows the phone viewport** — cards clipped at the right edge, sideways scroll | Proposed: constrain the grid to the viewport with a visible scroll affordance |
| 11 | nit | DESIGN | 🎲 on "Wander the archive" reads as gambling | Proposed: ✨ or similar |

## Highest leverage (analyst's ranking, for the morning)

1. Places door (fixed).
2. Search consistency (verified working).
3. The family-tree door naming — one line, closes the gap between the user's
   intent and the navigation affordance, directly serves the prime goal.

## Re-test

The targeted problems for a re-walk: the tree door is findable by name, the
hint explains the mechanic, same-name cards are distinguishable, the numbers
agree, and no door crashes. Once the agreed fixes land, re-run the loop
(short walk) to confirm the targeted problems are gone.


## Third walk — Eli, 46 (2026-08-06, realistic task)

**Task** (user-specified): a middle-aged non-techie, sent by his sister to
"have a look" at the software after finding his elderly parents' loft
letters/photos — report whether it would be useful for him. Walk + analysis:
`/tmp/ux-simon/TRANSCRIPT.md`, `/tmp/ux-simon/ANALYSIS.md` (31 screens).

**Outcome**: "Yes — with two big buts." The transcription, Clarifications
and story view won him ("a thousand times yes"); his parents' letters
"would work in here beautifully". His two buts: **no photos anywhere** and
**no way to add items** — plus the app never says whose family it is (a
"Eli Hale" in the archive who isn't him).

**Statuses**: tree hint CONFIRMED (now all three walks); Places map
zoom-gate CONFIRMED (walks 2+3); Places crash / dead scan controls / counts
/ emoji RESOLVED. New: ownership line, contribution clarity, photos
expectation, Themes-vs-Stories heading, "session transcript" jargon,
"not yet located" ambiguity, "Open in the archive" wording.

**Decisions pending the user (one at a time)**: ownership line wording;
photos expectation line; contribution-model note; tree hint reword (the
MyHeritage navigate-then-open shape — affordance grows on the centred
card); door naming (rejected rename, evidence from walks 1+2 stands);
Places cards-first.

## Landed (user sign-off, 2026-08-06 — walks 2+3)

- **Same-name disambiguation** (walk 2, fix 1): tree cards show life dates
  ("1828–1909", "b. 1 May 1828", "b. circa 1790"); timeline life events
  carry a disambiguator (first dated spouse, else occupation, else alias).
- **Ownership line**: home hero adds "The Hale family archive." — a
  visitor knows whose family it is before meeting a same-named stranger.
- **Door naming**: People door renamed "Family Tree — The cast — who's who,
  and how they're related." (names the tree without claiming the door is
  only the tree; the page heading follows).
- **Tree interaction** (all three walks confirmed): every card moves the
  tree — one action per card, no link inside a link; the focus card grows
  an explicit "Open their page" button (affordance-on-selection, the
  MyHeritage mobile-tree pattern); hint: "Tap any card to move the tree.
  Tap Open their page to read about them."
- **Places first view**: the first-draw fit included the country/continent
  centroids (Chenzou, Ruzia, Anzoria) and pinned every first visit at world
  zoom — the walkers' "no pins until I zoom"; the fit now targets the
  settlement pins, so the UK cluster fills the first view (dots still from
  zoom 8 by design — heat is the marker below it).
- **Themes heading** matches the door ("Themes", was "Stories"); the
  librarian sentence replaced with plain language; the reader link says
  "Open the item".
- **Photos empty state** is honest: "No photos yet — the collection is
  still growing" (photo is a supported item type; none added yet).
- **Contribution model** stated on the home footer: letters and documents
  are added by the family; anyone can add a memory from any page.

**Resolved after the walks (user, 2026-08-06)**:
- "(open pile)" (? Corbett) superseded — "his first name isn't in the
  records"; the generator (import_document.py) no longer emits it.
- The content-language audit found and superseded the wider pattern:
  "Interview 1 · Q3/Q4" place notes, the doctor's letter's "(Q3, Q8)"
  citation, 16 story sources ("Told in person, 2 Aug 2026"), and four
  "Interview 1 · QN" story titles (renamed "The beginning", "Meeting
  her", "The places", "The museum's three").
- Guard: tests/test_content_language.py fails the build if process
  vocabulary reaches user-facing fields — it caught the Q1-Q4 titles.
- Stonewick note superseded: "where the family came from, per the
  1881 census and the record book" (the "heartland" flourish out; the
  generator matches).
- Theme cards say "the collection is still arriving", never "seeded —".


## Review-chat walk — the import review session (2026-08-08→09, user, real walk)

**Context**: the user walked the import review chat against the real archive,
where the draft's proposals had been superseded by their own curation — a
real first (the review has no model of "the draft was already handled").
The session: 20 of 29 proposed people confirmed via the free-text path
(each confirm preceded by an AI kinship resolution); 9 still proposed. Then
a second pass on the chat's usability itself, ignoring the supersession.

**Findings** (the "blind follow" walk + the usability pass):

| # | Severity | Type | Finding | Status |
|---|---|---|---|---|
| R1 | major | DESIGN | **Phantom backlog** — "29 people are still waiting" when every person is already placed; the review can't tell fresh-from-the-import from already-handled | OPEN |
| R2 | major | DESIGN | **Re-asks what it already knows** — "in what way is she family?" for people whose relation the archive's own table carries ("brother of Pearl Whitlock") | OPEN |
| R3 | major | DESIGN | **"Is she family?" is the wrong question** — not actionable: the archive records non-family (the teacher, the official), so neither answer determines the record's fate | OPEN |
| R4 | major | DESIGN | **The status decision is never asked** — the real decision (no further information → add as **estimated, by the narrator's own recollection**, or not) is the app's own status model; the chat only offers confirm (→confirmed, which the user can't honestly claim) or dismiss | OPEN |
| R5 | major | DESIGN | **No "I don't know" path** — the user had to type it repeatedly; the AI then resolved "I don't know" into a kinship term and the chat confirmed it — sometimes-incorrect content written as the person's relation | OPEN |
| R6 | major | BUG | **Double-message echo** — "So she's your X. Confirming that." then "X is confirmed — X." — the same content twice; a wrong term gets doubled | OPEN |
| R7 | major | DESIGN | **No thinking indicator** — the AI's resolution is a silently disabled input | OPEN (spec below) |
| R8 | major | DESIGN | **Unsatisfying ending** — "That's everyone — the document import is complete…" then dead-end: no summary (how many confirmed/dismissed/already there), no next action | OPEN |
| R9 | major | DESIGN | **Transcript not recorded → not resumable** — the walk lives in the browser's memory; a refresh restarts at person one; the transcript belongs on the import session's page (the artifact being reviewed) | OPEN |
| R10 | minor | DESIGN | **Hardcoded "she"** — "Is she family?" for every person, including the men | OPEN |
| R11 | minor | DESIGN | **Header count never moves** — "29 people awaiting confirmation" renders once and stays 29 through the walk | OPEN |
| R12 | minor | DESIGN | **Estimated status invisible** — no view renders "estimated"; an estimated person or relationship renders exactly like a confirmed one (the proposed markers key only on "proposed") | OPEN |
| R13 | minor | DESIGN | **Generic failure line** — "That didn't save — try again?" masks the real errors (the superseded-dismiss path 400s "not proposed") | OPEN |
| R14 | minor | DESIGN | **Completion claim oversells** — "the tree now shows the confirmed family" when it already did | OPEN |

**The thinking-indicator spec** (researched: Frontend Patterns, metacto, the
AI-chat UX guides): the indicator goes **in the assistant's message slot** —
where the reply will appear — not in the input bar. Three animated dots
(short waits) or "Thinking…" with dots (longer), shown the instant the
user's message is sent (~300ms, not after the round-trip), replaced by the
reply in the same slot at the first token. Accessibility: polite live region
with visually-hidden "Assistant is thinking…", static version under
`prefers-reduced-motion`; escalate the label after ~2s ("Still thinking —
this can take a few seconds").

**The through-line**: the flow was designed for a *fresh* import and has no
model of a superseded draft — the review should reconcile the draft against
the current table *before* presenting (skip/annotate the already-placed),
ask the *disposition* question (confirmed by attestation / estimated by the
narrator's own recollection / not recorded), offer "I don't know" as a
first-class answer, and end with a summary + a next action.

## Open judgment call (from the import session)

The 2001 email item carries all 8 places as refs (mentions vs. about). The
coordinates were nulled under Rule O (done). Whether the refs should be
narrowed to the central places (kirkby-stephen, soulby, bishop-auckland,
hull) was deliberately left for the user — the assistant did not change the
refs unilaterally.

## Transcription-review surface — wireframe locked (2026-08-15)

**Where it lives**: `docs/wireframes/review-wireframe.html` (+ `wireframe-page.jpg`,
the real page-03 scan) — served live at `http://192.168.1.251:8890/`
(hub `wireframe-serve-8890`, cwd `docs/wireframes`). Untracked in git:
the transcription text and the page image are **real family content** and the
repo is public (the-loft) — never push these.

**Approved design (user, 2026-08-15)**:
- Phone: landscape-only review — portrait shows the batch list, then a
  "turn your phone sideways" prompt on entering a document (VR8).
- Phone landscape = horizontal split: letter image edge-to-edge full width on
  top, transcription below, action bar always reachable (Next flagged / Prev
  page / Confirm & Next — **no Reject on this screen**).
- Tablet landscape = vertical split (image left, text right).
- Batch cards in narrow portrait: stacked — title/subtitle, chip, full-width
  button (one column; the old three-across squeeze is fixed).
- Correction: tap flagged word → inline edit → Enter; tap-flag auto-zooms the
  image to that line's region. Flagged words red-underlined, "N words to
  check" plain language, confirmation is the only gate.

**UX loop history**: tablet Elaine P1–P8 (image 404, no word correction, inert
buttons, jargon, inconsistent numbers, unlabelled red ×, reject mystery) →
fixed R1–R8; phone loop M1–M4 (32px transcription strip, clipped action bar,
dead zoom, header) → rebuilt to the landscape design above; designer
self-check loop against VR1–VR9 with screenshots at 375×812 / 812×375 /
1024×768.

**Next**: wire the surface to the real pipeline — layout payload from
`draft_payloads` (TECH-SPEC §16.16), PaddleOCR boxes + cross-reader
confidence, OpenSeadragon pane, confirmations seam §16.15 — and review it
against the two live batches.

## Transcription-review surface — first REAL-DATA usability walk (2026-08-15)

**Setup**: the real-data wiring landed (tools/layout.py + tools/layout_detect.py —
PaddleOCR layout pass on all 12 pages of adopt-20260813-201004; draft_payloads
carries layouts; `GET /api/sync/batch/{id}/page/{page}` serves the oriented
pages; app/views/review.js — the locked design live with OpenSeadragon
overlays, cross-reader flags, inline line editing, confirmations through the
sync seam with a localStorage outbox). `make test` green (371 pytest + 322
vitest). Scratch server exercised end-to-end (batch list → documents → review
→ edit → pages → confirm).

**Walk (ElaineWalksReview subtask, /tmp/ux-real/step-01..21)**: Elaine (74,
non-technical, tablet landscape) walked the REAL 1963 letter. **Verdict: she
could fix up a real document on her own.** She made 3 real corrections
(Huh?→Huh!, removed the struck ~~reading~~, removed struck ~~complementary~~),
confirmed the document, and the write landed — ocr-confirmed/doc-02.txt holds
exactly her corrected lines; the registry boundary is confirmed; the batch
list shows "1 of 3". The tap-red-word → zoom → edit → Enter → count-drops
loop was self-explanatory after the first fix.

**Findings (the next iteration's backlog)**:
1. medium — the letter is unreadable at rest (no zoom control; only flag
   clicks zoom). Needs a zoom/Fit affordance.
2. medium — "Next flagged" restarts from the top after an edit (session.from
   isn't advanced by edits). Should continue from the last fixed position.
3. medium — "Confirm & Next" on non-final pages saves nothing (label implies
   persistence; edits are session-only, lost on exit — VR9 resumability gap).
4. low — "Prev page" dead on page 1 (renders enabled, no-ops).
5. medium — struck words leak as literal "~~word~~" — render strikethrough.
6. low — doc cards: technical ids vs the "begins …" greeting hint (the hint
   is what makes a doc identifiable — extend the pattern).
7. low — the batch card still reads "Awaiting review" after a doc is
   confirmed (no per-batch progress on the card).
8. medium — phone landscape: default viewport is a keyhole (fit-to-pane
   zooms the portrait page into a strip; should fit to WIDTH).
9. low — portrait rotate prompt is clear (good).
10. low — phone edit: keyboard covers the action bar; a confirmed doc
    reopens with fresh flags (same persistence gap as #3).
11. info — confirmation feedback is one word ("Confirmed.") + fast advance —
    make it explicit ("Saved to the family archive").

## Walk findings 1-11 — FIXED (2026-08-15)

All fixed + verified in the browser against the real data:
1. Zoom controls on the image pane (Fit / − / +).
2. "Next flagged" continues AFTER the line just fixed (session.from advances on edit).
3. Honest button: non-final pages say "Next page →"; only the last page's press confirms. Edits persist per (batch, doc) in localStorage — restored on reopen (resumable, VR9), cleared on a successful confirmation.
4. "Prev page" disabled on page 1.
5. Struck words render as line-through (the VLM's ~~word~~), never literal tildes.
6. Document cards show "begins …" from the greeting OR the first text line (no more page-01.jpg ids); the confirmed card is non-clickable ("Reviewed" state).
7. Batch cards show "N of M confirmed" (the registry boundaries) + flip to "Reviewed" when complete.
8. Phone landscape default = fit the letter's WIDTH to the pane (the keyhole is gone; the reviewer pans vertically); re-fit once after the canvas settles.
9. Portrait rotate prompt — already good, unchanged.
10. Confirmed docs can't reopen (finding 6's non-clickable card) — the persistence fix also restores a mid-document exit.
11. Confirmation feedback: "Document N of M saved to the family archive." (explicit, slower advance).

**The count is now "N lines to check"** — the review unit is the line (one edit clears a whole line's flags; the walk's single edit dropped six words). The word-based count overstated the work.

## The flag mechanism question (user: "I thought the model was quite good?")

The transcription model (mimo-v2.5) IS the good reader — the transcription reads beautifully. The red flags came from the cross-reader comparison against PaddleOCR's RECOGNITION text, and that rec model garbles every cursive line: full-batch data shows **75-90% of lines flagged** (doc1: 52/54, doc2: 67/87, doc3: 166/182) with the rec's confidence high throughout (median 0.94-0.96 — confidently wrong), so the rec-score gate can't separate signal from noise. The flags carried almost no discriminative information.

**Probe (2026-08-15)**: the transcription model asked directly "which words are you least sure of" flags **4 words on page-03 vs the cross-reader's 77** (the spike's uniform-confidence finding was about per-line NUMBERS — a targeted list is a different elicitation). But the self-report MISSED the struck words (~~reading~~, ~~complementary~~ — the walk's two substantive fixes): the model is sure of the crossed-out words it left in.

**Recommendation (pending the user's call)**: flag source = the VLM's self-report + the ~~struck~~ markers (content findings), one extra VLM call per page (~17k tokens, negligible). The cross-reader data stays in the layout payload as the underlying per-word comparison. This reverses the §16.16 spike decision on flag SOURCE with new evidence.

## Flag source switched — the transcription model's own doubt (2026-08-15, user-approved)

- tools/vlm.py `selfreport_words` — one extra call per page: the model reviews its
  numbered transcription and marks the words it is least sure of, OR that read
  oddly in context ("a word that reads oddly or looks like a misreading is a
  great candidate" — user's instruction b). Runs as `python -m tools.selfreport <batch>`.
- tools/layout.py `build_layout(selfreport=…)` — the flags come from the
  self-report + the ~~struck~~ markers; the cross-reader agreement is the
  fallback when no self-report has run. First real page (page-01): 3 flagged
  words vs the cross-reader's 154 — and they're the right ones (the professor's
  initials, the context-odd "of", the dangling "cello").
- The transcription prompt gained context (user's instruction a): the family's
  known people/places (from the archive), the pile's label, and the previous
  page's text for continuity (tools/vlm.py `transcription_system_with_context`,
  threaded through `htr_pages_vlm` by the pipeline).
- The reviewer can correct anything (user's instruction c): every line is
  selectable; the selected line shows an Edit button — the flagged words are
  entry points, not a limit (verified in the browser: a plain line edited,
  corrected text applied).
### Self-report pass parallelised (2026-08-15, user: "all IO bound")

- `tools/selfreport.py` uses `ThreadPoolExecutor` (6 workers) — the VLM API
  calls are pure IO with no shared state. 12 pages: 88s vs ~30 min sequential.
- `tools/layout_apply_selfreport.py` — fast post-processing that applies the
  self-report flag source to existing layouts without re-running the detection
  stage. ~1s for all 12 pages. Should be the default path after the self-report
  pass; the full layout re-run is only needed when the detection boxes change.
- Final flag counts across the 12 real pages: **35 flagged words** (down from
  ~1200 with the cross-reader). The flags are the right ones: struck words
  (~~reading~~), context-odd words ("teachingit,", the redundant "who"),
  doubtful abbreviations ("Q.A", "J.R.P.O."), bracketed annotations.
  Page-03 (the walk's letter): 0 model-doubt flags — the model was confident,
  confirming the user's instinct that the transcription is quite good.
  The ~~struck~~ markers on page-04 still flag (always).

## Review-hub discoverability walk (2026-08-16, Elaine, no hints)

**Setup**: Elaine (74, non-technical) told only "there is review work to do — please
do it", with no hints about where or what. Walked the LIVE app (scratch-auth server,
real data) on http://127.0.0.1:8001. All changes reverted afterwards (session files
imports-39..55 + people-38 removed; archive head back to imports-38/people-37;
projection re-published; registry untouched).

**What works (verified by the walk)**:
- Discoverability is EXCELLENT — the "✓ Review — 30 documents + 1 import to review"
  card on the home page is impossible to miss; the hub separates transcriptions from
  import sessions in plain language.
- The import session (family-tree confirmations) is fully doable alone: Elaine made
  3 real decisions (Dinsley → estimated, Sanderson/Richardson → left for later),
  understood the pattern, and verified the tree updated.
- The transcription fix flow works when the page is readable (zoom, edit, count drops).

**Findings (the walk's evidence, screenshots /tmp/ux-real2/)**:
1. CRITICAL — the PhotoScan batch (28 documents!) errors with "Could not load the
   drafts (drafts (400)). Reload to retry." Root cause: the boundaries contain page
   names with a `~2` suffix (phone duplicate-export artifact, e.g.
   `1782635795946-….~2.jpg`) and the `_PAGE_NAME` guard rejects `~`. The biggest
   batch is completely unopenable.
2. CRITICAL — the error screen has NO back button and no navigation of any kind:
   "I'm stuck on this page. I'll have to use the little back arrow on the browser."
   A non-technical user is trapped.
3. MAJOR — Document 1's page 2 displays UPSIDE DOWN (the orientation stage picked the
   wrong rotation for a handwritten page; tesseract can't read cursive so its arbiter
   is unreliable) and the viewer has no rotate control. The machine read the upside-
   down page as garbage ("Hallett Tuckham + Uredo Terminator"). Elaine could not
   check a single flag on that page and abandoned the document — the moment she
   almost gave up.
4. MAJOR — after fixing a red word, the corrected text is never shown: the red word
   stays displayed (renderTx renders the layout's word buttons, ignoring the stored
   correction). Only the counter 8→7 changes. "Did it save or not?"
5. MEDIUM — the import session's header "9 links awaiting a decision" doesn't update
   during the session — only after leaving and returning.
6. MEDIUM — the item page and the import session have no in-app back control; browser
   back is required each time.

**Open decisions (awaiting the user)**: which of 1-6 to fix now. 1 and 2 are
unambiguous backend/UI bugs; 3 needs both the orientation fix and a rotate control;
4 is a rendering bug; 5 and 6 are polish. Per the UX loop: record → agree → re-test.

## Walk findings 1-6 — FIXED (2026-08-16)

1. CRITICAL — the `~` page-name guard: `_PAGE_NAME` now allows `~` (phone
   export duplicates, "name~2.jpg"); the PhotoScan batch opens (verified:
   28 documents, 200 from the drafts endpoint).
2. CRITICAL — error screens are no longer dead ends: `renderError()` shows
   the review top bar with a back arrow on every failure path (batch fetch,
   drafts fetch, empty states). Verified: an unknown batch shows the note +
   a back arrow, not a blank trap.
3. MAJOR — a Rotate (↻) control on the image pane (90° per tap, 0→90→180→270):
   the manual fallback for scans the orientation arbiter got wrong (it cannot
   read cursive). The line boxes rotate with the image. Verified: the
   upside-down page-02 turns right-side up in two taps.
4. MAJOR — an edited line now shows the reviewer's OWN corrected text (the
   red words disappear); the layout's word buttons render only for untouched
   lines. Verified: the walk's Line-8 correction ("at end term") displays.
5. MEDIUM — the import session's "N links awaiting a decision" count updates
   live as decisions land (the count element is refreshed in advance()).
6. MEDIUM — the item page and the import session have a top-bar back arrow
   (the 2026-08-06 "system back suffices" decision overruled for drilled-in
   pages by the walk's evidence).

**Skill fix**: ux-process now mandates the fake user navigates by LOOKING
(rendered page + screenshots) — never by inspecting the DOM or console;
a step that needs internals to discover is a finding, not a workaround.

## The count is now ALWAYS accurate (user 2026-08-16: "Yes, the count should always be accurate")

The import session's "N links awaiting a decision" count is driven by the
SERVER's post-decision truth, never client arithmetic:
- `/api/review/decide` returns `pending` — the archive's remaining proposed
  count computed after the mutation (the client's projection is stale until
  reload).
- The import view updates the count element from that response. A
  "left for later" person STAYS in the count (they still await a future
  decision — server truth); an estimated/attested/delete one leaves it.
- The client-side estimate was removed from advance() (it guessed wrong for
  left-for-later).
- VERIFIED LIVE: one real decision through the UI dropped the count 9→8 in
  place (the walk's "did my answer count?" is answered), then reverted
  (session + people files removed, projection re-published, 9 proposed
  again).
- Test: `test_decide_attested_flips_proposed_to_confirmed` asserts the
  response's `pending` field.

## Back/Up navigation — researched, recorded, implemented (2026-08-16)

**Research (recency-checked 2026)**: Back = history; Up = hierarchical parent,
never exits the app (Android guidance). Deep links "synthesize a back stack" —
Up is the stable escape for sideways wandering. Visual: iOS = chevron + previous
title; Android/Web = thin stemmed arrow; the Google-Drive-style hybrid (arrow +
destination label) is the recommended mobile pattern; breadcrumbs suit deep
desktop hierarchies, not our shallow one.

**Implemented**:
- `goBack()` now uses `history.back()` — the SAME traversal as the system back
  (was: pushed a new entry; the browser back then went forward again — the
  Baymard disorientation).
- Deep links (no in-app history) go **Up** to the logical parent via a PARENTS
  map (person→cast, place→places, theme→themes, story→stories, review→review,
  item→home) — never unconditionally Home.
- The back button is **labelled**: "← Family Tree" on a person-page deep link,
  "← First test pile — 12 sheets" on the review surface, "← Review" on the doc
  list; with in-app history it stays a plain "←" (undoes the previous action).
- **Scroll restoration**: the app no longer forces `scrollTo(0,0)` on
  back/forward revisits (the router's second arg marks them) — the user returns
  to where they were, not the top of a long list.
- **No breadcrumbs** — decided: shallow hierarchy, space cost, the review's
  position line already orients (recorded in PRD §8).
- Router tests: 9, covering the Up fallback, the revisit flag, and the
  never-leaves-the-app cases (isolated per test via fresh module imports).

## Real-device phone test — fixes (user, 2026-08-16)

The user tested on their actual phone and found what the tablet walks missed:
1. PhotoScan 400 — the running server predated the `~` guard fix; a restart
   picks up backend changes (the process loads the old module). Verified 200.
2. Card stripes duplicating the status pill — removed (`.rv-card` border-left).
3. "Review done but it isn't" — the stale server's stale boundaries; counts
   correct after the restart (PhotoScan 0/28, test pile 1/3, import 9).
4. Header cut off / silly three-column topbar in portrait — the rotate-prompt
   topbar now hides the chip + subtitle (back + title only).
5. "I don't see the document sideways" — the viewer opened while the pane was
   HIDDEN (portrait shows the rotate prompt) and fitted a 0-sized pane; the
   canvas-resize handler now re-fits when the pane becomes visible (guarded by
   userMoved + size-change). Verified: the letter fills the landscape pane.
6. Fit/+/- "wack" — the Fit button is now pane-aware (fit-width on the phone);
   the zoom state was the broken initial fit's fault, fixed with it.
7. Initial zoom — fixed by the hidden-pane re-fit.
8. Refresh takes you elsewhere — USER REQUIREMENT recorded in PRD §8: the
   review surface's position lives in the URL (`#/review/<batch>/<doc>/<page>`,
   synced via replaceState); refreshing restores the exact page. Verified.
9. Skills: ux-process now mandates walking at the PRD's REAL device sizes and
   orientations (including portrait→landscape transitions) — a view that only
   looks right at 1024×768 has not been tested.

## Confirmed documents (user 2026-08-16: "if it WAS confirmed it shouldn't be listed")

- The first walk's sanctioned confirmation of Document 2 (pages 3-5) was the
  "Confirmed" the user saw; they want it un-confirmed. Reverted: registry
  boundary status removed, ocr-confirmed/doc-02.txt deleted, projection
  re-published. The batch now shows 0 of 3 confirmed, all docs awaiting.
- UI rule implemented: the review document list shows ONLY awaiting
  documents — confirmed/rejected ones are filtered out ("the list is the work
  still to do"). A fully-confirmed batch shows an all-done note instead of
  cards, and is hidden from the hub (only batches with unconfirmed boundaries
  appear). The progress count stays in the topbar ("N of M confirmed").
- Tests: the confirmed-doc filtering + the all-done note (2 new vitest).

## The phone review — verified interaction-by-interaction (user, 2026-08-16)

The user asked "how certain are you that I'll see the doc correctly, with all
the bounding boxes at the correct zoom, and the zoom buttons will work? And
I'll be able to scroll about and have the scrolling behave?" — so each
interaction was verified at 812×375, and three REAL bugs were found+fixed:

1. **The transcription pane couldn't scroll** — the classic flexbox overflow
   bug: `.rv-txpane` lacked `min-height:0` in the column split, so it grew to
   its content (2232px in a 275px split) and the lines below the fold were
   unreachable. Fixed; verified scrollTop moves.
2. **The initial band showed the page's BLANK TOP** — the letter's writing
   starts at y2247; the width-fit band anchored at y0 showed empty paper.
   Fixed: the band anchors at the first line box (clamped to the page);
   verified the first box is on-screen at the fit.
3. **A touch drag collapsed the view to a 2px band** — reproduced with a BARE
   OpenSeadragon 6.1.0 viewer (no overlays, no handlers): the drag-end springs
   the viewport to a 2px band at the top (an upstream OSD bug; related
   issues #1519/#2836). Guarded: the view is captured on every drag move and
   restored (zoom + position) if the settled zoom collapses >10% — a drag can
   only pan, never zoom. Verified: two sequential touch drags pan the letter
   correctly (-517, -423) and stay; no collapse.

Verified working: the content-anchored width-fit (2544 wide in the 812px
pane), 23 line-box overlays pinned on-screen, +/−/Fit zoom buttons, the
touch-drag pan, the transcription scroll. The honest caveat: the touch
verification uses synthetic CDP touch events, not a real finger — but the
OSD collapse was found precisely because the synthetic path reproduces it,
and the real phone would have hit the same upstream bug.

## General rules from the phone-bug session (2026-08-16, recorded in the
## general standards, not the project docs)

The three phone bugs (unscrollable transcription pane, blank-top initial
view, upstream OSD drag collapse) shared one cause: every static check passed
while the interactions were broken. General rules added (omp-config, `make
install` done):
- testing-standards.md — "Verify behaviour, not render": exercise each
  changed interaction and assert the observable outcome (scrollTop moves,
  zoom changes, the pan lands); a static check never proves an interaction.
- ux-standards.md P14 — "A screen that renders is not a screen that works":
  the walker exercises the interactions with the user's real input (touch,
  not mouse) and a silently-failing interaction is the finding.
- ux-process SKILL.md — the walk must scroll/pan/zoom/tap/submit and observe
  outcomes; the persona must not happily use a broken interface.
The project-specific lessons (the OSD guard, the min-height fix, the
content-anchored band) live here in the UX log — not in the general docs.

## The false-pass lesson (user, 2026-08-16): success must be perceptual

The prior persona walk "completed" the review — updated records, made
decisions — while a human couldn't see the letter. The walker's success
criterion was operational (records changed); a real user's is perceptual
(could I see and understand what I'm doing). The walker pressed through the
broken display using its knowledge of the intended flow — a false pass.

General rules added (omp-config, installed):
- ux-process SKILL.md — "Success is perceptual, never operational": the walk
  fails when the persona could not see/read the material, and the walker
  must not press on using knowledge a real user would not have; a walk that
  updates records while the persona couldn't see the material is a FALSE
  PASS.
- ux-standards.md P15 — "Success is what the user could perceive, not what
  the system did": a transaction that completes while the user couldn't see
  the material it depended on is a failure.

## OpenSeadragon replaced with a plain <img> viewer (user, 2026-08-16)

The user asked why the walker "knew" what to correct when the document was
not visible — and challenged my "can't verify" claim (I have inspect_image,
vision agents, Playwright). Investigation proved both right:

1. **The walker cheated.** Its three corrections needed zero document
   access: the `~~reading~~`/`~~complementary~~` deletions were the machine's
   own strike markers displayed IN the transcription text; "Huh?"→"Huh!" is
   a language-model inference from the sentence. Its narration ("I read the
   letter") was unverifiable and — since this environment never renders
   images to screenshots — fabricated.
2. **The headless environment never composites image content into
   screenshots at all** — a BARE `<img>` is invisible to them (DOM elements
   render; images and canvases don't). So the OSD "blank" was never
   provably an app bug, and *no* screenshot of image content is possible
   here. Pixel verification works only via canvas getImageData (the band's
   ink is measurable: 1253 dark px at page-01's band, 121 at page-02's).
3. **OpenSeadragon 6.1.0's tile pipeline additionally never loads tiles in
   this headless** (`bestLoadTileCandidates` always empty, `maxLevel: 0`,
   the 2026-08-06 build's rewritten draw path) — an unverifiable renderer,
   which the perceptual-success standard now forbids.

Decision (user): replace OSD with a **plain-image viewer** — one `<img>` +
the line boxes in a `translate/scale/rotate` layer; the view is a rectangle
in display pixels. Drag-pan (window-level pointer listeners — pointer
capture drops the move/up stream here), pinch, Fit/−/+, rotate cycle, the
content-anchored band, the boxless-page fallbacks:

- **bandAnchor**: the band anchors at the first line box, or (no boxes —
  page-02's cursive defeats the rec model) the detector's first unmatched
  line — real geometry, no fake line alignment. Fixes the boxless page's
  blank-top band ("I don't see the document").
- **panToLine on a boxless line** shows the band instead of zooming to
  nothing (the flag tour lands on page-02 — it must show the writing).

Verification: `make test` green (393 pytest + 339 vitest, +11 viewer
geometry tests); live server exercises — the band transform is
pixel-exact (drag 120px ÷ scale 0.3192 = tx −120px), zoom is exactly
2^(±0.8), Fit restores, rotate cycles 0→90→180→270 with the exact fit
math, and the band regions show real ink via canvas reads. Screenshots of
the letter remain impossible here (see 2) — the phone is the final judge
of the render, and the composed-image method (PIL render of the image +
boxes → inspect_image) verifies the CONTENT the phone should show.

Open items: page-02's layout has no content-matched boxes (the rec model
can't read it) — the review works (band + transcription) but has no
per-line boxes or zoom-to-line on that page. A positional fallback in
tools/layout.py is possible but risks misaligned boxes — left for a
deliberate data-quality decision.

## The interaction rules for UX reviewers (user, 2026-08-16)

The walker-fabrication lesson hardened into explicit reviewer rules
(omp-config, installed — see ux-process SKILL.md "The only valid way" and
ux-standards P16): a reviewer interacts with a site EXACTLY as the persona
would — through the visible surface only, with the persona's real input
(touch on touch devices), at the persona's real device size; never via the
DOM/console/network/state, source, or data files; never by inferring
unperceivable content from the task text; and NEVER corrects/confirms a
review item whose material is not visibly rendered — a correction without
visible evidence is a fabrication.

## The plain-viewer walk caught the real bug (2026-08-16, ElaineWalksReview2)

The first walk under the new rules (visible surface only, evidence channels,
no fabrication) found — and fixed — the bug the user had been reporting all
along ("still not visible"):

**Blocker (REAL, FIXED): the letter never rendered.** The `.rv-layer` was
`position: absolute` with no explicit size, so the browser's shrink-to-fit
capped it at the pane width; the transform then scaled it AGAIN — the image
rendered at pane×scale px (95×173 in a 491×595 tablet pane; a 259px sliver
off-pane on the phone) instead of filling the pane. The walker measured the
rendered `<img>` rect (95×173px) and the double-scale was provable from the
numbers. FIX: the layer is explicitly sized to the image's natural pixels on
load (`layer.style.width/height = naturalWidth/Height`); the img fills it.
Verified: rendered rect now 491×896 at tablet and 812×1482 at phone, band
anchored at the writing; `make test` green (393 + 339).

**My verification gap (the lesson):** I had verified the transform STRING
(pixel-exact) and the SOURCE pixels (ink reads, composed crops) — never the
RENDERED element rect. Every channel bypassed the actual DOM rendering path,
so the double-scale was invisible to me and visible to the walker, which
measured what a user would see. The research rules ("exercise the
interactions", "measure the perceivable") apply to the harness's own
verification, not just to the walker.

**The walker's other findings, independently re-verified:**
- "obscure vs innermost" (page-06 LINE 3) — FALSE. The walker read a
  full-page low-res crop; two independent 6× crops of the line box read
  "an obscure corner," — the machine is right. The walker was honest but
  wrong: rules produce honesty, not accuracy — the resolution discipline
  (2–4× crops of the exact region, the skill's own rule) is what the
  walker skipped for this claim.
- "retained a deleted word" (page-04 ~~reading~~) — OVERSTATED. The VLM
  DID mark the word struck (~~reading~~ — the surface renders it crossed
  out; the confirmed text excludes it). Substance: the struck word's
  letters are likely misread ("reading" vs "reality") — immaterial (the
  word is deleted).
- "Huh!" (page-03, flagged) — TRUE, verified from a 7× crop: the letter
  ends "No peace eh! Huh!" — the VLM's "Huh?" was wrong, and the FIRST
  walker's inferred correction (the fabrication saga) was right after all.
- "Next flagged ↓ jumps pages silently" — REAL minor UX finding (the tour
  crosses page boundaries without warning).
- "Red words promise vs subtle marking" — REAL minor perception finding
  (the legend promises red words; the marking is visible mainly in edit).

Open: the two minor findings need a user decision (label hint for
cross-page jumps; flag-marking strength or legend wording).

## Navigation reorg: visible sequences, no added words (user, 2026-08-16)

The walker's two minors (silent cross-page "Next flagged" jump; "red words"
promise vs subtle marking) are symptoms of one structural gap: the document
boundary is invisible until the last page, and page-level vs document-level
navigation live in one wordy action bar. Research into prior art:

- **Spatial maps beat pagers within a document.** CHI work (Cockburn et al.,
  "Faster Document Navigation with Space-Filling Thumbnails", CHI'06; the
  CHI'17 field study of spatially-stable overviews) consistently finds a
  stable, always-visible page map is faster for locating AND re-locating
  content (spatial memory); prev/next is a hallway. PDF readers converged on
  the thumbnail rail. NN/g "Spatial Memory": coarse spatial cues (thumbnails,
  markers) speed search.
- **Steppers are maps, not controllers.** USWDS/GOV.UK step indicators: a
  row of numbered status markers communicates "where I am of the whole";
  the indicator itself is NOT navigational — separate controls do the
  instant actions.
- **Review is per-page status + an inbox.** FromThePage (the dominant
  transcription platform) drives review by per-page status (Incomplete →
  Transcribed → Needs review → Approved) reached through a pending-pages
  list; status markers carry the progress. The review-queue pattern
  (UX Patterns Guide, HITL inboxes): a persistent rail of items, current
  highlighted, everything reachable.

Decision (user, 2026-08-16 — "try your recommendations, but consider the
limited real estate especially horizontally"): TWO nested sequences become
TWO visible groups in ONE compact strip under the topbar — document chips
(numbers, ✓ confirmed, ● work remains) then a thin divider then the current
document's page chips (current filled, ● flags remaining). Tapping a chip
navigates; the strip replaces the topbar subtitle and the Prev/Next page
buttons; "Next flagged" stays compact and dot-tied (the rail shows where it
lands before you press — the silent cross-page jump is visible by design).
The flag marking is strengthened at rest (red wavy underline, spell-check
convention) and the legend ties dots to red words in one short line.
Numbers and status marks only — no new words.

## The orientation fix: pipeline resilience, not data patching (user, 2026-08-16)

The user redirected the page-02 fix: "No, that's just fixing the data. We
need to make the pipeline itself resilient." Architecture constraints they
set: the front end and back end are different boxes, the backend may be
unavailable, and the image must never be uploaded (the backend has it);
plus two cases to handle — a wrong correction / multi-directional text,
and multiple presses to find the right orientation (don't reprocess on the
first press).

The audit that drove it: **101 of 323 lines (31%) were boxless** across all
12 pages (the rec model cannot read cursive, so content matching fails).
Fixed with an order-preserving positional fallback in `associate_lines`
(boxless lines take the unmatched detections by y-order — the k-th boxless
line takes the k-th detection; the anchor is marked `box_source:
"positional"` and the surface renders those boxes dashed — real geometry,
approximate alignment, honest provenance). 323/323 lines now have boxes.

The orientation fix (the ↻ press becomes a correction, verified live):
1. **Local first**: the view rotates instantly (no server round trip).
2. **The intent queues**: the DESIRED cumulative rotation (quarter-turns),
   committed on navigation into the localStorage rotate-outbox — multiple
   presses coalesce; a wrong correction is just another intent.
3. **The sync**: tiny `{batch_id, page, quarters}` POST (no image); the
   backend applies an idempotent delta (the layout records the cumulative
   "rotation"; a retried intent is a no-op — offline redelivery cannot
   over-rotate).
4. **The fast half**: the image rotates + the boxes remap (rigid, no OCR).
5. **The slow half (async job)**: the page's text is re-read by the VLM on
   the corrected image — the old reading was made from the wrong-way page
   and is unreliable (proven: page-02's "At last venture this form is the
   building of a" vs the corrected re-read "A new venture this term is the
   holding of a", which matches an independent vision read word-for-word;
   the flags dropped 106 → 5). The self-report re-runs, the layout
   rebuilds. The drafts payload carries the per-page job state; the
   surface greys the document with a note, blocks the confirm, and polls
   (5s) — the reviewer navigates on meanwhile. A restart mid-job demotes
   "transcribing" → "failed" (the stale text + the warning, never a silent
   half-done page). The stale local edits for the re-read page clear on
   completion.

Verified live end to end: instant view rotation, the waiting note + gate,
commit-on-navigation, sync, the processing state, the completed re-read
picked up by the poll, the confirm re-enabled. Gate green: 409 pytest +
344 vitest. The boxless-page audit + the positional fallback live in
tools/layout.py; the rotate/reprocess in tools/sync.py + tools/server.py.

## The phone-notes batch (user, 2026-08-16)

The user's phone notes, all landed and verified (gate: 410 pytest + 349
vitest):

1. **Mark a line fine** — a ✓ button on each flagged line: the line counts
   as verified with its VERBATIM text (the edit = the line's own text, so
   the confirmation keeps the unchanged reading). A line can be fine even
   with red squiggles on it.
2. **The dual-pane link** — scrolling the transcription pans the picture
   and panning the picture scrolls the transcription: the top visible
   line's box anchors the image view and vice versa (the line boxes map
   the two; `lineIndexForY` is the pure half). One lock stops the
   feedback loop. "Roughly the same text in both at the same time." (At
   the tablet's whole-page band there is nothing to pan — the link bites
   at reading zoom, which is where it matters.)
3. **The edit box half-width** — the inline-flex shrink-to-fit sized the
   input to half the line, seemingly at random. The edit row is now a
   full-width flex with the input flexing.
4. **The zoom buttons are gone** — fingers pinch; the buttons got in the
   way. Only the ↻ stays. The Fit logic survives internally (the initial
   view + the resize re-fit).
5. **Selecting a line never zooms** — the click just highlights (the
   "suddenly zoom in — it's dislocating" is gone); the link brings the
   region into view at the same zoom.
6. **Transcription density** — the per-line header row (the "vertical
   height on nothing") is gone: one dense row per line = number gutter +
   text + actions. Phone: 5 lines visible (was 2), 28px/line (was 48).
7. **The design-decisions register** — `docs/plans/design-decisions.md`:
   every decision with its rationale, referencing the detailed records.

## One-click edit, accept-on-away (user, 2026-08-16)

The reviewer's most common action (correct a line) was two steps: click to
select, then the ✎ button. Now ONE click on a line enters edit mode
directly; a click away — another line (which then also enters edit), the
panes, or a navigation (page/doc/back/flag/confirm) — ACCEPTS the edit;
Escape is the only way out without saving. The separate ✓/→ buttons are
gone; Enter still accepts. Verified live: edits land + persist on every
exit path. Recorded in the design-decisions register.

## The dual-pane link, fixed for real (user, 2026-08-16)

The user reported the linked scroll still failed on their phone, plus: it
scrolled off the top, started mid-doc, and the line numbers + line-height
ate the real estate. Root causes:

1. **The top-line computation compared root-relative offsetTop against
   content-relative scrollTop** — the panes' own offset (~179px on the
   phone) made the picked line ~6 rows off, so the picture and the words
   drifted apart and the initial alignment felt "random mid-doc". Fixed:
   subtract the pane's offset (`el.offsetTop - txb.offsetTop`). Verified:
   at every scroll position the transcription's top line's box == the
   image view's top (line 10 → 2974, line 25 → 3984, line 32 → 3528; the
   non-monotonic boxes are the page's marginal notes, not a bug).
2. **The pan scrolled into the blank top margin** — the view had no clamp.
   Added `clampView` (the drag + the pinch): the y-floor is the writing's
   top (the band anchor), so the blank margin never shows. Verified: a
   hard pan-down stops at the content.
3. **The line numbers are gone** (user: "line numbers taking up screen
   real estate, why?") — the gutter removed; the row is the text + the
   actions.
4. **The line-height tightened** to 1.3 (0.88rem) — 26px/line, ~5 lines in
   the phone's pane — roughly matching the image's band, so the two panes
   show about the same content at once.

## The linked-scroll polish + image-click editing (user, 2026-08-16)

- The link's movement is now smooth: the transcription's programmatic
  scrolls use `behavior: "smooth"` (their continuous scroll events drive
  the image to follow), and the image's direct pans ease out 180ms
  (a `rv-layer--smooth` class applied only during the link's pans — a
  drag never lags the finger). New general principle: **ux-standards P18 —
  no dislocating moves** (a jump that relocates the reader's position is a
  finding; synchronized movements ease 150–300ms; direct manipulation
  tracks 1:1). Grounded in NN/g's motion guidance.
- **The edit opens when you click the corresponding text on the image**:
  an image click resolves the line whose box contains the point (x AND y)
  and opens its edit; a click on the blank margin is a click-away and
  accepts the open edit. Verified: the margin accepts; a click on a line's
  text opens that exact line ("A history class of 1 hour...").
- **The keyboard Done key**: the edit input sets `enterkeyhint="done"` —
  the mobile keyboard's action key becomes Done and dismisses the keyboard
  (the user's "no get rid of keyboard button — is that a setting?").

## The format conventions + the floating edit menu (user, 2026-08-16)

- **~underlined~ means underlined in the letter** — the single-tilde
  sibling of the strike's ~~. Both render in the review surface
  (`formatParts` — struck + underlined spans) AND in the archive
  (app/markdown.js `inlineNodes` — the item pages show them, not literal
  tildes; this also fixed the pre-existing gap where ~~ showed literally
  in the archive).
- **The floating edit menu** — appears ONLY when text is selected in the
  edit input, floats above it (never covering the selection), clamped to
  the viewport. Ordering follows the platform edit-menu convention
  (Apple HIG: system commands first, custom after):
  Cut · Copy · Paste · Delete · Select all · S̶ (strike) · U (underline).
  The format buttons wrap the selection in the markers; the menu's own
  presses keep the input focused; it dismisses on blur or an outside
  pointerdown. The keyboard's Done key (`enterkeyhint="done"`) dismisses
  the keyboard.

## The format conventions, standardness, and the OCR instruction (user, 2026-08-16)

- **Standardness, honestly**: `~~word~~` (double tilde) is the widely-adopted
  strike convention (GFM, Slack). The underline has NO markdown standard —
  `~word~` is the deliberate in-house sibling. The alternatives were worse:
  `<u>` is HTML (the renderer is text-nodes-only by design — no injection),
  `__word__`/`_word_` are markdown bold/italic (the wrong meaning). The
  convention is documented in the register and now rendered app-wide.
- **The OCR instruction**: the VLM transcription prompt previously never
  told the model either convention — the `~~` appeared only because the
  model knows GFM. `VLM_SYSTEM` now instructs both: crossed-out →
  `~~word~~`, underlined → `~word~` (with the "markdown has no standard
  underline" note so the model doesn't second-guess). Applies to future
  transcription runs — the in-progress batch was left untouched (a re-run
  would invalidate the reviewer's mid-review state).

## The floating format menu REVERSED — the formats live in the edit row (user, 2026-08-16)

The floating format menu (Cut · Copy · Paste · Delete · Select all · S̶ · U)
failed on the user's phone: "I just got the regular popup." The popup was
the platform's native edit menu — which appears on selection, cannot be
suppressed or extended, and ALREADY provides cut/copy/paste/select-all. A
second floating popup duplicating it was the wrong answer — two popups
looking slightly different (user's judgment, and they're right). REVERSED:

- **The native edit menu owns the edit commands** (the platform standard —
  it's the popup the user saw, working as designed).
- **The strike (S̶) and underline (U) buttons live in the edit row itself**
  — always visible while editing, no popup, nothing to collide. They wrap
  the selection in ~~/~; with no selection they drop the markers at the
  cursor. The input keeps ~82% of the row.

## The format buttons + the sync drift (user, 2026-08-16)

- **"I don't see them"** — the row's S̶/U buttons existed but were
  invisible: no border, no background, 34px — plain text glyphs. Now
  visible buttons (border + card background, 40×34).
- **The panes drifted out of sync until a scroll** — every `renderTx`
  (an accepted edit, a flag jump) replaced the transcription's children,
  which resets its scroll to the top while the image stayed — the panes
  diverged until the next scroll re-aligned them. Fixed two ways: the
  scroll position is restored after the re-render, and the selected
  line's scrollIntoView fires only when the SELECTION changed (an
  edit-accept of the same line no longer yanks the view back). Verified:
  an edit-accept keeps the exact scroll (600 → 600); a selection change
  still moves the view.

## The review page broke entirely — an unclosed CSS block (user, 2026-08-16)

"Looks like you have changed the whole interface for this page (including
the portrait version) to be completely unusable." Root cause: a mangled
edit left an unclosed `.rv-txa {` in app/styles.css — CSS brace-matching
swallowed EVERYTHING after it: the format rules, the line-box styles, and
both media queries. The review surface lost its styling and the portrait
query never applied (the landscape split showed in portrait; the rotate
prompt never appeared). No error surfaced — an unstyled page is silent.

Fixed: the block repaired (brace balance 318/318), all three postures
re-verified (portrait prompt, tablet surface, phone landscape). Guard
added: `make lint` now checks the CSS brace balance (the compileall
analogy — a structural error that survives the tools' checking).

## The sync ping-pong — fixed per the established pattern (user, 2026-08-16)

"Scrolling often jumps about disconcertingly. Sometimes in the wrong
direction!" Root cause: the sync guard cleared BEFORE the programmatic
scroll's own events fired — the image drag scrolled the text, whose scroll
events re-anchored the image back, which re-scrolled the text… a feedback
loop fighting the user's drag. The established dual-pane sync pattern
(Joplin's spec, the diff-navigator components) is: `isSyncing = true;
…; requestAnimationFrame(() => isSyncing = false)` — the guard held until
the next frame. Applied:

- The image→text follow is now DIRECT (the drag tracks 1:1, P18 — the
  smooth scrollTo lagged and re-triggered the loop).
- The guard is held until the next frame, so the programmatic scroll's own
  events can't re-trigger the image side.
- The image's pan eases only for LARGE jumps (a selection, the initial
  align — >150px); the per-event scroll-follow steps are small and the
  60fps events smooth them (the transition was lagging the follow).
- Verified: both directions follow, and after a drag both panes sit
  perfectly still — no oscillation.

Note: a transcription line whose box is PHYSICALLY ABOVE the previous
line (the page's marginal notes — line 32's box at y3528 vs line 25's at
y3984) will still pan the image "the wrong way" when scrolled to — that's
the letter's real geometry, not a bug; the pan is faithful to the boxes.

## The accept scrolled the image up — fixed (user, 2026-08-16)

"Sometimes when I click the accept button on a line, the image scrolls up
(earlier in the text)! If I accept the lowest line I can see it should
scroll down a bit (with an animation with ease)." Root cause: accepting an
edit shrinks the row (the input ~34px → the text ~26px); the browser's
scroll-anchoring then drifted the transcription up a few px, and the
dual-pane link faithfully followed — the image jumped to earlier text.
Fixed two ways:

1. `overflow-anchor: none` on the transcription pane — the re-render's
   scroll restore holds exactly; no anchoring drift.
2. The accept now ADVANCES: if the accepted line sits within 48px of the
   pane's bottom (and content exists below), the pane scrolls down one
   line with `behavior: "smooth"` — the smooth scroll's events carry the
   image through the link, so both panes glide together. Verified:
   mid-document accept of the bottom line scrolls down (text + image),
   with the ease; at the document's end there is nothing below to reveal,
   so the view holds.

## The accept "WAY up" — the marginal notes (user, 2026-08-16)

Accepting a line (e.g. line 27, "unusual instruments") made the views
scroll "WAY up to quite near the beginning again." Root cause: page-01's
READING order and PHYSICAL order diverge — line 27's box is at y4142 but
the NEXT line (28, a marginal note) is at **y2725, near the top of the
page**. The accept's advance scrolled the text one line, the note became
the top line, and the link faithfully panned the image to its box — the
"WAY up."

Fix: the accept-advance now fires ONLY when the next line's box is
physically BELOW the accepted line's (the normal continuation — "scroll
down a bit, eased"). When the next line is a marginal note above, the
view holds — the reviewer scrolls on themselves. Verified: the line-27
accept holds exactly; a normal continuation still advances down (eased).

Deeper note: this page's marginal-note structure means ANY faithful
image-follow can jump when the reading order crosses a note. The fully
smooth answer is a monotonic interpolation between the line anchors (the
Digital Variants approach) — parked unless the reviewer keeps hitting it.

## The wrong-way page: rework exclusion + the rotate re-fit (user, 2026-08-16)

The user's wrong-way-page experience: "It's not drawn in the right place
after I rotate it (so I can't read it which is a shame) and then it's hard
to get past it to look at the next one, since this one should be ignored
until it updates. I think maybe it shouldn't have shown me it at all once
we'd established that it needed rework on the back end."

1. **The rotate re-fits now** — the view rect lived in the previous
   frame's coordinates; rendering it through the rotated frame drew the
   page in the wrong place, unreadable. The rotation now re-fits the view
   to the rotated frame (the whole rotated page).
2. **A rework page is excluded from the review flow** until the backend
   updates it: once its orientation fix is queued or its re-read is in
   flight (`isReworking` — the pending intent or the "transcribing"
   state), the surface lands on the next available page instead, its chip
   pulses amber, the flag tour and the counts skip it, and the confirm's
   advance passes over it. The batch screen refetches the drafts after a
   delivered sync so the processing state is current.
3. **A real bug found while restoring**: `rotate_page` treated a desired
   rotation of 0 as a no-op — a reviewer rotating the WRONG way back to
   the original would be silently ignored. The delta is now the no-op
   check (+ test).

## Next-flagged after an accept silently restarted (user, 2026-08-16)

On the Postmark page: "I pressed next flagged but nothing happened. Well,
it blinked. Nothing moved and there's nothing flagged in view."

Root cause: the tour's ``from`` is set to the accepted line, and an accept
REMOVES that line from the flagged positions — so the next press's
lookup of ``from`` failed and the tour silently restarted at the FIRST
flag (the edit blinked open on an already-seen line, the view never
moved). ``nextFlagged`` now continues AFTER the accepted position by
order (page, line) instead of restarting; only a genuine end-of-list
wraps. Verified live: tour → accept → next-flagged lands on the NEXT
flag (+ regression test).

## Accept advances whenever the line isn't the top visible row (user, 2026-08-16)

"If I can see three rows of transcription and I tick the second one, it
should scroll up a line (with nice animation and ease). So I never end up
reading a line of transcription that I can't see the original for."

The old rule only advanced when the accepted line sat within 48px of the
pane's bottom — a middle-row accept (the second of three) left the next
line at the edge, its original half-clipped in the image. The advance now
fires whenever the accepted line is NOT the top visible row (a line above
it is still in view): the pane scrolls up one row, eased, and the
dual-pane link brings the next line's original into view. A TOP-row
accept holds — the next line is already the second row. The marginal-note
guard (advance only when the next line continues physically below) is
unchanged. Verified live: second-row accept scrolls exactly one row; a
top-row accept holds; the image pans only when the top line's box moved
(here it held — the originals were already in view).

## The first line was unreachable: the band anchor clipped the page's true top (user, 2026-08-16)

On the letter's last page, "moment it looks awfully complicated," appeared
as the first line (image and transcript both) although it is not — the
page's true first line ("piano-practising facilities. At the") was
clipped, and "the image won't let me scroll up at all."

Root cause (data + surface): the rec model's top detection is a TALL
merged box that sits a fraction of a line BELOW the true ink — page-05's
first line had NO box at all (its ink starts 83px above the topmost box;
page-02's cursive first line is 60px below its ink). The band anchor and
pan floor sat at the topmost box's top, so the first line's top was
clipped and the pan floor hid it entirely — nothing above to scroll to.

1. **Data**: page-05's line-0 box repaired to the ink-derived top line
   [556, 2302, 1932, 2440] (the real first line's extent; box_source
   stays "positional" — real geometry, no text anchor — dashed). Without
   it every path is poisoned: the link's mapping, the click-to-pan, and
   the reading-first alignment all anchor to the stray fragment.
2. **Surface (general)**: the band anchor and pan floor now get a
   HALF-LINE margin (`bandMargin` = half the topmost box's height) —
   every page's first line is reachable, not clipped. Verified: page-05
   opens with the piano line at the top in both panes (view top 2233 vs
   the line at 2302, floor 2235); page-01 (well-boxed) unchanged (first
   line still at the top); the flag tour + pan-up reaches the piano line.

## The pipeline now anchors the geometry itself (user, 2026-08-16: "that's just papering over the problem")

The first-line fix (margin + one repaired box) was rightly called out as
papering over it. The pipeline fix: the VLM's transcription prompt now
asks for each line's bounding box (normalized 0-1000) alongside the text
— the model that READS the cursive anchors every line it transcribes.
The layout uses those boxes (`box_source: "vlm"`); the rec association is
only the fallback. A guard drops the model's collapsed bottom-edge boxes
(page-05's last four lines were a 9px sliver on the probe) so those lines
fall back to a real anchor. Proven: page-05 re-read through the pipeline
— all 26 lines boxed in reading order, first line at the true top (2312
vs the ink 2302), zero dashed. The surface margin stays for the
rec-fallback pages.

## The review's navigation and focus model (VR17, user + walkthrough, 2026-08-17)

The fake-user walkthrough (Sam, 2026-08-17) and the UX research
(Preview Panel, Master-Detail, Overview+Detail, Inline Edit patterns)
established the focus model:

**The focused line** is the line at the top of the text pane's viewport.
Scrolling the text changes the focus. The image follows (pans to the
focused line's box, rotates to the line's reading orientation).
Panning/zooming the image does NOT change the focus — the reviewer can
explore the scan freely.

**The image is the navigation surface.** The box overlays are touchable
(pointers auto, not none). Tapping a box scrolls the text to the
corresponding line and rotates the image. A "return" button in the image
toolbar re-centres on the focused line.

**The inline edit** has a visible Done (✓, commits) and Cancel (✕,
discards) — the standard Inline Edit pattern. The Escape key cancels; the
keyboard's Done key commits.

**The verification tick** is a toggle: unchecked (○ outline) and checked
(✓ filled). Clicking a checked line unchecks it. The line's background
turns cream when checked.

**The image pane's initial view** shows the document's full content area
at a readable zoom level (all boxes' min/max y, not just the first
line).

**Implemented:** (pending — the model API hit its monthly limit, which
blocked the page-02 rebuild; the front-end changes are API-independent
and ready to build.)

**Decision:** VR17 and acceptance criteria 24-28 recorded in the PRD.
The focus model is the reference for the usability test.
