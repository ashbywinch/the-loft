# AGENTS.md

Instructions for AI agents working in this repo. Humans can read this too.

## Quick start

- `make setup` — create venv, install Python + JS deps, install pre-commit hooks.
- `make test` — lint + typecheck gate, then the full suite (pytest + vitest).
- `make serve` — serve `app/` at http://localhost:8000.

## Testing Rules

- ALWAYS use `make` targets; NEVER construct ad-hoc test commands.
- CI runs exactly: `make setup && make lint && make test && make coverage`.
- `make test` depends on `make lint` and `make typecheck` — lint gates test.
- Tests must be deterministic: no wall-clock, network, or order dependence
  (see `docs/testing-standards.md`).

## Where things live — decision tree

| Task | Route to |
|---|---|
| Product requirements, scope, personas | `docs/PRD.md` |
| Architecture, stack, data model, decisions | `docs/TECH-SPEC.md` |
|Interview/observation instruments|`docs/DISCOVERY.md`, private session records|
| The story-capture flow spec ("Add your memory") | `docs/MEMORIES.md` |
| The artifact-import flow spec + its rules (A–S) | `docs/IMPORT-PRD.md` |
| Real-import lessons (worked example) | private review doc, not shipped |
| UI / visual conventions (the pattern library) | `docs/UI.md` |
| Chat / capture-dialog conventions | `docs/CHAT-UX.md` |
| UX loop working log (statuses, open items) | `docs/ux-fixes-plan.md` |
| Precedent research | `docs/PRECEDENT.md` |
| Project plan, slices, urgency | `docs/PLAN.md` |
| Code conventions | `docs/coding-standards.md` |
| Test conventions | `docs/testing-standards.md` |
| Documentation conventions | `docs/writing-documentation.md` |
| Real content (people, relationships, items, story text) | `archive/` — append-only, supersede never edit; regenerate `app/data` with `./loft publish` |
| Demo content for fake instances | `tools/demo_data.py` — fictional only, never real names |

Read the relevant doc before changing behavior. **Before any code change, read `docs/coding-standards.md` — it is the standing contract for how code is written here, not a reference to consult when in doubt** (2026-08-05: an entire session extended the record model without loading it — the class-over-dict rule it already contained went unread). **Before any documentation change, read `docs/writing-documentation.md`** (2026-08-05: the same session wrote standards and docs without loading the doc-standard — the pattern repeats until the contract is loaded first). The PRD's §10 principles are
product law: the app arranges evidence, never interprets it; no censorship by
default. Real content never lives in code (`docs/coding-standards.md`).

## Tool selection

- Python tools: `tools/` — ruff (lint/format), basedpyright (types), pytest.
- Web app: `app/` — vanilla ES modules. NO framework, NO build step, NO runtime
  npm deps (decision recorded in `docs/TECH-SPEC.md` §15). eslint + prettier + vitest
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
- Archive data (scans, sidecars) is committed during dev; on prod it is not committed but regularly backed up (user, 2026-08-03).

## Secrets

- Real secrets live in the shell environment — never in code, docs, logs, or
  `.env.example` (values there are blank by definition).
- In shell: `test -n "$VAR"` to check a variable — NEVER `echo $VAR` (leaks).
