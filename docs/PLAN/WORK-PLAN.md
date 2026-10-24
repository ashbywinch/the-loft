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

### What landed — PR #64 and the object-model phase 3 (PR #67), both on `main`

The stage-4 drawing loop (UR1.4) end to end, carried by the phase-3
merge that also landed the object-model layout (`document/` the model,
`pipeline/` the functionality, `tools/` the CLIs), the rows'
transcription, the lucidlint debt to zero (0 fail / 0 warn), and the CI
and eval-contract fixes. Main's `build-and-test` is green.

| Piece | Where | What |
|---|---|---|
| The reading keeps its words | `pipeline/detect/reader.py` `Reading`/`reading_for_page`; `pipeline/chain.py` writes `<page>.words.json`; `pipeline/api/sync.py`'s reprocess writes it too and `rotate_page` remaps it | the correction's input (the read stage previously discarded the words) |
| The rows' text is transcribed | `pipeline/transcribe/transcripts.py` — `Transcriber.transcribe`: the page's rows numbered and tipped with a chip in the row's own colour over its tinted band, sent as bands that each carry exactly their rows, and MASKED crops for rows the bands leave unsettled (the row's own words, the rest painted over) — driven by `pipeline/chain.py`'s `_read_pages`; the eval is the same module's CLI | the guess's text indexed onto the rows put a sentence one row out wherever the rows and the text's lines ran differently; each row now answers for itself, transcribed once |
| The correction's library | `pipeline/rows/rows.py` `Rows.from_words(words, row_adjustments, page_size)` — DR1's agreed name, `build` is gone — over the model `Word` records (each carries its reading line; the parallel `baselines` list is retired); the measurement behind it is `_Claims` | no lines → the words' own line structure IS the draft rows; an incomplete line set merges with them (a row no drawn line claimed survives) |
| The API | `POST /api/sync/batch/{id}/page/{page}/row-adjustments`; `pipeline/api/sync.py` `apply_row_adjustments`; the lines are validated at the seam by `document/schemas.py`'s `validate_user_row_adjustments` (shared with the file loader); a wordless page is refused with the remedy, never silently emptied | draws → rows; persists the lines + the rows (`Rows.to_wire`, the `schemas.Rows` contract) beside the reading |
| The surface | `app/views/review.js`: draw mode (one finger draws, a second finger still pinches), **live merge on finger-lift** (no Apply step), tap a line to delete it, Clear → the draft rows; the drafts payload carries `row_adjustments` + `adjusted_rows` per page so a reopened page restores both | `app/ui.js` gained `polyline` in the SVG tag set — `el("polyline")` had been building an HTML element inside the `<svg>`, so the drawn lines never painted |
| Reader defect found and fixed | `pipeline/detect/reader.py` `_attach` numbered the marks against the unfiltered fit while indexing the filtered list it was handed (page-01: **39 rows vs 41 word-lines**; two real lines silently lost) | the proposal on the gold goes **39 rows / 92.3% → 41 rows / 94.5%**; the correction holds at **41 / 97.2%** |

Tests: the draft path, the merge and the wire round trip
(`tests/pipeline/test_rows.py`); the marks' line-index contract
(`tests/pipeline/test_reader.py` — fails on the old reader); the SVG
namespace of every shape the views draw (`app/tests/ui.test.js`); the
delete hit-test and its tolerance (`app/tests/views/review.test.js`). The
gold contract (`test_the_adjudicated_rows_are_reproduced`) is untouched.
Re-measure the two groupers when either changes:
`.venv/bin/python research/render_rows_gold.py`.

Smoke (manual, on a scratch `LOFT_DISK_ROOT` with a real page scan):
draw → the merged rows render on the lift; tap → the line is deleted;
Clear → the draft rows; a reload restores both the lines and the rows.

### What remains

