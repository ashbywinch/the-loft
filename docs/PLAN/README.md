# The plans folder — map

Two kinds of files. **Plans** say what work remains. **Records** say what
happened and why — read them for context, never for remaining work.

Fresh agent: read `REWRITE-PLAN.md` first for the DB rewrite's order, then
`WORK-PLAN.md` for the active subset's detail, then the pointed design doc for
the item.

## Plans — work to do

| File | Scope |
|---|---|
| `REWRITE-PLAN.md` | the rewrite's order — the database as the system of record: phases A–F, one increment per PR, each with its gate |
| `PLAN.md` | the large-scale product plan — the full PRD: slices 1–6, feature inventory, per-slice status; the rewrite order is `REWRITE-PLAN.md` |
| `WORK-PLAN.md` | the small-scale plan — the work remaining on the active subset (the ingest → transcription → identity pipeline), ordered with acceptance; §5 is the rewrite's acceptance corpus |
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
| `test-port-ledger.md` | the rewrite's coverage ledger — every existing suite's disposition, port increment and new home; the rule is `REWRITE-PLAN.md` |