# Decisions

> Component of `docs/TECHSPEC.md`. Status: **register**. The decisions
> (D1–D49) are adopted.

## The register

Each live decision carries a tag:

- `[shape]` — depends on the deployment table in `00-deployments.md`.
- `[domain]` — survives a change of deployment.
- `[schema]` — depends on the database/typed-table choice.
- `[interface]` — depends on the code layout.

A change of shape revisits `[shape]`; a change of database revisits
`[schema]`; a change of code layout revisits `[interface]`. The `[domain]`
decisions survive all three. The blast radius is at the bottom.

### 17.13 Decisions

- **D1 [shape, schema] — The database is the system of record.** The plain-text archive
  is the nightly, lossless, human-readable export.
- **D2 [shape] — One host writes.** The laptop's Loft service is the only writer
  of domain state, and every write goes through its seam inside a
  `BEGIN IMMEDIATE` transaction. The worker and the sync agent are
  clients, not second writers; the Cloudflare backend never writes domain state.
- **D3 [shape] — Remote writes are commands.** Immutable, UUID-keyed,
  `entity_version`-checked, applied idempotently by the laptop.
- **D4 [shape] — The Cloudflare backend is replaceable for reads.** The published
  read model plus the caller's pending commands. It is the only copy of
  commands not yet pulled, so the outbox table is durable, replicated and
  never trimmed.
- **D5 [shape] — Originals stay home; the words and view images do not.**
  Scan pixels and full-resolution images stay on the big disk. Transcripts,
  stories, memories and review chat live in the Cloudflare backend behind
  family auth. The remote site serves **one view image per page**, readable
  and row-checkable; the same image is the reader's and the reviewer's.
  There is no separate review tier and no thumbnail-only policy. The
  resolution is signed off before the remote review surface ships.
- **D6 [shape] — Nightly, tiered, verified.** Nightly dumps and archive export;
  retention by tier; the export must be able to rebuild the DB.
- **D7 [schema] — SQLite at home.** No server database on the laptop;
  `synchronous=FULL` because the corpus is irreplaceable.
- **D8 [domain] — The archive stays append-only and scannable.** The DB and the
  snapshot are derived, gitignored, and never in the no-PII guard's
  layer.
- **D9 [domain] — No transaction spans slow work.** A model call, a file write or
  a network hop never holds the write lock; state-plus-work commands
  enqueue a job and commit their result separately.
- **D10 [domain] — One entity version, one export cursor.** `entity_version` for
  commands; `exported_through` for the export.
- **D11 [shape] — The outbox is permanent.** Progress is the laptop's
  `applied_through` cursor; the `command/applied` event is the idempotency
  marker. The cursor alone cannot protect an append-only decision.
- **D12 [domain] — A failed nightly is visible.** `last_verified_export_at` is
  shown on both surfaces, with a banner after N missed nights.
- **D13 [shape] — The backup contract is explicit and drilled.** Truth and domain
  projections rebuild from the operational backup; operational tables are
  reseeded; a monthly restore-and-compare is a gate.
### 18.11 Decisions

- **D14 [schema] — The truth is three append-only stores.** `events`, `content`,
  `schema_migrations`; everything else is a projection or operational.
- **D15 [domain] — Events are immutable.** A correction is a new event; a delete is a
  tombstone event; a repair is a compensation plus a withdrawal event.
- **D16 [schema] — The rebuild is a tested gate.** Drop, replay, compare; a
  projection that cannot be rebuilt is a bug.
- **D17 [shape] — Commands are events.** `received`/`applied`/`rejected`; the
  `applied` event is the idempotency marker.
- **D18 [schema] — Migrations are additive, nullable, and non-destructive.**
  Destructive changes are new tables plus rebuilds.
- **D19 [domain] — Item/document/page text is content-addressed.** A correction is a
  new sha; the old bytes stay. Short log lines may be inline in the
  immutable event.
- **D20 [shape] — The human archive is the viewer-facing current state.** Every
  browsable item, identity, theme and relationship; no version chains, no
  drafts, no proposed records. The operational backup carries the full event
  log and content store.
- **D21 [domain] — Stable flat item folders and generated indexes.** The path is the
  id; `INDEX.md`/`PEOPLE.md`/`PLACES.md` provide the browse.
- **D22 [shape] — The backup contract is explicit.** Truth + domain projections
  rebuild from the operational backup; operational tables are reseeded; the
  monotonic guard stops a backwards backup.
- **D23 [domain] — The human archive is the complete viewer-facing dataset.** Every
  browsable item, identity, theme and relationship; confirmed text but no
  drafts, proposals or model reasoning; sensitive items included and indexed;
  accounts and emails excluded. The hosted browse applies the family's
  visibility rule, not the archive. The Cloudflare backend holds the
  working state behind family auth.
- **D24 [domain] — A bad release is contained by withdrawal and compensation, not by
  a restore.** The nightly backup is the fallback.
- **D25 [domain] — Originals and previews are copied, never hardlinked.**
- **D26 [domain] — The human archive is readable without SQLite.** The backup carries
  `schema/truth.sql`, the event log and `content/` for the restore; FTS is
  optional.