| # | Item | State | Acceptance |
|---|---|---|---|
| 1.1 | `document/stages.py` — the Stage enum (object, artefact, human flag) + the Document and identity artefacts' schemas | **done** (this branch) | `document/stages.py`: the nine stages UR1 numbers 0–8, each with its object, its artefact, the `document/schemas.py` contracts that carry it, and its human flag; the page statuses (`new → oriented → marks → words → rows_draft → rows_pending`) name the stage they complete. `document/schemas.py`: the `Document`/`DocumentLine` contract — the states are a `Literal` (`review`/`confirmed`/`rejected`) and the writers/readers name them (`DOCUMENT_DRAFT`/`DOCUMENT_AGREED`/`DOCUMENT_REJECTED`), a line carries its box, its words, its kind and the line an injection follows. NO validator yet: a strict loader with no reader is dead weight, and the artefact's two entry shapes (the draft `{pages, greeting, signoff}` vs the registry's confirmed entry — the confirmation payload spread wholesale) are 1.3's to settle. The identity artefacts owed nothing — `tools/records.py` already types them (`Person`/`Place`/`Org`/`Relationship`, their tables, `validate_identity`). Tests: the stage list, numbering, human flags, contract names and status alignment (`tests/document/test_stages.py`) |
| 1.2 | `Rows.from_words` — the agreed classmethod name (DR1) | done (PR #64) | the rename + the no-adjustments draft path live; the typed `Traces` name landed in `document/schemas.py`; the `Rows.validate(traces)` fold is 1.4's remainder |
| 1.3 | Scan pickup (UR3): watcher + worker run orient → marks → words → draft rows → `rows_pending`. The row corrections are applied ON THE SERVER (`apply_row_adjustments` builds and persists them; the response is the apply the live merge needs). The server never contacts the worker — the worker picks the corrected rows up on its own next pass to transcribe them into the draft Document (the proposed-transcripts stage: each row's text, kind and injection target are read then) | not started | a dropped scan reaches the check-rows queue with no manual step |
| 1.4 | Drawing UI (stage 4) (design: `segment-review-stories.md`; the reference surface's rows flow) | mostly landed (PR #64): draw + live merge on lift + tap-to-delete + persistence through the row-adjustments seam. Remaining: the `rows_pending` status (1.3's), the `Rows.validate(traces)` fold of `pipeline/rows/boxjig.py`'s A1–A7 invariants (then delete the jig) | drawing fixes a wrong row; the adjustment persists through the typed seams |
| 1.5 | The portal: three doors + counts (rows to check / documents to review / identities proposed — unfinished memories ride the identities queue, per PRD §9 F10 / INGEST-PRD 2026-09-22) | not started | the home doors show the counts; each opens the right surface |
| 1.6 | Identification review (stage 8): proposed entities from agreed Documents → confirmations into the identity tables | not started (depends on 1.5) | confirmations land in `IDENTITY_TABLES` |
| 1.7 | Design task (DR2): where the non-per-page artefacts (identity tables, captured stories) live in the archive | undecided | a proposal showing each kind's home |
| 1.8 | PaddleOCR / `.venv-htr` remnants (ruling 2026-09-22: zero rec use) | **partly landed (2026-10-24)**: the dead helpers are gone (`load_vlm_boxes` and `word_conf` — no production caller; the `.venv-htr` interpreter left the layout path with the single pass), and so are the references this row listed: `pipeline/htr.py`'s docstring history, `pipeline/layout_apply_selfreport.py`'s comment, the `tests/test_eval_postcard.py` and `tests/test_standards.py` notes, plus `pyrefly.toml`'s excludes for three deleted files. **Remaining:** (a) `docs/TECHSPEC.md` still describes PaddleOCR's detector as the layout pass (§16.14/§16.17: lines ~968, ~979-983, ~1202) — the live description needs rewriting to the ink reader + the VLM; (b) the **cross-reader agreement fallback** is reachable but carries no signal — measured: with no self-report every word returns conf 1.0, because the detector no longer produces recognition words, so it agrees with itself; the open question is what a page with no self-report should report (today: certainty) | no PaddleOCR or `.venv-htr` reference in the served path, tests, or docs, and a defined confidence for a page with no self-report |
| 1.9 | The lucidlint gate's acknowledged families — `noqa` cleared and **`record-shape` FIXED IN CODE** (both 2026-10-17, the user's ruling: rewriting per the rule IS the point). Every record is now a class in a file named after it, owning its wire format (`from_dict`/`to_dict`); `document/schemas.py` (a TypedDict bag) is dissolved; ~150 record modules landed across `document/`, `pipeline/`, `tools/`, `research/` — the server's route answers and request bodies, the layout/detection/reader measurement records, the model's chat/answer/usage records, the identity and archive records (the archive's public seams now take and return `Item`/`Person`/`Place`/`PeopleTable`/…). The rule still reports ~336 findings, **305 of them the tool's own bug** (§1.5 of the review log: it fires on `from_dict(cls, raw: dict[str, Any])`, `to_dict(self) -> dict[str, Any]` and the literal that method builds — exactly what its message prescribes; the rest are return annotations naming a record's wire). The rule stays config-ignored for that bug only. Still config-ignored, each with a written why in `.lucidlint.toml` + `docs/PLAN/lucidlint-review-log.md`: `standard` 257 (all "referenced only from tests" — the DI/eval-harness convention; ~38 verified: test-driven seams and strip-era dead code, 1.8's territory), `magic-number` 162 (62 are tuple subscripts; the rest arithmetic/geometry), `fakefs` 197 (the testing standards' real-FS tests), `unused` 47 (in-module references — §1.2), `long-param-list` 10, `latent-class` 8, `vague-name` 4 (`Store`, sanctioned), the rest single digits. Every ignore off: 789 actions, down from 1098 | awaiting the ruling on the remaining collision families | the gate's verdict reflects only real debt |

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
| 3.4 | Word-cutting remnants (`tests/pipeline/test_reader.py`): word 9690 (ruled two words; the pipeline keeps one — targeted fix, deliberately not a page-wide rule); the y3640 nested-pair weld ((1164,3640,1386,3688) ⊃ (1314,3646,1348,3680)) — two words still fused | open |

## 4. Rulings (2026-09-22) — directions closed

- **PaddleOCR: zero use.** The rec is not a reader, not a fallback, not a
  check (1.8 removes its remnants; the rec-dependent research priorities
  are ruled out — `ocr-verification-research.md`).
- **Review edits store the transcription.** Edits are the correct text,
  stored as such; they will never feed a model (no retraining or
  calibration loop).
- **Transkribus is not a reference.**

Loose ends that fit neither plan: `SCRAPS.md`.
