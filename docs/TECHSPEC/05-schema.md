<!-- Component of docs/TECHSPEC.md. See the index for the status. -->

§18.8–§18.9 are in `07-exports.md`; §18.10 is in `06-schema-ddl.md`; §18.11 is in `09-decisions.md`; §18.12 is in `10-spikes.md`.

The DDL is `06-schema-ddl.md`; the exports are `07-exports.md`. This component describes; it does not define the tables.

## 18. The live schema and the archive's on-disk form

Status: **proposed schema, revised after an adversarial review; for review.**
§17 decides where the system lives; this section decides what it stores and
what a reader finds on the disk.

### 18.1 Three append-only stores, and everything else

The truth is three append-only stores:

1. **`events`** — every state change, immutable. `UPDATE` and `DELETE` are
   refused by triggers; a `BEFORE INSERT` trigger refuses a duplicate
   `event_id` or `(entity_id, event_no)`; `PRAGMA recursive_triggers=ON`
   closes the `INSERT OR REPLACE` hole that would otherwise delete a row
   without firing the delete trigger. The pragma is declared in
   `schema-truth.sql`, so a restore connection gets it too.
2. **`content`** — every text or JSON blob, keyed by sha256,
   create-if-absent. A bad release can add bytes; it cannot replace the
   bytes under an existing sha.
3. **`schema_migrations`** — the applied migration list, append-only.

Everything else is a projection or operational state:

- **Projections** (droppable, rebuildable from `events` + `content`):
  `items`, `people`, `places`, `orgs`, `themes`, `relationships`,
  `documents`, `document_pages`, `batches`, `scans`, `pages`, `page_rows`,
  `page_row_links`, `row_checks`, `readings`, `review_sessions`, `claims`,
  `review_messages`, `review_decisions`, `assets`, `item_refs`,
  `item_assets`, `item_content`, `person_residences`, `theme_items`,
  `aliases`, `withdrawals`, `commands`, `search_docs` and the FTS index.
  **The current state is typed**; there is no generic entity table.
- **Operational** (not truth; rebuilt or reseeded on restore): `jobs`,
  `sync_state`.
- **Auth state** (not truth; backed up, never in the human archive):
  `accounts`.

A projection may be updated or deleted freely. An operational table may be
reset. The truth may only be appended to.

This is the sidecar chain moved one layer down: the per-entity version
becomes `event_no`, and current state is derived. The difference is that one
place enforces it, and one query answers "what did the bad release write?"

### 18.2 The event log

The DDL is in `06-schema-ddl.md`.

- **`event_no` is the ordinal; `entity_version` is the state token.** Every
  event on an entity gets the next `event_no`; only the state-changing event
  types advance `entity_version`. Log-like kinds (`command`, `job`,
  `review_message`, `review_decision`, `asset`) leave `entity_version` NULL.
  This is the correction the first draft missed: one column cannot be both
  the unique ordinal and the optimistic token, or a machine derivative
  stales a human edit.
- **`change_id` groups the rows of one action.** Confirming a document
  writes a `document` event, an `item` event and one event per page; they
  share a `change_id`, so the debugger sees one action, not five.
- **`payload` is metadata and content references for state records.** An
  item event carries `text_sha`; a page-reading event carries `reading_sha`.
  A log-like event (a review message, a decision) carries its short text
  inline, in the immutable event; its optional `thinking_sha` points at
  `content`. The bytes live in `content` (§18.3). This keeps the log small
  and makes a text correction a new immutable blob, not an overwritten
  file.
- **`app_version` is the build id**, not a semver. A dev build that never
  bumps it makes the release query lie.
- **`actor` is the person, not the login.** `actor_kind = 'person'` carries a
  person id — the genealogy record; `actor_kind = 'system'` carries a
  reserved id (`pipeline`, `sync`, `import`). An account is an optional login
  attached to a person (`accounts.person_id`); the event log never stores the
  email. A contributor who is not yet in the cast gets a proposed person
  record, per the memory flow.
