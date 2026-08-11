# Coding Standards — The Loft

House conventions, copied in full from the canonical global standard
(`docs/coding-standards.md` in the omp-config repo) and adapted to this
project's explicit decisions (see `docs/TECH-SPEC.md` §15 for the rationale).
The reviewer (PR-Agent) enforces exactly the rules present in this file — the
full global standard is copied below, so every rule is in force. When the
upstream standard changes, refresh this copy.

## Design principles

How these rules are written (and how to add one): a **positive statement**
first, a **named anti-pattern** when it helps, then **one concrete
example** — a rule without an example is a stub. Name the failure mode
("repeated parallel parameters", "swallowed errors") so it can be spotted;
point at the existing codebase pattern rather than reproducing long inline
samples.

What actually moves an agent (and why this doc is written this way):
large-scale studies of agent rule-files find rule *content* is a weak
lever — random rules perform about as well as curated ones — while rule
*polarity* is the reliable one: negative constraints ("do not refactor
unrelated code") consistently improve outcomes, and positive exhortations
("write clear code, use an object model") often do not and can regress
them (arXiv:2604.11088). Agents under-specified instructions *guess*
rather than ask; the fix is to name the action, the exact target, and the
scope of every requirement (arXiv:2607.02294). And a contract that is only
described is not enforced — models pass happy paths and miss the contract
even when it is in the prompt (ContractEval, ACL 2026). Principles that
follow: keep rules few, minimal and non-overlapping; state what must not
happen rather than prescribing how to be good; and prefer structural
enforcement (a type, a test, an eval) over prose — a rule without a check
is a wish. Write the rules that stop a failure, not the rules that sound
good.

- **The app arranges evidence; it never interprets it** (PRD §10). No mood
  labels, no auto-summaries, no "this is when it went wrong". Dates, order,
  facts — the reader assembles meaning. Copy is factual; personal observations
  are attributed testimony ("The curator: …"), never app prose.
- **The whole-model pass at boundaries.** Before a body of model work is done
  (a feature, an import run, a demo, several additions to one record family),
  read the model back as the next maintainer: every entity, field,
  vocabulary and seam, in one place. If any persisted record family has no
  validating type — its shape lives only in prose (docs, examples, code
  conventions) — centralize it in code; don't re-document it. The checkpoint
  question: *can a developer who never saw this conversation learn the model
  from the code alone?* ✗ the item sidecar stayed an untyped `dict` whose
  shape lived in PRD §6, TECH-SPEC and a worked example while the identity
  records (Person, Place, Org) each got a class (2026-08-05). ✓
  `tools/records.py` — Person/Place/Org/Relationship/Item, every closed
  vocabulary, one validation seam.
- **Enforce at the write seam.** A path that persists state validates its
  input against the model before writing — one chokepoint, one rule; a call
  site never writes an invalid shape "just this once". ✗ `save_item`
  validated only the id while the item shape lived in prose (2026-08-05). ✓
  `archive.save_item` runs `Item.from_dict` first; the archive and the model
  cannot drift.
- **Fixtures obey the model.** Test fixtures write shapes the model accepts —
  a fixture that violates it (an item without a date, when PRD §6 requires
  every item to carry one, even approximate) masks the gap instead of
  exercising it; when new enforcement breaks old fixtures, the fixtures were
  the bug. ✗ 14 test fixtures saving dateless items (2026-08-05). ✓ the
  `_item()` fixture helper in `tests/test_archive.py` that always produces a
  valid sidecar.
- **One formatter per artifact, decided here.** Machine-generated files are
  formatted by their generator, and that generator's format is the only one
  ever applied. The projection (`app/data/*.json`) is written by the Python
  toolchain — its one formatter is Python's `json.dumps(indent=1,
  ensure_ascii=False)`, and its sole writer is `loft publish`. Prettier
  formats hand-written app code only; `.prettierignore` excludes
  `app/data/`, so `make format` never churns generated output. ✗ the
  projection prettier-formatted (2-space, inline arrays) while the Python
  writers emitted `indent=1` — two formatters fought and every regeneration
  churned the diff (2026-08-04). This paragraph is the decision; a "nicer"
  formatter is a standards change, never a local improvement.
- **Derived data is regenerated, never hand-edited — and a test proves
  it.** Any file computed from other data (the projection `app/data`,
  generated indexes, avatars) has exactly one writer; hand-editing it is a
  bug, and a test pins the committed output to what the generator produces,
  so drift fails CI instead of silently diverging. ✗ the relationships
  table hand-edited into `app/data/people.json` — it was the only copy, a
  merge dropped it, nothing noticed (2026-08-04). ✓ `loft publish` is the
  sole writer and `tests/test_publish.py` fails if the committed projection
  diverges from publish of the committed archive. A derived cache is never
  a migration source either: bootstrap scripts read the archive or the
  committed projection, never a regenerable file that a previous run may
  have polluted, and a half-run migration is fully cleaned (tracked and
  untracked) before re-running.
- **Real content never lives in code.** Anything a user provides or states
  directly — scans, story text, the identity tables (people, relationships,
  places, themes), a dated, attributed fact — is archive content
  (`archive/`), changed only by add (docs/TECH-SPEC.md §3). Code is the
  pipeline: `loft publish` (Archive.publish -> Projection) regenerates every derived file
  from the archive; `tools/demo_data.py` is the fictional demo generator and
  a test guards that the real family's names never appear in it. ✗ the
  family's PEOPLE/RELATIONSHIPS/letters hardcoded in the old
  `tools/demo_data.py` — it forked the archive into the codebase, drifted
  from the projection, and the relationships were lost in a merge (removed,
  2026-08-04). ✓ `archive/people.json` (append-only, versioned) + the
  derivation engine; the committed projection must equal what publish
  produces, enforced by test.
- **Never generate testimony.** A story is a person's own words, verbatim —
  an AI-generated account is never attributed to a narrator (`told_by`),
  never framed as the narrator speaking ("Alex: …"), and never committed to
  the archive or projection as if told. ✗ the import flow's synthesized
  "seed stories" about the flat hunt and the Sundown gigs, attributed to
  the narrator (removed, user 2026-08-03). ✓ the capture flow: the account
  is typed, saved verbatim, and only then linked by the AI — the AI's
  summaries stay curator prose or stay unwritten.
- **Nothing asserted unreviewed.** The `proposed`/`confirmed` seam is product
  law: machine output enters as `proposed`; the operator verifies it in the
  same flow's review — kept = `confirmed`, dropped = gone. No silent
  autolabels, and no separate confirmation gate.
- **Separation of concerns.** One reason to change per module/function. Data,
  view rendering, and navigation live in separate modules with one-way
  dependency chains; an urge to import across layers means split, not
  shortcut. `app/views/*` render; `app/data.js` reads; `app/date.js`,
  `app/connections.js`, `app/people.js` compute.
- **Cohesive modules and classes.** A module/class owns its data and its
  invariants; external code never reaches into structures to compute
  derived values. Data + behaviour together: a public-data module that
  others manipulate is a poorly-organised dict; several functions sharing
  the same data are methods on that class (three or more free functions
  taking the same leading parameter are a class waiting to happen); a pile
  of functions over one structure is a finding. **No module-level mutable
  state and no `global`** — put state in a class named for the domain
  concept it represents, never the pattern name.
- **Each class in its own module.** Named after the class; exception for a
  module grouping closely related handful-of-fields models that share one
  reason to change. Extract once a class grows non-trivial behaviour.
- **No over-abstraction.** No abstract base classes with a single concrete
  implementation, no plugin systems or pipeline frameworks — write
  straightforward functions that call each other. Protocols or `Callable`
  aliases define a seam; a hierarchy with one leaf is ceremony.
- **Imports.** Every import at the top of the file — never inside a function
  body (inline imports hide dependencies from static analysis). Never import
  private (underscore) symbols from another module — make the logic public
  and documented, or extract it to a shared module. Circular imports are
  fixed by restructuring modules, never bodged with lazy imports.
- **Names communicate intent.** Domain names, not shapes: `dateLabel` not
  `formatThing3`. A name needing a comment is a failed name. Functions are
  verbs (`sortByDate`, `rebuildIndex`); variables hold what they name
  (`items`, `counts`, not `x`); booleans read in `if` (`hasAssets`, not
  `assetFlag`); an id is never a label (`item.id` vs `item.title`).
- **Don't let output format drive the domain model.** Values that appear
  together in a report or API response are not necessarily the same domain
  concept. Think carefully before bundling them.
- **No mystery code.** Raw integers as column indices, magic numbers, and
  string literals for domain concepts are named constants. If you would
  write a comment to explain a block, extract it into a named function —
  the name is the documentation.
- **Semantic types over primitives.** Dates carry precision; references carry
  status (`proposed`/`confirmed`); IDs are strings that never change;
  structured data is an object with named fields, not a bare `dict`/`{}`.
- **Quantities carry their units.** A distance, duration, speed, or weight is
  a typed value with its unit attached — never a bare number. Before
  reaching for `float`/`int`, ask "what unit is this in?"; unit-named field
  names (`duration_min`) are a smell that the type is missing.
- **UTC datetimes: aware, explicit boundaries.** Store and process UTC —
  never `datetime.now()` without a timezone. Display local time only at the
  presentation boundary. Document an external source's timezone and convert
  to UTC before storing; after parsing from a DB or file, check
  `tzinfo is None` and fix it. Naive↔aware comparisons raise; arithmetic is
  wrong across DST.
- **Domain concepts are classes — the type is the documentation.** When a
  concept has an identity (an id that never changes), a state
  (`proposed`/`confirmed`), or invariants (closed kinds, refs that must
  resolve), or when the same dict shape is re-parsed in more than one place,
  it is a domain object: give it a class whose `from_dict`/`to_dict` own its
  wire format — the archive is persisted state, so the class *is* the
  persistence contract (crash resumption never rebuilds a record the class
  didn't author). Spot it by the smell: a bare `dict[str, Any]` re-read
  field-by-field in two modules; a comment saying "the X record"; a status
  enum living as string literals. ✗ the identity tables as raw dicts with no
  integrity checks, the proposed queue as dicts with no promotion path, dates
  as an ad-hoc string plus a stringly precision — every one a concept that
  existed with no name to carry its invariants (2026-08-05). ✓
  `tools/records.py` (`Person`, `Place`, `Relationship`, `PeopleTable`),
  `Story`/`Ref`/`Fact` in `tools/memory.py`, `Knowledge` and its member
  records. **The default is the class; the raw dict is the smell, not the
  starting point.** One carve-out: the class is where the invariant lives —
  never a second copy in a consumer (a view re-checking what derive already
  validated is the anti-pattern; a value type with behavior is not a second
  copy).
- **Groups that travel together are a type — never repeated parallel
  parameters.** When the same data goes into more than one function as the
  same set of fields (the standing knowledge: people, places, themes, items; a
  request; a config), give it a name and pass it whole — a second function
  copying the same parameter list is the anti-pattern. ✗
  `assess(people=…, places=…, themes=…, items=…)` and
  `build_story(people=…, places=…, themes=…, items=…)` pass the same four
  lists under the same names. ✓ `class Knowledge: people, places, themes,
  items` — one object, one name, one place for the invariant.
- **A hoisted class hoists its member types and its functions with it.**
  When a group becomes a class, its members are their own typed records
  (never a repeated `dict[str, Any]`), and the functions that operate on the
  group or its members become methods — private (`_`-prefixed) ones too.
  ✗ `Knowledge.people: list[dict[str, Any]]` and a module-level
  `resolve_speaker(who, people)` / `_standing_knowledge(knowledge)` /
  `_new_person(name, existing)` reaching into the dicts. ✓
  `Person`/`Place`/`Theme`/`Item` records normalized once in the
  `Knowledge` constructor, with `Knowledge.speaker_for(who)`,
  `Knowledge.render()`, `Knowledge.narrator_dob(...)`, `Person.matches(name)`
  and `Person.proposed(...)` — the caller never re-parses a member.
- **Follow established practice for well-trodden surfaces.** Chat,
  autocomplete, forms, REST APIs — solved problems with documented
  conventions (REST: nouns for resources, plural collections, query params
  for filtering, non-CRUD actions as sub-resources or PATCH state changes).
  When a surface has been done before, research the convention first and
  follow it; record the research and any deviation with a named reason and
  date (`docs/CHAT-UX.md` is the precedent for chat). ✗ inventing a novel
  layout for a standard widget — a native datalist for the name picker, an
  action button below the composer, a full-width button where quick-reply
  chips belong. ✓ the researched chat pattern (composer bottom-most,
  quick-reply chips above it) and the combobox with a committed value shown
  as a removable pill (docs/CHAT-UX.md).
- **One way through for invariants — never parallel paths.** When a store has
  rules (append-only, supersede-don't-delete), or a surface has a style
  (buttons, chat), all code goes through the single owning module and the
  rules are enforced there — a test double that fails on a violation is the
  enforcement. ✗ every caller writing `store.write_new(…)` directly, or a new
  button style invented in a view. ✓ `tools/archive.py` (with
  `MemoryStore` failing any in-place edit), `docs/UI.md` components
  (`.btn`/`.field`/`.bubble` — never a parallel style), `app/chat.js` for
  chat surfaces.
- **Never hand-roll parsing or extraction where a library or a structured
  assertion exists.** The anti-pattern is a bespoke regex date scraper when
  the answer is "the model asserts what a value is, the library parses it".
  Dates: dateparser (locale-aware) validates values the model asserts — no
  hand-written date parsers (docs/prd/MEMORIES.md).
- **Dev is the environment, not the quality bar.** Code written during
  development is the code that ships — production standard from day one; the
  only thing dev changes is where the data lives.
- **Every `python -m` entry point forwards its argv.** A module whose
  `main(out=None)` defaults to a real path but whose `__main__` ignores
  `sys.argv` writes to the default silently — a "dry run" actually touched
  real output. Forward `sys.argv` into `main`.
- **Batch external API calls wherever possible.** A loop that calls an
  external API once per element is the anti-pattern — batch where the API
  allows it (bound the batches, map responses back in order), and where it
  does not, cache and reuse within the run instead of repeating the call.
- **Cache key hygiene.** Never include API keys or tokens in cache key
  parameters (rotation must not invalidate the cache). Never cache non-OK
  API responses — a transient failure (rate limit, bad key) must not poison
  the cache.
- **Partial output is a resume strategy, never an accident.** Broken partial
  output — a truncated file, a half-written store, a run that silently stops
  mid-way — is a bug. Intentional partial output is fine as part of a
  resumable checkpointing design: long operations are resumable if they
  crash (idempotent, checkpointed) and troubleshootable (the state shows
  where it got to; logs cover the failed stretch). Derived outputs are
  written atomically or gated behind success — a failed run never publishes
  a partial result over a good one. Never bulk-clear a surface holding
  manual, user-entered, or curated data.
- **Deterministic checks beat model judgment.** A rule that can be checked in
  code (a narrator not in the cast gets a connection question; a date question
  when the year is computable; a new artifact gets a "tell me more") is
  enforced in code, in the same redo loop — the LLM review pass is only for
  what code cannot check.
- **Tests first; LLM behavior gets evals.** Write the test before the code (a
  failing test first), or an eval when the behavior needs a model. Evals use
  real AND fictional fixtures so nothing is overfit to one dataset, and they
  run the production path exactly once — never sample-and-pick, never
  "try twice and take the best"; the production call self-corrects (review →
  redo) or it does not.
- **Anti-fragile: correct by construction.** Pure functions preferred —
  same inputs, same outputs, no hidden state (see `app/date.js`);
  errors are explicit and observable, never swallowed; type-checker flags
  are fixed, never suppressed; happy paths read naturally.
- **Obviously correct, not just correct.** The rightness of code must be
  visible to the reader from the code itself — a reviewer should be able to
  *see* that it is right, not have to trust that it is. Corollaries:
  invariants are stated where they are enforced (the write seam validates
  its own input — "Enforce at the write seam" above); state and setup are
  visible at the point of use (a test's independence comes from its
  `beforeEach`, never from where it sits in the file or a "runs last"
  comment); nothing behaves differently because of something the reader
  cannot see (module-level mutable state, order dependence, hidden timers).
  ✗ a test that only passes in a particular position, or a module whose
  behavior depends on a module-level flag set by an earlier caller
  (2026-08-05: a draft-save debounce leaked across tests because the timer
  discipline lived inside one test instead of the setup). ✓ the timer
  discipline in `beforeEach`/`afterEach`; `save_item` running
  `Item.from_dict` first; the record classes owning their invariants
  ("Domain concepts are classes" above). If a comment must explain why
  something is right, the code should state it instead.
- **Fail fast, never swallow errors.** Every `catch`/`except` must log,
  re-raise, or handle observably. Invisible failure is a bug:
  ```js
  // ✗ invisible
  } catch { /* fall back */ }
  // ✓ observable
  } catch (error) {
    console.error('module: what failed — and the recovery taken', error);
    /* fall back */
  }
  ```
- **Two-tier failure messages.** A user-facing failure emits a plain-language
  line ("the archive didn't load — the data files may be missing") *and* a
  dev log with the root cause. One half alone is a bug (the boot error and
  the Leaflet fallback both got flagged for missing the log half).
- **No backward-compat shims.** Delete the old path; migrate callers in the
  same change. No aliases, no re-exports, no "will remove later". The archive
  is the durable thing — the code is disposable and should stay small enough
  to be replaced without pain.
- **Boring over clever.** The stack is vanilla by decision; prefer the
  obvious implementation a future keeper can read in any editor.

## Python (`tools/`, `tests/`)

- ruff with `select = E,F,I,UP,B,SIM,N`, line-length 120, double quotes.
- basedpyright, gated inside `make test` on the error count.
- **A type-checker flag is fixed with a cast only when the cast NARROWS a
  value the code has already proven (2026-08-10).** The one legitimate
  shape is validate-then-narrow: the runtime immediately before the cast
  raised (or returned 400, or exhaustively checked) on any value outside
  the target set, and the cast tells the type-checker what the check
  proved — `if status not in RECORD_STATUSES: raise ValueError(...)`, then
  `cast(Literal[...], status)`. The type model is correct; the static
  types just cannot see the runtime proof, and the cast must sit adjacent
  to the proof. **Otherwise fix the type model properly — a cast there is
  a bodge:**
  - a cast that *converts* data (a plain dict into a typed record, a
    wider shape into a narrower one) is a bodge — conversions belong in a
    domain method (`from_dict`, `from_projection`) at the class's own
    seam;
  - a cast whose target contradicts the class's own contract (its
    docstring, its `__post_init__`, its sanctioned constructors) means
    the *annotation* is wrong — correct the annotation or use the class's
    sanctioned entry point, don't cast (the `Knowledge` case: the raw
    constructor declared `tuple[Person, ...]` while the class documents
    and implements normalizing the projection's plain dicts; the fix was
    `Knowledge.from_projection`, the class's own converter);
  - the tell-tale symptom of a bodge cast: the cast's result type is the
    SAME as the parameter's declared type yet the error persists — a
    same-type mismatch is the type-checker saying the model is off, not
    that a cast will help.
- **Never `# type: ignore`** — a suppression hides both cases: the code
  is either already right (then cast it, adjacent to the proof) or wrong
  (then fix the model). A suppression compiles a lie either way.
