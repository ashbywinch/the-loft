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
verification: the green strips align with the message's vertical lines
(one per line), the HERNSPETH vertical center strip, and the
With-Greetings strip — none fundamentally misplaced. THE BOXES ARE
RIGHT, from the rec's ink, not the model's attention.

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
