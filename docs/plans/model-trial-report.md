# The layout geometry: what we learned and where we're going

Status: IN PROGRESS (2026-08-22) — the model trial's verdict is in; the
postcard's geometry has a proposed spike (§7).

This report is about one question: **how do we get a box around every
line of handwriting, aligned with the text, for family documents
(letters and postcards)?** It records the attempts, what each taught us,
the model comparison, and the proposed way forward. The running
experiment log (the what-we-tried-when ledger) is
`docs/plans/geometry-experiments-log.md`.

## 1. The goal and the two test documents

The review surface shows each scanned page as an image with line boxes
and a transcription. The pipeline must produce, per page: the **text**
and a **box per line of text**. This report is about the box half.

Two documents define the problem space:

- **The letter** (page-03): single-orientation handwriting, with a
  margin callout block top-left and an address block top-right.
- **The postcard**: printed top, a handwritten message at ~90°, an
  address, and vertical printed text down the center. Genuinely
  multi-orientation.

## 2. The pipeline and why its geometry broke

Three engines are involved:

- **The vision model (VLM)** — a cloud multimodal model. Reads cursive
  handwriting well; produces text and boxes from an image.
- **The rec** — PaddleOCR, a local OCR engine. Measures ink precisely
  (its detection boxes are real) but cannot read cursive (its text is
  garbage on handwriting).
- **The layout pass** — fuses the two.

Two structural facts broke the geometry:

1. **The VLM cannot measure a whole page.** Asked for per-line boxes on
   a full page, it returned a *schematic*: page-01's entire letter came
   back squeezed into the top 31-80% of its output canvas, so the
   rescale placed boxes 500-770px from the real text. The model can
   *read* a page but not *measure* it at full-page scale.
2. **The fusion requires matching the rec's text against the VLM's
   text** — and the rec cannot read cursive, so its text barely
   overlaps the VLM's. The matching fails exactly on the hardest pages;
   the fallback (position-based pairing) mispairs when the rec's
   detection count differs from the line count (17 merged detections vs
   31 lines on page-01).

## 3. What we tried, and what each attempt taught us

### 3.1 The full-page location report (the VLM's boxes for the whole page)
Tried because the VLM reads the text, so its own boxes should anchor it.
Result: schematic boxes (the squeezed canvas above); the gates had to
refuse the layouts. **Lesson: the model's geometry is only trustworthy
when the question is local — a crop, not a whole page.**

### 3.2 The rec's detection boxes as the geometry
Tried because the rec's ink boxes are real. Result: the boxes are real
but merged (one tall box per 2-4 lines) and the rec's text is
unreadable, so matching them to the VLM's lines fails; position-based
pairing mispairs. **Lesson: cross-engine text matching is the broken
seam — we need text and geometry from the same source.**

### 3.3 The arbitration rules and the gates (the patch era)
Tried because refusing whole pages was too coarse: an Anchor
arbitration, fail-fast gates (A-F), ink-presence and duplicate-region
drops. Result: the gates correctly refuse bad layouts (honest, never
silent bad data) but the pages stay unserved; the "boxless line" is the
arbitration saying *no candidate holds this text*. **Lesson: patching
the fusion fixes symptoms, not geometry — and the fail-fast gates are
the right backstop but the wrong first line of defense.**

### 3.4 The clip-location experiment (locate lines within clips)
Tried as the first "local geometry" idea: clip each known line, ask the
model for the clip's box. The simulation (a perfect local locator)
held accuracy. The real calls failed on **call mechanics**: multi-image
prompts spiraled (the model's reasoning consumed the 8000-token budget
and returned empty content), and single-image calls were slow (5 calls
in 25 minutes). **Lesson: the concept was right, the batching was
wrong — use sequential single-image calls.**

### 3.5 The crop-grid (measure locally, stitch globally)
The current approach: divide the page's ink region into overlapping
crops; read each crop with the VLM (text + boxes in the crop's own
frame); map the crop-local boxes into the page frame (the stitch);
drop the duplicates; order the lines. On page-01 (the current model):
**0 boxless lines** (the pipeline had 9), **67 lines** (the guess had
31) — the whole letter read, including margin notes and the bottom tail
the pipeline missed — with clean text. The boxes were approximate:
about half aligned one-line, the rest merged or slightly off.
**Lesson: local measurement gives complete coverage and good text; but
the model's boxes are attention-drawings, not measurements — the model
choice matters for box quality.**

### 3.6 The model trial (this report's experiment, §4)
Five models, the same crop-grid, two tasks. Result: every model gave 0
boxless; the models differed sharply in box quality; none handled the
postcard's rotated message. **Lesson: on upright text, glm-4.6v's line
segmentation is excellent; rotated text defeats upright reads — the
postcard needs reads at the text's own orientation.**

Operational learnings along the way: the crop read's completion budget
is 8000 tokens (64000 exceeds smaller models' context once the image is
in); the crop grid is anchored to the ink extent so blank margins are
never read; the IoU comparison must use text-matched pairs (and is
meaningless on the postcard, whose readings are scrambled for every
model).

## 4. The model trial — 5 models × 2 tasks

The same crop-grid, sequential single-image calls, via OpenRouter.
Task A: the letter (page-03). Task B: the postcard.