- Flat package layout; type every function signature (`dict[str, Any]`, never
  bare `dict`); each module has a docstring stating its contract.
- Functions take their dependencies as parameters — never read module-level
  mutable state (the generator's `main(out)` is the pattern).
- **Name tools and modules after domain nouns — the object model — with the
  domain verbs as methods on the noun.** The nouns are the archive's:
  `Archive` (the whole collection: `publish()`, `create_demo()`,
  `capture_document()`, `capture_memory()`), `Memory` (the narrator's
  capture flow), `GedcomDocument` (the interchange format:
  `from_text()`/`to_text()` — `import` is a keyword), `Server` (`serve()`),
  `Placeholder` (the stand-in family: `PlaceholderPaper`, `PlaceholderPhoto`,
  `PlaceholderObject`, `PlaceholderAvatar`), plus `Store`, `Records`,
  `Projection` (the derived `app/data`), `AiClient`. Never name a module
  after a verb ("publish", "derive", "import"), a transport medium
  ("email"), or out-of-domain jargon ("elicitation" — the UI's word is
  memory). When the UI has a word for a concept, the code uses the same
  word (2026-08-06: import_email.py → Archive.capture_document, after the
  model was agreed with the user).
- **Web servers are FastAPI + uvicorn** (2026-08-06, houses parity): the
  framework owns request parsing — query decoding, cookies, JSON bodies,
  redirects — which the former hand-rolled http.server handler
  reimplemented wrong one at a time (the auth bug class: a percent-encoded
  auth code, a `session=`-prefixed cookie, a JSON body).
- **Entities are nouns that own their invariants; operations are verbs
  with one effect.** Give the domain's *things* names (a person, a
  captured document, a rendered page) and let each own its invariants and
  be constructible in isolation — that is what makes it testable without
  the surrounding system. Give the domain's *actions* single-purpose verb
  methods on a noun (capture, merge, publish, render) that never carry
  content inside their control flow. The failure mode that undoes both: a
  body of content living inside a function that also performs I/O — it is
  neither a named entity you can test alone nor an operation with one
  effect. Spot it by asking whether the module's truth is only visible
  once it touches real state; if so, content was not separated from
  operation — split them.
