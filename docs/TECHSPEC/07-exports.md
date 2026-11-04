<!-- Component of docs/TECHSPEC.md. See the index for the status. -->

Status: **proposed**; this is the one nightly/export/backup procedure.

### 17.9 The nightly export, dumps, and retention

The nightly job runs on the laptop at a fixed local time; if the laptop
was off, it runs once on the next start (catch-up, never a backlog of
runs).

1. **Snapshot the DB** with `VACUUM INTO` (or `sqlite3 .backup`) to a
   temp file; run `PRAGMA integrity_check`; keep it only if it passes.
2. **Write the operational backup**: the full SQL dump, the full `content/`
   store and the full event log, to the big disk and one off-site location,
   encrypted. This is the restore source and the 3-2-1 copy; it is never
   filtered. Keep the tiered set.
3. **Write the human archive**: the confirmed current state only — one
   `item.json` per catalogued item, the confirmed `.txt`, the images
   (copied, never hardlinked), the confirmed/estimated identity tables,
   `INDEX.md`, `PEOPLE.md`, `PLACES.md`, `README.md`, `manifest.json` and
   `manifest.sha256`. No drafts, no proposed records, no model reasoning.
   Write it to the big disk and to the off-site readable copy. The tree and
   its format are §18.8.
4. **Verify the human archive**: every file against the manifest; no
   `trust='draft'` content anywhere; the confirmed subset equals the DB's
   confirmed rows; fail loudly on any mismatch.
5. **Verify the backup**: restore the dump and `content/` into a scratch DB,
   compare the §18.8 backup contract, and check every hash; fail loudly.
6. **Trim**: keep a tiered set of dumps and manifests (for example 14
   nightly, 8 weekly, 12 monthly), and trim only after the newest backup
   verifies. The event log is never trimmed; the human archive is rewritten
   in place; the dumps are the tiered copies. Keep a monthly readable
   snapshot for the annual external-media export.
7. **Report**: write `sync_state.last_verified_export_at`. Both the LAN
   and the remote surfaces show the last verified export and raise a
   banner after N missed nights. A failed nightly is not allowed to fail
   silently.

**Restore drill.** Monthly, the job restores the backup into a scratch DB,
and compares every table and hash. It is a gate, not a spike: a longevity
claim that is tested once is a hope.

**Rebuild.** `ArchiveImport` reads the **operational backup** — the dump,
`content/` and the event log — and reconstructs the truth and domain
projections. The human archive is a confirmed publication, not the restore
source; it can rebuild the confirmed subset only. The test is mechanical:
backup, wipe the DB, restore, compare the §18.8 backup contract and every
hash. If that test fails, the archive is not a sufficient longevity
artifact.

**The 2046 README** ships in the archive: what the tree is, how to read
it without the software, and how to restore it.
### 18.8 The two exports: the human archive and the operational backup

Two artifacts, two jobs. The **human archive** is the complete
viewer-facing dataset — everything a casual viewer can browse, in a form a
person can read without this software. The **operational backup** is the
full database, content store and event log — what restores the system.
Neither substitutes for the other.

#### The human archive

The human archive contains **all viewer-facing data**, not a curated
subset: every item the viewer can browse (including one whose transcription
is still pending), every photo, story, confirmed transcription, person,
place, org, theme and relationship, and the generated indexes. It contains
no admin-facing state: draft text, proposed identities, review chat, claims,
readings, jobs, the event log, the schema files or accounts.

```
archive/
  README.md                 # what this is, how to read it
  INDEX.md                  # dated index, links into items/
  PEOPLE.md                 # the cast, readable
  PLACES.md                 # the places, readable
  manifest.json             # exported_through, exported_at, counts, hashes
  manifest.sha256           # literal sha256sum -c output
  people.json               # confirmed/estimated identity tables
  places.json
  orgs.json
  themes.json
  relationships.json        # the family edges the viewer's tree renders
  tombstones.json           # deleted ids + reason + date; no content
  items/
    letter-1963-05-14-01/
      item.json             # current metadata; no -2/-3 chain
      transcription.txt     # the confirmed words, plain UTF-8
      page-01.jpg           # the original scan (a copy, not a hardlink)
      page-01.preview.jpg   # the view image (readable), derived
    story-2026-08-03-05/
      item.json
      story.txt
```

- **One folder per thing, one `item.json`.** No version chains; the DB holds
  the history. A date correction does not move the folder.
- **Every browsable item is here.** An item whose transcription is still a
  draft has no `transcription.txt`; its `item.json` says
  `"transcription": "pending"`. The scan and the metadata are there; the
  words arrive when confirmed. A photo with no text is a normal item.
