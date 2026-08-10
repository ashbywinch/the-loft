# SQLite-as-projection migration plan

Status: agreed direction (2026-08-09, user), revised after review (2026-08-09,
user: the frontend cannot fetch from the big archive disk — assets need their
own projection; and the user's app-authored additions must flow back into the
archive as part of the sync). Supersedes the per-event-file design in
`docs/archive-concurrency-plan.md` (which a DBA critique rejected — its
findings are the bomb-proofing table below; the full critique was session-local
and is not in this repo).
Research: `research/archive-longevity-research.md`.

## The topology

Three homes, and the rule that keeps them straight:

| Home | What lives there | Written by |
|---|---|---|
| **The archive disk** (the big disk in the house) | the system of record: versioned sidecars, plain-text content files, asset binaries, session event logs | ONLY the sync's flush direction and the CLI tools (`loft import`). Never the app, never the frontend. Append-only law unchanged |
| **The DB** (`loft.db`, on the app server) | the projection + the app's operational store: folded domain records, review sessions, the asset catalog (metadata + sha256 + paths — never bytes), the sync watermark, and the *unflushed* markers | the app (all user-visible writes) and the sync |
| **The app's served data** (`app/data/…`) | the frontend's own copy: the JSON-shaped reads and **the asset bytes the browser actually fetches** | the sync (copied from the archive on fold, or from uploads on flush) |

The frontend fetches **only from the app's served data** — it never reaches
the archive disk, and it never touches the DB directly (everything through the
API).

## The layers

```
plain-text archive (big disk — system of record, append-only)
      ▲                              │
      │ flush (DB → archive)         │ fold (archive → DB + served assets)
      │                              ▼
      └─────── sync job ────────► SQLite DB (projection + write buffer)
                                          │
                                          ▼
                              server API + static frontend
                              (reads the DB; serves app/data assets)
```

- **The app writes only the DB.** Capture, edits, review events, uploaded
  assets — all land in the DB first: fast, transactional, concurrent, and the
  user sees them immediately.
- **The archive is written only by the sync** (plus the CLI tools, which are
  archive-side writers the fold picks up). This is the single clean rule that
  makes the write paths easy to reason about: the app never touches the big
  disk, the sync is the only bridge.

## The sync job — bidirectional

### Fold: archive → DB + served assets

- A `sync_watermark` records, per archive domain, the highest version folded.
  The fold lists the archive's new versions, folds them into the DB in ONE
  transaction, advances the watermark, and **copies new/changed asset bytes
  into the app's served assets dir**. Re-running is safe and cheap; a partial
  run is impossible (transactional).
- Catches the CLI's imports and anything added to the archive directly.

### Flush: DB → archive

- Records authored through the app carry a `flushed` marker (or the archive
  version once written). The flush writes each unflushed record into the
  archive as a NEW versioned record (sidecar + content files, append-only,
  next version), copies uploaded asset bytes to the archive disk, then marks
  the record flushed with its archive id.
- **Idempotent by stable id**: every app-authored record has a UUID; if the
  archive sidecar for that UUID already exists, the flush skips it. A crash
  between the archive write and the marker update is healed by the next
  flush — the record is never duplicated, never lost.
- **Triggers**:
  1. **Write-through** — after every app write, the seam attempts a flush
     (best-effort synchronous). When the big disk is reachable, the archive
     is never meaningfully behind.
  2. **Scheduled reconciliation** (hub-managed `loft-sync`, ~60s) — flushes
     anything the write-through couldn't (big disk was off, crash between
     archive-write and marker), folds anything new, and runs verification.
  3. **On demand** — `loft sync`; `loft sync --rebuild` (drop the DB, fold
     from the archive) for recovery.
- **The unflushed window** (an app write not yet in the archive) is the DB's
  only unique content — the write-through keeps it to seconds, the scheduled
  job bounds it, and the DB joins the nightly backup so even the window is
  covered.

## What we do about the assets — the corrected answer

**The bytes live in two places and are catalogued in a third.**

