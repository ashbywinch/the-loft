# The plans folder — map

Two kinds of files. **Plans** say what work remains. **Records** say what
happened and why — read them for context, never for remaining work.

Fresh agent: read `WORK-PLAN.md` first (what's left, ordered, with
acceptance), then the pointed design doc for the item.

## Plans — work to do

| File | Scope |
|---|---|
| `PLAN.md` | the large-scale plan — the full PRD: slices 1–6, feature inventory, sequencing, per-slice status |
| `WORK-PLAN.md` | the small-scale plan — the work remaining on the active subset (the ingest → transcription → identity pipeline), ordered with acceptance |
| `SCRAPS.md` | loose ends that fit neither plan |

## Design and work records

| File | Records |
|---|---|
| `pipeline-stages-plan.md` | the pipeline refactor's design (object model, seams) — status per WORK-PLAN §1 |
| `INGEST-PLAN.md` | the claim-model review's design — WORK-PLAN §2 |
| `segment-review-stories.md` | the review structure-tools stories — adjudicated; the build is WORK-PLAN 1.4/1.6 |
| `row-review-ux.md` | the row review's phone surface — PROPOSED: the purpose, the pipeline's colours over the page, the reviewer's yellow lines, draw→redraw |
| `page-categories.md` | the page categories (photo, writing printed/handwritten, postcard face, form, drawing) and what each implies for reading; PROPOSED |
| `row-correction-rule.md` | how a drawn line edits a mostly-right page — LANDED: replace a covered row, claim only the words the line runs along, leave everything else |
| `ux-fixes-plan.md` | the UX loop's working log (findings + statuses) — R1–R14 open until WORK-PLAN §2 |
| `geometry-experiments-log.md` | the experiment ledger — check before trying a mechanism |
| `design-decisions.md` | the decision register |
| `lucidlint-review-log.md`, `lucidlint-snag.md` | lucidlint integration records |