### A described contract is not an enforced contract

A rule about how a system is shaped (which references resolve, which
vocabulary is closed, which data implies which link) is a *type, a
validator, or an eval*, decided where the data enters — and a test pins it
in the same change. A contract that lives only in a sentence is missed
exactly where it matters: models pass happy-path tests while the stated
contract is unmet (ContractEval, ACL 2026 Findings,
https://aclanthology.org/2026.findings-acl.2112/). A rule in prose without
a check is a wish:

- ✗ "The record's end date must be after its start date."
- ✓ `Record` is a type whose constructor rejects an end date before
  `startDate`, and a test pins that rejection.
- A validator that returns success when a required datum is missing is a
  finding: the fields the rule reads must be complete on the record, and a
  missing datum is a data gap that fails validation — never special-case
  the validator into guessing or skipping.
- **A rule that must hold across a collection names every surface it
  reads.** A fact can be expressed on more than one surface (a record's own
  text, a document that refers to it, a note); a cross-collection rule
  names every surface where the fact can be expressed, or it silently
  misses whole classes.
- **One operator surface: the `loft` CLI (`tools/cli.py`, wrapper script at
  the repo root). No per-module `__main__` shims.** `loft publish`, `loft
  serve`, `loft create-demo`, `loft capture-document`, `loft gedcom in|out`,
  `loft eval-memory`. The CLI constructs the nouns and calls the methods; a
  module's argv handling lives in the subcommand, never in the module
  (the old `tools/demo_data.py` ignored its argument and silently
  regenerated the real projection in `app/data` — 2026-08-04). ✓
  `loft` forwards argv by construction.

## JavaScript (`app/`)

- **Nothing told is lost.** Client-side capture auto-saves the whole chat
  transcript to the server ~1.5s after any change (superseding one draft id
  in place), and on close and page unload — a reboot must never eat more
  than the last few words, and Continue replays the chat from the stored
  transcript (docs/CHAT-UX.md).
- **Chat surfaces follow the chat standards** (docs/CHAT-UX.md, the detail;
  `app/chat.js`, the one way to build them): messages → input bar → action
  row, with the input bar **docked at the bottom** (only messages scroll) and
  the **send button on the bottom right** — the phone-thumb side; assistant
  bubbles on the left, narrator on the right, the bubble header a separate
  line from the body; the input auto-grows with the message, capped, so a
  long story is never clipped to one line; the input is disabled while the assistant is busy; the
  flow-ending action sits below the input; nothing told is lost on close or
  unload. A chat surface built outside `app/chat.js`, or a send button that
  is not bottom-right and docked, is a finding.
- Vanilla ES modules. **No runtime dependencies beyond vendored libraries** —
  the app ships as files; a small vendored runtime library is allowed if it
  degrades gracefully (e.g. Leaflet for the map, with the SVG dot view as the
  offline fallback — `docs/TECH-SPEC.md` §15). Dev tooling (eslint, prettier,
  vitest) is allowed and degrades well.
- **Vanilla is not classless.** The stack decision is no framework, no build
  step, no runtime deps — `class` is ES2015 and always allowed. A value type
  with real behavior and several consumers earns a class in `app/` too (the
  date model is the planned first one: a `PreciseDate` twin of the Python
  class, pinned by parity tests). What never belongs in a view is a second
  copy of enforcement — an invariant the archive or derive already checks is
  checked once, at that seam.
- eslint flat config + prettier (120 columns), run via `make lint` /
  `make format`.
- DOM access isolated in small view modules; data logic stays pure and
  testable (vitest + happy-dom). Views receive state and return nodes — they
  never fetch or reach into module singletons.
- No framework — if the code "starts to get messy," that is a decision point
  to revisit with the user, not a license to adopt one silently
  (`docs/TECH-SPEC.md` §15).

## Dependency injection

DI over patching: inject the dependency (archive handle, output path, fake
service) — never `monkeypatch`/`patch` global state. If something isn't
reachable through DI, refactor the code to accept a dependency. Fakes
subclass the real thing so the type checker still holds.

## Documentation

- **Delete, don't archive.** Obsolete content is a liability; remove it.
- **Single source of truth.** Each fact lives in exactly one doc; others
  link, never repeat.
- **Docs must match code.** Rename a function/module → update the docs in the
  same change; a doc whose contract lags the code gets cited by the reviewer,
  and correctly so.

## Conventions

- Tests never hit the network or wall-clock; seeded randoms only.
- Every public module gets a one-line docstring/comment stating its contract.
- `.env` values are read from the environment, never from a file at runtime.
