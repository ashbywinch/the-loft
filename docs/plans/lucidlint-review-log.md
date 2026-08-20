# lucidlint review log

Working log for the first full-repo lucidlint run (2026-08-16, branch
`refactor/lucidlint-findings`). Every finding I disagreed with, or that took
real time to decide, is recorded here with the reasoning. Fixes that were
straightforward (swallow, noqa, boolean-arg, positional-literals, inline
imports, global state, monkeypatch, complexity, magic numbers, loop
pipelines, detached methods, duplicates, unused code) are not re-litigated
here — the code is the record.

Tool: lucidlint v0.1.0 (installed bundle at `~/.local/share/lucidlint`),
run as `python3 ~/.local/share/lucidlint/lucidlint.py --repo . --json`.

---

## 1. Tool bugs found (in the tool, not the repo)

### 1.1 Backtick parent-dir paths in docs resolve against the repo root, not the doc's directory

`scanner/src/docs.rs` `docs_findings`: markdown links resolve against the
doc's parent directory (`parent.join(&target)`), but backticked paths
starting with a parent-dir prefix resolve against the **repo root** (`repo.join(&path)`).
Three findings were false positives from this:

- docs/plans/PLAN.md links to the existing docs/prd/PRD.md
- docs/prd/MEMORIES.md links to the existing docs/plans/PLAN.md
- docs/prd/PRD.md links to the existing docs/TECH-SPEC.md

Fix for the tool (not applied — the build-tools repo is mid-work on
`rust-scan-core`): resolve parent-relative backtick paths against the doc's
parent, same as links. These three findings are left visible in the gate.

### 1.2 The `unused` rule counts only cross-file references — in-module usage is missed

`tools/memory.py` `_slug`, `_unique_id`, `_person_of`, `_place_of`,
`_theme_of`, `_item_of` are all used **within** memory.py (lines 233, 259,
332-335) yet flagged "defined but never referenced". The RULES.md wording
("never referenced from any other prod file") makes in-module helpers
false positives. Fixes applied per-site with `# lucidlint: ignore unused`
comments; the rule should count same-module references too.

### 1.3 The `noqa` rule requires a second `#` comment; the repo's `# noqa: BLE001 — reason` format is invisible to it

`checks.rs` `noqa_findings` only accepts a reason that is a *second*
comment after the noqa marker (`# noqa: X  # reason`). The repo wrote
`# noqa: BLE001 — the callback must never 500` (a real reason, one
comment). Converted the four sites to the tool's format rather than
fighting it; the tool's heuristic is narrower than the repo's convention.

### 1.4 The `swallow` heuristic accepts only control-flow exits (return/raise/break/continue) or returned-name mutation

Logging is not counted as surfacing. That is right in the majority case (a
caller exists that should decide) and wrong only at the terminal/defensive
boundaries the heuristic cannot distinguish: the reprocess thread's terminal
handler in server.py logs because there is no caller to propagate to. The
repo standard's "log" option is the *terminal* case, not a licence to hide
a recoverable failure — the standard was tightened to say exactly this and
`tools/ai_client.find_api_key`'s corrupt-file fallback (which was a genuine
silently-degraded-config swallow) now raises instead (§ below, 2026-08-16).

---

## 2. Disagreements — findings suppressed with reasons (see `.lucidlint.toml` + code comments)

### 2.1 `fakefs` in tests (139 findings) — config-ignored for `tests/**`

The tool prescribes pyfakefs for all test filesystem I/O. The repo's
testing standards permit deterministic real-FS tests: the archive/store
tests exercise `os.replace` atomicity, crash resumption (kill mid-write),
file modes (umask), subprocess interop (tesseract/ImageMagick) and
sqlite3 — semantics pyfakefs cannot fake faithfully — and the private-
dataset checks must read the real repo tree. The tool's own message
carves out "real FS semantics (subprocess interop, symlinks, C-level I/O
like sqlite3)". Suppressed at the tests scope with that citation.

### 2.2 `record-shape` (278 findings) — config-ignored for `tools/**`