- **Confirmed and estimated identities, not proposed.** `people.json`,
  `places.json` and `orgs.json` carry the cast the viewer sees (estimated is
  the family's guess and is marked); proposed records wait in the DB, and a
  rejected proposal is audit-only — it never reaches the viewer. Email is an
  account field, not a viewer field: it is not in the human archive.
- **The words are `.txt`; the scans are open images.** UTF-8 and
  JPEG/PNG/TIFF; copied, never hardlinked.
- **The index is generated.** `INDEX.md` has year sections from day one;
  `PEOPLE.md`/`PLACES.md` are the cast. Sensitive items are included and
  indexed like any other; the `sensitive` flag stays in `item.json`, and the
  hosted browse applies the family's visibility rule, not the archive.
- **The manifest verifies.** Every file has a sha256; `manifest.sha256` is
  literal `sha256sum -c` output with relative paths.
- **Tombstones are recorded, not published.** A deleted item is an entry in
  `tombstones.json` (id, reason, date); its content is not in the tree.
- **The path is stable in normal use.** If `items/` outgrows a comfortable
  listing, shard by year; the id stays the citation key.

**The walkthrough.** A great-grandchild opens `README.md`, then `INDEX.md`,
finds "1963-05-14 — Letter from Nora to Owen", opens
`items/letter-1963-05-14-01/page-01.jpg` and `transcription.txt`, and reads
`item.json` for who/where/when. `PEOPLE.md` or `grep -R "Nora" .` finds a
name; `sha256sum -c manifest.sha256` verifies. No app, no database, no
network.

**The human archive is a publication, not a backup.** It is the viewer-facing
current state (confirmed text, no drafts or proposals); it cannot restore the
drafts or the full history. The backup does that.

#### The operational backup

```
backup/
  README.md                 # how to restore
  db.sql                    # the full SQL dump
  db-manifest.json          # exported_through, counts, hashes
  events/
    events-2026.jsonl       # the full event log, append-only
    events-2027.jsonl
  content/
    <sha2>/<sha>            # the full content store, including drafts
  content.json              # sha256, mime, size, created_at for every blob
  schema-truth.sql          # pragmas + events/content/migrations
  schema-projections.sql    # projections + FTS; regenerable
  migrations.json
  migrations/               # NNNN.sql
  vocabulary.json
  payload-schemas/
  assets.json
```

The backup is complete: every event, every blob (including drafts and model
reasoning), every schema and payload definition. It is the restore source,
the 3-2-1 copy and the audit trail. It is not a reading surface.

**The backup contract.** A restore rebuilds the truth and the domain:
`events`, `content`, `items`, `item_refs`, `item_assets`, `item_content`,
`people`, `person_residences`, `places`, `orgs`, `themes`, `theme_items`,
`relationships`, `documents`, `document_pages`, `batches`, `scans`,
`pages`, `page_rows`, `page_row_links`, `row_checks`, `readings`,
`review_sessions`, `claims`, `review_messages`, `review_decisions`,
`assets`, `aliases`, `withdrawals`, `commands` and `accounts` (the SQLite
mirror of the D1 logins).
`jobs` is rebuilt from `job/*` (a `running` job without a live lease becomes
`pending`); `sync_state` is reseeded from the manifest; the FTS index is
rebuilt from the typed tables and `content`. `schema_migrations` is
reconstructed from `migrations.json` and the `migrations/` SQL. The rebuild
test compares exactly that list, table by table; a table outside the list is
a bug in the contract, not a gap in the backup.

The backup manifest records `exported_through`, each entity's head hash and
every file hash. The restore seeds `sqlite_sequence` from
`exported_through`, so `seq` never reuses a value.

#### What is in neither

The derived rows/words, the job queue, the search index, the published read model
and the caches are regenerable or operational. The human archive omits them
because a reader does not need them; the backup omits them because they are
rebuilt from the log.

#### Export mechanics

**Human archive:** write changed files atomically; copy originals and
previews; write `INDEX.md`, `PEOPLE.md`, `PLACES.md` and `manifest.*` last;
never a version suffix, never a folder move. **Operational backup:** append
new events to the current year's file; copy new content blobs; dump the DB;
write the schema/payload files and the manifest last.

#### Alternatives considered

(a) Date-partitioned folders: better `ls` chronology, but a date correction
moves the folder; the generated index gives chronology without moves.
(b) Content-addressed originals in the reading tree: better dedup, worse
browsing; the manifest gives integrity without opaque paths. (c) Version
chains on the human archive: the DB holds the history; the chains would
duplicate it and confuse the reader. (d) A SQLite file as the human archive:
the archive must be readable without a DB.
### 18.9 What the disk no longer stores

| Today | Now |
|---|---|
| `item.json`, `item-2.json`, … | one `item.json`; history in the DB and the backup |
| `people.json`, `people-27.json`, … | one `people.json`; history in the DB and the backup |
| `proposed/people/*.json` | a `proposed` status in the table |
| `imports.json` with attempts/messages | `sessions/<id>.md` + the event log |
| `app/data/*` projection | the DB + the published read model |
| `work/<batch>/*` history | the DB's readings + the content store |
| `assets/<id>/` | `items/<id>/` (the one-time migration) |

The live archive's `assets/<id>/` tree is migrated once to `items/<id>/`;
the old tree stays read-only until the export verifies, then retires. This
replaces the object model's date-partitioned Phase 5 layout; that document
needs the one-line status change when this section is accepted.