- **Ordering is `seq`.** `recorded_at` is for humans; a clock jump must never
  reorder the log.

**The hash recipe.** `hash = sha256(canonical(event))` over a **frozen
column list** — `event_id`, `change_id`, `entity_kind`, `entity_id`,
`event_no`, `entity_version`, `event_type`, `payload`, `payload_schema`,
`recorded_at`, `actor_kind`, `actor_id`, `command_id`, `app_version`,
`prev_hash` — never `SELECT *`. Adding a column in a migration therefore leaves historical
hashes valid; a test applies every migration and re-verifies the chain.
Sorted keys, UTF-8, no insignificant whitespace. The hash covers the **stored**
`payload` string, not a re-serialisation: the seam canonicalises before
insert, and a test pins it, so a restore that writes JSON differently does
not turn the chain red. `prev_hash` is the previous event for the same
`(entity_kind, entity_id)`. The recipe is pinned by a
test. It detects accident, partial tampering and a truncated tail (the
manifest pins each entity's head); it does **not** stop someone who can
recompute the chain. Say so in the README rather than overclaiming.

**The vocabulary is closed.** The write seam validates the pair:

| `entity_kind` | `event_type` | advances `entity_version` |
|---|---|---|
| `person`, `place`, `org`, `theme`, `relationship` | `created`, `superseded`, `deleted`, `merged`, `unmerged`, `rejected` | yes |
| `item`, `document`, `page`, `batch` | `created`, `superseded`, `deleted`, `status_changed` | yes |
| `scan` | `created` | no |
| `review_session` | `created`, `status_changed` | yes |
| `page_reading` | `reading_recorded` | yes |
| `review_message` | `message_appended` | no |
| `review_decision` | `decision_recorded` | no |
| `asset` | `asset_added`, `derivative_added` | no |
| `command` | `received`, `applied`, `rejected` | no |
| `job` | `enqueued`, `started`, `finished`, `failed` | no |
| `withdrawal` | `withdrawn` | no |

**Merges carry a redirect; rejection ends the proposal.** A `merged` payload
names `merged_into`; the `aliases` projection resolves the loser to the
survivor. An `unmerged` event removes the redirect; the alias projection is a
fold of merge/unmerge, so withdrawing a merge restores the original id. A
`rejected` event is terminal for a proposed person/place/org: the row stays
in the log and the projection, excluded from browse and from reference
resolution; a ref to it is a `loft verify` finding.

**The review speaks four outcomes; the store has three statuses and a
terminal exclusion.** The vocabulary maps one way, and nowhere else:

| Review outcome | Record / link status | Event |
|---|---|---|
| `attested` | `confirmed` | `created` (a new record) or `superseded` (an existing one) |
| `estimated` | `estimated` | `created` / `superseded` |
| `pending` (undecided, left for later) | `proposed` | `created` / `superseded` |
| `delete` | the item's link is removed; a `proposed` record no other item references is excluded | the item is `superseded`; the record is `rejected` |

`proposed` is the machine's guess awaiting review (`pending` is the review's
word for it); `confirmed` is an attested fact; `estimated` is the reviewer's
own recollection, recorded with its basis; `rejected` is terminal and the row
stays. A `delete` on a `confirmed` record never downgrades it: the item's
mention goes, the record stays a fact. There is no parallel status vocabulary
in the UI, the commands or the export — a reader that needs the review's word
maps it through this table.

**Commands are events.** A remote command becomes `command/received`; the
apply writes the domain events plus `command/applied`; a stale or invalid
command writes `command/rejected`. The `command/applied` event is the
idempotency marker — the cursor alone cannot protect an append-only
decision, because decisions deliberately have no version predicate. A
replay finds the marker and stops.

