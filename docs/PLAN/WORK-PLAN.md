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
| 1.2 | `Rows.from_words` — the agreed classmethod name (DR1) | done (PR #64) | the rename + the no-adjustments draft path live; `Traces` (`document/traces.py`) is the correction's three inputs as one value, read by `Rows.from_traces`/`Rows.validate` |
| 1.3 | Scan pickup (UR3): watcher + worker run orient → marks → words → draft rows → `rows_pending`. The row corrections are applied ON THE SERVER (`apply_row_adjustments` builds and persists them; the response is the apply the live merge needs). The server never contacts the worker — the worker picks the corrected rows up on its own next pass to transcribe them into the draft Document (the proposed-transcripts stage: each row's text, kind and injection target are read then) | **landed (2026-10-27)**: `pipeline/worker.py`'s `Worker` — `pickup()` registers every pile in the scan area (adoption hashes in place; already-registered is a no-op), `run_pending()` runs each `pending` record through `BatchRun.process`, `watch(interval)` repeats the sweep, and `loft work [--watch N]` is the operator surface. The queue is the records; the page's status is the derived ladder (`BatchReadings.page_status`, 2026-10-27). A scan stages beside the inbox (a directory in the scan area is a finished pile), and a failed pass returns its record to `pending`, so the next sweep retries it. Smoke on a scratch root: a dropped pile registers and runs; the pass fails loudly on a fake page and the next sweep retries it. The full machine pass (model + real scans) is the chain's own (its tests + the transcription eval). REMAINING half of this item: a user write does not yet mark its batch for re-processing and the proposed-transcripts stage is unbuilt — `apply_row_adjustments` persists the correction, but nothing sets the record to `pending`, and `process` would skip a page whose rows exist, so the corrected rows are not yet transcribed into the draft Document | a dropped scan reaches the check-rows queue with no manual step |
| 1.4 | Drawing UI (stage 4) (design: `segment-review-stories.md`; the reference surface's rows flow) | mostly landed (PR #64): draw + live merge on lift + tap-to-delete + persistence through the row-adjustments seam; the `rows_pending` status is derived (1.3); the check has its own control: "Rows are right" records the page's check with whatever is drawn (nothing, when the draft rows are correct), the toolbar states "checked" once the page's two check files are on disk (and after a reload, from the payload), and it wraps rather than running off a phone's pane. `Rows.validate(traces)` runs on every correction (`apply_row_adjustments` returns a `RowCorrection`): the answer names a line that caught no writing, one that merges reading lines, one off the writing's slope or a row off the page, and the surface shows the first violation in the toolbar. The jig is gone; its box-against-line checks are structure now (a band IS its words' union). | drawing fixes a wrong row; the adjustment persists through the typed seams |
| 1.5 | The portal: three doors + counts (rows to check / documents to review / identities proposed — unfinished memories ride the identities queue, per PRD §9 F10 / INGEST-PRD 2026-09-22) | **landed**: `/api/sync/batches` carries `pages_pending` (the page names, not a count), home renders one door per item with its count, and each door opens the surface that clears it — the first page's draw view (`#/review/<batch>/<doc>/<page>`), the first document's transcript gate, or the import session whose proposed identities and unfinished stories ride that queue; the review hub carries the same items as sections ("Check the rows" lists the batches with pages to check, even when every document is confirmed) | the home doors show the counts; each opens the right surface |
| 1.6 | Identification review (stage 8): proposed entities from agreed Documents → confirmations into the identity tables | not started (depends on 1.5) | confirmations land in `IDENTITY_TABLES` |
| 1.7 | Design task (DR2): where the non-per-page artefacts (identity tables, captured stories) live in the archive | undecided | a proposal showing each kind's home |
| 1.8 | PaddleOCR / `.venv-htr` remnants (ruling 2026-09-22: zero rec use) | **done (2026-10-26)**: the dead helpers are gone (`load_vlm_boxes`, `word_conf`, the per-word `rec_words` fallback), the `.venv-htr` interpreter left the layout path with the single pass, the references are cleared from `htr.py`, `layout_apply_selfreport.py`, the two test files and `pyrefly.toml`, `docs/TECHSPEC.md` §16.16 now describes the ink reader and the VLM, and the **cross-reader agreement fallback is deleted** — the self-report is retried once and then the page carries no flags (user: no fallback; no flag is not a claim of certainty) | no PaddleOCR or `.venv-htr` reference in the served path or the tests; dated records keep their history |
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

**The review prompt's rules, and the evals' draw dependence.** A review
condition can fail on one draw and pass on the next with no code change, so a
red eval is treated as a prompt defect to fix at the source, never as a draw to
retry. The rules the prompt now states, each verified by one eval run over
every review condition plus the arc and the caching cross-check:

- the family reads their own language (this archive: English), and a quotation
  stays in the document's words, untranslated;
- relevance is judged by what the statement NAMES — a person or a family event
  in it; a place alone is not enough, and a record sharing the place's word
  does not make it so;
- an attested event carries its subject: a statement that hands that death to
  someone else contradicts the record even though the archive says nothing
  about the other person, and a same-name ambiguity buys no pass (ask in the
  question AND still flag);
- an exhausted reviewer gets a statement, never a question.

A failed draw is diagnosable from the CI log: the condition's message carries
the whole verdict (`ReviewRun.verdict`, `tests/pipeline/test_eval_review.py`),
and the gateway's per-request log keeps the model's own `reasoning`
(`skill://cloudflare-ai-gateway-analytics`). Open: the walk's stability under
draw (the arc's stalled turn, the second-Walter ambiguity) belongs to this
slice's own session.

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
