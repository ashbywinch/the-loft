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
   `item.json` per catalogued item, the confirmed `.txt`, the confirmed and
   estimated identity tables, `INDEX.md`, `PEOPLE.md`, `PLACES.md`,
   `README.md`, `manifest.json` and `manifest.sha256`. The page refs point at
   the scan area; nothing is copied. Write the document leg to the big disk
   and the off-site readable copy, and carry the image leg (the scan area) to
   the same off-site copy. No drafts, no proposed records, no model
   reasoning. The tree and its format are §18.8.
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

Two artifacts, two jobs. The **human archive** is the document leg (a dated
tree of records and text a person can read without this software) plus the
image leg (the scan area, linked by hash). The **operational backup** is the
full database, content store and event log — what restores the system.
Neither substitutes for the other.

#### The human archive

The human archive is **two legs**: the **document leg** (the dated tree of
records and text) and the **image leg** (the scan area). The document leg is
what a person reads without the software; the image leg holds the scans, and
every page reference carries the sha256 and the phash that find the scan again
if it moves. The 3-2-1 copy carries both legs; the archive is not a third copy.

The document leg contains **all viewer-facing data**, not a curated subset:
every item the viewer can browse (including one whose transcription is still
pending), every story, confirmed transcription, person, place, org, theme and
relationship, and the generated indexes. It contains no admin-facing state:
draft text, proposed identities, review chat, claims, readings, jobs, the event
log, the schema files or accounts.

```
archive/
  README.md                 # what this is, how to read it; the two legs
  INDEX.md                  # dated index, links into documents/
  PEOPLE.md                 # the cast, readable
  PLACES.md                 # the places, readable
  manifest.json             # exported_through, exported_at, counts, page paths + hashes
  manifest.sha256           # literal sha256sum -c output
  people.json               # confirmed/estimated identity tables
  places.json
  orgs.json
  themes.json
  relationships.json        # the family edges the viewer's tree renders
  tombstones.json           # deleted ids + reason + date; no content
  documents/
    All Time/
      Before 1963-01-01/
        letter-1963-05-14-01/
          item.json          # current metadata; no -2/-3 chain
          transcription.txt  # the confirmed words, plain UTF-8
      On or after 1963-01-01/
        ...
      story-2026-08-03-05/   # an undated item stays in All Time
        item.json
        story.txt
```

- **The tree is the date index.** One top folder, `All Time`. A folder splits
  when it holds more than **N = 200** documents; the split date is the median
  of that folder's own document dates, nudged to a natural label (year,
  half-year, quarter, month) only when both sides keep at least 40% of the
  content. The labels are the computed dates — `Before <date>` / `On or after
  <date>` — never a fixed year. The split is recorded once and never
  recomputed. A ranged date goes to the deepest folder whose span contains it;
  a document with no date stays in All Time.
- **A date correction moves the leaf.** The folder's path is chronology, so a
  corrected date re-files the document in the right partition; the item's `id`
  never changes, and `INDEX.md` is regenerated. The alternative — a flat tree
  with a generated index — makes a person search software to see chronology,
  so it is rejected.
- **The images are not copied.** Each page reference names the scan area's
  batch and page, with the `sha256` and `phash`; the scan stays where it is.
  A moved or reorganised scan is re-found by the hash; the page reference is
  repaired, never guessed. The `manifest.json` records each page's current
  path and hash so a reader in 2060 can verify or re-find it.
- **One folder per thing, one `item.json`.** No version chains; the DB holds
  the history.
- **Every browsable item is here.** An item whose transcription is still a
  draft has no `transcription.txt`; its `item.json` says
  `"transcription": "pending"`. The texts arrive when confirmed. A photo with
  no text is a normal item.

**The `item.json` shape.** One object per item, current metadata only; no
versions or event ids. The fields a reader or a tool needs:

```json
{
  "schema": 2,
  "id": "letter-1963-05-14-01",
  "type": "letter",
  "title": "A week in the flat",
  "date": {
    "calendar": "gregorian",
    "type": "date",
    "qualifier": null,
    "range": null,
    "from": {"year": 1963, "month": 5, "day": 14},
    "to": null,
    "phrase": null
  },
  "date_text": "14 May 1963",
  "description": "",
  "source": "Box 3 — Letters 1963",
  "provenance": "",
  "sensitive": false,
  "status": "catalogued",
  "people": [{"id": "p-mum", "name": "Nora", "status": "confirmed"}],
  "places": [{"id": "pl-aldgate", "name": "Aldgate", "status": "confirmed"}],
  "orgs": [],
  "themes": [{"id": "t-the-flat-search", "title": "The flat search", "status": "confirmed"}],
  "items": [],
  "assets": [
    {"kind": "page", "file": "page-01.jpg", "batch": "scan-20260813-1850",
     "sha256": "…", "phash": "…", "caption": ""}
  ],
  "transcription": "transcription.txt"
}
```

