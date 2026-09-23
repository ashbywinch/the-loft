# Segment & box review — user stories (draft for agreement)

Status: ADJUDICATED (2026-09-09) — all Q-rulings are in (Q1–Q3, Q5;
Q4's anchor design and Q6's placement-first are deferred to the data
model / TECHSPEC). The structure tools this works out are unbuilt:
they are the build order of `pipeline-stages-plan.md` (step 4's drawing
surface; stage 6's interjection decision). Inputs: the 2026-09-09
rulings (the box's purpose; logical consecutiveness; the gate; the
structure-first flow — recorded in `layout-requirements-draft.md`),
VR19–VR24 (TRANSCRIPTION-REVIEW-PRD), and the box-issue evidence in
`geometry-experiments-log.md` + `model-trial-report.md`. The
requirements live in the PRD; this doc
works the experience: what the reviewer actually does, and the corner
cases that need rulings before the surface is built.

## The reviewer's world

The reviewer (TRANSCRIPTION-REVIEW-PRD §1) is a family member, not a
technologist, on a tablet in landscape: image left, transcription
right, rows in reading order, ticks, flagged words, per-line rotation.
The segment/box work extends that surface (VR19–VR22); nothing here
redesigns what already works.

## What a box is for (the ruling, in the surface's terms)

- The box answers **"what text am I validating and where is it"** — its
  extent shows the ink behind a segment's text (the position in the
  original).
- The segment's relationship data answers **"where does this belong in
  the letter"** (the position in the text). A marginal annotation
  carries both: its own box, and — when it is an insertion — a point
  in a target segment.
- Consequence: a merged box is **not automatically wrong** (several
  lines of one paragraph may share a box). A **mixed-unit box is always
  wrong** (a paragraph + the sign-off; a body line + the margin note
  caught in its box). The pipeline cannot fully enforce this; the UX is
  the enforcement.

## The box issues the real pages actually have

| # | Issue | Real instance (evidence) | The reviewer needs to |
|---|---|---|---|
| I1 | Clean per-line boxes | page-01 after the ink-layout; page-05's 26 boxed lines | read, fix words, tick — exists today |
| I2 | A box merges lines of ONE paragraph | ~half the crop-grid boxes merged 2–4 lines (model-trial §4) | tick as one, or split for finer ticks — optional |
| I3 | A box merges DIFFERENT units | the ruling's named killer: body line + margin note; page-01's 11 doubles before the piece model | split at a text boundary, reshape both boxes |
| I4 | A margin block in one degenerate box | the P.S. block: 12 lines, one identical box (geometry log) | judge it as a block, or split; one point for the group |
| I5 | A box on the wrong ink or on blank | the SVG experiment: 1 of 15 boxes on blank card | move/reshape the box; text stays attached |
| I6 | Text with no box at all | page-01's margin notes below detector recall (0.15 @ 2x) | trace the ink or extend a neighbouring box; the miss is recorded (Q3, ruled) |
| I7 | A line fragmented into word-boxes | qwen's postcard reads; page-09's 22 fragments | merge into one segment |
| I8 | Boxes misaligned with the ink | "half aligned one-line, the rest merged or slightly off" (model-trial) | nudge/reshape without touching text |
| I9 | Rotated margin segments | the Godolphin back's rotated notes | read upright (VR18 exists); place points across orientations |
| I10 | An insertion mark (caret) in the scan | undetected today (L5 lists detection as open design) | place every point by hand — placement-first |
| I11 | A line boxed in pieces with a gap between | the user's example: boxes on the line's start and end, middle unboxed | trace the whole line once → one box (merge + any new ink) |

## The stories

### Reading and judging

- **S1 — I can see what kind of thing each row is.** Body text,
  independent margin note, insertion (and its point's state: proposed /
  unset / confirmed) are distinguishable at rest, so I know what
  judgment each row needs before I touch it. (Today every row looks the
  same.)
- **S2 — Every box shows its claim.** Reading a row, I see exactly
  which ink it covers — including when one box holds several lines —
  so I always know what I'm validating and where it sits.
- **S3 — The letter reads as written.** Confirmed insertions render at
  their points; independent notes sit visibly aside; the transcription
  reads with the document's sense, not against it.
- **S4 — Coarse boxes don't blind me.** When a box holds several lines
  I can still tell which text belongs to which line — I'm never
  validating a jumble.

### Fixing structure

- **S5 — Split where it belongs.** A box holds a paragraph and the
  sign-off: I split it, choosing the cut in the text; the box divides
  and I reshape both extents on the image.
- **S6 — Extract the caught note.** A body line's box caught the margin
  note's text: I select the note's text, extract it to its own segment,
  and place its box on its own ink.
