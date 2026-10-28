# The archive arrangement — where each artefact lives

Status: **proposal** (WORK-PLAN §1.7, DR2). It settles the legs; the move
of the live archive is Phase 5 of `docs/object-model.md`.

## The rule

The archive holds **what the family agreed**. Everything the machine made on
the way lives in the workspace (`Loft/work`, `Loft/registry`), which the
product never shows and which is regenerable from the archive.

- An **agreed** artefact is in the archive: the identity tables, and per item
  its sidecar, its content, and — for a scanned document — the agreed
  transcript.
- A **machine-made** artefact is outside it: the stage artefacts, the draft
  Documents, the readings, the row checks.
- A **proposed** record is the one unagreed thing the archive holds, and only
  inside the table it will join: `status: pending`, beside the agreed records,
  never in a queue of its own.

DR2 applied: the root a reader opens is the final artefacts — the identities
and the items — in that order; the intermediates are one leg down or outside.

## The tree

```
archive/
  README.md
  people.json  people-2.json …            identities, agreed; pending records marked inside
  places.json  themes.json  orgs.json     the same discipline, versioned the same way
  sessions/imports.json (+ versions)      the identity-extraction sessions — intermediate
  documents/<date label>/<item id>/       one item
      item.json (+ -N versions)           the sidecar; append-only
      <content files>                     the scans, the photograph
      transcript.txt                      the agreed Document (a transcribed item)
```

- **The identity tables stay at the root.** They are the final artefacts a
  person reads first, and they already version append-only (`people-2.json`
  supersedes `people.json`).
- **`imports` moves under `sessions/`.** A session is process state — the
  conversation that produced proposals — not an agreed fact, and it is the
  table that grows without bound. It keeps its versioning and its record
  class; only its leg changes.
- **`documents/` is the item leg**, replacing `assets/`: the date-partitioned
  tree `docs/object-model.md` already settles (N = 200, median split) — the
  partition is unchanged, the leg's name becomes what it holds.
- **An item's folder holds its text.** A scanned document's `transcript.txt`
  is the agreed Document; a story's text is its content file. Either way the
  sidecar declares it, so a reader needs `item.json` and nothing else to know
  what the item is.

## What feeds what

| Step | Artefact | Home |
|---|---|---|
| scan arrives | registry record: label, pages, hashes, status | `Loft/registry/` (workspace) |
| orient, marks, words, draft rows | `oriented/`, `<page>.words.json`, `<page>.rows.json` | `Loft/work/<batch>/` |
| the row check | `<page>.row-adjustments.json`, `<page>.rows-adjusted.json` | `Loft/work/<batch>/` |
| the reading | the page's rows and text (the draft Document) | `Loft/work/<batch>/` |
| **agree the transcript** | `transcript.txt` in the item's folder; the registry's boundary status | **archive** + registry |
| proposed entities | the identity tables' `pending` records | archive |
| **agree the entities** | the same records, attested | archive |
| the projection | `app/data` | `Loft/projection/` (derived, never in the archive) |

The item's id is minted at agreement (the document's date, per the object
model's slug rule); the registry keeps the page set, so the transcript's
provenance survives without the archive holding pipeline state.

## What this changes in the code

1. `record_confirmation` (`pipeline/api/sync.py`) writes the agreed text into
   `work/<batch>/ocr-confirmed/` today. It must write the item's folder
   instead, through the archive's write seam (`Archive`), minting the item at
   agreement.
2. `Archive.save_identity` keeps its shape; each table's leg becomes a
   parameter of the table's home rather than a bare root name.
3. `publish` reads the same records and gains the transcript's path per item.

## The decisions this proposal leaves open

| # | Question | Recommendation |
|---|---|---|
| 1 | Does a session belong in the archive at all, or only in the workspace? | **In the archive, under `sessions/`** — the proposals a session carries must survive a workspace loss; the leg keeps it out of the reader's way |
| 2 | Is the agreed transcript a content file of its item, or its own leg keyed by the batch? | **The item's content file** — the item is what the family agreed on; a batch is how it arrived |