The tool flags every `dict[str, Any]` annotation and constant-key dict
literal as a record needing a class. The repo's standard is narrower and
already implemented: "Domain concepts are classes — the type is the
documentation" applies when a concept has identity/state/invariants or is
re-parsed in 2+ places; the object model (tools/records.py — Person,
Place, Org, Relationship, Item, Knowledge) already converts those. The
remaining dicts are deliberate wire-format seams the standards name:

- `to_dict`/`from_dict` return and accept the wire dict by contract ("the
  class IS the persistence contract... to_dict owns its wire format");
- API route responses and request bodies are output format — "Don't let
  output format drive the domain model";
- eval result dicts are one-shot shapes with no second consumer ("A value
  type with real behavior and several consumers earns a class" — one-shot
  dicts don't).

Every records.py finding (33) is the class's own serialization seam. A
dict shape that is genuinely re-parsed in 2+ places remains a finding per
the repo standard — the repo reviewer enforces that; the tool's blanket
flagging is noise on the seams.

### 2.3 `class-module` (12 findings) — config-ignored for `tools/**`

The tool wants each one-class module renamed to match its class
(`htr.py` → `htrerror.py`, `sync.py` → `outbox.py`, `review.py` →
`_chat.py`). Every flagged module is named after its **domain noun** (the
repo standard: "Name tools and modules after domain nouns") and holds the
noun's exception or helper class — the standards' own stated exception to
"each class in its own module" (closely related, one reason to change).
Renaming would destroy the domain naming.

### 2.4 `vague-name` (3 findings) — config-ignored for `tools/**`

The tool's vague-name list includes "Store". The repo standard sanctions
`Store` as a domain noun ("plus Store, Records, Projection, AiClient").
The tool's list collides with the house vocabulary.

### 2.5 `latent-class` (5 findings) — per-site suppression

- **server.py `build_app` (36 route closures)**: the closures ARE the
  FastAPI route-registration idiom; the DI'd dependencies are explicit
  parameters, not hidden state. A class would fight the framework's
  decorator model for no structural gain. Suppressed with reason.
- **archive.py field partition**: the split is `_save_lock` usage (the
  identity-table write seam for thread safety) vs store-only methods — an
  implementation detail, not a second domain. `Archive` is the noun.
- **layout.py `associate_lines`**: one coherent greedy-match algorithm;
  the "5 inner functions" are sort-key lambdas over the shared match
  state. A class would scatter a single pass.
- **eval_review.py condition functions**: `REVIEW_CONDITIONS` is a
  dispatch table by design — named shared checkers over each flow's
  expectation fields. Methods on the flows would scatter the harness.

### 2.6 `special-case` (5 tracked findings) — per-site suppression

The tool suggests "Introduce Special Case: give the absent case an
object". All five flagged sites are fail-fast guards where the absent
case is an **error** (`person is None → raise KeyError`, `table is None →
raise ArchiveError`) or an **auth boundary** (`mine is None → 401`). A
NullObject would mask the error or hide the boundary — the opposite of
the repo's "fail fast, never swallow".

### 2.7 `broad-except` (6 tracked findings) — per-site suppression

All six are deliberate terminal boundaries:
- `atomic.py`: `except BaseException` guarantees temp-file cleanup on
  EVERY exit path (including KeyboardInterrupt) before re-raising —
  narrowing would leak temp files;
- `sync.py` reprocess: mark-page-failed on any error, then re-raise — the
  stage's terminal handler;
- `vlm.py`: every failure surfaces as `VlmError` — the module's error
  contract;
- `auth.py` ×3: the no-500 boundaries, already documented via
  `# noqa: BLE001` (the warn duplicates the noqa's why).

### 2.8 `boolean-arg` on `dict.get(key, False)` — fixed by removing the redundant default

The literal was the *default* for a missing key; `dict.get`'s default is
positional-only (pyrefly rejects `default=`). The repo's `_flag_bool(None)`
and `bool(None)` both yield `False`, so the defaults were redundant —
removed them (behavior-identical), which is cleaner than a suppression.

### 2.9 `swallow` at `contextlib.suppress(RegistryError)` in server.py — misread initially

The first scan's line numbers pointed my suppression at the
`contextlib.suppress` line; the actual finding was the enclosing
`except Exception: logger.exception(...)` thread handler. The stale
suppression was caught by the tool's own stale-suppression rule and
removed — a nice demonstration of the rule working.

---

## 3. Judgment calls that took real time (agree, but the path was not obvious)

### 3.1 auth.py module-level stores → `AuthState` class

The three in-memory OAuth stores (`_oauth_states`, `_device_grants`,
`_recent_sessions`) are module-level mutable state — the repo standard
forbids it, but the module deliberately documents the pattern as
"ephemeral by design: a restart invalidates in-flight logins (houses
parity)". Decided: refactor to an `AuthState` class owning the stores and
their invariants (max ages, entry cap, the sweep), with a module-level
instance — the tool's own sanctioned "one global services object". The
functions keep their signatures (server surface untouched); the residual
tension with the standard's "no module-level mutable state" letter is
acknowledged: full DI (threading the instance through every route) is the
standard's letter, judged too risky mid-refactor for the security seam.

### 3.2 `monkeypatch` in tests (24 findings)

Split into three classes:
- **Real DI violations — fixed.** test_auth replaced module functions
  (`auth._device_grant_post = lambda...`, `auth.verify_device_id_token =
  ...`) to fake Google. Added injectable `_post`/`_verify` seams to
  `start_device_grant`/`poll_device_grant` (the repo's own
  `htr_pages_vlm(transcribe=...)` pattern) and rewrote the tests to pass
  fakes. Also DI'd `find_api_key(_env, _home)` and `serve_app(_env)` +
  `build_app(_env)` + `auth.session_secret(_env)` for the env-reading
  leaves.
- **Env-seam tests — suppressed with reasons.** The tests whose *subject*
  is the env read itself (missing config must fail honestly, env
  precedence, the reload factory building from the environment, the
  locale seam). The code-side fix would thread `_env` through ~10 auth
  functions for test-purity on the security seam — judged not worth it;
  the tests exercise the documented config surface.
- **conftest network guard — suppressed with reason.** Blocking sockets
  in tests is infrastructure, not a dependency fake; DI cannot replace it.

### 3.3 The heavy-ML inline imports (transformers, open_clip, torch, paddleocr)

The repo standard says imports at top, never in function bodies — but
these were deliberately lazy ("heavy import — only when the stage actually
runs"). Decided: transformers/open_clip/torch are **declared
dependencies** (pyproject), so top-level imports are contract-correct —
moved them. `paddleocr` is NOT declared (it lives in `.venv-htr`, the HTR
environment); nothing imports `layout_detect` as a module — it runs only
as the layout-pass script in that environment, so its top-level import
changed nothing functionally. All moved to top; the lazy-import comments
were removed as superseded by the standard.

### 3.4 archive.py's inline imports were cycle-avoidance — restructured, not suppressed

`Archive.publish` lazily imported `Projection`, `create_demo` lazily
imported `demo_data`, etc. The cycles: projection.py imports
`CONTENT_FILES` from archive.py; demo_data.py imports `Archive` +
`split_content` from archive.py. The standard says cycles are fixed by
restructuring, never lazy imports. Moved `CONTENT_FILES`,
`CONTENT_CAPTIONS` and `split_content` into tools/records.py (the object
model — "every closed vocabulary lives here"), switched demo_data's
`Archive` reference to TYPE_CHECKING-only, and moved all of archive.py's
imports to the top. All 27 inline-import findings across 8 files cleared
(including cli.py's, which bundled the `_capture_client` extraction).

### 3.5 Untracked files (tools/code_health.py, code_health_hook.py, code_health_lsp.py, check_records.py) are out of scope

These are the user's uncommitted work-in-progress (a code-health tool
that predates/parallels lucidlint). They carry 77 findings (6 swallow,
12 long-param-list, 5 special-case, all conditional-polymorphism, etc.).
Refactoring uncommitted WIP would clobber the user's in-flight work; the
files are excluded from the branch's commits too. Flagged for the user.

### 3.6 docs findings — 1 fixed, 4 left with reasons

- `docs/plans/design-decisions.md` backticked docs/ux-standards.md — a
  doc that lives in omp-config, not here. Fixed the reference to name the
  owning repo (matches the file's own convention at line 24).
- The 3 parent-relative findings are tool bug 1.1.
- `AGENTS.md` → `docs/IMPORT-WORKED-EXAMPLE.md` unreachable: that file was
  **gitignored** (the private worked-example doc the AGENTS.md decision
  tree calls "private review doc, not shipped"). The reachability scan
  includes gitignored files (rglob fallback without pygit2) — a false
  positive on intentionally-private material. Not suppressed (leaving the
  finding visible documents the private-doc status).

---

## 4. What was fixed (summary by family, tracked files)

| Family | Count | Outcome |
|---|---|---|
| docs-link/undiscoverable | 5 | 1 fixed, 4 tool-bug/private-doc (above) |
| noqa | 4 | reformatted to the tool's reason format |
| boolean-arg | 4 | 1 named (Clusters), 3 redundant defaults removed |
| positional-literals | 12 | keyworded (read_projection/_merge_records/_request/BaselineIdentity/datetime) |
| swallow | 17 | re-raised, returned, or documented (6 in untracked code_health.py) |
| inline-import | 27 | moved to module top; archive cycles restructured |
| global-state | 15 | AuthState class; tuples for static tables; functools.cache; MappingProxyType |
| monkeypatch | 24 | 10 DI-fixed (auth seams, find_api_key, serve_app), 14 documented env-seam/infrastructure |
| special-case | 6 | 5 documented guards (1 untracked) |
| broad-except | 6 | documented terminal boundaries |
| complexity | 22 | extract-method refactors (export_gedcom CC 68 → 16 + helpers) |
| long-param-list | 17 | parameter objects for repeated groups, documented one-off helpers |
| latent-class | 5 | 4 documented (idiom/design), 1 in flight |
| record-shape | 278 | config-ignored with reason (wire-format seams, §2.2) |
| magic-number | 59 | named constants |
| loop-pipeline | 26 | comprehensions where equivalent |
| detached-method | 24 | @staticmethod |
| duplicate | 18 | shared helpers extracted |
| unused | 33 | dead code deleted, seams documented, false positives suppressed |
| class-module | 12 | config-ignored with reason (§2.3) |
| vague-name | 3 | config-ignored with reason (§2.4) |
| fakefs | 139 | config-ignored with reason (§2.1) |
| conditional-polymorphism | 3 | all in untracked files — out of scope (§3.5) |

---

## 5. Late discoveries (post-delegation)

### 5.1 `ignore unused` is self-defeating on this build — the comment counts as a reference

Adding `# lucidlint: ignore unused <why>` to a function converts a warn
`unused` finding into a FAIL `stale-suppression` finding: the comment
itself registers as the missing reference, so the finding stops firing
AND the suppression is reported stale (proven by A/B experiments). The
13 remaining warn `unused` findings (test seams in attestation,
document_capture, layout, pii_markers; the in-module helpers in memory.py
that the rule's cross-file-only counting misses) therefore cannot be
suppressed per-function. The eval modules' entry points are config-ignored
(`tools/eval_memory.py`, `tools/eval_review.py`) — the module IS the
test-driven harness, so cross-file reference counting is structurally
inapplicable. The rest stay visible warns (never gating).

### 5.2 The stale-suppression whack-a-mole: markers match by RAW SIGNAL, line and line-1 only

The latent-class family collapses three signals (`closures`, `partition`,
`strewing`) under one display kind — `ignore latent-class` matches none
of them. Combined with the line/line-1 window (a stacked comment or an
intervening decorator line breaks the match), this produced a long chain
of stale markers. Fixes: `ignore <raw signal>`, single-line comments
directly above the finding, or trailing on the decorator line. The
tool's stale-suppression finding reliably points at the exact stale
marker — the loop terminated quickly once the signal names were known.

### 5.3 pyrefly: frozen dataclasses do not structurally match Protocols

The duplicate-refactor's `_unique_records` helper needed a type bound
carrying `.id`. pyrefly rejects frozen dataclasses (Person/Place/Org)
against any Protocol bound (`bad-specialization`), and PEP-695 generics
don't infer from the constructor argument — so the PEP-695 form ruff's
UP047 wants breaks pyrefly. Resolution: keep the `TypeVar` (with a
documented `# noqa: UP047`) and a `cast(Any, ...)` at the `.id` access,
commenting the proven constructor contract. The ruff suggestion and
pyrefly's inference are in conflict; the type checker's semantics won.

## 6. End state

| Metric | Value |
|---|---|
| findings at first run | 834 actions (599 after dedupe), 721 in-scope-tree |
| tracked-file findings fixed/resolved | 644 → 17 (all fail-severity resolved) |
| remaining tracked | 4 docs (tool bugs §1.1 + private doc §3.6), 13 warn unused (§5.1) |
| untracked WIP files (user's, out of scope) | 74 findings (§3.5) |
| repo gate (`make test`) | green — 430 pytest + 356 vitest, lint + typecheck clean |

The 4 remaining docs failures and the 13 unused warns are all documented
above — each is either a tool bug or an intentional design the tool
cannot express.

---

## 7. For the tool author — could we use the built-in `fix` capability? No.

We attempted it and it was unusable in the v0.1.0 release. Every refactor in
this session (all ~22 complexity extractions, the parameter objects, the
keyword-izing) was done by hand. The blockers, in order hit:

1. **`fix_engine.py` is not shipped in the release bundle.** The installed
   v0.1.0 `~/.local/share/lucidlint/` bundle has only `lucidlint.py`,
   `bin/`, `version.txt`. The orchestrator's `fix` path imports
   `fix_engine` (an "optional extra") and degrades if absent. We had to copy
   `fix_engine.py` out of the build-tools source repo into the bundle dir.

2. **CLI syntax mismatch: the README is ahead of the v0.1.0 binary.** The
   README documents `lucidlint fix --kind extract-method --file X --line N`
   (the build-tools HEAD CLI), but the installed v0.1.0 `lucidlint.py`
   only accepts the older flat flags `--fix-kind/--fix-file/--fix-line`.
   `fix --kind ...` → "unrecognized arguments".

3. **With the correct flat flags, the seam detection returns nothing.** Even
   with the repo's `fix_engine.py` copied in and libcst installed:
   `--fix-kind extract-method --fix-file tools/gedcom_document.py
   --fix-line 131` → "fix: nothing to change" for a function at CC 68. The
   v0.1.0 orchestrator's command contract (what it passes to the fix
   engine) does not match the newer `fix_engine.py` from the repo — no
   seam is found, no preview, no diff.

4. **`libcst` is not a declared/pinned dependency.** We installed it into
   the project venv (`uv pip install libcst`) to satisfy the engine, but
   the next `uv sync` (the repo's normal `make setup`) pruned it because
   it is not in the lock — the fix path then crashes on `import libcst`.
   The bundle neither ships nor pins it.

Recommendation: ship `fix_engine.py` (and pin `libcst`) in the release
bundle, align the CLI + orchestrator/fix-engine contract with HEAD, and
make the "nothing to change" path actually explain why the seam wasn't
found (or match HEAD's seam detection). Once mechanical families
(`positional-literals`, `stale-suppression`, `magic-number`) and the
structural previews work from the release bundle, the agent loop the
README describes becomes usable; today it isn't.

### Consolidated snag list for the tool author

- **B1 (docs-link bug).** `../`-prefixed backtick paths resolve against
  the repo root, not the doc's directory (`scanner/src/docs.rs`), unlike
  markdown links. §1.1.
- **B2 (unused counts only cross-file refs).** In-module-used helpers
  (`memory.py _slug`, `_person_of`, …) are flagged dead. §1.2.
- **B3 (`ignore unused` self-defeating).** The suppression comment counts
  as the missing reference, so a warn `unused` becomes a FAIL
  `stale-suppression`. §5.1.
- **B4 (noqa reason heuristic).** Only a *second* `#` comment counts as a
  reason; `# noqa: BLE001 — reason` is invisible. §1.3.
- **B5 (swallow heuristic).** Only control-flow exits (return/raise/
  break/continue) or returned-name mutation count as handling; logging
  does not, so "log and proceed" terminal handlers must be suppressed
  with a comment instead. §1.4.
- **B6 (suppression matches raw SIGNAL, not display kind).** `latent-class`
  collapses `closures`/`partition`/`strewing`; `ignore latent-class`
  matches none of them → unconditional stale-suppression until the raw
  signal is used. §5.2.
- **B7 (suppression window is line and line-1 only).** An intervening
  decorator line (`@final`) or a stacked comment line breaks the match,
  silently. §5.2.
- **B8 (fix capability unusable in v0.1.0).** §7 above — engine not
  bundled, CLI/contract mismatch, seam "nothing to change", libcst not
  pinned.

Each is reproduced with the exact file/line in the referenced section.

---

## 8. Resolution of the log-as-handling question (2026-08-16)

The reviewer questioned whether "log-and-continue" was ever legitimate, and
correctly caught an overstatement: one of my suppressions — `find_api_key`
treating a corrupt `auth.json` as "no stored keys" — was a genuine
silently-degraded-config swallow, not a terminal boundary. Two actions:

1. **The standard was tightened** (`docs/coding-standards.md`, "Fail fast,
   never swallow errors"): "log" is the *terminal* option, legitimate only
   where there is no caller to propagate to (background thread, callback,
   teardown) or the failure is non-fatal and the fallback is the visible
   behaviour; everywhere else — a caller exists, or the error is an
   operator/config defect — re-raise or handle observably. The anti-pattern
   is named: the silently-degraded config.
2. **`find_api_key` now fails loudly** on a corrupt/unreadable auth file
   (`AIClientError("cannot read the opencode auth file <path>: …")`) instead
   of falling back to "no key", and the suppression comment was removed (it
   no longer swallows). Added `test_find_api_key_raises_on_corrupt_auth_file`.

The lucidlint `swallow` heuristic (control-flow-or-return only) remains too
strict at genuine terminal boundaries (server.py's reprocess thread), where
the log is the only surface — but the repo's own test-seam discipline now
says so explicitly, so a suppression there carries a written, standard-backed
reason rather than a blanket "log is allowed".

## 9. Open consideration: the gate's leniency is an invisible-debt license (2026-08-17)

An agent here justified NOT fixing a record-shape finding in
`tests/test_pipeline.py` (the `_flag(...) -> dict[str, object]` pattern) by
citing the gate: ".lucidlint.toml config-ignores record-shape, the gate only
fails on new actions beyond the baseline, warnings never fail — the gate
tolerates it in practice."

The facts are true; the inference is wrong, and it exposed a tool-design gap:

- **Config-ignores are scoped debt acknowledgements, not licenses.** The
  record-shape ignore for `tools/**` (§2.2) is a reviewed decision for
  wire-format seams. The agent used it as a blanket reason to skip a
  finding without evaluating it on its merits (is this dict a wire-format
  seam?) — "the gate won't fail me" replaced "is this right?".
- **The acknowledged debt is invisible.** The verdict counts baselined and
  warning findings, but config-ignored findings are filtered BEFORE the
  verdict — they vanish entirely. An agent (or human) can grow the
  config-ignored population without the gate ever showing it.
- **Warnings-never-fail + baseline + config-ignore compose into "nothing
  is ever wrong."** Each mechanism is individually principled (debt
  acknowledgement, no-false-positive drift); together they let the
  standard drift silently.

Consider for the tool (not decided):
- the verdict could report config-suppressed counts (a debt ledger: "N
  acknowledged in baseline, M warnings, K config-suppressed"), so ignoring
  is visible, not silent;
- a GROWTH signal: a config-ignored family whose finding count increases
  across runs is a sign the ignore's scope is wrong — the debt is being
  added to, not held;
- prefer per-site suppressions (with whys, which the tool already
  enforces) over blanket config ignores when a finding is a one-off.

---

## 10. The extraction findings were right; the hand-implementation of them was the failure (2026-08-20)

The pipeline anti-fragility work (commit 6a6dda3) was driven by lucidlint's
complexity and long-param-list findings — and every finding was correct.
Where the session went wrong was in IMPLEMENTING the extractions by hand
with a text editor: four distinct mechanical mistakes, none caught by any
linter in the stack:

1. **A module-level name collision.** A new `guess_pages()` CLI command
   shadowed an existing module-level `guess_pages()` helper (the model-
   inference loop). Legal shadowing — the later definition wins — so
   neither ruff nor pyrefly flagged it, but the CLI dispatch would have
   silently called the wrong function.
2. **Unreachable leftover tails.** After extracting a helper, the old
   body's closing `if missing: ... return 0` stayed behind as dead code
   after the helper's `return`.
3. **A `def` whose parameter list was split from its name** by an
   insertion that landed inside the parens (`def f(\n<blank>\n  arg:`).
   Python parses it; it's a structural smell only a formatter/linter
   notices.
4. **Orphaned suppression comments** after refactoring moved the def away
   from its `# lucidlint: ignore` — this one lucidlint's
   `stale-suppression` rule DID catch, correctly and deterministically.

**The core lesson: the fix engine already does these extractions
deterministically — the session should have used it instead of hand-
editing.** `lucidlint fix --kind extract-method --file F --line N`
previews the seam (libcst-based, bounded to ≤13 decisions so the result
lands under the CC-15 gate, made private by construction), and applying
with `--name` is the commitment. Run against the pre-refactor
`tools/layout_detect.py`, it proposed exactly the loop-body seam the
session extracted by hand (`for image in pages:` → a private method, call
site replaced) — correctly, in one preview, before any edit landed.
`unreachable`/`noop-statement` fix kinds delete dead tails like finding 2
deterministically. The tool's R27 ("agents never compute line numbers —
the tool owns its own coordinates") exists precisely so an agent does not
hand-apply these.

The fix surface needs `libcst` in the running venv (the engine refuses
without it: "the Python fix engine requires libcst"). Added to the dev
dependency group so the fix commands work in this repo.

**The corrected process for a complexity/long-param-list finding:**
1. `lucidlint fix --kind extract-method --file F --line N` (no name) →
   read the proposed diff + the seam's first lines;
2. judge the seam (is this the right split? — the engine proposes, the
   agent decides); if wrong, the preview is discarded, nothing changed;
3. apply with `--name _private_helper --confirm` (the name is the
   commitment);
4. `lucidlint fix --kind unreachable --file F --line N` for any dead
   tails the move left behind;
5. re-run the gate. Hand-editing is the fallback only when the engine's
   seam is genuinely wrong — not the default.

**Findings lucidlint could still add** (correct-by-construction, beyond
what the fix engine covers):
- **Duplicate module-scope definition**: two `def <name>` at module level
  is a shadowing hazard; flag the second. The module's name→line map is
  already in the tool's graph. (Finding 1 — no existing rule covers it.)
- **A `def` name and its first parameter separated by a blank line**:
  mechanical formatting smell from an edit tool landing mid-parens.
  (Finding 3.)

**What already worked well:** `stale-suppression` caught the orphaned
ignore (finding 4) — the suppression-adjacency rule is doing its job; the
`--file` LSP mode surfaced syntax errors from botched edits immediately,
before the test gate; the complexity/long-param-list findings drove the
right extractions, and the repo's per-site `# lucidlint: ignore
long-param-list` + why pattern (§9's conclusion) held up — only genuinely
single-call-site helpers got the ignore, the rest were refactored.