- **S7 — …and attach it.** The extracted note is an insertion: I attach
  it to its target at a point — placed by me, or confirmed from the
  pipeline's proposal when one exists.
- **S8 — Merge the fragments.** A line arrives as word-boxes: I merge
  them; the texts join in reading order; one segment remains.
- **S9 — Re-box without retyping.** A box sits on blank or wrong ink: I
  move/reshape it; its text comes with it, untouched.
- **S10 — Delete the noise.** A segment is pure noise: I remove it —
  visibly, reversibly.
- **S11 — Honesty on restructure.** I'd ticked a line, then split it:
  its pieces come back unticked. What I validated no longer exists as
  such; nothing silently stays "checked".

### Insertion points

- **S12 — Place an unset point.** No proposal exists: I tap "place",
  tap near the target word, pick the exact gap — coarse-then-fine,
  because this is a tablet and fingers are fat.
- **S13 — Confirm or move a proposal.** A dashed caret marks the
  pipeline's proposed point: tapping it confirms; placement mode moves
  it. Reversible either way.
- **S14 — Detach.** The "insertion" is really an independent note: one
  act returns it to its own row.
- **S15 — Points survive editing.** I fix words in the target line; its
  insertion point stays anchored to the same text, visibly unmoved. I
  split the target; the point lands in the piece containing its text,
  visibly.
- **S16 — Nothing settles silently.** I try to confirm the page with a
  point still unset: the surface names it and offers place /
  mark-independent (AC37).
- **S17 — A group at one point.** The insertion is several segments
  (the P.S. block as one insertion): one point, the group renders in
  order at it; each segment still ticks individually.

### Honesty and precedence

- **S18 — A refused page says so, and a flagged page shows its flags.**
  VR23: the pipeline's detected problems are visible; a page arrives
  either nearly clean (a couple of flagged fixes) or is refused
  outright — never the old silent raw-text fallback, which looked
  reviewable with no boxes and made VR1 impossible. The fallback must
  die (gap flagged to the TECHSPEC rewrite).
- **S19 — My work outlives the pipeline.** Returning after a re-run: my
  text, boxes, points, ticks are as I left them (VR22).
- **S20 — Rotated insertion, upright reading.** A rotated margin note
  inserts into an upright line: I read it upright (VR18) and place its
  point; the relationship renders regardless of orientation.

### The flow (the 2026-09-09 ruling; requirement-shaped as VR24)

- **S21 — Flags start the list; they don't end it.** The pipeline's
  detected problems are where structural work starts — but no flags
  never means "no problems": detection cannot flag what it cannot see.
  My own reading is the other detector: garbled text is the symptom of
  a structural fault, and I can act the moment I see it, wherever I am
  in the flow (VR23).
- **S22 — What the pipeline knows it doesn't know is visible.** A
  segment the pipeline couldn't classify says so; I answer it with the
  structural tools. What the pipeline doesn't know *it* doesn't know
  surfaces only through my reading — S21's case.
- **S23 — I always know where I am.** The segment I'm working on is
  highlighted on the image and marked in the text, with its kind
  (body / note / insertion + point state) visible (VR24).
- **S24 — Words are never checked against an unsettled structure.**
  Whatever the flow, the surface doesn't ask me to tick a row whose
  structural place is still a guess (VR24). When structure is settled,
  insertions render at their points and the check compares each row's
  words to its ink; a note and its target are neighbours in the
  letter, so the pan between their boxes is small.

## End to end: the pages, walked

Each walk: what I see → what I do → what it costs. The load test:
every step is either reading (which I was doing anyway) or one gesture
on the thing I'm already looking at.

**Walk A — the page the pipeline got right.** Rows in reading order; a
margin-note row carries its glyph; row 27's insertion shows a dashed
caret at the pipeline's proposed point. I read; the note and its
target are both in view at one zoom; I tap the caret (dashed →
solid), tick the row, move on. Cost over today: two taps.

**Walk B — the merge nobody flagged.** Row 12 reads "...my quartet to
start on. first Theory..." — garbled, and nothing is flagged: the
pipeline doesn't know it merged the margin note into the line (VR23's
blind spot). I select "quartet to start on." in the row; the image
highlights the covering box — visibly two inks, body line plus margin
scribble. "Split here" cuts at my selection; the box divides at the
ink gap (the inks are x-disjoint, so the mechanical split lands on
it); I drag the handles to tidy. Two rows; the text divided as I cut
it. The new piece needs a kind: the hint bar shows what the pipeline
knew about it (the reader's grouping — transcription-side evidence
survives the edit, VR20); it's weak here, so I set "margin note". It
reads like a continuation, so "insert into…" → row 12 highlights → I
tap the gap after "my" (coarse-then-fine) → the point is set and
renders inline. Cost: a few gestures I chose, no mode switch, no
box-drawing from scratch — only a reshape if the mechanical split
missed.

