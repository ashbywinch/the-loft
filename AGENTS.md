# AGENTS.md

Instructions for AI agents working in this repo. Humans can read this too.

## Quick start

- `make setup` — create venv, install Python + JS deps, install pre-commit hooks.
- `make test` — lint + typecheck gate, then the full suite (pytest + vitest).
- `make serve` — serve `app/` at http://localhost:8000.

## Testing Rules

- ALWAYS use `make` targets; NEVER construct ad-hoc test commands.
- CI runs exactly: `make setup && make lint-github && make coverage && make verify` — the
  suites run ONCE, inside `make coverage` (2026-08-11: running `make test`
  AND `make coverage` re-ran pytest + vitest twice, and the second,
  coverage-instrumented run surfaced a timing flake the first missed).
- `make test` and `make coverage` both depend on `make lint` and
  `make typecheck` — lint gates test.
- Three pytest selections, never mixed: `make test` = the fast unit gate
  (excludes `eval` and `archive` markers via addopts); `make verify` = the
  archive-quality data checks (`-m archive`, skipped in CI — no archive);
  `make evals` = the real-model evals (`-m eval`, need the API key;
  CI runs them only when `OPENAI_API_KEY` is configured). Split 2026-08-13
  (user: `make test` must stay fast).
- Tests must be deterministic: no wall-clock, network, or order dependence
  (see `docs/testing-standards.md`).

## Where things live — decision tree