1. **Archive disk** — the record of the bytes (the big disk's copy).
2. **The app's served assets dir** (`app/data/assets/<id>/…`) — the
   projection the browser actually fetches. The sync copies bytes here from
   the archive on fold, and from uploads on flush, so the frontend only ever
   talks to the app server.
3. **The DB** — the catalog only: per-asset metadata, relative path in both
   homes, sha256, size. **Never the bytes** (180 MB war-diary scans do not go
   into SQLite — the media-server catalog pattern).

- The write seam records each asset's sha256 at capture/import time. The sync
  copies the bytes between the homes and the catalog keeps both paths.
- `loft verify` re-hashes the files in both homes and compares against the
  catalog — a flipped byte anywhere is caught (the critique's F6).
- Because the archive is the record, deleting the DB or the served copy never
  loses an asset: the sync re-copies and re-catalogues from the archive.

## Concurrency story

- **The app writes only the DB** — SQLite's problem, solved by SQLite: WAL
  mode, one writer, `busy_timeout`, transactions. The 2026-08-09 crash
  (concurrent rewrites of a shared JSON table) cannot recur: the app's writes
  are DB transactions, and the archive side is content-independent appends
  done by the single sync writer.
- **The archive has one writer kind for app content** — the sync (plus the
  CLI, which writes distinct versioned files). The atomic create-if-absent
  store primitive claims versions; collisions mean re-claim. The old
  read-modify-write of the imports table is gone.
- **Reads** are DB queries — no fold on the request path, no delta markers.
- **Crash anywhere**: archive-write → marker is healed by UUID idempotence;
  DB-write → the record is in the archive and re-folds; sync crash → the
  watermark makes the next run safe. The user's words and uploads are never
  lost and never duplicated.

## Bomb-proofing (the DBA critique's findings, all addressed)

| # | Finding | Resolution |
|---|---|---|
| F1 | Archive writes not durable across power loss | Archive writes: temp + fsync + link + **directory fsync** before acking; startup re-link of orphans whose final name is absent |
| F2 | Topology undeclared (NAS/cloud-sync hostile) | Declared: the archive lives on local disk; the app writes only the DB; CLI writers on other machines go through the API/SSH; startup probe verifies link/fsync semantics, fails loudly otherwise |
| F3 | Retries can duplicate events | Every app-authored record and review event carries a UUID; the flush skips existing UUIDs and the fold dedups — retries and re-runs are idempotent |
| F4 | Snapshot re-apply loses updates | The fold and flush are both derived from stable ids and versions; no snapshot re-apply exists |
| F5 | Two-file fixed-name projection | The DB is ONE transactional file; the served assets dir is a byte copy, rebuildable from the archive |
| F6 | Bit rot undetected | sha256 at the write seam; `loft verify` (both byte homes + `PRAGMA integrity_check`); the scheduled job runs it; the no-PII guard verifies hashes while scanning |
| F7 | Delta-fold invariant fragility | Gone: the DB is the materialized fold; transactions + UUID dedup replace the marker/contiguity invariants |
| F8 | Temp lifecycle | Strict naming (`<final>.tmp-<pid>-<rand>`); only `^\d+\.json$`-shaped names are records; an explicit `loft clean-temps` command, documented |
| F9 | Retry livelock | Flush/fold retries with backoff; the scheduled job self-heals; write-through failures degrade to the job |
| F10 | O(1) read claim dies | Reads are DB queries; a corrupt DB → `loft sync --rebuild` — never a fold on the request path |
| — | Backups | The ARCHIVE disk is the primary backup target. The DB joins the nightly backup because of the unflushed window. The served assets dir is disposable (re-copied by the sync) |
| — | Guard | The archive stays the guard-scanned layer; the DB and the served projection are derived and gitignored — no new PII surface |
| — | Big disk offline | App writes still succeed (DB); the flush retries with backoff and the scheduled job catches up; the user is never blocked by the big disk |

## The review flow, mapped

- **Write**: the review appends one event (message / decision / attempt
  boundary, UUID-carrying) to the DB in a transaction; the write-through
  flush appends it to the session's event log in the archive (atomic,
  content-independent, idempotent by UUID).
- **Read**: the API queries the DB for the session's folded state (the
  `Session`/`Attempt`/`Message`/`ReviewDecision` typed models become the DB
  read layer). No fold on the request path.
- The archive's event log is the durable, plain-text, human-readable record
  of the conversation; the DB is the operational copy.

## Schema sketch

```
people / places / themes / orgs            — folded identity tables (latest version)
items                                       — folded sidecars + content text, + flushed/archive_version
relationships                               — family edges
review_sessions                             — {id, import_id, status, current_attempt}
review_messages                             — {session_id, attempt, seq, role, text, when, thinking, uuid}
review_decisions                            — {session_id, person_id, decision, basis, when, uuid}
asset_catalog                               — {item_id, archive_path, served_path, sha256, size, mime}
sync_watermark                              — {domain, version_folded, folded_at}
```

## Migration phases

1. **Event-log conversion** — the current imports table's attempts/messages
   become per-session event logs (one-time migration; the old versioned table
   stays as append-only history). The review's write path switches to the DB
   + flush.
2. **Store durability** — temp + fsync + link + directory fsync; the startup
   probe; strict temp naming.
3. **The sync job + schema** — `loft sync` (fold + flush, watermark, UUID
   idempotence, single transaction), write-through trigger, `--rebuild`,
   idempotency and crash tests.
4. **The API reads the DB; the frontend reads the app's served data** —
   capture/review/item reads switch from the archive to the DB; the publish
   step becomes the fold (its JSON output retires in favour of the API);
   assets are copied into the served dir by the sync.
5. **Verification** — `loft verify`, the scheduled reconciliation job,
   checksums at the write seam, the guard verifying hashes.
6. **Operations** — the 2046 recovery README: back up the archive disk and
   the DB, rebuild the projection (`loft sync --rebuild`), run verify, clean
   temps, what the scheduled job does.

## What "done" looks like

- The review flow runs with no version collisions under concurrent appends
  (test: parallel app writes + a killed sync, DB stays consistent with the
  archive; the archive holds every event exactly once).
- A memory + photo captured through the app on the phone appears
  immediately, lands in the archive on the big disk within the write-through
  flush, and survives a DB deletion (rebuild from the archive).
- `loft verify` catches a bit flip in either byte home; `integrity_check`
  passes; deleting the DB and `loft sync --rebuild` reproduces it exactly.
- A non-specialist can follow the README in 2046: back up the folder(s),
  rebuild the projection, read the transcript in plain text.