**Why one log, not typed version tables.** The literal translation of the
sidecar chain is `item_versions`, `person_versions`, … — one append-only
table and one current view per entity. It is more relational, but it
multiplies the places a bad release can write and the places a debugger must
look. The single log gives one guard and one history; the **current state is
typed** (§18.4), so the read model is relational without making every type a
second append-only table. The log is generic because it is a sequence of
facts; the state is typed because it is the domain.

### 18.3 The content store

The DDL is in `06-schema-ddl.md`.

- **Text, readings and review reasoning are content-addressed.** The item's
  `transcription`/`story`, the page's reading JSON and a message's
  `thinking` are blobs keyed by sha. The event references the sha; the human
  archive writes the confirmed `.txt` from it. A correction creates a new
  sha; the old blob stays. A bad release cannot overwrite the words.
- **The pipeline's reading is a blob, not a file.** A page's full reading
  (its lines with text, every word with its box, baseline and waistline) is
  one JSON blob referenced by `readings.reading_sha`; `page_rows` is the
  queryable projection. The reviewer's drawn lines are a second blob,
  referenced by `row_adjustments.sha256`. The pipeline's state is these rows
  and blobs; there is no `work/` tree.
- **Create-if-absent and verified.** The seam computes the sha from the
  bytes before insert; an existing sha is re-hashed and compared, never
  overwritten. A crash leaves an orphan blob; `loft verify` **reports** it
  and never deletes one (the delete trigger forbids it). The only safe GC
  is a rebuild into a fresh DB.
- **Path-backed blobs are re-hashed.** A large blob at
  `content/<sha2>/<sha>` is verified against its filename on every
  `loft verify`; a rewrite is caught.
- **A blob has no owner; its first event does.** The event that first
  references a sha carries the actor and `app_version`; `loft verify` can
  find the first reference by scanning the log, which is how a bad
  release's blobs are traced.
- **Images are not in SQLite.** The `assets` catalog holds the sha, mime,
  size and a path relative to the content store; the bytes are files. The
  human archive copies the confirmed item's images into its folder.
- **The snapshot's content bundle is part of the atomic publish.** The
  published manifest lists every content sha the snapshot references and is
  written last; a release without a manifest is not a release. Uploads are
  content-addressed with `If-None-Match: *`, so a retry is free and a partial
  upload never goes live.
- **The operational backup ships the blob metadata.** `content/` holds the
  bytes and `content.json` holds `sha256`, `mime`, `size` and `created_at`,
  so the table can be rebuilt byte-identically. A dump-only restore includes
  `content/`, or the dump is taken with all content inline.

### 18.4 The projections

**The map, not the definition.** The DDL is `06-schema-ddl.md`; this section
says what each table is for.

Projections are derived; operational tables are reset, not rebuilt. Their
`CREATE` statements live in `schema-projections.sql`; projection contents
are rebuilt by `loft rebuild`.

**The current state is typed.** Each entity kind has its own table. Scalar
fields are columns; small nested structures (aliases, `dob`/`dod`, a
residence list, a theme body) are JSON columns on that table; the edges the
browse queries join on are child tables. There is no generic entity table.

