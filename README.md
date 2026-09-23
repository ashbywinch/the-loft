# The Loft

A family history museum on a tablet — a lens over a folder of family artifacts:
letters, photographs, documents, heirlooms. Vanilla HTML/CSS/JS web app with
Python tools; no framework, no build step, no runtime backend by design
(`docs/TECHSPEC.md`).

**Status:** product docs complete (PRD v0.9), architecture reviewed, repo
scaffolded, **prototype shipped**, and the **letter-import experiment
landed** — the real 1949–2001 correspondence, the family record, the cast
and places imported through the process designed by interviewing the user
while trying it (see `docs/PRD/IMPORT-PRD.md`).
Serve it with `make serve`.

## Quick Start

```sh
make setup    # create venv, install deps (Python + JS), install pre-commit hooks
make serve    # serve app/ on the LAN — the printed address works on any device (phone included)
make test     # lint + typecheck gate, then pytest + vitest
make coverage # tests with coverage report
```

CI runs exactly `make setup && make lint-github && make coverage` — the suites
run once, inside `make coverage`; never ad-hoc tool commands (see `AGENTS.md`).

### Supervised dev server (survives daemon restarts)

`make serve` in a terminal is the normal foreground dev server (Ctrl-C
stops it; nothing to configure). For a phone-facing server that must
survive daemon restarts and omp exits, start it through the hub with:

- **name:** `loft-dev` · **application:** `./loft` · **args:** `serve
  --host 0.0.0.0 --port 8000 --reload` · **cwd:** repo root
- **detached:** `true` (survives broker/daemon restarts — `persist`
  alone does not)
- **ready:** log banner `Uvicorn running` **and** TCP port 8000

The general rule lives in `skill://lan-server`; this is this project's
launch spec.

## Documents

| Doc | What it is |
|---|---|
| `docs/PRD/PRD.md` | Product requirements — the "why" and the "what" (v0.9) |
| `docs/PLAN/PLAN.md` | Project plan — thin slices, time to value |
| `docs/TECHSPEC.md` | Architecture — the "how", decisions, and review record |
| `docs/PRD/MEMORIES.md` | Story-capture flow spec — "Add your memory" |
| `docs/PRD/IMPORT-PRD.md` | Artifact-import flow spec — the letter-import rules (A–S) |
| (private) worked-example review | Real-import lessons from the first letter |
| `docs/UI.md` | UI pattern library — tokens and components |
| `docs/CHAT-UX.md` | Chat / capture-dialog conventions |
| `docs/PLAN/ux-fixes-plan.md` | UX loop working log — findings and statuses |
| (private) interview records | Story-harvest and import-interview session records — not shipped |
| `docs/DISCOVERY.md` | Discovery instruments D1–D10 |
| `docs/PRECEDENT.md` | Precedent scan — what exists and what to avoid |
| `docs/coding-standards.md` | Code conventions |
| `docs/testing-standards.md` | Test conventions |
| `docs/writing-documentation.md` | Documentation conventions |

## Layout

- `app/` — the web app (vanilla ES modules; screens land with the prototype)
- `tools/` — Python: the archive object model (`archive`, `store`, `records`,
  `derive`), the publish pipeline (`publish`), the story assessor
  (`elicitation`), the import scripts (`import_*`), GEDCOM export/import
  (`export_gedcom`, `import_gedcom`), the LAN dev server (`serve`),
  `fake_data` (demo, fictional only)
- `tests/` — Python tests · `app/tests/` — JS tests (vitest)
- `archive/` — the append-only store: items, identity tables, transcripts,
  scans (see `archive/README.md`)
- The private interview records and worked-example review stay out of the public tree (real family content)
- `docs/` — the specs and standards (routing table above)

The archive (scans, sidecars, JSON) is committed to the repo during dev; on
prod it is not committed but regularly backed up (user, 2026-08-03) — see
`docs/TECHSPEC.md` §3–5 for where it lives.