- `transcription` is the filename or `"pending"`; a story item uses `story`.
- `date` is the structured `DateValue` (`05` §18.4); `date_text` is its
  display for a person. There is no `date2` or precision copy in the export;
  the query columns are the DB’s projection.
- Refs carry `confirmed` or `estimated`; `proposed` is never exported.
- The `id` never changes; the folder path can move with a date correction.
- `schema` is the export shape's version (`1`).
- The text is never embedded; it is the `.txt` file.
- The page refs carry the sha256 and phash; the JSON is UTF-8 with sorted keys
  and a trailing newline, so `manifest.json` can hash it deterministically.
- **Confirmed and estimated identities, not proposed.** `people.json`,
  `places.json` and `orgs.json` carry the cast the viewer sees (estimated is
  the family's guess and is marked); proposed records wait in the DB, and a
  rejected proposal is audit-only — it never reaches the viewer. Email is an
  account field, not a viewer field: it is not in the human archive.
- **The words are `.txt`; the scans are open images in the scan area.**
  UTF-8 and JPEG/PNG/TIFF. The document leg references a page by batch,
  filename, sha256 and phash; it never copies the image.
- **The index is generated.** `INDEX.md` has year sections from day one;
  `PEOPLE.md`/`PLACES.md` are the cast. Sensitive items are included and
  indexed like any other; the `sensitive` flag stays in `item.json`, and the
  hosted browse applies the family's visibility rule, not the archive.
- **The manifest verifies.** Every file has a sha256; `manifest.sha256` is
  literal `sha256sum -c` output with relative paths.
- **Tombstones are recorded, not published.** A deleted item is an entry in
  `tombstones.json` (id, reason, date); its content is not in the tree.
- **The tree shards itself.** The date partitions split at N = 200; the id
  stays the citation key, and a date correction re-files the leaf.

**The walkthrough.** A great-grandchild opens `README.md`, then `INDEX.md`,
finds "1963-05-14 — Letter from Nora to Owen", opens
`documents/All Time/Before 1963-01-01/letter-1963-05-14-01/transcription.txt`,
and reads `item.json` for who/where/when. The page ref names
`scan-20260813-1850/page-01.jpg` in the scan area; its sha256 verifies it.
`PEOPLE.md` or `grep -R "Nora" .` finds a name; `sha256sum -c
manifest.sha256` verifies the document leg. No app, no database, no network.

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
`pages`, `page_rows`, `page_row_links`, `row_checks`, `row_adjustments`, `readings`,
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

The job queue, the search index, the published read model, the derivatives and
the caches are regenerable or operational. The human archive omits the raw
reading blob and the rows because a reader gets the confirmed text; the backup
keeps them (`content`, `page_rows`). There are no work files to omit.

#### Export mechanics

**Human archive:** write changed files atomically; re-file a document leaf
when a date correction crosses a partition; write `INDEX.md`, `PEOPLE.md`,
`PLACES.md` and `manifest.*` last; never a version suffix; never copy the
images — the manifest records their paths and hashes. **Operational backup:**
append new events to the current year's file; copy new content blobs; dump the
DB; write the schema/payload files and the manifest last. The 3-2-1 copy
carries the scan area (the image leg) beside the document leg.

#### Alternatives considered

(a) Flat `items/<id>/` plus a generated index: rejected — a person browsing
the disk cannot see the chronology, and the index is software.
(b) Date-partitioned folders: **chosen**; a corrected date re-files the leaf,
which is the price of `ls` chronology.
(c) Content-addressed originals in the reading tree: rejected — opaque paths;
the scan area keeps readable names, and the sha/phash finds a moved file.
(d) Version chains on the human archive: rejected — the DB holds the history;
the chains would duplicate it and confuse the reader.
(e) A SQLite file as the human archive: rejected — the archive must be
readable without a DB.
### 18.9 What the disk no longer stores

| Today | Now |
|---|---|
| `item.json`, `item-2.json`, … | one `item.json`; history in the DB and the backup |
| `people.json`, `people-27.json`, … | one `people.json`; history in the DB and the backup |
| `proposed/people/*.json` | a `proposed` status in the table |
| `imports.json` with attempts/messages | `sessions/<id>.md` + the event log |
| `app/data/*` projection | the DB + the published read model |
| `work/<batch>/*` history | the DB's readings + the content store |
| `assets/<id>/` | the DB, then the export's `documents/<date>/<id>/`; the one-time import is [11-migration.md](11-migration.md) |

The live archive's `assets/<id>/` tree is migrated once into the DB; the
export writes the dated `documents/` tree; the old tree stays read-only until
the export verifies, then retires. The date tree is the archive's document
leg, not a Phase 5 experiment: `docs/object-model.md`'s storage section is the
model's summary, and this section is normative.