- **D27 [schema] — The current state is typed.** Every `entity_kind` has its own
  projection table; scalar fields are columns, small nested records are
  JSON columns on that table, and query-critical edges are child tables.
  There is no generic entity table.
- **D28 [domain] — The review queue is claims.** A session has a subject and an
  actor; a decision names its subject; the queue closes only when no claim
  is open for the origin. Unfinished memories and failed integrity checks
  are claims.
- **D29 [domain] — The actor is a person.** `events.actor_id` is a person id, or a
  reserved system id for machine work. An account is an optional login
  attached to a person; the event log never stores an email.
- **D30 [domain] — Rows are the grain.** The confirmed `page_rows` are the letter's
  words; document text is a cache; a confirmed document must have an item,
  and the export compares the cache to the published text.
### 19.9 Decisions

- **D31 [interface] — One SQL package.** `loft/live/` is the only code
  that imports `sqlite3`; the service uses `LiveStore`; every other process
  uses the service's local API. `08` §19.2.
- **D32 [interface] — One write path.** `Change` is the unit of work; saves
  derive events; no caller builds an event payload. `08` §19.4.
- **D33 [interface] — Product-shaped reads.** Queries return paginated view
  records, not rows or `dict`s. `08` §19.5.
- **D34 [interface] — Domain errors at the boundary.** No `sqlite3` exception
  escapes. `08` §19.3.
- **D35 [interface] — A memory store proves the interface.** The same contract
  suite runs against SQLite and memory. `08` §19.7.
- **D36 [interface] — Export and sync use the service's local API.** They
  never open the database or write SQL. `08` §19.2.
- **D37 [shape] — Logins are Google on both surfaces; D1 is the authority.**
  The model, allowlist and sessions are `00` §Authentication; the routes are
  `04` §17.5.1. SQLite mirrors the accounts; the home service is LAN-only.
- **D38 [domain] — The canonical chat transcript is SQLite.** D1 holds the
  live session. `05` §18.13.
- **D39 [shape] — The read model is a dated R2 release with a final manifest.**
  The contract (manifest last, newest folder current, old deleted, global
  `media/<sha>`, republish as rollback) is `00` §The read model.
- **D40 [shape] — The Worker runs chat, identify and remote re-read.** The
  initial row generation and transcription stay on the laptop; identify reads
  the transcript. `04` §17.6.1.
- **D41 [shape] — The remote is one origin; the Worker serves the images.**
  The shape and the cache rule are `00` §The read model.
- **D42 [domain] — The release's review half is the open claims only.** A
  confirmed document is in browse; a reopen command creates a claim. `00`
  §The read model, "What a release carries".
- **D43 [shape] — The service is the only process with the database.** The
  daemon, sync agent, exporter and CLI call its local API. `00` §The local web
  service and the local daemon are separate processes.
- **D44 [domain] — The live store is the pipeline's state.** There are no work
  files; a stage is done when its row is. `03` §16.14.2; `05` §18.3.
- **D45 [interface] — The remote API is resource-oriented.** Resource writes,
  cursor-paginated reads, `Idempotency-Key`, `If-Match`, and a `202` plus an
  operation resource; the command envelope is internal to the outbox. `04`
  §17.5.1–17.6.2.
- **D46 [domain] — The page's artifact is the row set.** The code's
  `RowsReading`, `readings` and `reading_for_page` are old names; the target
  names are the row set (rows + words), with `page_rows` as its query view.
- **D47 [domain] — Dates are structured; GEDCOM is an adapter.** Every dated
  row stores the `DateValue` (`date_json`): calendar, type
  (date/period/range), qualifier (about/estimated/calculated), range
  (before/after/between), from/to and phrase. The query columns `date`,
  `date2` and `date_precision` are derived; `date_text` is the display.
  `tools/gedcom_date.py` is the output/import adapter, never the source.
- **D48 [domain] — A record stores a disposition, a basis and a confidence.**
  Status `proposed | confirmed | rejected`; basis `document | knowledge |
  recollection | inference`; confidence `certain | probable | possible`
  (basis and confidence in `basis_json`). The review’s `estimated` is a
  display — a `confirmed` record with a recollection/inference basis below
  certain — not a status.
- **D49 [interface] — The boot graph is bundled; the source stays vanilla.** `make app-build` (esbuild, dev-only) emits `app/dist/boot.js` and lazy view chunks; `app/` remains the source of truth. The former no-build rule was about no framework/runtime build; a boot bundle removes the 12 module round trips, not the source.


## Blast radius

| Change | Revisit |
|---|---|
| The remote becomes a server | `[shape]`: D1–D6, D11, D13, D17, D20, D22; `04-live-system.md` §17.5–17.6, §17.11 |
| The Cloudflare backend/services are replaced | `[shape]`: D4, D5, D11, D13; the static app's API calls; the outbox and read-model adapters |
| The laptop becomes a home server | `[shape]`: D2, D6, D12; `00-deployments.md` |
| SQLite becomes Postgres | `[schema]`: D1, D7, D14, D16, D18, D27; `05-schema.md`, `06-schema-ddl.md` |
| The code layout moves to `loft/` | `[interface]`: D31–D36; `08-code-organisation.md` |
