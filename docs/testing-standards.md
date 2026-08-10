# Testing Standards — The Loft

## Definitions (2026-08-10, user — the vocabulary is strict, one meaning everywhere)

- **Test** — a check that is *deterministic*: same inputs, same result, always, on any machine. No network, no model, no wall-clock.
- **Eval** — a check that runs deliberately *non-deterministic* code — a real model. An eval costs money and takes time, so the discipline is economy: **never more than one eval covering the same thing** (duplicate coverage is waste); and when the code under test can be run **once** and its output evaluated for several conditions in one go, do that — never recreate the output for each condition.
- **Tests and evals share the same harness** (pytest, 2026-08-10) for consistency. Both run exactly **once** — a check that would need re-running to go green is flaky, and flakiness is a bug in the check, never a reason to re-run ("we run it once. If it fails we fix it" — user, 2026-08-10). Both **fail fast** — a check that cannot run because needed infra is missing (the API key, tesseract) fails loudly and is **never skipped**: a skipped check would green a suite that never ran (2026-08-05).
- **Unit test** — a single class or function, with fakes for any dependencies.
- **Integration test** — a group of related classes together (a class and its dependencies), with fakes for everything outside the set under test.
- **E2E test** — a process end to end: user input to user output through the series of steps.

Given the definitions, the repo's inventory:

| | Deterministic? | Runs in `make test`? | Examples |
|---|---|---|---|
| **Tests** (pytest + vitest) | yes | always | the archive-quality checks (drift guard, description, place-note, story-date, completeness — the older wording called them "evals"; they were always tests) |
| **Evals** (the `eval` marker in pytest) | no — a real model | **no** — deselected by `addopts -m 'not eval'`, run only with `pytest -m eval` (or `-k` for one piece) | the review cases (each a single conversation turn), the multi-turn arc, the caching prefix check, the memory cases, the transcription pipeline (the one e2e-shaped eval) |

The marker's name is `eval`, not `e2e`, so "e2e" keeps its definition (2026-08-10): most evals are per-turn checks against the model, not end-to-end processes.

## The split

- `tests/` — Python (pytest) for the tools (`tools/`): import, publish,
  rebuild-index, fake-data, archive checks. These carry the real logic; they
  get the coverage gate.
- `app/tests/` — JS (vitest + happy-dom) for the web app: date handling,
  the router, the index builder, view rendering. Pure functions first; DOM
  only through small view modules.
- **Organisation: unit / integration / e2e (the definitions above).** Unit tests exercise a single class or function in isolation with fakes for its dependencies; integration tests exercise a group of related classes together (a class and its dependencies), faking everything outside the set under test; e2e tests exercise a process end to end, from user input to user output through the series of steps. The real-model **evals** sit in the same pytest harness, marked `eval`, never in the gate.

## Rules

- **Mirror module paths.** `tools/foo.py` → `tests/test_foo.py`;
  `app/bar.js` → `app/tests/bar.test.js`.
- **Deterministic, always.** No wall-clock, no network, no order dependence,
  no unseeded randomness. Fake data uses seeded generators.