| Table | Holds |
|---|---|
| `items` | id, type, title, date, date2, date_precision, status, source, description, provenance, sensitive, created, identified, `date_mentions_json`, `extra_json`, plus the shared columns |
| `item_refs` | item → person/place/org/theme/item, with status, date, date2, precision and basis |
| `item_assets` | item → asset, kind, caption, ordinal |
| `item_content` | item → content sha, kind (`story`/`transcription`/`other`), trust (`draft`/`confirmed`) |
| `people` | id, name, years, relation, bio, email, pronouns, hue, status, `dob_json`, `dod_json`, `aliases_json`, `occupations_json`, `basis_json`, plus the shared columns |
| `person_residences` | person → place, from/to, precision, status, basis |
| `places` | id, name, note, precision, lat, lng, x, y, address, status, `aliases_json`, `basis_json`, plus the shared columns |
| `orgs` | id, name, address, branch, note, status, `aliases_json`, plus the shared columns |
| `themes` | id, title, subtitle, seeded, `body_json`, plus the shared columns |
| `theme_items` | theme → item, ordinal |
| `relationships` | id, a_kind/a_id, b_kind/b_id, kind, label_a, label_b, `date_json`, `basis_json`, status, plus the shared columns |
| `documents` | id, item_id, batch_id, doc_index, title, date, date_precision, status, greeting, signoff, text_sha, confirmed_at, plus the shared columns |
| `document_pages` | document → page, ordinal |
| `batches` | id, label, source, path, status, arrived_at, started_at, started_pid, started_host, `fingerprint_json`, content_changed, plus the shared columns |
| `scans` | scan id, batch, page, sha256, path, ordinal, created |
| `pages` | page id, image asset, sha, revision, rotation (applied, relative to the original), category, status; the document edge is in `document_pages` |
| `page_rows` | the current rows with `source`, `trust`, orientation and `revision` |
| `page_row_links` | insertion links: target row, character offset, proposed/unset/confirmed |
| `row_checks` | the reviewer's per-row verification ticks |
| `row_adjustments` | page → the drawn-lines blob sha; the current correction |
| `readings` | the row set (the code's old name): page → row-set sha, the correction sha it was built from, row count, word count |
| `review_sessions` | session id, kind, subject (batch/document/item/person/place), actor, status, current attempt, closed_at |
| `claims` | the review queue: origin, subject, phase, state, evidence |
| `review_messages` | the review chat, one row per message, with its human actor |
| `review_decisions` | the reviewer's determinations: subject, decision, basis, actor |
| `assets` | the catalog: sha, kind, mime, size, relative path, derivative-of |
| `aliases` | merged ids → survivor ids |
| `withdrawals` | bad changes and their compensation change |
| `commands` | remote commands: `received`→pending, `applied`→applied, `rejected`→parked or rejected |
| `search_docs` + `search` | FTS5 over titles, names, transcripts and stories |
| `sync_state` | cursor progress and `last_verified_export_at`; operational |
| `jobs` | the worker queue, leases and attempts; rebuilt from `job/*` |

**Auth state is not a projection.** `accounts(account_id, email, subject,
person_id, role, status)` is the login authority in D1; SQLite mirrors the
linked accounts for LAN auth, attribution and backup. `events.actor_id` is the
**person id**, not the account id; the log never stores an email. A person may
have no account — most of the cast never will — and a contributor who is not
yet in the cast gets a proposed person record. The owner invites an email; the
first sign-in binds the Google subject; the laptop links the person (creating
a proposed one if new). The chat session is live in D1; the canonical
transcript is SQLite `review_messages`, one row per session and ordinal; the
D1 message carries a unique request key for the retry. Accounts are
never written to the human archive.

The shared columns on a state table are `version`, `event_no`, `event_seq`
and `updated_at`; `version` is the optimistic token a command carries. The
log-like tables (`review_messages`, `review_decisions`, `assets`,
`commands`, `withdrawals`) have no `version`; they are append-only
projections keyed by their own id or ordinal.

**The review queue is a view over `claims`.** A claim is one thing a
reviewer must resolve — an identity, a document, a memory, a failed
integrity check. `review_sessions` is the conversation, `claims` is the
queue, `review_decisions` is the outcome. The queue closes only when no
claim is open for the origin. An unfinished memory is a claim with
`origin_kind='memory'`; a failed integrity check is a claim with
`origin_kind='integrity'`, so the weekly check produces work rather than a
log line.

**Constraints live on the typed tables.** `CHECK`s are reserved for
vocabularies that will not grow without a migration — `page_rows.source`,
`item_content.kind`, `item_refs.ref_kind`, `withdrawals.target_kind`,
`commands.outcome`, `jobs.status`. The record statuses, item types and
relationship kinds are validated by the seam against the domain class,
because extending them must not require rebuilding an immutable table.
Natural indexes go on `items(date)`, `items(type, date)`, `people(name)`,
`item_refs(ref_kind, ref_id)` and `document_pages(page_id)`. The seam
validates the payload before the projection writes, so the table and the
class cannot drift. A new `entity_kind` needs a table, a migration and a
projector; a test fails if the kind has no table.

**Rows are typed where the constraint matters.** `page_rows` exists because
§17 promises that a machine re-read cannot silently replace a human row set.
It carries `source` (`machine` | `human`), `trust` (`raw` | `guess` |
`confirmed`), the page `revision` and the segment `orientation`; the seam
refuses a re-read whose input is older than the human rows. `row_checks`
holds each reviewer's tick, and `page_row_links` the insertion target,
character offset and state. The payload is still the reading; the projection
is the constraint surface.

**Rows are the grain; the document text is a cache.** The confirmed
`page_rows` are the letter's words; `documents.text_sha` is a cache of them,
and the item's `item_content(kind='transcription', trust='confirmed')` is the
published text. A confirmed document must have an item (`CHECK (status <>
'confirmed' OR item_id IS NOT NULL)`); the export writes `transcription.txt`
from the item content and compares it to the document cache; a mismatch
fails. There is no third authoritative copy.

**FTS is deferred.** The FTS index is not updated inside the pipeline's
write transaction; a projector applies `events` since `projected_through` to
`search_docs`/`search`. The index is a cache; the search lag is seconds, and
the write lock is not held for a full-text update.

**Reads are current for the domain.** The typed tables are updated in the
same transaction as the event, so a review read after a write sees it. The
rebuild path exists for recovery, not for the happy path.

**The rebuild is the test.** `loft rebuild` drops every projection, replays
`events` in `seq` order (skipping nothing; there is no quarantine filter),
rebuilds `search`, and compares every table in the `07-exports.md` backup
contract list. The
gate is mechanical: drop, replay, compare, fail on any difference. A kind
with no projection table is a failure, not a silently skipped event.

### 18.5 The write path

**Only the service opens the database.** The daemon, the sync agent, the
exporter and the CLI call the service's local API; no other process holds a
SQLite handle. The one transaction below runs inside the service, so the
"single writer" is a process boundary as well as a seam.

**Normative: the one write-path transaction.** The remote command flow that
reaches it is `04-live-system.md` §17.5.

One transaction per **change**, not per event. A batch import of 2,000
pages is one transaction with 2,000 events; an interactive edit is one
transaction with one or two.

```
-- before BEGIN: write any new content blobs (create-if-absent)
BEGIN IMMEDIATE;
  compute event_no = max(event_no) + 1 for each entity;
  insert the events, hash-chained per entity;
  upsert the typed projection row for the entity kind, with the guard:
    INSERT ... VALUES ...
    ON CONFLICT (<table primary key>) DO UPDATE ...
    WHERE <table>.version IS :base_version;
  -- a create command carries base_version NULL; the seam validates it.
  -- log-like kinds (command, job, review_message, review_decision, asset)
  -- have no version predicate; they are upserted by their own key.
  replace item_refs / item_assets / document_pages / person_residences
    / theme_items for the entity;
  upsert pages / page_rows / readings / review_* / assets / aliases;
  insert command/applied when the change came from a remote command;
COMMIT;
-- after commit, the FTS projector catches up from projected_through
```

The projector is a dispatch table: `entity_kind` → the class that owns the
mapping (`Item.write_projection`, `Person.write_projection`, …). The class
already owns `to_dict`/`from_dict`; it also owns the row mapping, so the
typed table and the wire shape stay in one place.

- **Idempotent.** `event_id` is unique, and `events_one_apply` is a unique
  index on `command_id` where `event_type = 'applied'`; a second apply
  aborts inside the transaction. A decision is protected by the same index,
  not by a pre-read.
- **Version-checked atomically.** The guard is the typed table's
  conditional UPSERT, `WHERE <table>.version IS :base_version`
  (`pages.revision` for a page and everything under it: its rows, its drawn
  lines, its ticks); a zero-row result is a stale command, and the seam writes
  `command/rejected`. A
  create command must carry `base_version = NULL`, and the seam validates
  that before the UPSERT; a non-existent entity with a non-null base is a
  protocol error, not a create. `IS`, not `=`, because a nullable version
  must compare NULL-safely. No Python read-then-write.
- **No slow work inside the lock.** A model call, a file write or a network
  hop is a job; the transaction records the intent and the result. Content
  blobs are written before the transaction, so a crash leaves an orphan,
  never a half-referenced event.
- **One host.** The worker and the sync agent call the same seam; they do
  not open the database themselves.
- **Pragmas:** `journal_mode=WAL`, `synchronous=FULL`, `busy_timeout=5000`,
  `recursive_triggers=ON`, `wal_autocheckpoint=1000`. No foreign keys: the
  write seam is the integrity check, and a generic ref cannot carry an FK
  safely. Say that rather than leaving a `foreign_keys=ON` that does
  nothing.

### 18.6 Migrations

- **Additive only.** `CREATE TABLE`, `CREATE INDEX`, `CREATE VIEW`,
  `ALTER TABLE … ADD COLUMN`. A test reads the migration files and refuses
  `DROP`, `RENAME`, and any column type change.
- **A migration never writes projection rows.** It creates schema; the
  rebuild is the backfill. A migration that inserts, updates or deletes a
  projection makes the live table unreproducible from the log and fails the
  rebuild gate.
- **New columns are nullable.** Under `STRICT` a `NOT NULL` column needs a
  default, and a default fabricates a value for every historical row of an
  immutable log. Only the five strict types (`INTEGER`, `REAL`, `TEXT`,
  `BLOB`, `ANY`) are allowed. A column is never removed.
- **Two schema files.** `schema-truth.sql` starts with the pragmas
  (`journal_mode=WAL`, `synchronous=FULL`, `busy_timeout=5000`,
  `wal_autocheckpoint=1000`, `recursive_triggers=ON`), creates `events`,
  `content` and `schema_migrations`, and has no virtual tables, so a 2046
  reader on a SQLite without FTS5 can still rebuild the truth.
  `schema-projections.sql` adds the projections and the FTS index; it is
  regenerable.
- **The migration SQL is exported.** `migrations/NNNN.sql` ships beside
  `migrations.json`, so `schema_migrations.sql_sha256` is verifiable and a
  future reader can see exactly what changed. A test applies every migration
  and re-verifies the event hash chain: the frozen hash column list is what
  makes that pass.
- **Payload schemas are exported.** `payload-schemas/<kind>.v<n>.json` and
  `vocabulary.json` ship in the archive, so `payload_schema` is a lookup, not
  a bare number. `schema_migrations` is append-only
  (`version`, `applied_at`, `app_version`, `sql_sha256`, `note`), and
  `PRAGMA user_version` mirrors the head.
- **A destructive change is a new table plus a rebuild**, never an in-place
  alteration. The old table stays until the new one is proven.

### 18.7 A bad release: withdrawal, not quarantine

The first draft's `quarantines` table was wrong: filtering events makes the
projection a function of mutable operator state, breaks drop-and-replay,
and leaves the exported history permanently wrong with no marker. The
repair is an **event**.

`loft withdraw --change <change_id>` (or `--release <build>`) runs one
transaction that:

1. finds every entity the bad change touched and its **current** last event;
2. classifies each entity:
   - **created by the bad change** → append a `deleted` tombstone (there is
     no prior payload to restore); if other changes reference it, list each
     dependent ref in `needs_attention`;
   - **a merge** → append `unmerged`; the alias projection drops the
     redirect, so old refs resolve to the original id;
   - **changed, with no later edits** → append `superseded` carrying the
     payload from before the bad change;
   - **changed, with later edits** → three-way merge (before, bad, current).
     If a later edit touched a field the withdrawal would overwrite, list
     the entity in `needs_attention` and refuse without `--force`; with
     `--force`, restore the prior payload and record the overwritten fields;
3. appends one `withdrawal` event with `target_kind`
   (`change` | `release` | `event`), `target_ref`, the affected change set,
   the compensation change, the reason, and the `needs_attention` list.

The fold stays pure: the compensation is later than the bad event, so the
entity's last event is the restored one. The withdrawal is an audit marker
that the export carries, so the history is self-describing. The bad events
remain visible; nothing is edited.

| Symptom | Containment | Recovery |
|---|---|---|
| Bad projection | Stop the writer; rebuild | `loft rebuild`; compare; resume |
| Bad events (valid but wrong) | Stop the writer; `loft withdraw --change <id>` | Compensation events + a withdrawal marker; rebuild |
| A release wrote thousands of events | `loft withdraw --release <build>` | One compensation change with many events, not a seq range; later edits are merged or listed |
| Unparseable event | The projector aborts; the rebuild cannot proceed | Withdraw the change; the compensation restores the entity; nothing was skipped |
| Bad delete | Withdraw it | A `superseded` event with the prior payload |
| Bad merge | Withdraw the merge | An `unmerged` event removes the alias; refs resolve to the original id |
| Withdrawn create with dependents | Withdraw the create | Dependent refs are listed in `needs_attention`; nothing is silently retargeted |
| Bad migration | Additive-only means the old columns/tables still exist; roll the code back | The new columns stay unused; no data restore |
| Corrupt DB | Restore the nightly dump | Replay the event log exported since the dump; verify the chain |
| Bad reading blob | Content is sha-keyed and immutable; the prior blob remains | A new `reading_recorded` pointing at the prior sha |

- **`exported_through` is monotonic.** The exporter refuses to run when the
  DB's `max(seq)` is below the manifest's `exported_through`; a restore must
  re-import the backup's `events/` before the next backup. The human
  archive never regresses.
- **No global rollback.** There is no `trusted_through` cutoff; a withdrawal
  is per-change, so the worker's good page reads and other people's edits
  are untouched.
- **The release is in every row.** `app_version` makes "what did the bad
  release write?" one query.

### 18.13 The remote store (D1)

The Worker's store is D1 (SQLite); it holds only what the remote needs while
the laptop is off. The live archive is the SQLite DB at home: D1 is a working
store, not a second archive.

The DDL is [`schema/d1.sql`](../../schema/d1.sql).

**The account is the allowlist.** An invite is a row with `status='invited'`
and no `subject`; the owner creates it from the laptop through
`POST /internal/accounts`. The first Google sign-in binds `subject`, sets
`active`, and the laptop links `person_id` (or creates a proposed person and
writes it back). An email with no row, or a `disabled` one, gets `403` and a
log line.

**The session is revocable.** The cookie carries only the `session_id`;
`auth_sessions` is the authority, so a sign-out or a disable revokes at once.
The cookie is `HttpOnly`, `Secure`, `SameSite=Lax`, short-lived.

**The outbox is the command log.** `seq` is the laptop's cursor
(`applied_through`); `command_id` is the operation id; the unique
`(actor_account_id, idempotency_key)` index makes a retry return the first
row. `outcome` is `pending` until the laptop applies it, then `applied` or
`parked`; `rejected` is terminal.

**The transcript is the live session.** `review_sessions` and `messages` are
the D1 copy the app reads while the laptop is off; the laptop writes one
`review_messages` row per session and ordinal, and the SQLite copy is
canonical. The D1 message's unique `(actor_account_id, request_key)` makes a
retried message return the existing row.

**No foreign keys, like the live schema.** D1 is not the archive; the laptop
validates every reference on apply.
