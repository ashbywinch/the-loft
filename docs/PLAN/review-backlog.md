# The review backlog — the local review's open findings

A whole-repo review (`skill://review-loop`) ran on 2026-11-14: eight read-only
passes, one per area (`loft/live` + schema, the pipeline's orchestration, the
reading/rows domain, `tools/`, `app/`, CI + evals, the docs, and the B4a
diff). This is the **plan** for the findings it raised that are not yet fixed.
The findings fixed in that round are recorded at the end, with their PRs, so a
later reader can tell a closed finding from an unexamined one.

A row names the defect, its trigger and where it lives. Fix related rows in
one bundle — the gate is slow, so a bundle per theme, not a PR per line.

## Open — the pipeline and the API

| Where | Defect and trigger |
|---|---|
| `pipeline/api/sync.py:291` | `ConfirmationPayload.validate` checks that `pages` is a list, never each name; a name with `/` is persisted into the registry and makes `/drafts` 400 for the whole batch. `/api/sync/approvals` (`approval.py:193`) is worse: an unknown page becomes a fabricated boundary and mints an item. |
| `pipeline/api/server.py:902` | `sync_page` calls `load_batch` with no handler — an unknown batch id is an unhandled 500 while every sibling route answers 4xx. |
| `pipeline/detect/reader.py:279` | `covered_by` tests each stroke point, not its segments: a sparsely sampled drag covers only the words under its endpoints. |
| `pipeline/rows/rows.py:402` | `_discount_annotations` only tests words within the touch radius — an asterisk in the leading keeps its reading line's row, contrary to `row-correction-rule.md`. |
| `pipeline/rows/rows.py:271` | a word with no reading line is claimed on box-touch alone (the pre-fix halo rule for that subset). |

## Open — the app

| Where | Defect and trigger |
|---|---|
| `app/views/places.js:21` | `ROUTE` hardcodes three place ids that the projection does not hold, so the route never draws (SVG and Leaflet alike). Geography is archive content; a frontend constant cannot own it. |
| `app/views/identify.js:113` | `mergeAnswer` replaces the item in `state.items` but not in `state.byId`, so the item page shows pre-identify mentions until a reload. |
| `app/data.js:138` | `documentsToReview` counts `documents_ready` only while the hub adds `documents_partial`: a half row-checked batch contributes 0 to the front door. |
| `app/views/item.js:192` | provenance source URLs go into `href` with no scheme check — an ingested `javascript:` URL runs on click. |

Dismissed: `export.py`'s manifest page field — `f"{batch}/{page}".partition("/")[2]` is the page name; the id has two segments and the reviewer misread it.

## Open — policy and test design

| Where | Defect and trigger |
|---|---|
| `pipeline/api/server.py:759` | the private layer is gated on a valid session, not on being a family member: any Google account that signs in can read `/data/*` and use the review APIs. Intent may be "household only"; nothing enforces it. |
| `tests/pipeline/test_classify.py`, `test_orient.py` | the classify/orient seam tests construct the model client and read the key from the environment, so CI must hand a secret to `make coverage` — the client should take an injected key, as every other seam takes its dependency. |

## Fixed in the review's round

| Finding | PR |
|---|---|
| the gate accepted a cancelled run's guide and the incremental skip; the check run never published (config, permissions, a required check) | #117, and the live `pr-agent-config` branch |
| the review bot judged a PR against the standards in the PR's own head; the gateway token reached checkout and tag-pinned actions; main's run was cancellable; `make lucidlint` absorbed a scanner crash | #119 |
| a drawn line could crash (`_replaced` KeyError); a correction was never read back (`read_gap`); a finished pass kept its stamp | #118 |
| `save_item` was not serialized; `atomic_write` never flushed the directory | #120 |
| a transcript segment spanning rows was duplicated onto every row; a re-read deleted the drawn correction; a right-to-left stroke was a 180° line; confirm/promote lost updates; two private atomic writers | #123 |
| a page mid re-read could be approved; the review stage's redactions were lost on close; the SANE config env var was misnamed; an unknown placeholder hue raised a bare `KeyError` | #124 |
| the review prompt read a hedge as doubt about the record (the confidence eval) | #122 |
| README's committed-archive claim and the three "CI runs exactly" lists; the PRD version | #121 |
| the live store: a status-only page save no longer erases the reading/rows; a status-only batch save no longer erases the scans; `rebuild_all` and the backup are one transaction under the lock; a locked database is `Busy`, a nested change `Conflict`; the orient call gets room to think | #126 |
