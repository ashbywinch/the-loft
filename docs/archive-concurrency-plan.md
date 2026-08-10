# Archive concurrency architecture — plan and context for review

Status: design under critique. Nothing here is implemented yet.
Date: 2026-08-09. Author: the session. Reviewer wanted: a DBA-grade critique
of the concurrency and performance properties, with alternatives.

---

## 1. The failure that started this

The import-review chat (a family reviewing machine-proposed family-tree links)
records every message and decision. That transcript lives in one JSON identity
table (`imports.json`), rewritten read-modify-write on every review action.
In the live walk, two concurrent writes computed the same next-version number;
the append-only store refused the second (`ImmutableStoreError: refusing to
edit existing file: imports-27.json`), and the whole review died with
"Sorry — the assistant couldn't be reached. Try again?" — the user's typed
answer was lost and the walk restarted.

Digging exposed three layers of the problem:

1. **The CAS primitive isn't atomic.** The disk store's `write_new` is
   check-then-write (`if exists: refuse; write_bytes`). Two processes can both
   pass the check and both write — the last writer silently wins, no error.
   The refusal that caught the race was luck, not a guarantee.
2. **The CAS response is handled wrong.** The first patch retried on collision
   by re-writing the *stale snapshot* at the next version — a silent **lost
   update**: the concurrent writer's change vanished from the visible state.
3. **The contention domain is too wide.** The whole transcript for every
   session lives in one mutable aggregate, rewritten on every message.

The archive's append-only immutability is a deliberate, load-bearing design
(see Constraints). The failure is in how the write path uses it, not in the
concept.

## 2. Constraints — the non-negotiables that shape any solution

1. **The plain-text append-only archive is the product's soul.** Records are
   JSON sidecars plus plain-text content files in a directory tree. The
   archive is diffable, greppable, human-readable, GEDCOM-adjacent, and
   *scanned by the no-PII guard* (every tracked file is checked for real
   names before CI goes green). Any storage that the guard cannot scan is a
   violation unless the guard is deliberately rethought.
2. **Append-only is domain law.** Records are versioned (`item-1.json`,
   `item-2.json`, …); a change is the next version, never an edit; superseded
   versions stay forever; deletion is a tombstone. This is the audit-history
   contract, not an accident.
3. **Decades of operation with minimal skilled human intervention.** This is a
   family archive, hosted on a home LAN, maintained by non-specialists. No
   DBA on call. No clusters, no replication, no orphaned services that need
   babysitting. A storage format that rots, or a corruption that needs a
   specialist to repair, is a failure of the design. Whatever we choose must
   be recoverable by an ordinary person following a README, decades from now.
4. **The concurrency setup must be extremely easy to reason about.** The same
   way a real database "prevents foot guns" (transactions, single-writer,
   atomic visibility), our setup must have a property a non-expert can state
   and check. If a future maintainer has to think hard about whether a race is
   possible, the design has failed.
5. **Real content never lives in code.** The archive is data; the code is
   tooling. (This is why the PII guard exists at all.)
6. **Minimal dependencies.** The app has no runtime JS dependencies; the
   server tooling is Python stdlib + FastAPI/uvicorn. A heavy third-party
   storage dependency is a real cost — but *acceptable* if it buys the
   properties above (see §5).
7. **Two kinds of writers.** A single long-running server process (uvicorn,
   the review/capture API) and CLI batch tools (`loft publish`, imports) that
   write the archive directly. Any concurrency story must cover both — a
   process-local lock does not.
8. **Fail-fast, no silent loss.** Errors surface to the user; nothing is
   silently dropped; the transcript is the user's own words, recorded verbatim
   or not at all.

## 3. Current architecture (what exists today)

- **Store** (`tools/store.py`): `write_new(path, content)` — create-only, no
  edits, one delete operation. DiskStore + in-memory store for tests. The
  atomicity gap from §1.1.
- **Archive** (`tools/archive.py`): `save_item` (versioned sidecars + content
  files `story.txt` / `transcription.txt`), `save_identity` (tables: people,
  places, themes, orgs, imports). Version = last listed + 1.
- **Review flow**: the imports table holds `{imports: [{id, title, status,
  attempts: [{started, messages: [{role, text, when, thinking?}], decisions:
  [{person_id, decision, when, basis?, last}]}]}]}`. Every message/decision/
  attempt transition rewrites the whole table. The session's typed model
  (`Session`, `Attempt`, `Message`, `ReviewDecision` in `tools/records.py`)
  is built by reading that table.
- **Projections**: `loft publish` already materializes the raw archive into
  the app's `data/` (index, people, transcripts…) as a batch build. The
  pattern of "raw archive → readable projection" exists and is understood.
- **The AI review**: the model's investigation returns verdicts; the server
  renders the assistant's words; the transcript records exactly what the
  family saw, verbatim, plus the model's raw reasoning as the "thinking".

## 4. The proposed architecture

Three layers, one atomic primitive under all of them.

### 4.1 The store: an atomic create-if-absent-and-publish primitive

`write_new` becomes: write the content to a temp file in the same directory
(`<final>.tmp-<pid>-<rand>`), `fsync`, then `os.link(temp, final)`. POSIX
`link()` is create-if-absent (fails EEXIST if the target exists) and publishes
the complete inode atomically — readers see either absence or the complete
file, never a partial one. The CAS and the content publication collapse into
one syscall. Orphaned temps (crash) are swept by the next write in the
directory. MemoryStore (tests) implements the same contract as an
insert-if-absent dict op (atomic under the GIL).

Store guarantee: *a write publishes the complete file under the final name or
not at all, and only one writer can publish a given name.*

### 4.2 The log: per-session append-only event log (system of record)

