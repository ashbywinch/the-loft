# Testing Standards — The Loft

> **Standard** — the Definitions below are the repo's live
> standard, read by every agent and reviewer working here (they replace the
> older "eval == e2e" wording). This is a repo document, not a symlinked
> skill: it takes effect for agents reading the repo immediately — no
> `make install`, no `omp` restart.

## Definitions (user — the vocabulary is strict, one meaning everywhere)

- **Test** — a check that is *deterministic*: same inputs, same result, always, on any machine. No network, no model, no wall-clock.
- **Eval** — a check that runs deliberately *non-deterministic* code — a real model. An eval costs money and takes time, so the discipline is economy: **never more than one eval covering the same thing** (duplicate coverage is waste); and when the code under test can be run **once** and its output evaluated for several conditions in one go, do that — never recreate the output for each condition.
- **Tests and evals share the same harness** (pytest) for consistency. Both run exactly **once** — a check that would need re-running to go green is flaky, and flakiness is a bug in the check, never a reason to re-run ("we run it once. If it fails we fix it" — user). Both **fail fast** — a check that cannot run because needed infra is missing (the API key, tesseract) fails loudly and is **never skipped**: a skipped check would green a suite that never ran. **A gate's verdict is the run's verdict**: a failed CI step is never re-run in search of a pass — the code (or the check) changes, then the gate re-runs; a green obtained by re-running an unchanged failure is not green and is prohibited, locally and on CI, for tests and evals alike.
- **Iterate on the failing check, never the suite.** A change in progress
  is tested against the ONE failing test — or the smallest subset that
  covers the change (`pytest path/to/test.py::test_name`), not the full
  suite and not the full gate: the suite and the gates run ONCE, for the
  final verification of a ready change. Running the whole suite to test
  each iteration is the same waste — and the same prohibited re-run — as
  running it to find a green. For an EVAL change, the failing run is the
  single paid run OF THE ITERATION LOOP: read its output, the request,
  and the model's reasoning from that captured artifact, iterate on the
  prompt or code from that evidence alone, and make the final
  verification the only further model run — a failed run is never
  re-run as-is to sample a better draw.
  *(Deployment: this file is the scaffolded copy of the standard — the
  canonical lives in omp-config's `standards/`, and this repo's copy
  does not update itself:`edit the canonical → make install → restart
  omp` per `skill://update-skills`.)*
- **Unit test** — a single class or function, with fakes for any dependencies.
- **Real-world data enters tests as committed fixtures of the pipeline's
  detector output (user).** Never open the archive's scans or
  images in a test, and never hardcode an archive path in a test: a real
  page's correctness is tested from the detector's **committed output —
  the marks file, image-free** (page-01: `tests/fixtures/page01-marks.json`
  — the marks' boxes, measurements and ink pixels, serialised once from
  the canonical scan). Downstream stages (words, rows, the drawing pins)
  run FROM that fixture, at the detector's own scale where the geometry
  lives. A test that needs the scan to run is a test whose data is not
  committed — commit the data or re-express the property; a test is
  never skipped because the scan is absent, and never gains an archive
  path. The archive-quality checks (below) remain the one exception whose
  dataset is intrinsically the live archive.

Given the definitions, the repo's inventory:

| | Deterministic? | Runs in `make test`? | Examples |
|---|---|---|---|
| **Tests** (pytest + vitest) | yes | always | the archive-quality checks (drift guard, description, place-note, story-date, completeness — the older wording called them "evals"; they were always tests) |
| **Evals** (the `eval` marker in pytest) | no — a real model | **no** — deselected by `addopts -m 'not eval'`, run only with `pytest -m eval` (or `-k` for one piece) | the review cases (each a single conversation turn), the multi-turn arc, the caching prefix check, the memory cases, the transcription pipeline (the one e2e-shaped eval) |

The marker's name is `eval`, not `e2e`, so "e2e" keeps its definition: most evals are per-turn checks against the model, not end-to-end processes.

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
- **Never sleep.** A test must not wait wall-clock — `time.sleep`,
  `await sleep`, a busy-wait loop, or a fixed tick count in a test is a
  bug, not a convenience: it makes the suite order- and
  machine-dependent and slow. Production code that legitimately waits (retries,
  polling, backoff) takes its delay as a parameter — the DI seam — so
  tests inject `0` and the same code path runs instantly and
  deterministically. A rule that needs "if not CI: sleep" to pass is
  written wrong.
- **No fire-and-forget leaks.** An app-under-test that fires fetch calls
  without awaiting them (a `recordMessage`-style `fetch().catch()`) can
  keep running after the test ends: a chain still in flight when the next
  test starts lands on the next test's mock — or, once globals are
  unstubbed, on the real network (happy-dom resolves relative URLs against
  `http://localhost:3000`). Every suite drains pending chains until a full
  macrotask passes with no new call before the next test — condition-based
  quiescence, never a fixed tick count; CI and the local gate run the SAME
  command.
