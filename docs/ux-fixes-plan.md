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


## Open judgment call (from the import session)

The 2001 email item carries all 8 places as refs (mentions vs. about). The
coordinates were nulled under Rule O (done). Whether the refs should be
narrowed to the central places (kirkby-stephen, soulby, bishop-auckland,
hull) was deliberately left for the user — the assistant did not change the
refs unilaterally.