| model | task | lines | boxless | tokens | time | IoU* | visual result |
|---|---|---|---|---|---|---|---|
| **glm-4.6v** | letter | 54 | 0 | 23,646 | 525s | 0.751 | ~100% one-line aligned boxes; callout + address boxed |
| | postcard | 23 | 0 | 15,964 | 248s | 0.961 | message fragmented into words |
| **glm-4.5v** | letter | 49 | 0 | 17,189 | 237s | 0.765 | top ~90% clean; bottom third fragments |
| | postcard | 37 | 0 | 29,148 | 301s | 0.940 | message fragmented; address mostly missed |
| **qwen2.5-vl-72b** | letter | 57 | 0 | 9,112 | 56s | 0.634 | spatially right but every line split into word groups |
| | postcard | 17 | 0 | 7,922 | 24s | 0.269 | fragmented |
| **gpt-4.1-mini** | letter | 53 | 0 | 9,107 | 39s | 0.489 | middling; only 8 lines on the postcard |
| | postcard | 8 | 0 | 9,000 | 31s | 0.400 | sparse |
| **gpt-4o-mini** | letter | 54 | 0 | 156,089 | 41s | 0.334 | poor boxes; ~10× the tokens of everyone |
| | postcard | 9 | 0 | 185,554 | 37s | 0.883 | sparse |

\*IoU = box overlap against the current layout's rec-ink boxes, averaged
over the text-matched pairs only (exact normalized-text match). The
postcard's readings are scrambled for every model (1-2 matched pairs),
so its IoU reflects only the printed lines and is not comparable.

Baseline: the current image model (Mimo) on page-01 — 67 lines, 0
boxless, ~27k tokens, ~6 min, about half the boxes approximate.

**Verdict:** every model achieves full coverage (0 boxless) — the
crop-grid works regardless of the model. The model matters for box
*quality*. On upright text, **glm-4.6v is the winner** (~100% one-line
boxes on the letter). qwen is far faster and cheaper but fragments
lines into word groups. The OpenAI pair is the worst (and gpt-4o-mini
costs ~10× the tokens). Recommendation: route the image model to
`z-ai/glm-4.6v` (or `glm-4.5v` if speed/cost matter more).

## 5. Why the postcard still fails

The crop-grid reads every crop in its natural orientation. The
postcard's message is at ~90° and the vertical center text at 90°, so
the model sees rotated text, which it fragments into words, and its
boxes do not align with the ink. The letter works because its text is
already horizontal. The postcard fails because its text is not — a
model-picking fix cannot solve that.

## 6. The proposed pipeline — read each crop at its own text orientation

The idea that unifies the two documents, without classifying the
document type in advance:

For each page:

1. Find the ink region (the rec's detection, or the current layout's
   boxes) and divide it into overlapping crops.
2. **Read each crop with the VLM.** The read returns the lines' text
   and their boxes within the crop.
3. **Check the read's boxes for orientation.** A box that is much
   taller than wide means the text in it is vertical, not horizontal.
4. **If the text is rotated, rotate the crop so it is horizontal and
   read it again.** This is the step the postcard needs: the models
   segment text into clean lines only when it is horizontal.
5. Map each crop's boxes into the page frame (the stitch).
6. Drop the duplicates (lines read in overlapping crops).
7. Order the lines (the block-aware reading order).

How the two documents flow through this:

- **The letter:** every crop's text is already horizontal, so step 4
  never triggers — the reads are exactly the ones the trial measured
  (glm-4.6v: ~100% one-line boxes).
- **The postcard:** the message crop's text is vertical, so step 4
  rotates it, the model reads horizontal text and segments it into
  lines, and step 5 maps the boxes back into the page frame.

The pipeline never asks "is this a letter or a postcard?" It asks each
crop the same question — "which way is the text?" — and reads
accordingly. One misclassification costs one crop, not the page. The
rec stays as the backstop (its ink finds regions the crops missed).

## 7. The next experiment (spike)

**Question:** does reading the postcard's message crop rotated-upright
fix the fragmentation and produce aligned, one-line boxes?

**Steps:**
1. Take the message crop from the postcard (the left region, whose text
   is ~90° per the orientation report).
2. Rotate it 90° so the text is horizontal (the rotation and its
   inverse are already implemented and test-pinned).
3. Read it with glm-4.6v — text and crop-local boxes, now on horizontal
   text.
4. Remap the boxes back through the rotation into the page frame.
5. Compare against the upright read from the trial (fragmented): line
   count, one-line-per-box on the image, agreement with the rec's ink.

**What the result decides:** if the rotated read segments the message
cleanly, we build the per-crop orientation step (§6.3-6.4) into the
pipeline. If not, the postcard needs a different idea — and the spike
tells us that with one rotated read instead of a full build.

## 8. Open items

- The spike's run on the postcard (§7).
- The per-crop orientation check's accuracy (the model's box aspect as
  the signal, vs the orientation report's regions).
- The reading order for the two-column letter (the block-aware order
  exists but the crop-grid's grid order reads the left column first).
- The self-report stage (a second VLM read flagging unsure words) is
  built but never run by the process — a cheap quality win independent
  of the geometry work.
