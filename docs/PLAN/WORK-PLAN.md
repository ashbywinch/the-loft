# The current work — remaining on the active subset

The living plan for what's left on the current PRD subset: the ingest →
transcription → identity pipeline. The full-PRD plan is `PLAN.md`; the
folder's map is `README.md`. Detailed designs are linked per item.

Every item lands with the repo's test conventions (`make test`). Ordered
by dependency.

## 1. The typed pipeline (design: `pipeline-stages-plan.md`)

Ordered by dependency; step 4 landed early because the row correction
was the live work — steps 1–3 are its prerequisites and are still
unbuilt.

### What landed — PR #64 (`feat/row-adjustments`; on `loft/feat/row-adjustments`, NOT yet on `main`)

The stage-4 drawing loop (UR1.4) end to end:

| Piece | Where | What |
|---|---|---|
| The reading keeps its words | `tools/reader.py` `Reading`/`reading_for_page`; `tools/pipeline.py` writes `<page>.words.json`; `tools/sync.py`'s reprocess writes it too and `rotate_page` remaps it | the correction's input (the read stage previously discarded the words) |
| The correction's library | `tools/rows.py` `Rows.from_words(words, row_adjustments, page_size)` — DR1's agreed name, `build` is gone — over the model `Word` records (each carries its reading line; the parallel `baselines` list is retired); the measurement behind it is `_Claims` | no lines → the words' own line structure IS the draft rows; an incomplete line set merges with them (a row no drawn line claimed survives) |
| The API | `POST /api/sync/batch/{id}/page/{page}/row-adjustments`; the lines are validated at the seam by `schemas.validate_user_row_adjustments` (shared with the file loader); a wordless page is refused with the remedy, never silently emptied | draws → rows; persists the lines + the rows (`Rows.to_wire`, the `schemas.Rows` contract) beside the reading |
| The surface | `app/views/review.js`: draw mode (one finger draws, a second finger still pinches), **live merge on finger-lift** (no Apply step), tap a line to delete it, Clear → the draft rows; the drafts payload carries `row_adjustments` + `adjusted_rows` per page so a reopened page restores both | `app/ui.js` gained `polyline` in the SVG tag set — `el("polyline")` had been building an HTML element inside the `<svg>`, so the drawn lines never painted |
| Reader defect found and fixed | `tools/reader.py` `_attach` numbered the marks against the unfiltered fit while indexing the filtered list it was handed (page-01: **39 rows vs 41 word-lines**; two real lines silently lost) | the proposal on the gold goes **39 rows / 92.3% → 41 rows / 94.5%**; the correction holds at **41 / 97.2%** |

Tests: the draft path, the merge and the wire round trip
(`tests/test_rows.py`); the marks' line-index contract
(`tests/test_reader.py` — fails on the old reader); the SVG namespace of
every shape the views draw (`app/tests/ui.test.js`); the delete hit-test
and its tolerance (`app/tests/views/review.test.js`). The gold contract
(`test_the_adjudicated_rows_are_reproduced`) is untouched. Re-measure the
two groupers when either changes: `.venv/bin/python research/render_rows_gold.py`.

Smoke (manual, on a scratch `LOFT_DISK_ROOT` with a real page scan):
draw → the merged rows render on the lift; tap → the line is deleted;
Clear → the draft rows; a reload restores both the lines and the rows.

### What remains