**Walk C — the writing the machine never saw.** The page opens with no
flags. Row 9 says "as I noted at the side" — no note is transcribed;
zooming the image, there is ink with no box at all (I6: below detector
recall). The machine cannot flag this — it never saw it. I trace the
ink (or extend the neighbouring box over it): the box exists, the
machine reads the clip, I correct its words. The miss is recorded and
feeds the gate (VR23; VR14 amended).

**Walk D — the proposal that's wrong.** The dashed caret sits between
the wrong pair of words (the machine misread the mark's reach). I tap
the caret, tap the right gap, it's solid. One fix, reversible.

**The precision trap (walk B, generalised).** Every structural edit
carries the pipeline's evidence forward visibly: grouping, kind,
provenance. If an edit orphans a hint — the box moved off the ink the
grouping was measured on — the glyph goes hollow ("hint stale")
instead of silently confident. (Design idea; the requirement is VR20's
survive-or-visibly-clear clause.)

## The trace: drawing boxes on ink (the user's proposal, 2026-09-09)

One gesture covers create, merge, extend, and replace — because we
know the ink bounds (the adaptive-ink grid; the rec's detection
pieces) even where no box exists. The finger sweeps a corridor;
intersecting ink components light up as it passes (the text-selection
feel); on lift the system proposes boxes snapped to what was swept.

- **Create** — trace unboxed ink: a new segment's box (per line band;
  rectangles of any aspect, rotated with the band — the extent is for
  communication, not an ink contour). No text yet: the machine reads
  the clip (it does what it can — L11's per-segment read, cost bounded
  by clip size, L10); I correct as usual.
- **Merge** — trace across two boxes and the gap between them (the
  gap-in-the-middle line, I11): one box spanning the lot; the texts
  join in reading order.
- **Extend** — trace from a box onto neighbouring unboxed ink: the box
  absorbs it.
- **Replace** — trace the wonky boxes, clear (one tap, reversible),
  re-trace properly. The quick redo loop the fast path wants.

Guards: the proposal prefers ink whose centre lies in the corridor (a
fat sweep down the margin doesn't grab the body column's edge);
nothing commits until the lift is accepted; reshape handles stay.

## The gnarly corners (rulings needed)

**Q1 — ANSWERED (2026-09-09): split is spatial; the text is re-read.**
A split cannot divide the transcript — no character-to-ink mapping
exists — so the divided boxes' text is unconfirmed and re-read after
the box pass (L11: a segment's text is a reading of its own extent;
the batch re-read is design). The interaction answer — click selects,
never cuts — with the prior art:

- eScriptorium: segmentation is its own panel; click activates;
  commands act on the selection; a scissors tool draws the divider
  stroke across a box; select-many + join merges; vertex handles
  reshape; undo throughout. It carries the two-pass warning too: fix
  segmentation before transcribing, or you erase transcription work.
- Transkribus: the same pair — scissors to separate regions, a merge
  tool to join, boundary handles to reshape.
- Trove: hover reveals per-line controls and the split happens at the
  text cursor — it can, because Trove has a text-image alignment. We
  don't, so that paradigm doesn't transfer.

Ours: click selects the box (handles + toolbar appear); then trace out
the piece to extract (the margin-note case — the trace section above)
or draw the divider stroke across (the two-lines case), snapped to the
ink gap; the preview follows the sweep; release commits, undo covers
(VR25).

