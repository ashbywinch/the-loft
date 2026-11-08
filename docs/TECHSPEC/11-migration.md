# The migration from the file archive to the database

> Component of `docs/TECHSPEC.md`. Status: **proposed; the one-time move.**
> This is a current workstream, not a history record.

The old tree is the source; the DB is the live store. The migration is a
one-shot, resumable import with a dry-run and a compare gate. The old tree is
never modified.

## Preconditions

- A verified backup of the archive (`assets/`, the identity tables,
  `imports.json`, `registry/`, `work/`) and its marker. The migration refuses
  without one.
- The service is stopped. The DB is empty, or holds the migration's own
  committed prefix from a prior run (the cursor resumes it).
- The old tree is mounted read-only; the migration only reads it.
- `loft migrate --dry-run` prints the operation list and writes nothing.

## What maps

| Old | New |
|---|---|
| `assets/<id>/item.json`, `item-N.json` | events: `created` for v1, `superseded` for vN; `entity_version`; the sidecar `supersedes`; `items`/`item_content` |
| `assets/<id>/story.txt`, `transcription.txt`, `-N` | content shas; `item_content`; the event payload's sha |
| `people.json`, `places.json`, `orgs.json`, `themes.json`, `-N` | identity events; `people`/`places`/`orgs`/`themes`/`relationships` |
| `imports.json`, `-N` | `review_sessions`/`review_messages`/`review_decisions` events |
| `registry/<batch>.json` | `batches`/`scans`; `pages`; the item id; the boundaries |
| `work/<batch>/classify.json`, `oriented/`, `ocr-guess/*` | `pages.category`, `pages.rotation`, `readings`, `page_rows`, `row_adjustments`; the work files are read once and not carried |
| item/ref/document/residence dates (`date`, `date2`, `date_precision`) | `date_json` (the `DateValue`) plus the derived columns: exact/month/year → date; approx → about; before/after → range; between → between; a residence’s from/to → period |
| person/place/org/theme/relationship/ref statuses (`confirmed`, `estimated`, `proposed`) | disposition `confirmed`/`proposed`/`rejected` + `basis_json`: old `estimated` → confirmed + recollection + possible; old `confirmed` → confirmed + knowledge + certain; old `proposed` stays |
| review decisions `estimated` | `attested` + basis recollection + confidence possible |
| `app/data/*` | discarded; the projection is derived |

## The order

1. **Snapshot** the archive and write the backup marker.
2. **Dry-run** and keep the operation list.
3. **Identity tables**: people, places, orgs, themes, relationships.
4. **Items and content**: per item, versions in order; the content shas.
5. **Imports/review sessions**: attempts, messages, decisions.
6. **Batches, scans, pages**: the registry records and the item links.
7. **Current readings, rows and words**: the latest reading only; the work
   files are read once and discarded.
8. **Documents and grouping**: the confirmed boundaries.
9. **Verify** (below).
10. **Cut over** (below).

## Idempotency

Every imported record has a stable id or UUID. A re-run skips a record already
present at the same version; a cursor records the last committed item or
batch. A failed run leaves the old tree untouched and the DB at the last
committed transaction; the next run resumes.

## Verification

- **Counts** per kind: items, sidecar versions, people, places, orgs, themes,
  relationships, import sessions, messages, decisions, batches, scans, pages,
  readings, documents.
- **Versions:** the highest sidecar version equals the item's
  `entity_version`; the `supersedes` links resolve.
- **Bytes:** every content file's sha256 is in `content`/`item_content`, and
  the bytes match.
- **Records:** the identity tables, the review messages, the registry
  boundaries.
- **Sample read:** open 10 items, 5 people and 5 documents through the live
  service and compare them to the old tree.
- **Rebuild equality:** export the DB to the human archive, compare the
  current-state tree to the old `assets/` (same records, new layout), and
  rebuild the DB from the export.
- **The old tree is byte-identical** to the pre-migration copy (it was
  read-only).
- **The dry-run's operation list equals the executed operations**, and the
  post-state counts equal its projection.

## Cutover

The service starts against the DB. The old `assets/` tree stays read-only; the
exporter writes `items/`; the old tree retires only after the export verifies
and the backup is retained.

## Failure

- **A bad record:** the migration stops, names it, leaves the DB at the last
  transaction and the old tree untouched. Fix the input or the mapping and
  re-run.
- **A verify mismatch:** the migration fails; the DB is not cut over; the old
  tree is still the live archive.
- **A power loss:** the last transaction is atomic; the cursor resumes.
