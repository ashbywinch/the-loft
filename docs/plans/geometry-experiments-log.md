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
