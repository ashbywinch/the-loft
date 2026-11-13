# The rewrite plan — the database as the system of record

**Status:** v0.6 — A0–A8, B1 and B2 landed; B3a is in review. Change a row's
State to its PR when it lands.
**PR:** #89 carries A0/A1 and the boot-path fixes as one review unit (the
user's call); the ladder's one-increment-per-PR rule applies to later
increments.
**Date:** 2026-11-09.
**Companion:** `docs/TECHSPEC.md` v1.0 is the target. `docs/PLAN/PLAN.md` is
the product backlog. `docs/PLAN/WORK-PLAN.md` is the active subset. This file
owns the **order**; it links to the target and never restates it.
**Length note:** the ladder runs past the 150–200 line ceiling — the increment
table is the artifact, and splitting it would scatter the order. The
per-suite detail is `test-port-ledger.md`.

## Reuse verdict

- `PLAN.md` — keep the **feature inventory, value order and slice acceptance**;
  its sequencing assumes the file store and is superseded by this file.
- `WORK-PLAN.md` §5 — keep as the **acceptance corpus** for Phase A/B: the
  dates, status, human-archive, live-store, remote and app test groups.
- `TECHSPEC/11-migration.md` — the **import mechanics** (order, idempotency,
  verification, cutover) are Phase A and the final cutover (E3).
- `TECHSPEC/10-spikes.md` — the **gates**; each milestone names the ones it
  must pass.
- `pipeline-stages-plan.md`, `INGEST-PLAN.md`, `segment-review-stories.md` —
  designs for behaviour that moves onto the DB; re-point their seams, do not
  re-design.

There is no existing rewrite plan. `PLAN.md` is a product plan, and
`WORK-PLAN.md` §5 is a list of test names.

## What counts as progress

Real progress is a capability the family can use, a named risk retired, or a
guarantee that moves from convention to enforcement. It is **not** a table
with no importer, a store no surface reads, tests against fixtures, a package
move, or a percentage measured in layers.

Scaffolding is allowed only when the next increment in the same phase uses it.
Scaffolding is never called a milestone.

**The product-works check — every increment, no exception:**

- `make test` green (lint + typecheck + pytest + vitest), including every
  ported test for the surfaces the increment touches
  (`docs/PLAN/test-port-ledger.md`).
- `make serve` on the real archive, and the walk in `docs/review-surface.md`:
  Home, Timeline, an item lens, a person page, search, the review hub, the row
  surface, the import chat.
- From B1, the archive files change only through the exporter; before that,
  only the current writers touch them, and no increment leaves them
  half-written.
- The no-PII guard passes.

One increment = one PR, one revert. If it cannot be reviewed in a day, split
it. The test port is part of the increment, never a follow-up.

## Test first, port first

Every increment starts with its tests failing: the acceptance cell is the
test list, and a green suite without those tests is not the gate.

When an increment moves a surface, it **ports that surface's existing tests
before writing any new test for it**:

1. **Port** — the old tests define the user requirement; they move to the new
   framework and run red until the new implementation exists.
2. **Add** — the target's new tests (the acceptance cell), also red.
3. **Implement** — until both are green.
4. **Extend** — only now ask whether extra tests are needed.

A test is never deleted because the mechanism it tested disappears. It is
replaced by the same scenario in the new home; `test-port-ledger.md` records
the mapping, and the old suite keeps running until E2. Coverage of a user
requirement never goes backwards.

**Authority.** The file tree is the source of truth until B7. The DB is not
eligible to be authoritative until A7 (the import verifies) and A8 (the
export and rebuild verify); it becomes authoritative at B7. Nothing deletes
the old tree: the code stops writing it at B7, and it stays the rollback until
E3.

## The ladder

### A — the DB holds the archive

No caller moves. The tree is read-only to this work; the DB is a copy. The
product works because nothing it uses changes. A0–A6 are the build-up; A7 and
A8 are the progress.

The new code lives in `loft/` from A0 because the architecture rule needs one
SQL package; **moving the existing packages waits for E1**. The move and the
storage rewrite are separate changes.

Each importer's tests land failing first; the existing archive and records
tests are the oracle and stay green throughout.