- **Never real timers.** A test must not wait wall-clock: vitest fake timers
  (`vi.useFakeTimers()` + `vi.advanceTimersByTimeAsync`) drive every
  timeout, debounce and interval; a real `setTimeout`/`await sleep` in a
  test is a bug, not a convenience — it makes the suite order- and
  machine-dependent (2026-08-05: a draft-save debounce leaked across tests
  because the fix used a real wait). Timers are drained
  (`advanceTimersByTimeAsync`) before the test ends so nothing fires into
  the next test. **The discipline lives in `beforeEach`/`afterEach` — every
  test's independence is visible from the setup, never from a test's
  position, its order in the file, or a comment.** A test whose correctness
  depends on where it runs, or that needs a "runs last" comment, is a test
  that leaks. Where the behaviour under test is an *event* rather than a
  timer (a router's `hashchange`), dispatch the event explicitly
  (`window.dispatchEvent(new Event("hashchange"))`) — deterministic, no
  timer at all.
- **Assert behavior, not implementation.** Test the observable contract —
  what the function returns and what the user sees — not how it's wired.
- **DI fakes over `unittest.mock.patch`.** Inject the archive handle or the
  Drive client; fakes subclass the real classes so type checking still holds.
  Injection patterns, in order: **parameter injection** for leaf-level
  dependencies (underscore-prefixed optional param falling back to the real
  implementation); **services container** for deep call chains;
  **ContextVars** for request-scoped singletons. Forbidden:
  `monkeypatch`/`unittest.mock.patch`, module-level mutable state, lazy
  imports, and abstract base classes with a single implementation. Pure
  functions need no mocking; global patching is a last resort and a smell.
- **Every test defends an observable contract** and fails on a plausible bug.
  A test that cannot fail is not a test.
- **The 2060 test is a test.** The archive must be understandable with no app:
  a test walks the README + a sample sidecar and asserts a stranger could
  reconstruct the item.

## Gates

- `make test` runs lint + typecheck first; a lint failure blocks tests.
- `make coverage` emits `coverage.xml` (Python, CI gate) and
  `app/coverage/clover.xml` (JS). CI floor starts at 0 until real code lands
  and is raised toward 80 as tools get tests.
- **Archive-quality tests are part of the gate (2026-08-05/06)** — the
  archive itself is under test, not just the code: the projection drift
  guard (committed `app/data` ≡ publish of committed archive), the
  description check (letters/documents are specific and correspondence-
  distinct), the place-note check (no process jargon in notes), the story-date
  check (no catalogued story dated by its told day without the narrator's
  words), and the completeness check (everything catalogued is visible
  somewhere). A data change that breaks one is a bug, not a test update —
  unless the *rule* changed, in which case the check is rewritten with the
  rule, failing first.
- **The private dataset never lives in the public repo (2026-08-08).** The
  real family archive (`archive/`) and its derived projection (`app/data/`)
  are gitignored — the public repo carries the code and the synthetic
  fixtures, never real content. The archive-quality tests therefore run
  **locally** (the dataset is present in the working tree) and **skip in
  CI** (the checkout has no archive): each carries
  `skipif(not (REPO / "archive" / "people.json").exists())` — the one
  deliberate exception to the fail-fast rule (2026-08-10): a check whose
  dataset is intentionally absent from the environment is SKIPPED with the
  reason stated, never a green lie — and never silently. Every evals and
  other infrastructure gap (the API key, tesseract) FAILS loudly instead.
  These same tests are the **integrity
  check for the live product** — the deployed instance runs them against
  the real archive on a schedule (see the PRD's weekly integrity check);
  a failure there is family data needing a fix, never a test update.
- **Never let a derived artifact drift from a fresh run (the odd model,
  named).** This codebase's data is unusual: it is *committed* (real
  content in `archive/`) *and* *produced* (imports and the demo generator
  write it) — so whenever something is both committed and derived, its
  shape rule is enforced per [A described contract is not an enforced
  contract](coding-standards.md#a-described-contract-is-not-an-enforced-contract)
  — verified here against regeneration. Three tests:
  - the committed version equals a fresh run, compared on a defined stable
    form implemented as a normalizing function declared alongside the
    producer (canonical ordering, no timestamps, paths relative to the
    repo root, locale-independent) — never raw output, so a
    non-deterministic producer cannot make the test flaky; pin the
    normalizer itself with a unit test for determinism and environment
    independence;
  - re-running a producer changes nothing (idempotent), compared on the
    same defined stable form — incidental raw-output nondeterminism
    (ordering, timestamps) is not drift;
  - the invariant is asserted on the producer's *declared* inputs and
    outputs (a unit-level check, no live state, no real names) and
    separately on the fresh-run result using the same defined stable
    form; both assertions must pass — because a producer bug re-manifests
    on every fresh build while the hand-patched committed output stays
    green.
  Two failure modes, each needing its own check: **the product is wrong**
  (bad content, a missing edge, wrong dates — the archive-quality evals
  check the committed data directly) and **the producer is wrong** (would
  write wrong data on a fresh run — caught by the declared-inputs check
  above). Regenerability is a claim, verified not assumed.
- **Thorough means the boundaries and the whole surface, not the happy
  path.** Test what can actually break: closed sets, resolution seams,
  and the cross-checks between a producer and its consumer. When a
  property must hold across a collection, the test walks the whole
  collection, not a sample, and checks every surface where the fact can
  be expressed and every boundary where it can fail. A test that passes
  on well-formed input while a stated contract is unmet is not testing
  the contract.
- UX (engagement, legibility) is verified by the D8/D10 observation protocol
  (`DISCOVERY.md`) — there is deliberately no analytics in the product, so
  observation is the substitute, not a test gap.

- **Evals run once and are never flaky (2026-08-10).** The real-model
  evals (review, memory, transcription) run each case exactly once — never
  a retry, never a majority-of-runs (the Definitions). The model's judgment
  varies even at temperature 0, so a case that fails its single run is a
  REAL failure to fix — the case's scenario, the prompt, or the guard is
  at fault — and the eval stays red until the behaviour is right (the
  Seascale stall: the multi-turn arc case caught the live regression and
  stayed red until the prompt was fixed). A case that would only pass on a
  re-run is flaky, and flakiness is a bug in the eval, never a reason to
  re-run. If a case proves genuinely stochastic despite a fair scenario,
  the fix is to make the scenario unambiguous (anchor the pronouns, name
  the claim), not to give the case another chance.
- **Eval economy — no duplicate coverage, one run many conditions
  (2026-08-10).** No two evals cover the same thing: every eval pins a
  distinct contract facet, and a new eval that re-exercises ground an
  existing one covers is a review finding, not an addition. When one run of
  the code under test produces an output that several conditions must hold,
  evaluate them all against that one output — never run the code again per
  condition. (The review cases each exercise a DIFFERENT input, so they
  need their own run; the persona guard and the feedback property are
  evaluated on every case's one output.)

- **When a failing test catches a narrow problem, hunt the pattern
  (2026-08-06).** The named case is the symptom, not the whole bug: if one
  invented artifact exists, check them all; if one date is mis-placed,
  scan the dataset for the same class. The failing test for the narrow
  problem is written first, then the pattern-hunt widens it into the
  rule's test.

- **When a narrow bug appears more than once, refactor the duplicate code
  that caused it (2026-08-06).** The same class of bug recurring in
  several places is a duplicated-implementation smell: fix the shared
  seam (a helper, a component, a single rule) and let the tests cover it
  once — the place/theme/item pages' story-lists each re-implemented the
  same render-once split until one component owned it.
