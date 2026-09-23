# Single-Pass Landing Plan — What Remains

**Status:** COMPLETE (2026-09-22) — all three remaining items are done:
the four superseded PRs are closed, the confirm-flow audit found no
old-path references left, and the end-to-end real-data run served
through the review surface. Written 2026-09-07 as a session handoff;
kept for the record and the operational traps below.

## What this is

The §16.17 single-pass segment-and-transcribe redesign — one VLM call per page
returning per-line segments with verbatim text, orientation, and pixel boxes —
replaced the PaddleOCR detect-then-match pipeline. All of its content is now on
`main` (tip `cf930dc`, CI green). Four open PRs are leftovers from the old
stacked-branch structure; merging any of them would *revert* newer `main`
content. They must be **closed, not merged**.

## Read these first

| To understand | Read |
|---|---|
| The single-pass design and its contract | `docs/TECHSPEC.md` §16.17 |
| Product law (the app arranges evidence, never interprets it) | `docs/PRD/PRD.md` §10 |
| The layout redesign requirements this implements | `docs/PLAN/layout-requirements-draft.md` |
| The transcription-review surface the review PRs serve | `docs/PRD/TRANSCRIPTION-REVIEW-PRD.md` |
| The measured geometry findings behind the orientation gates | `docs/PLAN/geometry-experiments-log.md` |
| The pipeline stage map and per-page recovery | `docs/TECHSPEC.md` §16.14.2 |

## What is on `main` now (verified)

- `tools/segment_page.py` — the single-pass stage. Raises `SegmentPageError`
  on any contract violation; the page refuses loudly (rc 1). No fallback to
  the old path — that is deliberate (user directive).
- `tools/layout_detect.py` — `_build_page_layout` calls `segment_page` and
  converts to the Layout, threading `urlopen=`/`api_key=` keywords through
  `run_batch`/`_process_page`/`_layout_one`. The detector engine and every
  old-path function are deleted.
- The review surface v2 (dual-pane, per-line boxes, the persona-guard fix in
  `tools/eval_review.py`), the scoring modules, and `tools/pipeline_store.py`
  — landed via PR #31.
- The review-posted gate rewrite (`tools/check_review_posted.py`): polls the
  comments list (4×8 s, injectable delay — the never-sleep rule in
  `docs/testing-standards.md`), accepts the bot's logged "PR output" as
  coverage, reports the bot's own error on genuine death.
- `tests/fixtures/godolphin-1906-back.jpg` and the VR15 eval contract
  (`tests/test_eval_postcard.py`): ≥ 12 segments, the address lines separate,
  multi-orientation present. The eval needs the direct gateway URL — the local
  proxy rejects `dynamic/image`.
- `tools/layout_stage.py` runs the layout stage on the main venv (`.venv-htr`
  is no longer needed for layout).

## What remained — all closed (2026-09-22)

### 1. Close the four superseded PRs — DONE (all four CLOSED)

Each diff vs `main` was checked on 2026-09-07 with
`git diff loft/main..loft/<branch> --numstat`: every delta is an *older*
version of a file `main` has since superseded. Merging would revert the review
surface, the gate rewrite, or the old-path deletion.

| PR | Branch | Why superseded |
|---|---|---|
| #32 | `pr/torch-pin` | Still carries `tools/eval_batch.py`, `eval_columns.py`, and the pre-conversion `layout_detect.py` that `main` deleted. The CPU-index pin itself is stale — `main`'s CI resolves torch green without it. |
| #36 | `pr/ink-2` | Review-surface files are older than #31's landed versions; `tools/layout.py`/gate deltas are pre-rewrite. |
| #37 | `pr/ink-3` | Same, plus `eval_crop_grid.py`/`box.py` deltas that would remove `main`'s lucidlint-ignore annotations and refinements. |
| #38 | `pr/ink-pipeline` | Its one unique contribution (the conversion) is on `main`; the remaining 9-file diff would revert the review surface and scoring tests. |

Done: closed with the one-line comment (content landed via #31/#33/#35;
the diff would revert newer `main` content). Verified 2026-09-22: all
four are CLOSED on GitHub.

### 2. Audit the confirm flow for old-path references — DONE

Grep of `tools/pipeline.py`, `tools/sync.py` and `tools/server.py`
(2026-09-22): no `ENGINE`/`region` references remain; the surviving
`detect` mentions are prose (boundary detection, a historical
`layout_detect` comment). The single-pass Layout (per-line `words_out`,
self-report flags applied per line index) is the only path.

### 3. Verify main end-to-end once on real data — DONE

The strip-grouping DoD served page-01/page-02 of the Music College
letter through `make pipeline ARGS="layout …"` with 0 gate violations and
rendered in the review surface (2026-09-09); the Godolphin VR15 contract
is pinned in `tests/test_eval_postcard.py` (in the passing suite).

## Operational traps this session paid for (hours each)

- **CI run attribution is unreliable.** `gh run list` rows misattribute
  `head_branch` across pushes. Match runs by head SHA, never by PR number or
  branch name. Only output artifacts count — v0.41.1's `PRAgent.handle_request`
  swallows exceptions, so a bot step can claim success while publishing nothing.
- **Branch surgery: verify from the refs, never from memory.**
  `git show $branch:<file> | grep …` before every merge decision. A stale
  memory of which branch carried which commit caused the day's worst churn.
- **Rebase-merge is the only allowed method** (the ruleset blocks merge and
  squash). A blocked `gh pr merge --rebase` means the branch needs rebasing
  onto `main` first, not `--auto` and not a base switch.
- **Gateway (Cloudflare AI Gateway):** unknown User-Agents from datacenter
  ranges get WAF error 1010. `tools/ai_client.py` and the pr-agent config both
  set `opencode/1.14.20`. The intermittent 401s were transient gateway bursts,
  not key rotation — the repo secret and the local key are identical (verified:
  both 53 chars, suffix `1c60`). Never chase phantom auth bugs before
  re-reading the actual run log.
- **Tests never sleep.** Injectable delays via DI seams only
  (`docs/testing-standards.md`).
- The `428 "Precondition Required"` strings in old logs are
  `tools/auth.py`'s Google device-flow comment, not gateway responses.