| ID | Increment | Acceptance | Gate | State |
|---|---|---|---|---|
| A0 | Move the CLI wrapper to `scripts/loft` and create the `loft/` package; the port ledger lists every current suite | every command still runs; no doc or Makefile reference to the old path; no suite is unclassified in the ledger; `make test` | — | done (2026-11-09; branch `docs/live-system-schema`) |
| A1 | `loft/live/` opens the DB; the migration runner applies `schema/truth.sql` + `projections.sql`; `loft db init`, `loft verify --schema`; the architecture test makes `sqlite3` legal only under `loft/live/` | empty → init → verify; UPDATE, DELETE and a duplicate INSERT abort; a reopened connection has the pragmas; runs on a temp `LOFT_DB_PATH` in CI | 18.12.1 | done (2026-11-09; branch `docs/live-system-schema`) |
| A2 | Events, content and one change: the frozen hash list with `prev_hash`, create-if-absent blobs, `Change`, the `person` projection, `rebuild person`, `MemoryLiveStore` | one write = one event + one row; the chain verifies; a duplicate `command/applied` aborts; a blob round-trips; drop + replay the person projection; the same suite on both stores | 18.12.3; 19.10.1–3 | done (#92) |
| A3 | Import the identity tables; the old statuses map to disposition + basis + confidence and the old dates to `DateValue` (`WORK-PLAN.md` §5) | a verified backup marker exists (`11` §Preconditions); on the real archive: counts and a field-by-field compare match; the dry-run writes nothing; a re-run is a no-op; five people read back through the new store | `11` §What maps | done (#93) |
| A4 | Import items, content, refs and assets | counts, versions, refs, bytes; ten items compared field by field; every content sha verifies; the sample export carries the same facts in the new shape | `11` §What maps | done (#94) |
| A5 | Import `imports.json` and the review sessions | counts per session; message order; decision mapping; a sample session replays; no message lost or duplicated | `11` §What maps | done (#95) |
| A6 | Import the pipeline state — registry, work files, readings, rows, documents | page and row counts; every reading sha matches its bytes; a sample page's rows equal the work file; the document boundaries equal the registry's; a re-run is a no-op | `11` §What maps | done (#96) |
| A7 | **Milestone A — the verification gate.** `loft migrate --verify` implements `11` §Verification; `loft rebuild` replays every projection; run it on the big disk | counts; versions; bytes; records; 10 items / 5 people / 5 documents; **rebuild equality**; the old tree byte-identical; the dry-run's list equals the executed operations; the run resumes after a kill | 18.12.3, 18.12.13 | done (#97) |
| A8 | **Milestone B — the exporter and the operational backup.** The human archive document leg and image leg references; the backup; `loft export`, `loft backup`; a fresh DB rebuilt from the backup | every browsable record in the export; `sha256sum -c`; the backup rebuilds an equal DB; the 2060 walkthrough; the export writes a scratch path, never the live tree | 18.12.4, 18.12.8, 18.12.19 | done (#98) |

After A8 the rewrite has real progress: the DB holds the archive, the archive
can be rebuilt from it, and a verified backup exists. The product is still on
files.

### B — the DB becomes the writer, surface by surface

The tree stays the **read** source; the DB becomes the **write** source one
surface at a time. After each flip the **compatibility exporter** rewrites
that surface's files, so the old readers see no difference. Each flip starts
with an import of that surface's records not yet in the DB, and the importer
never regresses a newer DB record; each ends with a file diff on a real sample
plus the walk. A short read-only freeze covers the flip window; the worker
pauses. The compatibility export runs synchronously with the write until B7,
because the old readers still read the old-shape tree; from B7 the target
exporter writes the new human archive and the nightly job takes over.

Each flip ports its surface's existing tests first (the ledger row), then adds
the new tests; the old and the new pass together before the flip.

| ID | Increment | Acceptance | Gate | State |
|---|---|---|---|---|
| B1 | Identities write through the service (`Change`): confirm, resolve, reject, promote, merge; the compatibility exporter writes `people.json` (its `relationships` included — the old readers' shape), `places.json`, `orgs.json`, `themes.json`. The standalone `relationships.json` is the target human archive's (A8), not the old tree's | one confirm = one change + its events + rows; the exported tables diff equal to the old format on a real sample; a re-import is a no-op; the walk | 19.10.1 | done (#100) |
| B2 | Items, content and document agreement write through the service; the exporter writes `assets/<id>/item.json`, `transcription.txt`, `story.txt` | a save, delete and agreement each write one change; the exported sidecar equals the old shape; the item lens and the review surface work | 19.10.1 | done (#107) |
| B3a | Review sessions write through the service: ensure, start a walk, messages, decisions, the completion rule; the exporter writes `imports.json` | a review turn persists; the transcript (with the thinking) and decisions read back; the imported `imports` state stays consistent; the chat surface works | `08` §19.4 | in review (#109) |
| B3b | The proposed queue writes through the service: propose, promote, reject; the exporter writes/removes `proposed/people|places/<id>.json` | an identify or story-capture proposal persists; promote/reject updates the old queue; the identify and capture surfaces work | `08` §19.4 | todo |
| B4 | Page work writes through the service: row adjustments, ticks, rotation, re-read requests; the exporter writes the work files the current readers parse | a drawn correction, a tick and a rotate each write one change; the exported work files diff equal; the row and review surfaces work | 18.12.21 | todo |
| B5 | Story and memory capture writes through the service; the exporter writes `story.txt` | `#/add-memory` assess + save persists; the exported story is the confirmed text; the walk | `docs/PRD/MEMORIES.md` | todo |
| B6a | Classify and orient write through the service; the exporter writes the work files the next stage reads | a scan runs classify + orient; the DB rows and the work files agree; the review hub sees the page | `04` §17.8.1 | todo |
| B6b | Read, rows and the reading blob write through the service | a page read lands as `readings` + `page_rows` + the blob; the draft rows equal the work file; a re-read resumes | `04` §17.8.1 | todo |
| B6c | Transcribe writes through the service | every row has text; the draft document equals the old draft; the row surface renders it | `04` §17.8.1 | todo |
| B6d | Group writes through the service (documents and page links) | the document boundaries equal the registry's; the review hub lists the documents; a re-run is a no-op | `04` §17.8.1 | todo |
| B7 | **Milestone C — read parity and the flip.** The service reads the DB behind a read flag; a parity command diffs every read route and the published JSON against the file implementation on the real archive; then flip | parity reports zero differences; the walk on the DB; the published JSON is semantically equal; rollback is the flag; `publish` reads the DB; the exporter writes the new human archive; the old-shape tree is frozen read-only as the rollback | 19.10.4–6 | todo |
| B8 | The pipeline reads its stage state from the DB; the work tree becomes export-only; `loft work` resumes from rows | a killed pass resumes from the rows; no stage reads a work file; the reconciler's completion is the row; the pipeline run is unchanged from outside | 18.12.10; spike 31 | todo |

B1 flipped the identity **tables** — the review determination, the
identification pass's proposed records and its stage-8 determinations write
through the service, and the compatibility exporter rewrites the old tables
after each write. The item half of an identification and the `proposed/`
queue files stayed on the old path; the review route catches the DB up from
the old tree before each decision, so a proposal the old path wrote is never
lost and a newer DB record is never regressed.

B2 closes the item half: the save, tombstone and document agreement are one
`Change` each, and the item compatibility exporter replays every version's
sidecar and content files into the old tree (a missing version is replayed
from the event log, so a crash leaves no gap). B3a flips the review session:
a walk, a message and a decision are one `Change` each, and the exporter
rebuilds the old `imports.json` (thinking text restored from its content sha).
The `proposed/` queue files stay on the old path until B3b, and the page/work
files until B4.

After B7 the DB is the system of record. B8 removes the last reader of the
work tree.

### C — the target's live capabilities

These add capability or move a guarantee from convention to enforcement. Each
leaves the walk green. Each increment ports the existing tests for the
capability it changes first.

| ID | Increment | Acceptance | Gate | State |
|---|---|---|---|---|
| C1 | Claims and the review queue: import today's open queues, the hub reads `claims`, reopen creates one, resolving one closes it; an unfinished memory and an integrity finding are claims | every open item in today's queues has a claim; resolving every claim closes the queue; a reopen creates a new one; the hub counts match | 18.12.22 | todo |
| C2 | `jobs` with leases and attempts; the reconciler over rows; fail-loud; a killed pass returns to pending | a job survives a restart; a lease decides a live worker; a failed pass is visible and retried | 18.12.10; 19.10.3; `03` §16.14.2 | todo |
| C3 | FTS5 search off the write lock; the published search index; parity with today's search | a query set returns the same hits; a write never waits for the index; the index rebuilds | 18.12.9, 18.12.18 | todo |
| C4 | **Milestone D — the nightly job.** Export + backup + retention tiers + `last_verified_export_at`; the banner after missed nights; the monthly restore drill | the drill restores the newest and the oldest retained dump; the banner appears; an unchanged export writes nothing | 18.12.4–5, 18.12.19; 17.12.5 | todo |
| C5 | `loft rebuild`, `loft verify`, `loft withdraw` and the schema gates | append-only proof; withdrawal drill; content-addressing; draft exclusion; projection coverage; attribution; review state; merge/unmerge; document authority; command outcome rebuild | 18.12.2, 18.12.6, 18.12.14, 18.12.16–17, 18.12.20, 18.12.23–24 | todo |
| C6 | LAN Google auth on the service; the accounts mirror; sessions, revocation, CSRF; the daemon's service token | a LAN request without a session is refused; an invited account resolves to a person; a revoked session fails at once | 17.12.9; spike 26 | todo |
| C7 | The app reads the date/status model: `date_json` and `date_text` on the timeline and filters; the `estimated` display; the GEDCOM adapter round-trips | every `DateValue` form renders and filters; GEDCOM in and out; the timeline is unchanged for exact dates | spike 33 | todo |
| C8 | The pipeline-in-DB proofs: no work files in the served path; the 50k-page size, write time and backup size; lock-hold | the 50k measurement is recorded; no work file is read on the served path; the lock is never held across a model call or a file write | spike 31; 18.12.10 | todo |

### D — the remote

Prerequisites: a Cloudflare account and domain, an R2 bucket and token, a
Google OAuth client and the AI Gateway. D cannot start without them. The LAN
product keeps working through every D increment; the remote is additive. Each
increment ports the app and API tests it touches first; the app suite is the
oracle.

| ID | Increment | Acceptance | Gate | State |
|---|---|---|---|---|
| D1 | Cloudflare D1 accounts, the Worker's Google OAuth flow, the SQLite mirror, the invite flow | an invited account signs in; an uninvited one gets `403` and a log line; the laptop links the person; the LAN uses the mirror | 17.12.9; spike 32 | todo |
| D2 | **Milestone E — the read model.** `Snapshot` from the DB; the dated R2 release (browse + open claims); manifest last; the Worker serves the app from the newest complete release | a partial upload never goes live; a rollback republishes; the app walks the release; the publish is off the request path | 17.12.1, 17.12.10; spike 27 | todo |
| D3 | The Worker read API and the app's move to it: resources, `published_at`, ETags, cursor pagination, the caller's pending overlay | the app boots from the API; a `304` works; a pending edit is visible to its author; no bulk endpoint | 17.12.1 | todo |
| D4 | View images: one per page, `media/<sha>` upload, `/img/<sha>` on one origin, the immutable cache; the legibility gate | the view image passes the row check on the phone; a second view costs no Worker request; the 10 GB budget is measured | 17.12.4; spikes 28, 29 | todo |
| D5 | The outbox and the sync agent: `Idempotency-Key`, `If-Match`, `202` + the operation; ticks and rotation first, then review decisions, story, identity and document review; parked commands | an applied-twice command is a no-op; a stale command parks; a crash leaves no partial state; the outbox replays | 17.12.2, 17.12.7; spike 30; 18.12.15 | todo |
| D6 | **Milestone F — the remote review.** Open claims, reopen, the pending state; the reviewer works while the laptop is off | a confirmation and a reopen round-trip; the release carries only the open claims; the laptop applies on return | 17.12.1; D42 | todo |
| D7 | Chat and identify on the Worker; the D1 session log; the canonical transcript mirrors to SQLite | the PRD review cases pass on both implementations; a retried message returns the existing row; the key stays in the Worker | spike 25 | todo |
| D8 | Remote re-read: the TS row-adjust module, the view image, the VLM; the result queues for the laptop | the corrected rows match `Rows.adjust`; the laptop re-validates and applies; no original is requested | 17.12.4; spike 28 | todo |
| D9 | Uploads and phone capture: R2 staging, the asset pull, re-hash, derivatives | a phone photo uploads, pulls, hashes, derives and appears; a staged object is deleted after the pull | 17.12.9; `MULTI-DOC-IMPORT-PRD.md` | todo |
| D10 | The app's offline shell, the pending/release-age UI and the remote cache | the app browses offline after one visit; the age and pending count are visible | 17.12.1 | todo |

### E — retire and re-layout

| ID | Increment | Acceptance | Gate | State |
|---|---|---|---|---|
| E1 | The rest of the `loft/` move (`records`, `document`, `pipeline`, `archive`, `app`) and the layer rules in `tests/test_architecture_layers.py` | `persistence` depends only on `domain`; `domain` depends on neither persistence nor surfaces; `sqlite3` only under `loft/live/` | 19.10.1 | todo |
| E2 | Delete the file write path, the work files and the old `publish`; update `Makefile`, `README.md`, `AGENTS.md` and the routing docs | no served path writes the tree; no doc points at a deleted command; no open `port` row for the retired home; `make test` | — | todo |
| E3 | **Milestone G — the final proofs.** Rebuild, restore, the 2060 walkthrough, the no-PII guard against both the DB and the export, the off-site copy, the 10k/50k measurements; retire the old-shape tree once they pass | every gate in `10-spikes.md` is green on the real archive; the fresh-copy walkthrough passes | all | todo |

### F — the product slices

The slice definitions and acceptance stay in `PLAN.md`; this table adds only
the sequencing.

| Slice | Lands after | Blocked by |
|---|---|---|
| 2 — phone capture & curation | D9 + D1 | uploads, remote auth |
| 3 — show mode | anywhere on the LAN; D2 for the remote | nothing in this plan — it needs only a projection |
| 4 — testimony at scale | text: B5; chat: D7; semantic search: C3 | voice is independent of this plan's storage work |
| 5 — trust & continuity | C4 + C5 | the nightly job and the withdrawal/rebuild gates |
| 6 — scale & polish | D2 + D4 + D10 + the 10k measurement | the release, the images and the cache |

## Risks and open questions

| Risk | Mitigation |
|---|---|
| The compatibility exporter must reproduce the exact file shapes the old readers parse (B1–B6) | Every flip diffs the exported file against the old file on a real sample; the app walk runs on the flipped surface; the exporter is a target component, not a throwaway |
| The import's field-by-field mapping (statuses, dates, versions) hides a loss until cutover | A3/A4 compare fields, not counts; A7 samples 10 items / 5 people / 5 documents; A8 compares the rebuilt tree |
| The worker depends on the service from B6 on | The service is supervised from A1 (`README.md` "Supervised dev server"); the daemon retries; a service-down pipeline is visible |
| The remote cannot start without accounts | D1 lists the prerequisites; no D work is scheduled before they exist |
| The 50k-page / 10k-item scale is assumed, not measured | A7/A8, C3 and D2 measure size, publish time and query time; a failed measure changes the design, not the plan |
| The flip window interrupts use | A read-only freeze and a runbook; a rehearsal on a copy; the rollback is the old service on the frozen old-shape tree |
| The DDL may not cover every table, index and trigger in `05` §18.4 | A1 reconciles them before the store is written; the migration test pins the hash chain |
| The app's read shape is an implicit contract | B7 treats the published JSON as a contract and diffs it; D3 moves the app deliberately |
| The DB's home | The internal disk (`LOFT_DB_PATH`), never the big disk; the backup covers the big-disk content separately |

## Start here

Every step begins with its failing tests.

1. **A0** — move `loft` to `scripts/loft`; create the package. Small, mechanical,
   unblocks everything.
2. **A1** — schema, store, verify, the architecture rule.
3. **A2** — events, content, one change, one projection, the contract suite.
4. **A3** — the identity import on the big disk. The first increment that
   proves the schema against real data.

Do not start B until A7 and A8 pass on the real archive. Do not start Phase D
until its prerequisites exist.
