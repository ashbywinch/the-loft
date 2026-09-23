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

## Records — history

| File | Records |
|---|---|
| `pipeline-stages-plan.md` | the pipeline refactor's design (object model, seams) — status per WORK-PLAN §1 |
| `INGEST-PLAN.md` | the claim-model review's design — WORK-PLAN §2 |
| `strip-grouping-plan.md` | the layout stage's strip path — SERVED 2026-09-09 + postmortem; seams in WORK-PLAN §3 |
| `segment-review-stories.md` | the review structure-tools stories — adjudicated; the build is WORK-PLAN 1.4/1.6 |
| `layout-requirements-draft.md` | the layout requirements — adjudicated + landed (VR19–24; TECHSPEC §16.17) |
| `single-pass-landing-plan.md` | the §16.17 landing — complete 2026-09-22 |
| `row-data-migration-plan.md` | user-lines → rows library — landed 2026-09-19 |
| `model-trial-report.md` | the model trial — superseded as mechanism |
| `vlm-word-segmentation-spike.md` | the VLM word-segmentation spike — milestones 1–3 landed in `tools/` |
| `ocr-verification-research.md` | research synthesis — its rec/Transkribus directions ruled out 2026-09-22 |
| `ux-fixes-plan.md` | the UX loop's working log (findings + statuses) — R1–R14 open until WORK-PLAN §2 |
| `ux-review-chat-solution.md` | the review-chat redesign — superseded by INGEST-PLAN |
| `geometry-experiments-log.md` | the experiment ledger — check before trying a mechanism |
| `design-decisions.md` | the decision register |
| `lucidlint-review-log.md`, `lucidlint-snag.md` | lucidlint integration records |