**Q2 — ANSWERED (2026-09-09): unconfirm the touched text.** Box
checking precedes word checking, so the collision only happens when
the reviewer goes back. When it does — split, confirm the new boxes —
the text in the touched boxes is unconfirmed: the machine may re-fill
it (VR22's untouched state, restored) and the reviewer word-checks it
again. eScriptorium carries the same warning (fix segmentation before
transcribing, or you erase transcription work). AC39 stands.

**Q3 — ANSWERED (2026-09-09): the reviewer adds it.** Drawing,
extending, merging — the trace gestures (below). The miss is recorded
and feeds VR23's improvement loop; VR14 amended ("the reviewer may
supply what is missing, drawing or extending boxes, without hiding
that the machine missed it"). Remaining design bit: whether the
clip-read fires on creation or waits for a tap.

**Q4 — Point anchoring.** The point must store an anchor (the text it
sits within), not a raw offset, so word fixes can't shift it and target
splits relocate it deterministically (S15). The requirement is
VR21/AC36; the anchor choice is TECHSPEC. Noted so the data model
isn't painted into a corner.

**Q5 — How an insertion renders at rest — ANSWERED by the
structure-first flow (2026-09-09): during the words pass, logical
order wins — insertions render inline at their points, visually
distinct (struck words set the convention); independent notes stay
rows. The trilemma dissolves because the passes split the concerns:
the structure pass is spatial (boxes on the image; reading order
irrelevant), the words pass is logical (structure already settled, so
nothing is confusing to check and the view jigs are small). Remaining
design bit: the inline marker's exact look.

**Q6 — Placement-first, marks later.** No mark detection exists (I10):
every point starts unset, so the placement UX *is* the feature; caret
detection is a later proposal-source. Cost-conscious (L10): don't build
mark detection first.

## Can the pipeline detect marginal-insertion boxes better?

Not impossible — three documented levers: a bigger upscale or a
different detector (page-01's notes sit below PP-OCRv5-mobile-det
recall even at 0.15 with 2x upscale — a capability boundary, geometry
log); the rec model's own ink bounds (the gated recovery recovered 3 of
the margin pieces but the reassembly refused); and the vision model
proposing geometry as SVG — 15/16 boxes on real writing on the postcard
test, block-level, frame rescaling required, never trusted raw
(layout-requirements-draft, 2026-08-30 experiment) — combined with
pre-rotated passes for rotated content and per-box clip reads for text
(L11's candidate mechanism).

But per L9/L10, detection quality is the TECHSPEC's design
conversation, bounded by cost. The requirement-side answer to imperfect
detection is honest proposals (L5/L8) plus the reviewer tools (VR20) —
the tools are needed regardless, because the pipeline will never be
perfect at this.

## Next

All rulings in: Q1 (split is spatial; text re-read after the pass),
Q2 (restructure unconfirms the touched text), Q3 (reviewer adds
missed writing; the miss feeds the gate), Q5 (logical render in the
words pass). Remaining design bits: the re-read's timing (batch after
the box pass vs on-creation), the inline marker's look, group order
at a point. Build order: the trace + select/command structure tools,
the re-read pass, then the persona walk through page-01 — the loop's
re-test is the acceptance.

## The box-detection method (spiked 2026-09-10, asserts to zero)

The spike is one script — `/tmp/boxspike.py` (throwaway path, not the
repo's) — with a companion test jig `/tmp/trace_jig.py` that asserts the
invariants and exits non-zero on failure. Run the spike, then the jig.

**The stages.** Ink mask (pixel darker than its local paper level) →
artifacts removed (long thin ink: scan streaks and rules/underlines — a
1px scan line welding every line it touches into one shape was the worst
failure of the whole exercise) → connected components = words → fitted
baselines (seed by row, refit and reassign, merge fits describing one
baseline, split any line whose members spread more than one line) →
**every shape belongs to exactly one line**, and a shape spanning two
lines is split between them at the row where its nearest baseline changes
→ detector boxes per line-run (the line's words, split at column-sized x
gaps, extent = the ink's own, ascenders/descenders included, capped at
±0.8 pitch) → strokes → composition.

**The semantics (user rulings, 2026-09-10).** The detector boxes the page;
the user only traces where it is wrong. A trace *is* its line — there is
no such thing as tracing part of a line. A trace covering part of a box's
text is the user saying the box holds two segments: the box splits, the
traced span becoming the trace's box and the rest keeping its own. Text
under no box and no trace is user error and the surface must ask for it.

**The invariants the jig asserts** (all passing on page-01's 27 strokes):
each yellow line inside exactly one box (≥90% of its path, x within 90px
of the mark); no box holding two different yellow lines (judged by the
writing each stroke covers, never by the strokes' heights — two strokes on
one line can be drawn 40px apart and are still one line); every word in
exactly one box; boxes on the letter surface; slopes plausible (≤6°).
Words in two boxes are allowed only across *different* lines — the
ascender/descender overlap the boxes imply.

**The traps** (each cost real time):

- **Page-wide thresholds chain.** Any threshold comparable to the noise
  (a row-ink cut, a row-gap) merges neighbours transitively — a 300px
  "line" from a 60px pitch. Thresholds must be stated in the data's own
  scale (word size, line pitch, ink gaps) and compared against a seed,
  never against the growing set.
- **Mixed units.** Ink measured at working resolution and strokes in page
  pixels, both scaled once more, produced boxes running off the letter —
  invisibly, until the jig printed corner coordinates beyond the page.
- **Ink welding two lines.** A descender touching the next line's ascender
  makes one shape spanning both; the fitted lines and the strokes both say
  where the boundary is, so the shape is split by row assignment.
- **Determinism is not robustness.** Every failure above was deterministic
  and looked random: fixed thresholds against noisy data are step
  functions, and greedy grouping turns one stray pixel into a different
  answer. A test jig that prints the offending geometry is what made each
  one visible.

**Not part of this**: the phone sketch (`/tmp/trace_spike.py`) is a
throwaway for drawing yellow lines, never to be ported as-is — the review
surface in the app gets the method, not the sketch.
