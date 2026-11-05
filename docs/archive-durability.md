# Archive durability rules

Status: **current**. The topology is `docs/TECHSPEC/00-deployments.md`; the
write transaction is `docs/TECHSPEC/05-schema.md` §18.5; the human archive is
`docs/TECHSPEC/07-exports.md` §18.8.

These are the engineering rules every writer, sync and backup holds to. They
are not a second architecture: the components are the TECHSPEC's.

## One writer

- The service is the only process that opens `loft.db`; the daemon, sync
  agent, exporter and CLI call its local API (D43).
- SQLite WAL, `BEGIN IMMEDIATE`, `busy_timeout`; one transaction per change.
- No model call, file write or network hop inside the transaction.

## Durable before ack

- A file write is temp + fsync + rename + directory fsync before the caller
  sees it.
- A DB write is a committed transaction; the response is sent after the
  commit, never after a projection rebuild.
- The export writes `INDEX.md`, `PEOPLE.md`, `PLACES.md` and the manifest
  last.

## Idempotent by UUID

- Every command, event, message, review decision and uploaded asset carries a
  UUID; a retry finds the existing record and stops.
- `command/applied` is the apply marker; the cursor alone cannot protect an
  append-only decision.

## Assets

- The bytes are files: the scan area (originals), the derivatives, R2 (view
  images). SQLite holds the catalog: sha256, mime, size and path.
- The write seam hashes before it records; `loft verify` re-hashes and
  reports; the manifest lists the hashes.
- A moved or reorganised scan is re-found by sha256/phash; the reference is
  repaired, never guessed.

## Temp files

- `<final>.tmp-<pid>-<rand>`; only the final name is a record.
- `loft clean-temps` removes stale temps; it never touches a record.

## Retries

- Backoff, then the scheduled pass; a failure is journalled and raised, not
  silently retried forever.
- The outbox is an append-only log; `applied_through` advances only after the
  apply commits.

## Offline

- With the laptop off, the remote reads the last release and queues writes.
- With the big disk off, the service still commits metadata; the content
  write retries; the user is not blocked.

## Verification

- `PRAGMA integrity_check` on the DB; sha256 on every blob; the export's
  manifest; the restore test.
- The public repo's no-PII guard scans **tracked files** for family names;
  the DB, the scan area and the read model are outside the repo, so the guard
  is not part of this layer.

## Backups

- The operational backup: the DB dump, the content store, the event log.
- The human archive: the document leg and the scan area's image leg.
- The 3-2-1 copy carries the backup and both archive legs; a restore verifies
  the manifest and the chain before it is used.

## The failure table

| Failure | Rule |
|---|---|
| Power loss during a file write | Temp + fsync + rename + directory fsync; startup re-links an orphan whose final name is absent |
| Power loss during a DB write | The transaction is atomic; the cursor and the `command/applied` marker resume it |
| A retry of a command | The UUID finds the existing row; the apply is a no-op |
| A moved scan | sha256/phash re-identifies it; the reference is repaired |
| A flipped byte | The write-seam hash and `loft verify` catch it; the blob is content-addressed and immutable |
| A partial export | The manifest is written last; a release without one is not a release |
| A partial read-model upload | No manifest; the previous release stays current |
| The big disk is off | Metadata writes commit; content writes retry; the user is not blocked |
| The service is down | The daemon's projection waits and retries; no write bypasses the seam |
| A bad release | Withdraw the change; the prior blob and the chain remain |
