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
| 1.3 | Scan pickup (UR3): watcher + worker run orient → marks → words → draft rows → `rows_pending`. The row corrections are applied ON THE SERVER (`apply_row_adjustments` builds and persists them; the response is the apply the live merge needs). The server never contacts the worker — the worker picks the corrected rows up on its own next pass to transcribe them into the draft Document (the proposed-transcripts stage: each row's text, kind and injection target are read then) | **landed (2026-10-27; requeue + corrected re-read 2026-10-29)**: `pipeline/worker.py`'s `Worker` — `pickup()` registers every pile in the scan area (adoption hashes in place; already-registered is a no-op), `Reconciler` runs each batch's missing stages through `BatchRun.process`, `watch(interval)` repeats the sweep, and `loft work [--watch N]` is the operator surface. The queue is the records; the page's status is the derived ladder (`BatchReadings.page_status`, 2026-10-27). A scan stages beside the inbox (a directory in the scan area is a finished pile), and a failed pass returns its record to `pending`, so the next sweep retries it. **A killed pass cannot reset its record**: the chain stamps when a pass goes `processing` — the start, its pid and its host — and the sweep returns the record to `pending` when the pass's own process is gone on this host (a dead pid decides, however recent the stamp: a read killed after 40 minutes must not look live for six hours) or, for a pass stamped on another machine, when the stamp is older than six hours; a record with no stamp predates the stamping. `review` is never touched automatically, because it may be a person's work in progress. A batch finished with, or left `review` by a tool before the rows stage, re-enters explicitly — `loft work --requeue <batch-id>` (`pipeline/registry.py` `set_status`; the CLI requeues, then sweeps). **The corrected rows are re-read**: a drawn line marks its batch `pending` (`apply_row_adjustments`), and the next pass rebuilds the page's rows from the drawn lines, reads each row as itself (`Transcriber` over the corrected rows), and writes them as the reading's lines (`box_source: rows-adjusted`, `corrected` = the drawn lines' sha) — so the transcript gate shows the corrected text and boxes; a check with no lines requeues nothing, and a reading already carrying those lines is skipped. Smoke on a scratch root: a dropped pile registers and runs; the pass fails loudly on a fake page and the next sweep retries it; a killed pass's record is requeued (a dead pid at once); `--requeue` re-enters a `review` batch; a correction requeues its batch and the re-read replaces the page's draft lines. The full machine pass (model + real scans) is the chain's own (its tests + the transcription eval); measured on adopt-20260813-201004, the row read is ~10 minutes a page, so a 12-page batch outlasts an interactive session and is resumed by the queue (the interrupted pass's four read pages already wait in the row queue). REMAINING piece: the interjection/marginalia decision — the transcriber returns each row's kind and injection target, but the reading's lines carry text only; the Document's `kind`/`injection_after` and the surface's rendering at the target are `pipeline-stages-plan.md` § "The interjection / marginalia decision" | a dropped scan reaches the check-rows queue with no manual step; a drawn line's re-read text reaches the transcript gate |
| 1.4 | Drawing UI (stage 4) (design: `segment-review-stories.md`; the screen: `row-review-ux.md` — LANDED 2026-11-02 as its own page-only surface, `#/rows/<batch>/<doc>/<page>`; the transcription surface keeps only its words review) | landed (PR #64; row screen 2026-11-02): draw + live merge on lift + tap-to-delete + persistence through the row-adjustments seam; the `rows_pending` status is derived (1.3); the check has its own control: "Rows are right" records the page's check with whatever is drawn (nothing, when the draft rows are correct), the toolbar states "checked" once the page's two check files are on disk (and after a reload, from the payload), and it wraps rather than running off a phone's pane. `Rows.validate(traces)` runs on every correction (`apply_row_adjustments` returns a `RowCorrection`): the answer names a line that caught no writing, one that merges reading lines, one off the writing's slope or a row off the page, and the surface shows the first violation in the toolbar. The jig is gone; its box-against-line checks are structure now (a band IS its words' union). | drawing fixes a wrong row; the adjustment persists through the typed seams |
| 1.5 | The portal: one page, counts and routing (the transcription door lists only documents past the row check — `documents_ready`; a batch with none ready is shown as *before the row check*, 2026-11-02) (rows to check / documents to review / identities proposed — unfinished memories ride the identities queue, per PRD §9 F10 / INGEST-PRD 2026-09-22) | **landed (single door 2026-10-29)**: `/api/sync/batches` carries `pages_pending` (the page names, not a count). The identifying page is the review hub (`#/review`): it lists every pending human item as a section — "Check the rows" (the batches with pages to check, even when every document is confirmed), "Transcriptions", "Identify people/places" (the documents whose people/places wait, from the projection), "Import sessions", "Unfinished stories" — and each card opens the surface that clears it (`#/review/<batch>/<doc>/<page>`, `#/identify/<item>`, `#/import/<session>`, `#/item/<id>`). The front page shows ONE "Review" door with the work named (`pagesToCheck`, `documentsToReview`, `documentsToIdentify` in `app/data.js`), never a card per item: the per-item cards duplicated the hub and drifted from it (a stale import-session card alongside the identification one) | the home door names the work waiting; the hub lists every item with its count and routes each |
| 1.6 | Identification review (stages 7–8): proposed people/places from agreed Documents → confirmations into the identity tables | **landed (2026-10-29)**: a document's agreed text is read once (`pipeline/identify.py` — the model names the people and places, the pass resolves each against the archive's tables, a known name links its record, an unknown one mints a proposed record carrying the document's own words); the result lands as refs on the item (an existing link keeps its status — a pre-existing archive's confirmed links survive the first read — and a newly named entity is proposed) and proposed records in `people.json`/`places.json` (an unagreed record sits marked inside the table it will join). The item's own `identified` flag keeps the document from being read again; it sits beside the refs it produced, so a document that pre-dates the pass is read once on its first visit, and a re-agreement (which reuses the sidecar) keeps it. `POST /api/identify/document/{id}` runs the pass; `POST /api/identify/decide` applies one determination (attested / estimated / pending / delete) to the mention AND the table together — a confirmed record is never deleted or downgraded by a mention's delete, and a proposal another item still names stays (`PlacesTable.resolved` is the place analogue). The surface `#/identify/<item id>` lists each mention with the document's own words and the four dispositions; the review hub's "Identify people/places" section lists the documents whose entities still wait (and the home Review door names the count; §1.5). What remains: UR1 stage 7 names relationships, themes and orgs too — this slice reads people and places; the story path's proposals still travel the `proposed/` queue rather than the tables (a separate consolidation) | confirmations land in `IDENTITY_TABLES` — the people and places tables, moved together with the document's mention |
| 1.7 | Design task (DR2): where the non-per-page artefacts (identity tables, captured stories) live in the archive | **ruled** (`docs/TECHSPEC/07-exports.md` §18.8): the archive holds agreed artefacts, the machine's stages stay in the workspace, and a proposed record sits marked inside the table it will join. Identities at the root; the import sessions one leg down in `sessions/`; items in `documents/<date label>/<id>/` with the agreed Document as the item's `transcription.txt` (`tools/records.py` `CONTENT_FILES`) — the batch is provenance, not a coordinate. The code move it implies is §1.3's remainder (`record_confirmation` writing through the archive seam) | a proposal showing each kind's home |
| 1.8 | PaddleOCR / `.venv-htr` remnants (ruling 2026-09-22: zero rec use) | **done (2026-10-26)**: the dead helpers are gone (`load_vlm_boxes`, `word_conf`, the per-word `rec_words` fallback), the `.venv-htr` interpreter left the layout path with the single pass, the references are cleared from `htr.py`, `layout_apply_selfreport.py`, the two test files and `pyrefly.toml`, `docs/TECHSPEC.md` §16.16 now describes the ink reader and the VLM, and the **cross-reader agreement fallback is deleted** — the self-report is retried once and then the page carries no flags (user: no fallback; no flag is not a claim of certainty) | no PaddleOCR or `.venv-htr` reference in the served path or the tests; dated records keep their history |
| 1.9 | The lucidlint gate's acknowledged families — `noqa` cleared and **`record-shape` FIXED IN CODE** (both 2026-10-17, the user's ruling: rewriting per the rule IS the point). Every record is now a class in a file named after it, owning its wire format (`from_dict`/`to_dict`); `document/schemas.py` (a TypedDict bag) is dissolved; ~150 record modules landed across `document/`, `pipeline/`, `tools/`, `research/` — the server's route answers and request bodies, the layout/detection/reader measurement records, the model's chat/answer/usage records, the identity and archive records (the archive's public seams now take and return `Item`/`Person`/`Place`/`PeopleTable`/…). The rule still reports ~336 findings, **305 of them the tool's own bug** (§1.5 of the review log: it fires on `from_dict(cls, raw: dict[str, Any])`, `to_dict(self) -> dict[str, Any]` and the literal that method builds — exactly what its message prescribes; the rest are return annotations naming a record's wire). The rule stays config-ignored for that bug only. Still config-ignored, each with a written why in `.lucidlint.toml` + `docs/PLAN/lucidlint-review-log.md`: `standard` 257 (all "referenced only from tests" — the DI/eval-harness convention; ~38 verified: test-driven seams and strip-era dead code, 1.8's territory), `magic-number` 162 (62 are tuple subscripts; the rest arithmetic/geometry), `fakefs` 197 (the testing standards' real-FS tests), `unused` 47 (in-module references — §1.2), `long-param-list` 10, `latent-class` 8, `vague-name` 4 (`Store`, sanctioned), the rest single digits. Every ignore off: 789 actions, down from 1098 | awaiting the ruling on the remaining collision families | the gate's verdict reflects only real debt |

## 2. The ingest review — the claim model (design: `INGEST-PLAN.md`)

Slices 1–6 (identity → disposition → population → closed; pre-answered
claims; discovery; compound-claim decomposition; closure). **None
landed** — the review chat still runs the disposition-first walk; the
review-chat findings R1–R14 (`ux-fixes-plan.md`) stay open until these
land.

**The identification surface is the same defect in another place.**
`#/identify/<item>` (`app/views/identify.js`) renders every proposed
person/place at once, each with four buttons: a form that asks every question
whether or not the answer can change anything (PRD §9 R1 "a conversation with
a hired genealogist, not a form"; R4 "one question at a time"), where the
stage plan says the entities "enter the review chat"
(`pipeline-stages-plan.md` — "Identify people/places (stage 8)"). The fix is
Slice 1's walk over the document's mentions: one entity at a time, the
document's own sentence as the evidence (R2), the four dispositions as
consequence-named options (R5), "not sure" routed to the family's own words,
and a closing message saying what changed. Resuming needs no new state — the
walk starts at the first mention still `proposed`. The genealogist's own
follow-up questions (R3), conflicts before recording (R6) and the persisted
transcript (R7) come with Slices 1–3; the decision seam under the surface is
right (read once, append-only table writes, tested). Found by the PR-Agent
review of PR #85 (2026-11-02).

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

## 3. Layout and measurement seams (the live path: `docs/TECHSPEC/03-import-and-pipeline.md` §16.14.1; `geometry-experiments-log.md`; `design-decisions.md`)

| # | Seam | State |
|---|---|---|
| 3.1 | Cursive/rotated-page measurement — the served ink-projection primitive measures upright text only; the Godolphin 90° message is unmeasured; the orli rotated pass hallucinated and was deleted | REOPENED |
| 3.2 | RegionGate vs grouped boxes — bands may overlap in y across columns; whether the typed-page Gate B allowance extends here | undecided |
| 3.3 | Tight-schedule multi-line bands — page-01's tight section measures merged; the grouping model transcribes multi-line segments (L3 violated in the serve; the reviewer sees it; 287 doubt-flags awaiting review) | known limitation |
| 3.4 | Word-cutting remnants (`tests/pipeline/test_reader.py`): word 9690 (ruled two words; the pipeline keeps one — targeted fix, deliberately not a page-wide rule); the y3640 nested-pair weld ((1164,3640,1386,3688) ⊃ (1314,3646,1348,3680)) — two words still fused | open |

## 4. Rulings (2026-09-22) — directions closed

- **PaddleOCR: zero use.** The rec is not a reader, not a fallback, not a
  check (1.8 removes its remnants; the rec-dependent research priorities
  are ruled out — `docs/TECHSPEC/03-import-and-pipeline.md` §16.14).
- **Review edits store the transcription.** Edits are the correct text,
  stored as such; they will never feed a model (no retraining or
  calibration loop).
- **Transkribus is not a reference.**

## 5. The target store — the acceptance corpus

The order is `REWRITE-PLAN.md`; this list is its Phase A/B acceptance. The
tests name the target (`TECHSPEC/05`–`08`, `11`; `schema/truth.sql`,
`schema/projections.sql`, `schema/d1.sql`), not the active subset. Each lands
failing and drives the increment the plan names.

- **Dates** — the `DateValue` for exact, year, month, about/estimated/
  calculated, before/after/between, period, phrase and calendar; the derived
  `date`/`date2`/`date_precision`; `date_text`; the GEDCOM round trip; the
  `item.json`; the app timeline, filter and display; the migration from
  `date`/`date2`/`date_precision`.
- **The status model** — disposition (`proposed`/`confirmed`/`rejected`) +
  basis + confidence; the review responses (`attested`/`pending`/`delete`);
  the `estimated` display; the migration from `estimated`; the GEDCOM
  `EST`/`QUAY` mapping.
- **The human archive** — the dated document tree; `item.json` plus the
  readable views (`INDEX`, `PEOPLE`, `PLACES`, `THEMES`, `ORGS`,
  `RELATIONSHIPS`) generated from the DB; the manifest and `sha256sum`; the
  image leg; the sha/phash re-find.
- **The live store** — the service-only DB, the local API, the seam,
  events/content, the projections; the daemon reading rows.
- **The remote** — the resource API, the outbox, the D1 tables, the dated
  release, auth, images.
- **The app** — the row set, the rotation (desired absolute; the atomic
  apply), the correction, the messages, the review.

Loose ends that fit neither plan: `SCRAPS.md`.