- **Never real timers.** A test must not wait wall-clock: vitest fake timers
  (`vi.useFakeTimers()` + `vi.advanceTimersByTimeAsync`) drive every
  timeout, debounce and interval; a real `setTimeout`/`await sleep` in a
  test is a bug, not a convenience — it makes the suite order- and
  machine-dependent. Timers are drained
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
- **A check that fails inconsistently is fixed at the source — ALWAYS.**
  There is no other answer, for tests and evals alike: no
  re-run-until-green, no "merge anyway, the content is safe", no golden
  file that stops checking the behaviour, no widening the assertion until
  the case passes. A test's bug is its data, seam, or assumption — fix it
  deterministically. An eval's bug is the scenario, the prompt, the guard,
  or the client's handling of the provider — fix it so the real behaviour
  passes consistently, and prove the fix with the live suite. This is not
  a judgement call with options; it is the only permitted answer.
- **A retry is never the fix.** The eval evaluates the ONE
  output the flow produced. Building a re-ask into the flow so a
  content condition can pass on a later attempt — a "correction turn"
  for a missing or misspelled verdict key, a regenerate-on-empty-field,
  a "repair" loop that re-rolls the model until the guard is satisfied —
  is the rerun lottery by another name, and it is forbidden: the flow
  must not reshape or regenerate the model's content to satisfy the
  eval's conditions. A malformed verdict FAILS the eval loudly, carrying
  the full output (the missing-field guard reports "lacks the 'question'
  key — the output was: …", never a silently empty field); the eval
  stays red until the scenario (the schema's presentation) makes the
  model pass. The ONE permitted retry: the client may re-attempt a
  transient transport/provider failure — a response with NO content at
  all (a 5xx, a dropped connection, a 0-token 200) — as part of the same
  logical run; content the model produced is never regenerated.
- **Failure messages never truncate the failing content.** An
  assertion must show the WHOLE offending output — the persona guard's
  `text[:80]` hid the words that failed. Truncation is for sliders
  and previews, never for an error that must be diagnosable from its own
  message.
- **The 2060 test is a test.** The archive must be understandable with no app:
  a test walks the README + a sample sidecar and asserts a stranger could
  reconstruct the item.

## Gates

- `make test` runs lint + typecheck first; a lint failure blocks tests.
- `make coverage` emits `coverage.xml` (Python, CI gate) and
  `app/coverage/clover.xml` (JS). CI floor starts at 0 until real code lands
  and is raised toward 80 as tools get tests.
- **A refactor never reduces coverage.** Migrating code brings its
  tests: same cases, same assertions, re-pointed to the new home —
  never dropped "to be re-added later." The only tests a refactor may
  delete are those pinning the code it deletes. The coverage floor is
  a floor, not a target that falls when code moves: `make coverage`
  stays green, and a moved module's test count does not shrink.
- **Archive-quality tests are part of the gate (split to
  `make verify` at the user's request: "make test should take a couple of seconds")** —
  the archive itself is under test, not just the code: the projection drift
  guard (committed `app/data` ≡ publish of committed archive), the
  description check (letters/documents are specific and correspondence-
  distinct), the place-note check (no process jargon in notes), the story-date
  check (no catalogued story dated by its told day without the narrator's
  words), and the completeness check (everything catalogued is visible
  somewhere). They carry the `archive` marker and run under `make verify`
  (`pytest -m archive`), excluded from `make test`/`make coverage` by
  addopts; CI runs `make verify` too (the checks skip there — no archive in
  the checkout). A data change that breaks one is a bug, not a test update —
  unless the *rule* changed, in which case the check is rewritten with the
  rule, failing first.
- **The private dataset never lives in the public repo.** The
  real family archive (`archive/`) and its derived projection (`app/data/`)
  are gitignored — the public repo carries the code and the synthetic
  fixtures, never real content. The archive-quality tests therefore run
  **locally** (the dataset is present in the working tree) and **skip in
  CI** (the checkout has no archive): each carries
  `skipif(not (REPO / "archive" / "people.json").exists())` — the one
  deliberate exception to the fail-fast rule: a check whose
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

- **Evals run once and are never flaky.** The real-model
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
- **Eval economy — no duplicate coverage, one run many conditions.**
  No two evals cover the same thing: every eval pins a
  distinct contract facet, and a new eval that re-exercises ground an
  existing one covers is a review finding, not an addition. When one run of
  the code under test produces an output that several conditions must hold,
  evaluate them all against that one output — never run the code again per
  condition. (The review cases each exercise a DIFFERENT input, so they
  need their own run; the persona guard and the feedback property are
  evaluated on every case's one output.)

- **When a failing test catches a narrow problem, hunt the pattern.**
  The named case is the symptom, not the whole bug: if one
  invented artifact exists, check them all; if one date is mis-placed,
  scan the dataset for the same class. The failing test for the narrow
  problem is written first, then the pattern-hunt widens it into the
  rule's test.

- **When a narrow bug appears more than once, refactor the duplicate code
  that caused it.** The same class of bug recurring in
  several places is a duplicated-implementation smell: fix the shared
  seam (a helper, a component, a single rule) and let the tests cover it
  once — the place/theme/item pages' story-lists each re-implemented the
  same render-once split until one component owned it.