| Task | Route to |
|---|---|
| Adopt / ingest planning (the batch adoption flow's docs) | `docs/PLAN/INGEST-PLAN.md` |
| Product requirements, scope, personas | `docs/PRD/PRD.md` |
| Architecture, stack, data model, decisions | `docs/TECHSPEC.md` |
| Pipeline stages, completion markers, and per-page recovery (`make pipeline ARGS="guess\|layout <batch> [page...]"`) | `docs/TECHSPEC.md` §16.14.2 |
| Layout / geometry experiments ledger (the ink work's measured findings) | `docs/PLAN/geometry-experiments-log.md` |
| Serving the app — foreground `make serve`; the supervised hub spec that survives daemon restarts | `README.md` (Quick Start → "Supervised dev server") |
| The PLAN/ work logs (trial reports, walkthrough records, snags) | `docs/PLAN/` — `docs/PLAN/ocr-verification-research.md`, `docs/PLAN/model-trial-report.md`, `docs/PLAN/lucidlint-snag.md`, `docs/PLAN/ux-review-chat-solution.md`, `docs/PLAN/INGEST-PLAN.md` |
| The layout stage's strip path — its plan, postmortem and reopened seams (ink-projection line bands; the grouping read) | `docs/PLAN/strip-grouping-plan.md` |
| Acting on lucidlint findings (fix-engine workflow, baseline, per-file checks) | `skill://lucidlint-workflow`; the repo's findings log at `docs/PLAN/lucidlint-review-log.md` |
| Layout redesign requirements (the adjudication draft — layout-requirements-draft) | `docs/PLAN/layout-requirements-draft.md` |
| The reader — how a page's writing is found and boxed, and its acceptance check | `docs/box-detection.md`; `tools/reader.py`, `tools/boxjig.py` |
| The per-word detection internals (ink → connected marks, baseline/waistline measurement, the streak-rule drop) | `tools/mark.py` (`find_marks`, `baseline_row`, `waistline_row`); the page ruler `tools/pagescale.py`; pinned by `tests/test_reader.py` |
| Showing the user a visual artifact (renders, maps, zooms, case sheets) | `.omp/skills/show-the-user/SKILL.md` — existing tooling only, LAN URL, self-check before presenting |
| The segment/box review & edit UX (user stories, the box-issue taxonomy, the corner rulings) | `docs/PLAN/segment-review-stories.md` |
|Interview/observation instruments|`docs/DISCOVERY.md`, private session records|
| The story-capture flow spec ("Add your memory") | `docs/PRD/MEMORIES.md` |
| The artifact-import flow spec + its rules (A–S) | `docs/PRD/IMPORT-PRD.md` — the ingest-side planning spec: `docs/PRD/INGEST-PRD.md` |
| The transcription-review surface spec | `docs/PRD/TRANSCRIPTION-REVIEW-PRD.md` |
| Sign in and verify the rendered review surface (boxes on text) | `docs/review-surface.md` |
| The projection / sqlite plans + the research corpus | `docs/sqlite-projection-plan.md`; `research/archive-longevity-research.md`, `research/ocr-correction-ux-tools-guide.md` |
| The multi-document capture seam (batches, hashes, sidecars, labels) | `docs/PRD/MULTI-DOC-IMPORT-PRD.md` |
| UI / visual conventions (the pattern library) | `docs/UI.md` |
| Chat / capture-dialog conventions | `docs/CHAT-UX.md` |
|UX loop working log (statuses, open items)|`docs/PLAN/ux-fixes-plan.md`|
|Design decisions with rationale (the register)|`docs/PLAN/design-decisions.md`|
| Precedent research | `docs/PRECEDENT.md` |
| Project plan, slices, urgency | `docs/PLAN/PLAN.md` |
| The work remaining on the current subset (pipeline, ingest review, layout seams) | `docs/PLAN/WORK-PLAN.md` — the detailed designs are linked per item |
| The plans folder's map (plan vs record) | `docs/PLAN/README.md` |
| Code conventions | `docs/coding-standards.md` |
| Test conventions | `docs/testing-standards.md` |
| Documentation conventions | `docs/writing-documentation.md` |
| Documentation structure — the required doc set, folder rules, discoverability | `docs/documentation-structure.md` |
| UX standards (the reviewer rules and UX-process norms) | `docs/ux-standards.md` |
| UX spec — the PRD's UX answers + the journeys to usability-test | `docs/UX.md` |
| Real content (people, relationships, items, story text) | `archive/` — append-only, supersede never edit; regenerate `app/data` with `./loft publish` |
| Demo content for fake instances | `tools/demo_data.py` — fictional only, never real names |

Read the relevant doc before changing behavior. **Before any code change, read `docs/coding-standards.md` — it is the standing contract for how code is written here, not a reference to consult when in doubt** (2026-08-05: an entire session extended the record model without loading it — the class-over-dict rule it already contained went unread). **Before any documentation change, read `docs/writing-documentation.md`** (2026-08-05: the same session wrote standards and docs without loading the doc-standard — the pattern repeats until the contract is loaded first). The PRD's §10 principles are
product law: the app arranges evidence, never interprets it; no censorship by
default. Real content never lives in code (`docs/coding-standards.md`).

## Tool selection

- Python tools: `tools/` — ruff (lint/format), pyrefly (types), pytest.
- Web app: `app/` — vanilla ES modules. NO framework, NO build step, NO runtime
  npm deps (decision recorded in `docs/TECHSPEC.md` §15). eslint + prettier + vitest
  are dev-only tooling.
- Everything goes through `make`; npm/pytest/ruff are invoked only inside
  make targets.

## Git workflow

- NEVER commit to main. Branch off main, PR required, protected main.
- NEVER commit with `--no-verify`. If a pre-commit hook blocks a commit (a
  formatter modified files), re-stage the modified files, verify the staged
  diff matches your intent, and re-commit with the hook (2026-08-06: a
  blocked commit's stash/restore reverted a fix, and a blind re-add
  committed the stale content).
- Atomic commits; reference issues with `Fixes #N`.
- Archive data (scans, sidecars) is committed during dev; on prod it is not committed but regularly backed up (user, 2026-08-03). The concurrency model for the archive's writers: `docs/archive-concurrency-plan.md`.

## Public repo (2026-08-08, user)

- The live repo is **the-loft** (github.com/ashbywinch/the-loft); local
  `main` tracks `loft/main`. The private repo (family-history-album) is
  **frozen** — it keeps its full history but receives nothing; no local
  remote points at it.
- Pushing is a normal `git push`: main is protected (the `build-and-test`
  check is required, force-pushes and deletions are disabled), so a push
  runs the full gate — including the no-PII guard — before CI goes green.
  No rebuild, no force-push, no release step: the public history is clean
  (it starts at the scrubbed root), so ordinary commits accumulate on it.

## Secrets

- Real secrets live in the shell environment — never in code, docs, logs, or
  `.env.example` (values there are blank by definition).
- In shell: `test -n "$VAR"` to check a variable — NEVER `echo $VAR` (leaks).