```
imports/<id>.json              — the import record {id, title, status} (changes rarely)
imports/<id>/events/<n>.json   — one event per file:
    {"type":"message","role":"user","text":…,"when":…}
    {"type":"message","role":"assistant","text":…,"thinking":…,"when":…}
    {"type":"decision","person_id":…,"decision":"attested","basis":{…},"when":…}
    {"type":"attempt_started",…} / {"type":"attempt_completed",…}
```

Each event is one small versioned file claimed by the store's atomic
create-if-absent. **Appends are content-independent**: the event's bytes don't
depend on any prior state, so a collision simply means "re-list and claim the
next number" — there is no stale content to lose. This is event sourcing:
state is a fold over the log; the log is only ever appended and never read on
the request path.

### 4.3 The projection: per-session read model + human view

```
imports/<id>/session.json      — the folded Session state, carrying the version
                                 it folds through ({version: 87, …state})
imports/<id>/transcript.txt    — the conversation in plain prose, for the family
```

- The projection is written by the same seam, content-dependent → on collision
  it re-reads the current log, re-folds, re-claims (the lost-update rule:
  never reuse a stale snapshot).
- **Correctness never depends on the projection.** A reader sees
  `session.json` at version 87 and events through 90 → folds only 88–90 (the
  delta). Missing or stale projection → fold from the log. The projection is a
  durable, rebuildable cache; `fold(session.id)` regenerates it at any time
  (the `loft publish` pattern, per-session and incremental).
- **The projection write can never lose user data**: it is not a user-data
  write. The user's words are already in the log; the projection is a
  materialization. If it fails entirely, the next read folds.
- `transcript.txt` mirrors the archive's existing machine-sidecar +
  human-content split (`split_content` → `item-N.json` + `transcription.txt`).

### 4.4 The seam: write-shape rules

| Write shape | On collision (EEXIST) | Retries exhausted → |
|---|---|---|
| Log append (content-independent) | re-list, claim N+1, same bytes | **loud failure** — the API errors, the app surfaces it, the user's words remain in their input; nothing half-recorded |
| Projection / identity transition (content-dependent) | re-read CURRENT state, re-apply intent, claim N+1 | **invisible** — the log is the truth; the reader folds; the projection is eventually consistent by construction |
| Crash mid-write | — | orphaned temp; final name never appeared; rebuild the projection if stale |

Invariant: *the log is the only write whose failure can affect the user, and
it is the one write that is content-independent — so a collision can only mean
"re-claim the next version." Everything else is a materialization of the log
and rebuildable. Files appear atomically complete or not at all.*

### 4.5 Performance property

Per operation, regardless of history length: read = one file + the delta since
its version marker; write = one event append + one projection write. The log
grows unboundedly but never appears on the request path. Session boundaries
isolate contention: different sessions never contend; within a session,
concurrent appends order deterministically by file version (which is the
interaction order).

## 5. What is explicitly on the table

The critique should treat nothing as sacred except §2. In particular:

- **A third-party cache/index layer is completely acceptable** if it buys
  longevity or simplicity — but it must not create a second system of record
  that can drift, and it must survive a non-specialist decades from now.
- **A database is acceptable** — SQLite first (a single file, no server) —
  *with regular plain-text exports* so the archive's soul and the PII guard's
  scannability survive. The question is whether the plain-text design can meet
  §2 without it.
- **File-count scale**: per-event files mean one file per message. At family
  scale (tens of messages per session) this is trivial; the critique should
  say where it stops being trivial and whether a single JSONL log with
  kernel-atomic `O_APPEND` appends is better (at the cost of changing the
  store's create-only contract).
- **fsync cost** on every write; **directory listing cost** for version
  computation; **temp-file sweep** policy.
- **Projection staleness**: is the version-marker + delta-fold rule simple
  enough to be obviously correct to a future maintainer?

## 6. Prior art consulted

- Event sourcing (Fowler, "Event Sourcing"; Azure Architecture Center —
  snapshots as an optimization, never a correctness dependency; optimistic
  concurrency: rehydrate from the stream, retry after reloading state).
- Apache Iceberg reliability — concurrent writers produce metadata and
  atomically swap; on conflict, retry by building a new metadata tree from the
  *updated* state (never the stale read).
- Compare-and-swap / optimistic locking practice — the CAS gate is the
  essential anti-lost-update mechanism; retry loops must re-read before
  recomputing; conflicts surfaced, not swallowed (abstractalgorithms.dev; a
  dev.to case study of AI agents losing updates: "an append-only log does not
  prevent lost updates; the CAS gate is the essential mechanism").
- Fowler, "Singular Update Queue" — the single-writer alternative, rejected
  because it is process-local and does not cover the CLI writers.

## 7. What the DBA critique must judge

1. Is the concurrency claim (§4.4 invariant) actually sound — any interleaving
   of the two writer kinds that breaks it? Any TOCTOU or half-visible-state
   window left?
2. Performance at the realistic ceiling (decades, thousands of sessions, long
   transcripts): where does the design stop being cheap, and what breaks first?
3. The §2 operational bar: can a non-specialist recover this in 2046? Is the
   "easy to reason about" claim honest, or does the delta-fold/projection
   subtlety already exceed it?
4. Alternatives with tradeoffs: SQLite (+ exports), a cache/index layer, JSONL
   logs, or anything else — judged against §2, not just throughput.
5. A clear recommendation: adopt as-is / adopt with changes / move to a
   database-backed design, with the specific reasons.

## 8. Deliverable

A critique report: findings (each with severity: blocker/major/minor),
alternatives (each with tradeoffs against §2), and a recommendation. The
session reports the critique verbatim; nothing is implemented until the user
decides.
