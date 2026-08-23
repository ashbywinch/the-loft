# Model Trial Report — the crop-grid geometry rework

Status: IN PROGRESS (2026-08-22) — the trial's verdict is in (route the
image model to `z-ai/glm-4.6v`); the postcard's geometry is an open
problem with a spike proposal (§6-7).

The running experiment ledger: `docs/plans/geometry-experiments-log.md`.

## 1. The problem

The layout pipeline fuses two engines whose capabilities barely overlap:
the VLM reads cursive well but its **full-page** geometry is schematic
(the location report squeezed page-01's whole letter into the top 31-80%
of its output canvas — boxes landed 500-770px off), and the rec
(PaddleOCR) measures real ink but cannot read cursive (17 merged
detections vs the guess's 31 lines). The cross-engine fusion is where
every fix-up has landed.

The hypothesis (tested in the ledger): **measure locally, stitch
globally** — read the page as a grid of crops; the model's geometry is
trustworthy only when the question is LOCAL (a crop ≈ the model's
canvas); stitch the crop-local boxes into the page.

## 2. What the crop-grid already proved (Phase 1-2, page-01)

- The stitch (`stitch_crop_box`) is exact — the synthetic fixture
  anchors at IoU 1.00.
- The real run (the current Mimo model, 6 crops, ~27k tokens, ~6 min):
  **0 boxless** (vs the pipeline's 9), 67 lines (vs the guess's 31) —
  the whole letter read, text clean. The boxes are approximate (the
  visual: ~half one-line, the rest merged/offset) — the model's local
  boxes are attention-drawings, not measurements.

## 3. The model trial — 5 vision models × 2 tasks

The same crop-grid, sequential single-image calls (the proven shape —
multi-image prompts spiral), via OpenRouter. Task A: **page-03** — the
callout-box letter (the P.S. margin top-left, the address top-right, the
body). Task B: **the 201024 postcard** — the printed top, the 90°
message, the address, the vertical center text.

| model | task | lines | boxless | tokens | time | IoU* | visual |
|---|---|---|---|---|---|---|---|
| **glm-4.6v** | letter | 54 | 0 | 23,646 | 525s | 0.751 | ~100% one-line boxes; callout + address boxed |
| | postcard | 23 | 0 | 15,964 | 248s | 0.961 | message fragmented into words |
| **glm-4.5v** | letter | 49 | 0 | 17,189 | 237s | 0.765 | top ~90% clean; bottom third fragments |
| | postcard | 37 | 0 | 29,148 | 301s | 0.940 | message fragmented; address mostly missed |
| **qwen2.5-vl-72b** | letter | 57 | 0 | 9,112 | 56s | 0.634 | spatially right but every line split into word groups |
| | postcard | 17 | 0 | 7,922 | 24s | 0.269 | fragmented |
| **gpt-4.1-mini** | letter | 53 | 0 | 9,107 | 39s | 0.489 | middling; sparse postcard reading (8 lines) |
| | postcard | 8 | 0 | 9,000 | 31s | 0.400 | |
| **gpt-4o-mini** | letter | 54 | 0 | 156,089 | 41s | 0.334 | poor boxes; ~10× the tokens of everyone |
| | postcard | 9 | 0 | 185,554 | 37s | 0.883 | |

*IoU is over the text-matched pairs only (exact normalized-text match vs
the current layout's rec-ink boxes). The postcard's readings are
scrambled for every model (1-2 matched) — its IoU reflects only the
printed lines and is not comparable to the letter's.

Baseline for reference: the current Mimo (`dynamic/image`) on page-01 —
67 lines, 0 boxless, 27.4k tokens, ~6 min, ~half the boxes approximate.

## 4. The verdict

- **Every model: 0 boxless** — the crop-grid's coverage holds across the
  board. The model only matters for the box *quality*.
- **The letter (task A): glm-4.6v wins outright** — ~100% one-line
  aligned boxes, the callout and the address boxed. glm-4.5v is close
  (top excellent, bottom fragmented) at a third of the time. qwen is
  fast and cheap but fragments every line into word groups — not line
  boxes. The OpenAI pair is the worst (and gpt-4o-mini costs ~10× the
  tokens).
- **The postcard (task B): none of the models segment the message
  cleanly.** The 90° message + the address defeat the upright crop
  reads — a model-picking fix cannot solve it.
- **Recommendation (user's route): image model → `z-ai/glm-4.6v`**
  (glm-4.5v if the speed/cost matter more).

## 5. Why the postcard fails

The crop-grid reads each crop UPRIGHT. The postcard's message is at
~90° and the vertical center text at 90° — the model sees rotated text,
fragments it into words, and its boxes don't align with the ink. The
letter works because it is single-orientation; the postcard is genuinely
multi (the orientation report's degrees {0, 90, 180, 270}).

## 6. Spike proposal — the orientation-aware crop-grid

Extend the crop-grid so each crop is read at the text's OWN orientation:

1. The content-anchored crops (existing).
2. **Per-crop orientation**: the crop's dominant text orientation — from
   the orientation report's regions where present, else the model's own
   first-read boxes' aspect (a tall box = vertical text).
3. **The rotated read**: rotate the crop UPRIGHT by its orientation,
   read it (glm-4.6v), get the text + crop-local boxes.
4. **The remap**: the rotation's inverse back into the page frame —
   `remap_box`/`rotate_detections` already exist and are test-pinned.
5. The stitch + the cross-crop dedupe + the block-aware reading order
   (existing).

The spike's questions: (a) does the upright read fix the message's
fragmentation and produce aligned boxes? (b) the per-crop orientation's
accuracy (the clip classifier was flaky on misplaced clips — measure it
on real crops); (c) the remap's exactness through the crop grid.

## 7. The fit with the letter — the unified pipeline

We won't know the document type in advance, and we don't need to: **one
pipeline** — the crop-grid + the per-crop orientation:

- A single-orientation letter: every crop classifies 0° → upright reads
  (the current behavior, the trial's proven quality with glm-4.6v).
- A multi-orientation postcard: the crops classify their rotations →
  rotated reads → the remap.
- The classification is the only seam, and it is local (per crop), so a
  misclassification costs one crop, not the page.

The rec stays the backstop (its ink finds regions the crops missed; the
clip path labels them). The outcome for both document types: lines with
text + page-frame boxes, from the model that read them — no cross-engine
text matching, no schematic global geometry.

## 8. Open items

- The spike's run on the postcard (the orientation-aware reads).
- The per-crop orientation's accuracy measurement.
- The reading order for the two-column letter (the block-aware order).
- The self-report stage is still never run by the process (a cheap
  quality win, independent of the geometry work).