| # | Item | State | Acceptance |
|---|---|---|---|
| 1.1 | `tools/stages.py` — the Stage enum (object, artefact, human flag) + the Document and identity artefacts' schemas | not started | typed scaffold, no behaviour change |
| 1.2 | `Rows.from_words` — the agreed classmethod name (DR1) | done (PR #64) | the rename + the no-adjustments draft path live; the `Traces` naming and the `Rows.validate(traces)` fold (boxjig's A1–A7 invariants; delete `boxjig.py`) are part of 1.4's remainder |
| 1.3 | Scan pickup (UR3): watcher + worker run orient → marks → words → draft rows → `rows_pending`. When it lands, move the row build out of the server (today `apply_row_adjustments` builds inline; the plan's seam = the server records the adjustment and marks the page, the worker rebuilds) | not started | a dropped scan reaches the check-rows queue with no manual step |
| 1.4 | Drawing UI (stage 4) (design: `segment-review-stories.md`; the reference surface's rows flow) | mostly landed (PR #64): draw + live merge on lift + tap-to-delete + persistence through the row-adjustments seam. Remaining: the typed `Traces` name, the `rows_pending` status (1.3's), the boxjig fold (above) | drawing fixes a wrong row; the adjustment persists through the typed seams |
| 1.5 | The portal: three doors + counts (rows to check / documents to review / identities proposed — unfinished memories ride the identities queue, per PRD §9 F10 / INGEST-PRD 2026-09-22) | not started | the home doors show the counts; each opens the right surface |
| 1.6 | Identification review (stage 8): proposed entities from agreed Documents → confirmations into the identity tables | not started (depends on 1.5) | confirmations land in `IDENTITY_TABLES` |
| 1.7 | Design task (DR2): where the non-per-page artefacts (identity tables, captured stories) live in the archive | undecided | a proposal showing each kind's home |
| 1.8 | PaddleOCR remnants (ruling 2026-09-22: zero rec use) — remove the vestigial references: `layout_stage.py`'s stale ".venv-htr" docstring + paddle FLAGS env; `pipeline.py`'s stale comment; the cross-reader agreement fallback in `layout.py` (verify it is dead in the single-pass path, then delete); `test_layout.py`'s `_stub_paddleocr` no-op | not started | no paddleocr reference or stub in the served path or tests |

PR #64's merge: rebase-merge onto `loft/main` when `build-and-test` +
`pr-review` are green (merge commits are refused); it is not landed yet.

## 2. The ingest review — the claim model (design: `INGEST-PLAN.md`)

Slices 1–6 (identity → disposition → population → closed; pre-answered
claims; discovery; compound-claim decomposition; closure). **None
landed** — the review chat still runs the disposition-first walk; the
review-chat findings R1–R14 (`ux-fixes-plan.md`) stay open until these
land.

Unfinished memories (PRD §9 F10) enter this same review — the same
queue, the same walk (INGEST-PRD ruling: an unfinished
memory may simply have more to tell; the conversation is the same one
that elicits further memories about the item and the identities that
emerge).

## 3. Layout and measurement seams (records: `strip-grouping-plan.md` postmortem; `geometry-experiments-log.md`; `design-decisions.md`)

| # | Seam | State |
|---|---|---|
| 3.1 | Cursive/rotated-page measurement — the served ink-projection primitive measures upright text only; the Godolphin 90° message is unmeasured; the orli rotated pass hallucinated and was deleted | REOPENED |
| 3.2 | RegionGate vs grouped boxes — bands may overlap in y across columns; whether the typed-page Gate B allowance extends here | undecided |
| 3.3 | Tight-schedule multi-line bands — page-01's tight section measures merged; the grouping model transcribes multi-line segments (L3 violated in the serve; the reviewer sees it; 287 doubt-flags awaiting review) | known limitation |
| 3.4 | Word-cutting remnants (`tests/test_reader.py`): word 9690 (ruled two words; the pipeline keeps one — targeted fix, deliberately not a page-wide rule); the y3640 nested-pair weld ((1164,3640,1386,3688) ⊃ (1314,3646,1348,3680)) — two words still fused | open |

## 4. Rulings (2026-09-22) — directions closed

- **PaddleOCR: zero use.** The rec is not a reader, not a fallback, not a
  check (1.8 removes its remnants; the rec-dependent research priorities
  are ruled out — `ocr-verification-research.md`).
- **Review edits store the transcription.** Edits are the correct text,
  stored as such; they will never feed a model (no retraining or
  calibration loop).
- **Transkribus is not a reference.**

Loose ends that fit neither plan: `SCRAPS.md`.