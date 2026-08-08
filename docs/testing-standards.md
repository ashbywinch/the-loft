# Testing Standards — The Loft

## The split

- `tests/` — Python (pytest) for the tools (`tools/`): import, publish,
  rebuild-index, fake-data, archive checks. These carry the real logic; they
  get the coverage gate.
- `app/tests/` — JS (vitest + happy-dom) for the web app: date handling,
  the router, the index builder, view rendering. Pure functions first; DOM
  only through small view modules.
- **Organisation: unit / integration / e2e.** Unit tests exercise one
  function or module in isolation with no API calls; integration tests run
  a full pipeline with fakes; e2e tests hit real external APIs, one
  consolidated suite per API, skipped by default (`@pytest.mark.e2e`).
  Shared infrastructure (fixtures, fakes) is extracted once, not copy-pasted
  per file.

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
- **Archive-quality evals are part of the gate (2026-08-05/06)** — the
  archive itself is under test, not just the code: the projection drift
  guard (committed `app/data` ≡ publish of committed archive), the
  description eval (letters/documents are specific and correspondence-
  distinct), the place-note eval (no process jargon in notes), the story-date
  eval (no catalogued story dated by its told day without the narrator's
  words), and the completeness eval (everything catalogued is visible
  somewhere). A data change that breaks one is a bug, not a test update —
  unless the *rule* changed, in which case the eval is rewritten with the
  rule, failing first.
- **The private dataset never lives in the public repo (2026-08-08).** The
  real family archive (`archive/`) and its derived projection (`app/data/`)
  are gitignored — the public repo carries the code and the synthetic
  fixtures, never real content. The archive-quality evals therefore run
  **locally** (the dataset is present in the working tree) and **skip in
  CI** (the checkout has no archive): each carries
  `skipif(not (REPO / "archive" / "people.json").exists())`, and the skip
  is the contract, not an accident. These same evals are the **integrity
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
