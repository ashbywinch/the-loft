# Geometry experiments log

The running record of what we try, what happens, and what we decide — the
anti-regression ledger: before trying anything, check here that we haven't
already tried it and learned why it failed. Append chronologically.

## How to use this log

- Before a new idea: grep this file for the mechanism — if we tried it,
  read the outcome before re-trying.
- Every experiment entry: what, why, the inputs, the outcome, the
  decision. Keep it short enough to scan.

---

## 2026-08-20 — the experiment session's history (reconstructed)

### The failing classes we have measured (the fixtures in tools/eval_geometry.py)

1. **Misplaced transcription boxes** — page-01's marker boxes sit ~770px
   above the real text; page-03's ~200px. A well-proportioned box in a
   blank region: every pure gate passes it. The synthetic-letter fixture
   injects this: the baseline anchors the margin lines at IoU 0.44; the
   rec-only candidate (the rec's ink-grounded boxes) at 1.00.
2. **The single path loses multi-page orientations** — the synthetic
   postcard: the baseline's orientation accuracy 0.57; the multi path
   with the located report 1.00.
3. **Duplicate regions** — two lines claiming the same box (the
   postcard's message). Detected by RegionGate (Gate E).
4. **Loose boxes** — the stamp-class (a 680px box for 'POSTAGE').
   Detected by TextExtentGate (Gate B).
5. **False content matches** — the rec's merged bands matching 2-word
   lines. The Anchor's text-sync arbitration drops the false match.

### The pipeline changes tried (each committed, tests green)

- The gates A–E (validate_layout + the stage-level ink check) — the
  fail-loud detection layer.
- `_box_overlap` fixed (the epsilon-min bug inflated every overlap to
  ~1e12 — the dedupe, the arbitration, and the gates consumed it).
- The Anchor arbitration: the report's located box wins over a positional
  match; a content match's box only overrides when the text-sync passes;
  no candidate holding the text → boxless-flagged.
- The remap_box exact inverse (the old matrix form mirrored 90°/270°).
- The reading order: the single path keeps the transcription order; the
  multi path uses the block-aware order (Block cluster, top-to-bottom,
  transcription order within).
- The clip path falls back to the located report's boxes when the
  transcription gave no geometry.
- The architecture split (text/box/gates/reading + the Layout/Anchor
  classes) — the code carries the structure.

### The Caradog 1915 postcard run (the reference multi page)

- The transcription came through SCRAMBLED (the model misread the
  cursive: "Card of", "with notes.", "in hand." — not the inspector's
  "GOOD NATURE / Yours faithfully").
- The clip path ran (source: clip, degrees {0, 90, 180}) — the
  classifier mislabeled some clips (the same class as the family
  postcard's message lines).
- **The layout was REFUSED by Gate A** — "'and R.A. Knock-er':
  orientation 0.0° inconsistent with a 183x593 box". The Anchor found no
  aspect-consistent candidate; the orientation is unknown; fail-loud.
- **Consequence: the existing postcard eval (test_eval_postcard) is now
  broken** — the refused layout is never written/served; the eval's
  contract ("every line boxed, both orientations present") is
  unfulfillable by the current pipeline. NOT yet updated — open item.
- The scoring needs: (a) the COMPUTED layout captured (the write was
  refused — a write-skip driver), (b) a POSITION-based truth (the text
  matching fails — the model's readings don't match the inspector's).

### The clip-location batch-size sweep (ClipLocation + the cost model)

- The idea: replace the flaky full-page location call with per-batch
  clip-location calls (N lines per call; the model returns each clip's
  box + angle). The batch size is the experimental variable.
- The cost model (overhead 800 + 300/clip per call): batch 1 = 1100
  tokens/line, batch 4 = 529, batch 8+ = 414 — the overhead amortizes
  ~2.6×. DO NOT assume batch 1 is the most cost-effective (user).
- The simulated locator (perfect within the clip, inheriting the crop
  quality) holds the accuracy at every batch size on the fixtures.
- Open: the REAL model calls at batch sizes {1, 4, 8} — the measured
  tokens + accuracy on the Caradog's marker boxes.

## Open items

- The Caradog scoring (the computed layout + the position-based truth).
- The real clip-location calls at the batch sizes.
- The eval's contract: assert the gates' detection (the current reality)
  or enhance the pipeline until the Caradog passes — decision pending.
- The family pages serve: page-03 + the postcard refused — the user's
  in-app verification needs them served (the enhancements land first).
- The easy letter: pick a clean single-orientation page (page-02 — the
  known-good 17-line page) and get it 100% (serving + verified in app).

## 2026-08-22 — the Caradog scoring capture + the real clip-location calls

### The Caradog computed layout (captured via a write-skip driver)

- 30 lines, 7 gate violations, orientations {0: 14, 180: 3, 90: 5, 270: 8}.
- The model's readings are scrambled AND misplaced ('POST CARD.' at y 911 —
  the printed header is at the top; 'with notes.' shares the date's box).
- The text matching cannot score it (the readings don't match the
  inspector's); the scoring needs a POSITION-based truth built from the
  image regions — open item.
- The captured layout is the honest baseline: the multi path's current
  output on the reference postcard is far from the truth.

### The real clip-location calls (batch sizes {1, 4, 8})

- Batch 8: 0/16 located, 17123 tokens (1070/line). Batch 4: 0/16 located,
  33371 tokens (2086/line). Batch 1: 5 calls in 25 min then the timeout.
- DIAGNOSIS: a single-image call returns the JSON correctly (4857 tokens,
  the fence-wrapped parse works); a 4-image call returns EMPTY content
  (8314 tokens, zero content — the model's reasoning ate the 8000-token
  budget). The multi-image location prompt spirals like the full-page
  call did — the same class of failure.
- NOT YET TRIED: the 64000-token headroom on the multi-image calls (the
  established reasoning headroom) — the next experiment. Batch 1 is the
  only WORKING size so far — the cost model's "batch 4 is cheaper" holds
  only if the model can actually answer at batch 4.

### The easy letter (page-02) — the self-report stage bug

- Page-02 served with ALL 111 words flagged: the self-report stage is a
  SEPARATE command (python -m tools.selfreport) that the process never
  runs — the layout falls back to the cross-reader agreement, which
  garbles every cursive line.
- The selfreport CLI had the same bare-stem filter bug as layout_detect
  ("page-02" never matched "page-02.jpg" — silent no-op, exit 0).
  FIXED (2026-08-22) — the normalized filter.
- After the fix + the run: 2 unsure words (violinist, performing) vs 111.
  Page-02 rebuilt: 17 lines, 2 flagged, gates clean, serving — the easy
  letter is ready for the user's in-app verification
  (#/review/adopt-20260813-201004/0/1).
- OPEN: the process should RUN the self-report stage (the pipeline gap —
  the cursive pages all-flag without it).

## 2026-08-22 — "how did this pass tests?" (the user's in-app finding)

The user opened page-03 ("Chere Maman") in the app: no text visible in
the image, the transcription without structure. ROOT CAUSE:

- The current page-03 layout FAILS Gate E: the boxless lines' wrong
  boxes ("critic's view. To quote:" on the P.S. margin, "quartet to
  start on." on "my first Theory", the "noting?\nNote" rec fragment on
  "1st page") — 4 same-region pairs with different text. The drafts
  EXCLUDE the layout (fail-loud) — the app falls back to the raw text
  with NO boxes, and the image pane has no content band to fit.
- Why the tests passed: the unit tests + the fixtures never cover the
  real page-03's SERVED state; the gates' exclusion is the new behavior.
  The page served before the Gate E + rebuild changes.
- FIX: drop_conflicting_boxes (Gate E as a correction) — when two lines
  claim the same region with different text, the lower-confidence box
  drops (the line stays flagged); the confirmed anchor keeps its region.
  Wired into the Layout class + the stage, after the Gate D drop.
  Rebuild page-03 to confirm the drafts include it again.

## 2026-08-22 — the consistent fix + the diagnosability (the user's challenge)

The user challenged the "spiralling" claim + the bodge nature of the
drops. Findings:

- The instrumentation revealed the truth: the page-03 clip reads — 3 of
  20 FAILED with "vision model produced only reasoning tokens, no
  content — the max_tokens limit was hit. reasoning=8747-12916 chars,
  tokens=40-400" (the VlmError's captured counts). The "spiralling"
  label is an inference from the counts — the reasoning TEXT was never
  read, and my first instrumentation truncated the failure message to
  120 chars (str(exc)[:120]), throwing the reasoning tail away. FIXED:
  the full VlmError message (with the reasoning tail) is now logged.
- The single path's unconditional marker-box anchoring was the bodge's
  root: page-01/03's misplaced marker boxes anchored directly, and the
  stage's drops patched the symptom. FIXED: the single path now uses
  the Anchor arbitration (the rec's ink-grounded content match wins
  when the marker's estimate misses the text). The experiment measures
  it: the synthetic-letter baseline went IoU 0.44 -> 1.00 (the injected
  failing PREVENTED, not patched). The eval tests now pin the fix.
- The run log: each layout run writes a FRESH file
  work/<batch>/logs/layout-<timestamp>-<pid>.log (the write mode, the
  unique name — never an accumulating log, per the user). A problematic
  run is examinable after the fact.

## 2026-08-22 — the crop-grid experiment, Phase 1 + 2 (the geometry rework)

The user's architectural question: the pipeline's cross-engine fusion (the
VLM's text vs the rec's ink) is the seam where every fix-up lands. The
proposal: MEASURE LOCALLY, STITCH GLOBALLY — the page read as a grid of
crops, each crop's lines measured in the crop's OWN frame (the model's
geometry is trustworthy only when the question is local), stitched into
the page.

### Phase 1 — the pure stitch (committed f961919)

- stitch_crop_box: the crop-local normalized 0-1000 box -> the page
  frame, exactly. The synthetic-letter fixture's crop-grid candidate
  anchors at IoU 1.00 with full coverage (the truth by construction).
- The content-anchored grid: the crops cover the INK extent (the real
  pipeline anchors to the rec's detection bounds), never the blank
  margins — all 6 crops carry lines.
- The order metric is a separate concern (the reading-order machinery).

### Phase 2 — the real crop-grid on page-01 (tools/eval_crop_grid.py)

Two runs (27.4k tokens, ~6 min each, sequential single-image calls — the
proven shape; the multi-image prompts still spiral):

- **Coverage SOLVED: 0 boxless (vs the current pipeline's 9), 67 lines
  (vs the guess's 31), the full letter read (y 2263-4640) with clean
  text** — the model's per-crop cursive reading is good, and it finds
  MORE lines than the guess (the finer segmentation: "Our week includes
  :" + "Professor: J.R.P.O." split, the margin notes, the bottom tail).
- **Box PRECISION is model-limited**: the visual assessment — roughly
  half the boxes align with single lines; the rest are merged (2-4
  lines), misaligned, or overlapping at the bottom. The model's local
  boxes are MUCH better than the full-page schematic (the location
  report) but are attention-drawings, not measurements.
- The exact-text matching vs the current layout found only 2-3 pairs
  (the finer segmentation breaks the 1:1) — the IoU numbers are not
  the point; the visual is.
- The reading order: the grid order reads the two-column letter's LEFT
  column before the RIGHT (the "Helen Just" at y 3894 after "questions"
  at y 4387) — the block-aware order (reading.py) is the fix.

### The decision point

The crop-grid solves the coverage + the text; the boxes need the
rec's ink for precision. Next candidates:
(a) the crop-grid's line regions + the rec's ink WITHIN each region (the
    intersection = the precise box) — the fusion inverted: the VLM
    segments + labels, the rec measures;
(b) accept the approximate boxes + the review's correction;
(c) the crop-grid's regions as the rec's detection ROIs (the rec
    re-detects within each crop-grid line at a higher zoom — the
    merged-line problem may resolve at the single-line scale).

## 2026-08-22 — the model trial (5 models x 2 tasks, OpenRouter)

The full report: `docs/plans/model-trial-report.md` — the table + the
visual breakdown. The summary:

- All 5 models (glm-4.6v, glm-4.5v, qwen2.5-vl-72b, gpt-4.1-mini,
  gpt-4o-mini) via OpenRouter, the same crop-grid, the same 6 crops:
  **every model 0 boxless** — the crop-grid's coverage holds regardless
  of the model.
- The letter (page-03, the callout): glm-4.6v's boxes ~100% one-line
  (IoU 0.751, 23.6k tok, 525s); glm-4.5v's top excellent + bottom
  fragmented (0.765, 17.2k, 237s); qwen's fast/cheap (56s, 9.1k) but
  fragments every line into word groups; the OpenAI pair the worst
  (gpt-4o-mini: 156k tokens!).
- The postcard: NONE of the models segment the 90° message cleanly —
  the upright crop reads fail on the rotated text. The postcard needs
  the orientation-aware crop-grid (the spike proposal, report §7).
- DECISION (user's route): the image model -> z-ai/glm-4.6v.
- The crop read's completion budget: 8000 (64000 exceeds the glm-4.5v's
  65536 context once the image is in — the 400).

## 2026-08-22 — the postcard spike + the honest negative

The spike's CONCEPT succeeded: the postcard's full message panel
(1600x1950, x 100-1700) rotated +90 (PIL's rotate(90) = the
counter-clockwise) reads CLEANLY with glm-4.6v — "If it is at all a
decent day tomorrow come as early as you can so as to get a walk in the
morning I hope it will be better Than today! / With Greetings and Best
Wishes" — 10 lines, 10 boxed, including the ~~strike~~ marker. The
rotation's inverse was pinned empirically: +90 maps (x,y)->(y, H'-x),
so the inverse is x = H'-y', y = x'.

The INTEGRATION failed: the crop-grid's automatic run on the postcard
(the per-crop orientation: read upright, check the boxes' aspect, rotate
+90 if tall) produced fragments, not lines:

- The uniform 2x3 grid's message crops are WIDE (1203x609), so rotated
  they are only 609px wide — the message's lines are CUT at the crop's
  edge, and the model reads the word-fragments ("deceu, corne, can,
  walk, I hope, Thank").
- The stitched boxes sit off-crop (x beyond the crop's width) — the
  remap needs verification against the real rotated reads.
- The address was not read (the top-right crop returned only the
  printed header + fragments).

LESSON: the rotation concept is right; the CROPS must be the REGION
(the message's full panel, or a tall strip), not a uniform grid quarter
— the vertical-text regions need crops that, when rotated, fit the
full line length. The spike's panel read is the reference.

## 2026-08-22 — the ink-column experiment: the postcard's BOXES are right

The decisive pivot: the model's boxes are schematic EVEN locally (the
rotated panel's read returned even 100px row-bands, not measured
extents); the rec's recognition is garbage but its DETECTION pieces are
real ink. The experiment (tools/eval_columns.py):

1. The message panel (x 100-1700, y 150-2100) rotated +90.
2. The rec's detection pieces (55) on the rotated panel.
3. The pieces clustered by Y into the message's rows (the lines are
   horizontal in the rotated frame — the first attempt clustered by X,
   the wrong axis, and merged the message).
4. Each row's union-box is the MEASURED line box (the ink's extent).
5. The VLM reads each row's clip and labels it.
6. The union-boxes remapped into the page frame.

RESULT: 10 lines, 0 boxless, ~12.5k tokens, ~5 min. The visual
verification (2026-08-30 correction): an overlay with green strips was
generated and inspected by the AGENT, not by the user — the user never
saw it, and it must not be cited as user-verified. The boxes measured
plausibly from the rec's ink, not the model's attention — but the
verification bar for "right" is the review surface, not an
agent-generated overlay.

The remap had two bugs found along the way (both fixed + verified):
the normalized boxes must scale to the rotated frame's pixels before
the inverse; and the union-boxes (pixels) need the unscaled inverse.

The remaining imperfection: the per-row clip labels are noisy ("ceut
day forworre" for "decent day tomorrow") — the text needs the cleaner
source (the panel's full read, or the label matching).

## 2026-08-22 — the text refinement + the UI attempt's honest blockers

The ink-column's per-row clip labels were noisy; the fix (2be75dc):
read the whole rotated panel ONCE (the spike's clean read), match its
lines to the measured rows by y-overlap — the text from the read that
reads well, the boxes from the ink that measures well. The postcard's
labels are now clean ("decent day tomorrow", the ~~strike~~), ~8-9k
tokens (one read vs ten). The script generalizes to upright pages
(--rot 0).

The UI attempt (the user: "get the docs in the UI") exposed the honest
blockers — the serve's validation refuses both layouts:

- The LETTER's crop-grid output (49dc1df's run) is degenerate: 12
  lines share one box [526,2238,1325,3083] (the P.S. margin block —
  the model's schematic read). The earlier "~100% one-line" visual was
  the 43 distinct boxes; the P.S. block's 12 identical boxes were
  hidden under the one visible rectangle.
- The rec's ink on the LETTER is coarse too: 26-28 clustered rows vs
  ~35 lines (its det merges cursive lines at any gap 20-50).
- The POSTCARD's vertical message lines sit at the Gate B 80px/char
  boundary (81-82) — the legitimate vertical handwriting's glyph
  height, a borderline false-positive of the "wildly out" threshold.
- The label y-matching fails when the model's boxes are schematic (the
  letter's full-page read: every row matched the first band) — order-
  based matching is the next candidate.

DECISION: the layouts stay out of the UI until they pass the serve's
validation (the user's "no faults" gate). The next candidates: the
P.S. block's rec-ink rows (the letter), the order-based label
matching, and the Gate B threshold's honest calibration for vertical
text.

## 2026-08-22 — the order-based matching verified + the UI's remaining blockers

Item 2 (8a23326): tools/ink.py's match_labels — the proportional
order-based assignment (each row's y-center, as a fraction of the
content's span, picks the line at the same fraction), with the
y-overlap refinement gated by the degenerate-detector (<60% distinct
bands -> fall back). The tests pin the 1:1, the merged rows, the
degenerate fallback, and the non-degenerate refinement.

VERIFIED on both docs: the letter's 22 rows now carry the clean
transcription in order (Chère Maman, Queen Alexandra's House, the
whole letter — the 'all rows -> first band' collapse is gone); the
postcard's message rows read cleanly (If it is at all a / decent day
tomorrow / can so as ~~to~~ get a / walk in the morning / I hope N
will be better / Than today! / With Greetings and Best Wishes).

The UI's remaining blockers (the serve validation refuses):
- The postcard's row 0: the rec merged the date and the HERNSPETH into
  one wide row [208,147-1900,219]; its label ('13.11.63') is 8 chars
  vs the 1692px axis = 212 px/char. The rec's top-row merge, not the
  matching.
- The letter's 'London ~S.W.7.~': 15 chars in a 1280px rec-union =
  85 px/char — 5 over the horizontal 80 ceiling. The rec-union's width
  includes the inter-word gaps; the line's real glyph extent is
  tighter.

DECISION: the machinery is verified; the layouts need (a) the rec's
row-union x-tightening (the pieces' glyph extents, not the full
width) and (b) the postcard's top-row merge handling. The docs stay
out of the UI until the validation is clean.

## 2026-08-22 — the carry-on: the order-based matching's residual error

The UI's two remaining rows were inspected (the user: carry on):

1. The postcard's row 0 is a REC MERGE of two lines sharing a y-band:
   the date's pieces (x 208-241) + the HERNSPETH's (x 1206-1900). An
   x-split is needed — but the DISTINCTION matters: the letter's row 5
   has a similar x-gap WITHIN one line (the words at the two ends, the
   blank middle — the inspector confirmed "send something of interest
   each week." is one line). The gap size alone cannot distinguish a
   line boundary from word spacing.
2. The letter's row 5's LABEL is wrong: the order-based proportional
   assigned "London ~S.W.7.~" but the row's actual ink is "send
   something of interest each week." — the rows' merges + the uneven
   spacing + the line-count mismatch (22 rows vs ~40 transcription
   lines) skew the fraction-based index.

DECISION: the labels need a per-row VERIFICATION — accept a label only
when the model's read has a line whose text plausibly matches the
row's rec-read pieces (the rec reads the ink; the model reads it
cleanly); otherwise the row stays flagged rather than carrying a wrong
label. The x-split (for the true two-line merges like the postcard's
row 0) follows the same verification — split only when the two sides'
rec-read texts differ. This is the next micro-step; the docs stay out
of the UI until the validation is clean.

## 2026-08-22 — the letter is in the UI with the ink-measured boxes

The x-split (tools/ink.py's cluster_rows): split each row at its wide
x-gaps — the fix for BOTH the postcard's date+HERNSPETH merge and the
letter's two-end words with a blank middle (the union must not span
the blank). Test-first (the side-by-side split + the close-words
kept-together).

RESULT: the letter (page-03) validates CLEAN (24 lines) and is served
in the UI — the reviewer sees the ink-measured boxes, one line each,
aligned with the handwriting (the visual: 14/15 fully-visible boxes
correct). THE LETTER'S GEOMETRY IS DONE.

The transcription's labels are imperfect (the model's read: some
duplicates, some readings differ from the handwriting — "No pears eh!
Huh!" vs the actual "No peace eh! Huh!") — the text refinement (the
label verification: accept only when the row's rec-read overlaps the
assigned line) is the next micro-step.

The postcard REGRESSED under the x-split: the HERNSPETH's pieces sit
at scattered y's (358, 838, 1356) and became separate rows, and the
message's rows got duplicate labels. The previous 10-row state had the
clean message + the top's mismatch; the x-split's over-splitting needs
the rec-union refinement (the scattered pieces' handling). The
postcard is not served.

## The batch runs + the VLM escalation ladder (2026-08-25)

**The scale-up** (`7c3b083`): `tools/eval_batch.py` ran every page
through the ink-column pipeline — the rec sequential, the VLM reads
4-at-a-time (independent HTTP). Three bugs from the first untested run,
each pinned by a failing-test-first test: 37 photo pages skipped for
want of a full-page fallback (`prep_panel(None)`); good layouts
overwritten by worse re-runs (a stored layout that validates clean now
skips); orientation hardcoded 0 failing Gate A on tall boxes
(`orientation_from_aspect` added beside its inverse `aspect_consistent`,
with the both-agree property test).

**Run results across the three runs:**

| run | letters clean | photos clean | wrong-stuff failures |
|---|---|---|---|
| first (untested) | 4 / 12 | 0 / 38 | ~8 raw-JSON/empty |
| tested (`7c3b083`) | 9 / 12 | 11 / 38 | ~5 raw-JSON, 1 empty, collapses |
| ladder (`0a59a1d`) | 9 / 12 | 11 / 38 | **0** |

**The escalation ladder** (`0a59a1d`, user's challenge: "could we just
have a better prompt?"): partly yes. The empty-content and truncated
`{"lines": ...` echoes are completion-BUDGET failures (glm-4.6v's
reasoning eats the 8000 tokens — the trial saw this on multi-image
prompts), and the ink-column pipeline measures geometry from ink so the
boxed JSON buys it almost nothing. The ladder per page: [boxed JSON
@ glm-4.6v] → [plain text @ glm-4.6v] (no format to fail mid-echoing, a
fraction of the tokens) → [plain text @ glm-4.5v] (the trial's
runner-up; page-02 emitted the IDENTICAL raw JSON in two runs, so
same-model retry alone would repeat). `transcription_problem` decides;
`transcribe_with_fallbacks` escalates with stderr evidence; every
fall-through logged. A response must also plausibly cover the measured
rows (`transcription_line_count_plausible`: >=40% when >=10 rows) — the
birth certificates' collapse folded 26 rows into one 323-char line.

Result: zero wrong-stuff responses in the ladder run (was ~14% of
pages). Every page got a read. One page exhausted all three attempts
honestly (1697895793138, the Leigh-on-Sea photo — its remaining refusal
is a Gate B extent mismatch, not response quality).

**The honest state**: 20 of 50 pages serve clean layouts (9 letters +
11 photos). The 30 refusals are NO LONGER response-quality failures —
they are the deeper clustering/matching problem on sparse-photo layouts:
short labels on long rows ('POST CARD' 9 chars on a 1206px axis),
long labels on tiny rows ('1938 BIRTH...' 67 chars on a 46px axis),
empty noise rows. The next lever is the clustering/matching quality for
scattered captions, not the model call.

## Caption clustering: the runaway-row fix (2026-08-25, `6b9cc44`)

The user pointed at caption clustering. Diagnosis from piece-level
dumps: single-linkage chaining — every ADJACENT center-gap small —
builds rows spanning many real lines. The birth certificate's form
table chained 40 cells into one 290px row (6.2x its own piece scale);
a photo's big handwriting chained 13 pieces into 1077px (6.3x).

cluster_rows now splits over-tall rows at internal y-gaps until every
part is within 2.5x its own median piece height (ascenders/slant live
under that; tables hit 6+), before the x-split. Own-scale thresholds:
resolution-invariant. Evidence: birth cert 27->40 rows, 0 implausible;
photo 5->10; council letter 33; postcard 37 (3 remaining talls are the
ROTATED message judged upright — region separation, still open).

Re-run: page-10 (26 lines) and the Liber Wedding photo (6 lines) now
write clean. Total 22/50 (10 letters + 12 photos).

The 28 remaining refusals decompose (each its own lever):
A. Matching count-mismatch: 40 measured rows vs ~25 transcribed lines
   — proportional assignment hands long labels to fragment rows (the
   birth certificates).
B. Gate B assumes handwriting scale: 'NHS' at 109 px/char and
   '~PAUL WINCH~' at 126 px/char may be BIG print/handwriting on
   photos — the 80 px/char ceiling needs the row's own letter size.
C. Mixed orientations on one page (the postcard's message panel):
   needs region separation before clustering.
D. Noise rows: non-text detections become empty-box lines.

## The contact-sheet walk: what "serving" actually looked like (2026-08-25, `712eb9d`+`196ddbb`)

The user asked "will the first page of the first letter look correct?"
It would not have. The new instrument (tools/walk_review.py — every
stored layout drawn onto its own scan) + a vision audit of ALL 26
boxed pages found:

- **page-01 WRONG** (stale old-pipeline layout, structurally valid,
  geometrically garbage — the clean-skip had protected it from every
  fix since), **page-05, page-09 WRONG**, and **page-10's boxes all
  floating above the writing**: the crop-origin offset bug
  (`712eb9d` — detection in crop space written verbatim into page
  space; full-page-fallback pages immune).
- Photos: postcard/3940169... the audit also caught MY transposed-id
  deletion (took out Heinz `…f652d938`, audited CORRECT, instead of
  `…5f7905a9`); Heinz reprocessed and now refuses on Gate B at exactly
  the handwriting-scale ceiling (135 px/char big print) — lever B.
  `1782635795946` (multi-line boxes, pre-tall-split stale) invalidated.

After invalidation + reprocessing with fixed code: every wrong layout
is OUT of the UI; the affected pages refuse loudly. Serving now:
letters 03/04 (vision-correct) + 06/07/08/11/12 (mostly, 1-2 residual
boxes each); photos 818826(+~2), 363276, 07449, 752512 mostly-good,
307227 has 1 misplaced box of 3, Liber Wedding serves word-level
fragments (on ink, not clean one-liners). ~15 pages verified-acceptable;
everything else refuses rather than lies.

**The ensure-mechanism** (the user's question): (1) the sheets exist —
rerun `walk_review` after ANY layout write; (2) no "it works" claim
without the per-document vision-audit table in list order; (3) the
gates stay loud — a refusal is the system telling the truth. Still to
wire: the structural serve-walk as an archive-marked test in make verify.

## Source-level improvements + the honest coverage drop (2026-08-26, `1cb4dab`)

Three pipeline changes so mistakes stop being MADE, not just caught:
provenance-gated skip (layout_is_current — only ink-provenanced layouts
earn protection); split_by_bands (multi-band unions divide along their
own ink before label matching); image-aware gates at write time
(previous turn). Plus the panel-tmpdir leak fix, and Phase 2 moved back
inside Phase 1's try after my restructuring briefly resurrected the
delete-before-read bug (run16 caught it in minutes — the gates work).

Run17's honest outcome: letters serve 03/04/11/12 (+08 refused on one
empty-label row); 06/07 LOST their rough old layouts to the provenance
reprocess and refuse on empty-label rows; photos: several former
rough-serving pages now refuse at the image gates. Coverage ~13 pages,
every one of them gate-clean; everything else refuses loudly.

The residual failure classes, precisely:
1. Over-wide single-band rows from sparse-caption clustering ('Windsor.'
   8 chars on a 1156px axis) — needs caption-scale clustering.
2. Label count mismatch persisting after band-split (model under-reads;
   empty-text rows).
3. Gate B assumes handwriting scale — big print ('57 Varieties' 90-135
   px/char) fails though correctly boxed.
4. Duplicate region claims from overlapping unions (page-01/09).

## The token-economy layer: the VLM read cache (2026-08-26, `4475300`)

The user's question — future passes must not re-pay tokens for pages
that didn't change. Answer: tools/vlm_cache.py. A read is a pure
function of (panel bytes, call spec); persist it keyed by
sha256(panel)+sha256(spec) and every subsequent run hits for free.
Demonstrated live: same page, cold 7,926 tok → warm "CACHED",
"tokens": 0. Gate/assembly iterations over the whole archive are now
free; only changed panels or changed PROMPTS re-read.

Same cycle, Gate B recalibrated (`e72b4b2`): the ceiling is the box's
own perpendicular extent ×1.7 (big print legitimate), density counts
non-whitespace glyphs ('E    R' stays rejected), and the STRICT pair
(glyph_extent_violation: [0.12, 1.7]×perpendicular) applies at batch
write-time to measured unions only. Plus `_recover_crashed_layout`
now rotates by the stale layout's recorded pre-turn dims — the
coordinate-frame class again, caught by scaled fixtures.

## Run 18: the cache-population pass + the fragment-box false pass (2026-08-26)

Full re-run under the scale-aware Gate B with the write-time image
gates. HONEST spend note: this pass paid fresh tokens (~400k) — the
cache only covers reads made after it existed, so run18 populated it;
every LATER iteration is free.

Letters: page-10 newly written (21 lines, vision-CORRECT — 25 boxes
each on one line) -> 5 serving (03/04/11/12 + 10). Photos: 7808715
(2 lines, vision-correct) newly written; 071639 written then
INVALIDATED — vision caught the fragment-box false pass: ink present,
single band, but the box covered only part of the text while the real
line sat rotated beside it. The mechanical gates cannot see that class
(boxes are on ink); it must not serve. ~12-13 photos serving.

New failure class named: the fragment box (union covers part of a
line). Cheap next gate: the box's ink band extends beyond its x-range —
compare the box width against its band's contiguous ink extent (>=60%
or refuse). Also: the image-gate refusal message should name WHICH
gate and the box indexes (off-ink vs multi-band vs glyph-density) —
today it lumps them.

## The HTR head-to-head: existing tools vs our pipeline (2026-08-26)

The user's challenge — "should we be using existing tools?" — answered
empirically on 5 real pages (tools/eval_htr_trial.py, outputs in
work/eval-htr/). CER vs a vision-model reference read (directional,
not human GT):

| page | tesseract | kraken | ours (served) |
|---|---|---|---|
| page-03 cursive | 66.8% (conf 37) | 87.3% | 33.5% |
| page-10 cursive | 79.3% (conf 33) | 92.8% | 23.5% |
| postcard | 78.0% (conf 26) | 96.6% | 100% (no layout) |
| birth cert printed | 42.4% (conf 79) | 95.3% | 100% (no layout) |
| photo captions | garbage (707%) | 100% | 96.3% |

Verdicts:
1. kraken's historical-script models cannot read 20th-century family
   cursive (87-97% CER) — switching recognizers would be a regression.
2. tesseract is faithful-but-unable on cursive and genuinely useful on
   PRINTED forms (42% CER, and its confidence 79 vs 26-37 is exactly
   the research's point: confidence correlates with quality). Its
   confidence could be a second opinion on print pages; our own rec
   confidence should be used the same way.
3. Our pipeline's problem is COVERAGE (nothing serves for refused
   pages), not recognition quality — 2-3x better wherever it serves.
4. Transkribus (cloud, needs user account) remains the only untested
   option; local alternatives do not change the calculus.

## Transkribus trial: infrastructure verdict (2026-08-26)

The user created a Google-login account; Transkribus issues no API keys
— OIDC password-grant after setting an account password. Credentials
worked (token minted; legacy REST /rest/collections returned 200 with
the user's collections). But:

- The documented Text Recognition API (processing/v1; the docs' v2
  path 404s) REJECTS the token: its audience is TrpServer (legacy),
  not the processing service. Likely an account/API-activation issue
  on READ-COOP's side ("Get API access with a free account" — no
  self-serve activation found in the app).
- The legacy REST flow the token DOES authorize needs the full
  document lifecycle (create doc, multipart upload, HTR job, poll,
  fetch PAGE XML) and its model-listing endpoints 404 at every
  documented guess — real integration work on an under-documented API.

Verdict pending user choice: invest in the legacy flow (~an hour of
endpoint archaeology), or treat the head-to-head as settled on
tesseract/kraken/ours + the research (recognition quality is not the
gap — coverage is), or ask READ-COOP support how to enable the
processing API on a Google-login free account. Tunnel + file server
used for the abortive imageUrl path were torn down; the trial leg now
uses base64 (no tunnel needed).

## The self-report wired (2026-08-26, `03d7d3e`)

Research priority #1 done: the model's own doubt now flags words in the
served layouts — the UI's "red words" promise finally has data behind
it. Verified end-to-end: page-10 carries one flagged word ("blows"),
rendered as a .rv-wc button in the review surface.

Two bugs found along the way:
- the 64000-token default hangs this model on a page image (the trial
  report's budget finding again) — the doubt call is capped at 8000.
- the report's line numbers cite the RAW VLM text, which drifts from
  the layout's indices when the raw text has empty lines — the flag
  was silently lost; matching is now by WORD CONTENT.

Honest regression exposed: page-12's reprocess refuses on empty-label
rows under the strict glyph gate (the count-mismatch class, previously
hidden by the gate postdating its last write). Coverage now ~14 pages
serving; refusals loud and named.

## The rec-agreement lever: rejected with evidence (2026-08-26)

Research priority #2 (Consensus Entropy) probed empirically before
building: PP-OCRv6's confidence is MEANINGLESS on cursive — page-10's
pieces sit at score>=0.85 while reading "Aomeore says we should have"
for "someone says we should have" (30/32 detections above the gate).
Score-gating cannot separate the rec's good readings from its garbage;
agreement would flag 75-90% of cursive lines (the 2026-08-15 finding,
reproduced). On print (birth cert: 93/93 at 1.0, correct text) the rec
is a fine reader but agreement only confirms. Verdict: one strong
reader + one weak reader does not give Consensus Entropy; the
self-report remains the correct flag source. NOT BUILT — the probe is
the deliverable, saved a wasted implementation.

The rec's print-strength suggests the real next lever is the LABEL-
COMPLETENESS class instead: rows the VLM left unlabeled (empty-text
refusals — page-12, the birth certs) get a targeted per-row re-read
of their own clip, the eval_columns pattern, cached like everything
else.

## The row-read path + named refusals (2026-08-26, `96adf08`)

The birth-cert class cracked: 40 measured rows vs 16 VLM lines was
proportional matching smearing 16 lines over 40 rows (a 21px box
holding a 20-char label). When needs_row_reads fires (rows >= 10,
lines < 2/3 rows), every row gets its own clip read (parallel,
cached). Wide rows (aspect > 25:1) split at their PIECE gaps first —
each form cell is a detection piece; ink-column projections fail
because a full-width printed rule touches every column.

Refusals now NAME their gates (no-ink / multi-band / glyph) with
per-box label+size — the lumped "off-ink or multi-line" hid which gate
fired for weeks.

Results: 1781706319847 converted refused->written (32 lines);
1781706279582 28->2 failures. One page (1781706301316) is a known
hard case: its header row is a SINGLE rec piece (no per-cell pieces to
split) AND its column projection shows zero gaps (a full-width rule)
— neither segmentation mechanism can see the cells; logged with the
evidence rather than chased further.

## The fragment-box gate (2026-08-26, `861fce3`)

The last false-pass class closed at write time: 071639 served a box
over part of a caption while the rest of the line sat outside — ink
present, single band, plausible label, WRONG box (the vision audit
caught it twice; the cheap gates could not). fragment_violation
measures the FULL-WIDTH strip at the box's band: ink extending beyond
the box's x-edges by >0.4x its width = the box truncates the line.
Verified: 071639 now REFUSES with fragment=1 and every other gate
zero. The named-refusal message now reports all four gates.

Coverage: ~17 pages serving; every failure class that used to slip
through (offset, fragment, multi-line, stale provenance) now refuses
loudly with its name. Remaining research items: the calibration/eval
contract, and the one hard cert (1781706301316, single-piece header
row).

## The eval contract, settled (2026-08-26, `fa3c6b1`)

Three sessions blocked on the Caradog scoring contract; settled with
the first real calibration numbers. Contract: a served page's
transcription = LCS of normalized WORD TOKENS vs the reference, whole-
page (granularity-invariant). Why not line-level: the first settlement
scored vision-verified page-03 at 0.02 because handwriting wraps at
arbitrary points — the calibration instrument caught its own contract
bug, exactly the lesson the research predicted. Write-skip: refused
pages count as refused, never as wrong text.

First measured baseline (references outside the repo, real family
text): page-03 0.62, page-10 0.77, Silver Wedding 0.22, aggregate 0.68
on serving pages; postcard + birth cert refused. The archive-marked
regression gate fails if serving coverage drops below 0.55. Gates are
no longer incident-tuned heuristics without a yardstick — they now
have one.

## The box-coverage gate + the exactly-once finding (2026-08-26, `87e8739`)

The user's reframe refocused the whole effort: text errors are
fixable in the review UI, box errors are NOT (no box-fixing
interaction exists). Boxes are the hard contract. The new gate
(coverage_violations) measures it directly on the first full-archive
run:

- uncovered=0 on ALL 33 pages — no significant unboxed text region
  anywhere; the clustering preserves coverage (the noise_ratio=2.0
  filter tolerates rec over-detection specks).
- DOUBLE CLAIMS are rife: 33 overlapping box pairs on one page, 6-13
  on several, >1 on 17 pages. The 'exactly once' contract is
  violated pervasively — the real box-layer defect, quantified for
  the first time. Overlap resolution in assembly is the next
  mechanism.

Calibration item: the fragment gate false-positives on two-column /
annotation pages (page-01's margin notes at the same y trip the
full-width strip). Synthetic cases are handled; the real page needs
the labeled set — exactly what the eval instrument is for.

## Exactly-once resolution (2026-08-26, `a6238d7` + ordering fix)

The coverage gate quantified double claims (33 pairs on one page);
resolution landed at the source: merge_near_duplicate_rows (same
x-span + y-overlap >= 0.3 = one line detected twice) and the
sibling-aware fragment gate (outside ink with its own box is not this
line's continuation — page-01's margin notes). page-01: doubles 2->0,
fragments 14->2. page-09 remains at fragment=22 with distinct
geometry — the next calibration case, logged with the evidence rather
than a fourth mechanism attempt.

## The review-surface bugs from the user's session (2026-08-26, `8d9dbf0`)

Two user-reported bugs, both pinned by failing behavior tests first:

1. The approve tick needed TWO clicks on the letters' doc 0. Root
   cause: pages 01/02 are the REFUSED set — no layout. The surface
   falls back to raw guess lines, which render approve buttons, but
   applyMarkedFine's `if (!line) return` silently no-opped with
   layout?.lines undefined. The jsdom test WITH a layout passed —
   exactly the fixture gap that let it through; the layout-less
   fixture reproduced it.

2. Scrolling the image left the transcript behind. The image pane had
   NO wheel handler (overflow hidden, touch-action none): the wheel
   scrolled the page, session.view never moved, syncTxFromImage never
   fired. A wheel handler now pans view.y through renderView, which
   syncs the transcript. jsdom cannot lay out scroll, so the wheel
   test pins the pan (the layer transform changes); the sync's own
   units cover the transcript side.

Also logged: the browser tool's request interception wedged mid-
session (blank page after a navigation) — a tool-state issue, not the
app; the server itself was healthy throughout (DNS was the user's
earlier outage).

## The phone dual-pane report (2026-08-26, `80f70ee`)

"Scrolling the image view or the transcript view still does nothing
to the other one" — on the phone. Root cause: the letters' doc 0 is
the refused set (no layouts), and BOTH sync directions early-returned
on layout-less pages. No geometry = no boxes to pan to — but the
document still has POSITION. Both directions now use the fractional
fallback: the transcript's scroll fraction maps to the same fraction
of the page height, and back (feedback guarded by the existing <2px
early-return). Two failing behavior tests pinned it first (transcript
scroll -> layer pans; touch drag -> transcript scrolls). The
layout-bearing mobile path was unchanged (worked before) — the phone
report was the refused pages.

## The missed-region recall pass (2026-08-26, `1cb2b09`)

The user's requirement — the low-sensitivity detection runs ONLY on
pages/areas where boxes are known missing, and only AFTER the normal
pipeline — is built exactly so: fragment_regions returns the missed
areas (unclaimed outside ink at a box's band); the Phase-3 recall
branch fires only on fragment/glyph refusals, crops exactly those
regions (upscaled 2x), runs a second PaddleOCR at det_db_thresh 0.15
(created lazily after the main engine is freed), maps boxes back to
page space, merges, and re-assembles via the unified assemble()
closure.

Verified: fires with regions=6, recovers 3 margin pieces on page-01 —
but the reassembly still refuses. The recovered pieces are 25-38px
fragments: the margin notes sit below PP-OCRv5-mobile-det's recall
even at 0.15 with 2x upscale. The mechanism is gated and correct;
page-01's specific notes are a detector capability boundary. Next
levers: a larger upscale (4-8x), or a different detector (the rec's
deskew/quality options), or accepting the notes as a known-hard class
until the eval coverage gate measures them.

## The ink-layout: per-line x-run boxes for the dense-cursive class (`592c122`, 2026-08-28)

The user's structure insight: margin notes interleaving with the main
text is NORMAL for letters, and boxing them as a paragraph mangles the
sense. The ink-layout reads the page DIRECTLY (no detector pieces):
lines from the ADAPTIVE ink (a 4x4 block median - 35 — the has_ink
standard; the scan's shading is not ink), each line's FULL-WIDTH
x-runs with word-merge (80px): a line with a real gap becomes TWO
boxes (the item + its annotation, transcribed separately), a
continuous line stays ONE box. X-disjoint by construction — no
double-claims regardless of the y-interleaving (page-01's 11 doubles
from the piece model -> 0).

The gate fixes it demanded, all test-first:
- fragment_violation's outside-ink now counts DARK rows (PIL's
  getprojection is BOOLEAN; the 255-p sum counted the paper) with a
  text-sized minimum: the page-wide 1-3px specks flagged 23 of 32
  honest boxes. SIDE EFFECT: page-09's 22 phantom fragments were the
  same class — the BASE pipeline serves it now (23 lines).
- the ink path drops the shading boxes (has_ink), the decoration
  strips (min-height 25), the unreadable edge artifacts (empty
  labels); its boxes are ink-truth so the glyph gate + Gate B skip
  the label-read class (text errors are the reviewer's fix — the
  user's contract; the box-level gates vetted the geometry).

Overfitting validation (the user's question): the constants were
page-01-tuned but the gates refuse rather than fabricate success on
the other pages — page-01 written (36 boxes), page-09 written via the
BASE pipeline, pages 02/05/06 honestly refused (uncovered pieces after
the drops, over-split fragments). KNOWN CAVEAT: min_w/min_h are
absolute pixels (scale-dependent — the rest of the pipeline
normalizes); make them fractions of the measured line height for
non-300dpi scans.

Also: the batch's temp dirs moved to the WORK DISK (/tmp is a shared
3.6G tmpfs that fills with other sessions' work — 'Disk quota
exceeded' mid-batch; panels/tiles/clips now live in work/tmp, still
rmtree'd in finally).

## The dual-pane sync's third round: the fit zoom swallows the wheel (`b548be3`, 2026-08-28)

The user's report — page-01 serving (the ink-layout) but "it STILL
doesn't scroll the transcript when you scroll the image". Reproduced
with evidence in a fetch-mocked real-browser session against the REAL
page-01 layout: the fit's view.height (2376px) ~= the writing's height
(2336px) — the pan range is 25px of margin; the wheel's pan is
clamped, the visible line never changes, the transcript can never
follow.

The fix: when the view shows ~90%+ of the writing's vertical extent,
the wheel ZOOMS (the standard image-viewer behavior) — giving the
view a pan range, after which the pan + the transcript-follow work.
The condition measures the WRITING (the layout's line boxes), not the
page: the first attempt (the page-height range) still saw a 25px
'range' and stayed on the pan path — the writing-relative measure was
the correct one.

THE FRAGILITY (the user's question — three fixes, same symptom):
the dual-pane sync is a state machine (view, floor, offsets, lock)
whose transitions are environment-driven (the pane aspect decides the
fit; the render timing decides the offsets) — and the tests covered
only the pure functions (lineScrollFor, the pan), never the WIRING
(event -> view -> renderView -> sync -> scrollTop). The 2026-08-26
phone fix (the layout-less fractional sync), the resume-floor fix
(c92dfe0), and this one each patched a link in a chain no test
covered. The follow test (the wheel -> the transcript scrolls to the
line at the view's top) + the no-range zoom test now close the gap.
jsdom's layout limits forced a HTMLElement.prototype offsetTop stub
(Element.prototype is shadowed by jsdom; the renderTx re-creates the
line elements, so per-element stubs die with them).
