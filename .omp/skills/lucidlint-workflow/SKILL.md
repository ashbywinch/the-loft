---
name: lucidlint-workflow
description: |
  How to act on lucidlint findings in this repo — the fix-engine workflow,
  the per-file LSP mode, and where the findings log lives. Read this before
  addressing a lucidlint finding.
---

# lucidlint workflow

The deterministic code-health gate (`github.com/ashbywinch/lucidlint`).
Bundled at `lucidlint-dist/`, run via `make lucidlint`. Findings and
disagreements are recorded in `docs/plans/lucidlint-review-log.md`; tool
gripes for the maintainer in `docs/plans/lucidlint-snag.md`.

## The gate

```bash
make lucidlint                    # install + run with the baseline
.venv/bin/python lucidlint-dist/lucidlint.py --repo . --baseline lucidlint.json
.venv/bin/python lucidlint-dist/lucidlint.py --repo . --json   # machine-readable
```

The baseline (`lucidlint.json`) acknowledges known debt; the gate fails on
NEW actions only. Warnings never fail.

## Acting on a finding — use the fix engine, never hand-implement

The fix engine needs `libcst` (in the dev deps; `uv sync --dev` installs
it). The engine is agent-driven and R27 means it owns its own
coordinates — you do not compute line numbers.

For a structural finding (complexity, long-param-list, extract-class,
dispatch-registry, ...):

1. **Preview the seam without a name** — nothing is written:
   ```bash
   .venv/bin/python lucidlint-dist/lucidlint.py fix --kind extract-method --file tools/layout.py --line 435
   ```
   Read the proposed diff + the seam's first lines.
2. **Judge the seam** — is this the right split? The engine proposes, you
   decide. Wrong → discard the preview (nothing changed).
3. **Apply with the name as the commitment**:
   ```bash
   .venv/bin/python lucidlint-dist/lucidlint.py fix --kind extract-method --file tools/layout.py --line 435 --name _helper --confirm
   ```
4. **Clear dead tails** the move left: `--kind unreachable` (and
   `noop-statement`).
5. Re-run the gate.

The extracted seam is bounded to <=13 decisions (lands under CC-15) and
made private by construction. The exact output is name-dependent — that is
why the preview comes first.

For a mechanical finding (magic-number, stale-suppression,
positional-literals): the fix command applies deterministically; run it.

## Per-file LSP mode

`lucidlint.py --file <repo-relative>.py` scans ONE file — use it after
every structural edit to catch transient bad states (duplicate blocks,
undefined names, defs mid-import) before they compound:
```bash
.venv/bin/python lucidlint-dist/lucidlint.py --file tools/htr.py
```

## The edit-tool discipline this repo learned the hard way

- Structural changes (whole functions, blocks, dict entries, signatures)
  → `ast_edit`, not the line editor. The line editor has produced a
  duplicate body, a mid-import insertion, and a dropped import in one
  change (2026-08-20, lucidlint-review-log §10).
- A finding with `fix: <kind>` in its message means "run the fix", not
  "hand-extract".
- After every structural edit: re-run `--file` on the touched file before
  the next edit.

## Baseline updates

`--update-baseline --baseline lucidlint.json` locks today's debt so the
gate fails only on NEW actions. Prefer a per-site
`# lucidlint: ignore <kind> <why>` over a config ignore when a finding is
a one-off (see the review log §9 — config ignores are invisible debt).
