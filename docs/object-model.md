# The Object Model — the techspec

The object model: what each class is, what it is named, and which file it
lives in. This is the techspec the code is held to — a class in a file
named after the class; methods that operate on a class's objects are
members of that class, its collection classes owning their factories
(`Words.from_marks`, `Rows.from_words`); a module named after anything
that is not a domain concept does not survive — the word/row types are
`Word`, `Page`, `Row`, `Verdict`, `Rectangle`, whatever module they
currently sit in (today `tools/boxrows.py`, a code name, not a
concept).

Status: **complete — the full object model, approved provisionally**.
Implementation follows the spec; the module-mapping table below is the
record of every old module's home.

## The rule that started this

`latent-class` findings: "introduce a record named with a domain noun, with
named fields". A name made by nouning a verb is not a domain noun. Generic
suffixes (`Options`, `Context`, `Style`) are allowed only when the suffix is
the honest noun for the object.

## Settled — item 1: GEDCOM read/import
- **`GedcomDocument` holds the records.** It becomes a real document object:
  parses text into itself, and the read produces wire shapes from its own
  state. The separate im/export working class is gone (was `GedcomImporter`,
  whose state was the document's records — see below).
- **The island is the folder.** `loft gedcom import <file> <folder>`
  writes the derived record files **into** the named folder — the
  folder is the import's storage: its own self-contained copy of the
  archive's record structure, unrelated to the existing archive
  (another import of the same file = another identical structure
  elsewhere). The folder itself is not a model *concept* — no `Folder`
  record, no registry entry; the record files inside it are the
  records. The import **refuses a target folder that exists and is
  non-empty**; two imports of the same file = two identical structures
  in two places.
- **Export reads the folder.** `loft gedcom export <import-folder>
  <path>` reads the folder's record files, re-emits the confirmed
  subset's GEDCOM, and writes it to `<path>`. Swapped parameters
  cannot make a mess — the command refuses before writing when: the
  first argument is not an import folder (a bare file path, or a
  folder without the imported structure); the destination is the
  import folder or any path inside it (the source island stays
  untouched); the destination is an existing directory; or the
  destination is an existing file (no silent overwrite).
- **One status schema.** Records carry the entity review vocabulary —
  **attested / estimated / pending / delete** — nothing parallel:
  "proposed" is the old word for **pending**, "confirmed" is everything
  else. GEDCOM carries it in the custom tag
  `1 _LOFT_STATUS pending` (user tags start `_`); the import reads it;
  unmarked records are everything-else.
- **Export stays confirmed-only.** `to_text` emits nothing unconfirmed
  (unchanged contract: nothing pending). Round trip is therefore exact
  on the confirmed subset; pending records are not expected to match
  across an export.
- **The record set is closed by round-trip fidelity.** The import writes a
  record for every construct the file carries that export must re-emit:
  people, families, relationships, places, residences; events, dates,
  name parts, notes as their record data. The mapping is pinned by the
  `maximal70.ged` round-trip — a construct the fixture exercises and the
  export re-emits must have its record; nothing is dropped as a
  parse-time convenience (the old importer's error the fixture flags).
- **No destination coupling — the import is an island.** The imported
  records are completely unrelated to the existing archive: no
  resolution, no dedup, no linking against what is already there. There
  is no review process for GEDCOM import — **all entries are created at
  import, places included** (the file's places become `Place` entities).
  A theoretical future merge is not a consideration now. Residences are
  their own record on the person — the place name as given, the
  residence dates, any note (whatever the file spells); no link ties a
  residence to a place at import: the name is the only shared text. The
  invented unknown-place `ValueError` is gone.

- **Fixture:** `tests/fixtures/maximal70.ged` — vendored from
  `python-gedcom7`'s `test/data/maximal70.ged` (MIT, © 2022 David Straub;
  attribution in the fixture header). It is a maximal-feature GEDCOM 7 file
  ("intended to provide coverage of parts of the specification"), which is
  the point: the sample must cover the format's feature surface, not just
  the subset the importer currently uses. The `gedcom7code/test-files` suite
  (51 files) is the reference corpus for feature isolates.
- **Tests** (all against the fixture): import → export → import identical on
  the confirmed subset (both directions); double import into the same folder
  refused / fresh folder identical; status faithfulness (marked →
  proposed, unmarked → not).

## The document chain

The document side is a chain of collections, each owning the factory that
makes it from the previous:

- **`Ink`** — the page's ink, made from the page image: `Ink.from_image(image)`,
  where `image` is the **decoded page image** (pixels). The document
  model never opens files or touches paths — the Archive (or pipeline)
  hands it the decoded image at the boundary;
- **`Marks`** — the connected ink components: `Marks.from_ink(ink)`;
- **`Ruler`** — the page's measurement, made from its marks:
  `Ruler.from_marks(marks)` (the writing scale: unit, pitch, the line
  ratio; `pagescale.py` retires into it). The Page owns the `Ruler`;
  the chain passes its scale along: `Words.from_marks(marks, ruler.scale)`;
- **`Words`** — the words: `Words.from_marks(marks, scale)` — `scale` is
  the ruler's writing scale, from the page's `Ruler`;
- **`Rows`** — the rows: `Rows.from_words(words, page)` (the pipeline's
  grouping; the reviewer's drawn lines correct them — `rows.adjust(lines)`,
  the adjudicated path);
- **`Document`** — owns its pages; a **confirmed archive record**. The
  grouping scorer (`grouping.py`: a page opens a document at a greeting,
  closes it at a sign-off) proposes the pages; the review confirms the
  grouping; confirmation creates the record. Pages arrive ordered and
  not interleaved.
- **Page references are stable and verified**: a document references its
  pages by each image's **sidecar id** (allocated once at registration,
  never reassigned, kept in the image's sidecar) with the image's sha
  as the content check. Loading a document verifies the image's current
  sha against the recorded one — a moved, renamed, or replaced file
  fails loudly at load, never silently detaches a document from its
  pages.

**`Page`** is the container: it owns the whole chain — its `Ruler` (the
page's measurement: x-height, spacing, line ratio; `pagescale.py` retires
into it), its `Ink`, its `Marks`, its `Words`, its `Rows` — and,
through them, its **`Transcript`** (the page's text): each **row carries
its own text and its trust stage** (R7: the raw reading, the corrected
guess, the user's confirmed text), stored per row, no separate page-level
copy. The Transcription review surface promotes a row guess → confirmed;
nothing unconfirmed is the document's words. The page renders itself
(`Rows.render`; `Document.render_review` renders the document's review
view). The renders **return the image** — PNG bytes / an in-memory
image; the model never writes files, the app or pipeline writes the
image where the front end needs it. The review's case-sheet draws stay
where they are for the moment (parked).

**The transcription and its report.** `Vlm(VlmOptions)` performs the
page's vision readings — text, orientation, the row-kind metadata —
with the self-report: token usage plus the
guessed-word flags (the model's own "I am guessing at this word" notes)
— the review surface can mark guessy words without trusting machine
confidence beyond a flag. The per-page **`.vlm.json` sidecar** is the
read record and the cache: input-sha skip (a page whose image is
unchanged is never re-read), token usage per page, alongside the page
itself. `VlmOptions` is the constructor config: model,
base URL, prompt, timeouts, cache toggles.

**The model call is a conversation.** When the model returns bad output,
the caller sends back its own message, the model's message, and a
coherent error, and the model fixes the problem — the same architecture
as an LLM chat (as when a user tells the model it did something wrong).
Failures are corrected in-conversation, never by re-prompting from
scratch and never accepted silently.

**The rows persist — the two boxes.** The pipeline and the web app
run on **different machines**: the persisted rows *are* the handoff.
The page's rows — boxes, per-row text + trust stage, kinds — are stored
with the page in the date-partitioned tree at read time; nothing
re-runs on the app's box, the review reads the stored rows, and
confirmed rows are the document's words. The web app's box reads the
files directly (the archive location both boxes reach); there is no
in-memory or service handoff between the two.

**`Rectangle`** is the geometry record of the model. **`Verdict`** is the
drawn-line correction's measurement: when a reviewer draws a line over
the page, the grouping measures how the stroke agrees with it —
`right`/`split`/`unboxed`, the row indices the stroke covers, the words
it passed over — before `rows.adjust(lines)` re-derives the rows from
the drawn lines. Rows carry no verdicts.

## The packages and their layout

The house Python layout is a flat package at the repo root. The Loft's:

- `loft/archive/` — `Archive`, the `Entity` families and tables, the
  review machinery (`tools/review.py` + its records `Message`,
  `Attempt`, `ReviewDecision`, `ReviewContext`, `ReviewQueue`) — **one
  review, two sources**: the memory review and the document review are
  the same conversation (`ReviewChat`) with the same per-entity outcome
  vocabulary (**attested / estimated / pending / delete**). The only
  difference between the two is depth: the memory's reviewer can dig
  deeper (the user was present and can answer more questions than
  someone reviewing a found document); whether they are literally one
  conversation is to be settled by trying the single conversation
  first. Also here: the memory side
  (`Memory`, the assessment machinery), `GedcomDocument`
  (the GEDCOM interchange class), the publish derivation, and the
  storage (`store`, `atomic`, `loft_paths`);
- `loft/document/` — `Document`, `Page`, `Word`, `Row`, `Verdict`,
  `Rectangle`, `Ink`, `Marks`, `Ruler`, `Rows`, the page's `Transcript`,
  the renders — and the **transcription** of a page: it belongs here.
  The `Vlm` client (with `VlmOptions`) is the vision reading tool of
  the document model (text, orientation, the row-kind metadata, the
  self-report);
- `loft/pipeline/` — **wiring for the UI**: `Pipeline` (the
  remaining-work view, the stage drivers that wire work to the front
  end, the work records). No domain mechanics live here: `ocr.py` and
  `htr.py` are wiring on the transcription, and the transcription part
  of them belongs to the document model; "htr" is a stale acronym from
  the dead local recognition stack (kraken/orli/TrOCR, measured
  garbage, unused) — its live content is the VLM reading cursive
  pages, which is the document's transcription;
- `loft/app/` — the API the app uses to access the work to be done by
  the user, factored into per-surface classes (named from the UI: the
  review). **Each surface serves the view the UI needs** — the payload
  shapes live with the surfaces, read from the persisted records (the
  rows, the proposals, the documents); no domain logic:
- `loft/cli/` — the command surface of the **scanner box**: every
  operation that lives on the box connected to the scanner, none of
  the website's — scan, the per-image ops (rows, transcribe,
  orientation, rotate), GEDCOM import/export, publish, the verify and
  maintenance commands. The review surfaces and serving stay with the
  web app.

**Infrastructure**: `store` + `atomic` + `loft_paths` in `loft/archive/`
(the archive's storage and the seam declaring its layout); `ai_client`
(the injected chat-client Protocol) at the `loft/` package root;
`pii_markers` in `tools/` with the other guards.

**Tools** live in a top-level `tools/` for the moment — `scan` (the scanner
driver) and **`BoxAudit`** (the box-invariant check; the name replaces
`boxjig`). `NumberedWords` lives where it is used:
`loft/document/` (it renders a page's words).

`tools/` is not a domain concept and dissolves; `archive/` at the repo
root is the gitignored data location, never committed, never code.

## Settled — item 2: the declared-content import code gets deleted

Verdict: delete it. Verification: the live archive already contains
everything the import asserts — the 2001 email item with its five page
scans and transcriptions; the email's cast in the people table (the
declared `first_person_id` is present; 36 table versions, 104 people,
182 edges); the orgs table (2); the record-book items among 95 asset
items; the proposed queue populated; import sessions on record. The
declared-content import has no remaining work.

Scope of the deletion:
- `tools/document_capture.py` — the whole module (the class, the
  `capture_*` entry functions, the `email_*`/`record_*` cast accessors,
  `_import_data`).
- `tools/archive.py`: the `capture_document` method and the
  `capture_demo_documents`/`capture_document` import. The
  `_ensure_import_session`/`refresh_import_status` session machinery is
  assessed separately — the front page still shows pending sessions, so
  they may outlive the import.
- **The demo path dies entire** — `tools/demo_data.py` is deleted with
  it: no demo instances for the moment, no fictional-content seeding.
- `tools/cli.py`: `cmd_capture_document`, its parser entry, and the
  docstring/help references.
- Tests pinned to it: `tests/test_import_session.py` (session behavior),
  and the cast-oracle evals (`test_import_completeness`,
  `test_import_edges`, `test_family_membership` read the `email_*`/
  `record_*` accessors) — deleted or re-pointed in the same change.
- Docs: `docs/coding-standards.md` CLI examples name
  `loft capture-document`.

Side note: TECHSPEC §13 cites "the 2001 email's 91 people"; the declared
content carries 61 — one of the two is stale, check at implementation.

## Settled — item 4: the strip layout stage is not the architecture

The wired batch-layout path contradicts the architecture. The pipeline's
layout stage runs `layout_stage` → `layout_detect` → `GroupedRead`: one
VLM call per page, VLM-grouped segments become the layout lines, "no
compute-engine call". The architecture (schemas `tools/schemas.py`,
`docs/box-detection.md`, AGENTS) is marks → words → rows: the reader
writes `words.json`/`boxes.json`; rows come from the user's lines.
Evidence: `tools.reader` has one production importer (`schemas.py`);
`Rows.build` has none; the live `layout.json` artifacts are the strip
path's output.

Verdict: the strip layout stage (`GroupedRead`, `layout_detect`,
`layout_stage`'s wiring in `tools/pipeline.py` and `tools/sync.py`) is
removed; the layout stage runs the marks → words → rows chain — the
**pipeline makes the rows** (the detector's own grouping of the words
into rows), and the reviewer reviews them and fixes them
where necessary (the drawn lines are the correction path — the review's
lines feed `rows.adjust(lines, …)`, which re-derives the rows to match
what the reviewer drew; `Rows.from_words` stays the chain factory).
The VLM's contribution is text, orientation, and the per-row kind metadata.
The kind vocabulary (ruled): a row is `body`, `interjection`, or `marginalia`.
An interjection is text added into the flow ("insertion" = interjection);
it carries an insertion point — a character index into a row's text
(L4: proposed from a mark, reviewer-confirmed, unset without a mark).
Marginalia are notes with no insertion point, not part of the body text.
`Row.kind` grows `marginalia`; the gold fixture — the adjudicated
page-01 reference (41 rows over 364 words) — is extended with each
row's kind and insertion points, and **the extended results are
validated by the user by hand before they count**. Anchors:
`layout-requirements-draft` L3–L6, `Row.kind`. The §16.17/VR14 doc
framing that blessed the strip path is corrected in the same change.
The strip stage's `layout.json` dies with it — and so does "layout" as a
concept name: the rows are the reading (boxes, text, trust stage, kind
per row), no `Layout` class exists, nothing validates a separate layout.
`BoxAudit` (the box-invariant check) is the independent tool, unrelated
to any layout concept.

## Settled — item 5: no batch; Archive owns its paths, Pipeline owns the work

The "batch" concept is machinery, not the model — but **the scanner
ingest is first-class work and is retained**: documents DO arrive in
batches, each batch a **scan run** (a folder of scanned files, named by
the run name — optional, default the current date; the files
timestamp-named). What dies is batch-specific **stored state**
(`BatchContext`, `sync.Batch`, the `imports-*.json` session ledger): a
run is not a record, the folder has no record, hash, or fingerprint —
each image in the run registers itself with its sidecar. The system's
unit is the **Image** (arrived scan; sha, source, arrived_at, processing
results).
**Images never move**: each image sits wherever it was scanned into,
and stays there — the archive never copies or relocates it. Each image
carries its own record — a **sidecar written beside the file** (in the
scan folder): sha, source, arrived_at, the processing results, and its
id (allocated at registration, never reassigned). Superseding writes
**version the sidecar** (`…-1`, `…-2` per write) — the archive's
data-safety and concurrency discipline, kept from today
(`docs/archive-concurrency-plan.md`). There is no central
registry or ledger file; an image whose sha matches an existing
image's sidecar **is** that image — a reorganised folder, a copy, or a
re-scan all resolve to the same image (matched by sha; R4's
folder-fingerprint re-association dies with it). **An image has no
stored status** — its state is derived from the artifacts that
reference it: rows exist → read; confirmed rows exist → reviewed; a
document references it → allocated. Nothing derivable is stored. The
date-partitioned tree therefore holds **documents, not images** — its
folders hold the document record and its pages' readings, and the page
references (sidecar id + sha) are verified against the scan-folder
files wherever they are.

**`Entity`**: the base class for the archive's typed records — `Person`,
`Place`, `Org`, `Item`, `Theme` (id, status, validation live here;
`Relationship` is a link between entities, not an entity).
**`Relationship(a, b, kind)` may link ANY two entity kinds** —
person↔person (family links), person↔place ("lived at", "worked at"),
person↔item ("owned"), theme↔item (curated), and any other pair — the
`kind` names the relation, recorded as-is when the link is made.
**`status` is the shared review vocabulary for ALL entity kinds** —
attested / estimated / pending / delete — the same schema the GEDCOM
tag carries. No `Entities` collection class: the collections are per
type and the **`Archive`** class is what exposes them (people, places,
orgs, items, themes) — those typed collections are the standing view;
`tools/memory.py`'s `Knowledge` retires (it was the same view, made
twice). The record classes move into a `loft/archive/` package, one
class per file named after the class. `ReviewChat` reads a `Memory` or
a `Document` with the raw projection as its facts context (through
`ReviewContext`) and produces the review outcomes;
the memory and the document reviews are the same conversation.

**Archive**: owns every path (content, staging outputs, the sidecars) and the
per-image operations (**rows**, **transcribe**, **orientation**,
**rotate**). **rows** runs the row-building chain; **transcribe** maps
the page's text onto its rows — one model call, the entities and the
rows fed in together, the text per row returned; **orientation** reads
the page's turn; **rotate** applies the correction. The document
boundaries are not part of the model call — the grouping scorer
proposes them, the review confirms. No external
context threading paths into it.

**Pipeline**: stays separate from Archive — it is **wiring for the UI**,
nothing more. Its responsibilities:
- the remaining-work view — what automated work and what user work is
  pending, per image;
- the stage drivers that wire each piece of work to the front end —
  calling the document model's transcription (`Vlm`'s text,
  orientation, kinds; the row/word factories) and the archive's
  operations, then handing the review surface what it needs (the
  transcription to review, the insertion point to confirm, the
  proposals to confirm/dismiss).

Consequences: `pipeline.BatchContext` and `sync.Batch` die (paths on
Archive, per-image ops on Archive, remaining work on Pipeline). The
`imports-*.json` session ledger dies — with the pending-sessions view,
in Phase 6, when Pipeline's remaining-work derivation over the
archive's review statuses replaces them.

## The chats and their interfaces

Every conversational class is named `XChat`; every chat's interface is
its contract — what it takes in and what it hands back.

| Chat | Home | The interface |
|---|---|---|
| `ChatClient` | `loft/` root (`ai_client`) | The LLM client: `chat(system, user, *, thinking) -> str` — one call, the caller owns the conversation (messages in, the reply out) |
| `ReviewChat` | `loft/archive/` (the review machinery) | The review conversation over a source — a `Memory` or a `Document`: takes the source and the facts context (the standing collections, through `ReviewContext`), runs the read-only tool harness and the verdict loop (the digs + correction turns; the model-call-is-a-conversation rule; depth is the only per-source difference), hands back the `ReviewDecision` outcomes (attested / estimated / pending / delete per entity) and the `Message` log |
## Settled — the archive's document storage: date-partitioned folders

**The live archive is migrated — this is not optional and not
deferred.** The existing archive's data is in the old
`assets/<id>/` layout and must be converted to the date-partitioned
tree below; the new code does not read or write the live archive's
data until the migration has run. The migration is **Phase 5**, the
only phase allowed to touch the live archive, under the Archive-safety
contract (opt-in command, dry-run first, backup precondition,
verify-loudly — see above). Until it runs, everything stays on the
old layout and keeps being backed up as today.

Current layout: every item is `assets/<id>/` — the
sidecar chain (`item.json`, then `item-N.json` per superseding write)
plus the content files (`Archive.content_path`). Ids already carry a date
in the slug (`story-2026-08-03-05`, `letter-1963-05-14`,
`doc-2001-02-07`). Dependents: `Archive._sidecar_path` /
`content_path` / `_sidecar_versions` / `item_ids`, the projection (reads
via `item_ids`), the server (`item_ids`), `store.list("assets")`, the
tests; the live archive needs a migration.

**What the refactor changes and what it keeps**: the refactor replaces
the *placement* — the flat `assets/<id>/` layout and the document
tree — never the safety mechanisms. The **superseding version chain is
kept** (`item.json` → `item-N.json` per write): it is the archive's
data-safety and concurrency discipline (one writer at a time, every
write safe by append, `docs/archive-concurrency-plan.md`), and the new
layout versions its sidecars the same way. The atomic write seam, the
store layer, the sha identity, and the per-image sidecar records all
carry over; nothing that makes a write safe is discarded.

The design:

- Folders partition documents **by the document's own date** — never the
  scan or recorded date.
- One top folder, "All Time". A folder splits when it holds more than
  **N = 200** documents (a listing a person scans; ext4 read-heavy stays
  comfortable to 10k-20k entries — Red Hat tuning guide — and slowdowns
  begin at "a few thousand" — Bombich).
- The split date is the **median of that folder's own document dates**,
  nudged to a natural label (year, half-year, quarter, month) only when
  both sides keep ≥40% of the content; otherwise the exact median date.
  It is **recorded once and never recomputed** — boundaries and documents
  never move.
- Labels read `Before <date>` / `On or after <date>`.
- A ranged date goes to the deepest folder whose span contains the range;
  failing that, the folder holding the largest part of the range; a tie
  goes to the earlier folder.
- A document with **no date** stays in **All Time** — never in a dated
  child folder (it has no span, so it must not mislead the binary
  search).
- The tree **is** an index: every folder's span is its label, so a date
  resolves by binary search. `DocumentDateIndex` is the cached map the app
  reads for speed; it is bomb-proof by derivation — rebuildable from the
  tree plus the sidecars, written through inside the archive's single
  write seam, with a verify step that rebuilds and reports loudly on any
  mismatch.
- The document's date rides in the id slug (`YYYY-MM-DD`, or the certain
  part where unsure), so a broken link resolves by the same search.

## Open queue

| Item | Object | Verdict | Open question |
|---|---|---|---|
| 2 | `DocumentCapture` (document_capture) | **settled: delete** — capture-document is dead, replaced by the pipeline; nothing in the module is needed by it | see the item-2 section above |
| 3 | `_RowBuilder` (rows) | **settled: merge into `Rows`**, public entry **`Rows.from_words`** | no open question |
| 4 | `GroupedRead` (segment_page) | **settled: dies with the strip stage** — not an architecture component | see the item-4 section above |
| 5 | `pipeline.BatchContext`, `sync.Batch` | **settled: no batch in the model** — Archive owns paths + per-image ops; Pipeline owns remaining work + stage delegation + front-end objects | see the item-5 section above |
| 6 | `CallOptions` (segment_page) | **settled: dies with the strip stage**; the surviving DI set is `Vlm` + `VlmOptions` — the document model's vision reading tool (text, orientation, kinds) | no open question |
| 7 | `NumberingContext` (word_numbering) | **settled: rename to `NumberedWords`** — a first-class tool, lives in `loft/document/` where it is used (supersedes the earlier "stays in `tools/`" note) | no open question |
| 8 | `_FocusOptions` (page_visuals) | **settled: rename to `FocusView`** — MapView-parallel | no open question |
| – | `Assessor`, `AssessmentContext`, the `Memory` class, the `assess`/`build_story` functions (memory) | **settled**: the review is the process — `ReviewChat` reading a `Memory` (the assess/build_story machinery retires into the one conversation). **`Memory`** names the memory itself (the account and the story it becomes) | no open question |
| – | `PileIdentity` (adopt) | **settled: folds into `Image`** — registration is per image by sha; folders have no record, hash or fingerprint; no group id | no open question |
| – | scan run naming (`tools/scan.py`) | **settled**: the run name is optional (default: the current date) and names only the scans' parent folder; the files are timestamp-named (R15 in `MULTI-DOC-IMPORT-PRD`) | no open question |
| – | the archive's document storage | **settled**: date-partitioned folders, N = 200, median split, `DocumentDateIndex` | see the storage section above |
| – | `GedcomImporter`, `FamilyBuilder` (gedcom_document) | dead with item 1 — detail of the document rework below | — |
| – | pile/run **labels** | **settled**: the label is the user's scan folder name; it is recorded (in the arrival's sidecar) only when the user enters one. `MULTI-DOC-IMPORT-PRD` R3/R6 and TECHSPEC §16.13/§16.14 amended | no open question |

Keep list (true nouns, no change): `Colour`, `CropWindow`, `SplitCase`,
`_Sheet`, `_Jig`, `ExportSet`, `StoryRefs`, `StoryFacts`, `PageFlags`,
`LineFrame`, `_UnionFind`, `PageGeometry`, `ClipSeam`, `AnchoredSource`,

`_TextBounds`, `HalfRegion`, `WordBox`, `MapView`, `ContentBounds`,
`CropExtent`, `PageRef`, `ToolHarness`, `PageClassification`,
`GuessArtifacts`, `PageArtifacts`, `Chip`.

## Rollout phases

**Status (2026-10-04):** Phase 1 (delete the dead architecture) and
Phase 2 (the GEDCOM island — `tools/gedcom_document.py`, `loft gedcom in|out`)
are landed on `main`; Phase 3 (the word/row model) is in progress on
`feat/object-model-phase3`; Phases 4–6 are unbuilt.

The model lands in phases, each leaving the gates green
(`make lint && make typecheck && make test && make lucidlint`) and the
box working. A phase is reviewable and mergeable on its own.

**Test parity on every move — the standing policy
(`docs/testing-standards.md`, "A refactor never reduces coverage"):**
Migrating code brings its tests: every
test covering retained functionality moves with the code — re-pointed
to the new home, same cases, same assertions — never dropped as "to
be re-added later." The only tests that may disappear are those
pinning code this plan deletes. Mechanically: the moved suite keeps
its cases (the moved modules' test count does not shrink), the
coverage gate stays green (`make coverage`), and no phase drops a
test whose module survives.

## Archive safety — the live archive is read-only to this plan

The existing archive is the family's data: nothing in this plan may
touch it except the explicit migration (Phase 5), and the migration is
provably safe. Mechanical guards, enforced by the gate:

- **The hermetic invariant**: the whole suite constructs archives over
  temp roots; a conftest guard resolves every archive root the suite
  touches and asserts none equals the live archive's real path
  (resolved, absolute). The live path comes from an environment
  variable — **the guard fails loudly when the variable is unset**, so
  a missing pin can never pass vacuously; a negative test proves the
  guard trips when pointed at the live path. The suite is green with
  the live archive absent.
- **The write-seam rule** (architecture test): the Archive module
  (wherever it lives that phase — `tools/archive.py` until Phase 6)
  is the only writer of the archive's paths; no other module may write
  the live root during Phases 1–4 or 6. The migration command is the
  only code that alters the **existing** archive's structure, ever;
  the Archive's normal writes operate on the new structure after
  Phase 5.
- **The migration's contract**: an explicit opt-in command
  (`loft migrate`), refused when the target state already exists; a
  mandatory dry-run first (reports exactly the operations, writes
  nothing — the dry-run and verify are the sole sanctioned **reads**
  of the live archive); a backup precondition — the marker carries the
  backup's manifest and timestamp, and a missing, stale, or
  mismatched marker refuses to run; on completion, the verify step
  rebuilds the index and reports loudly on any mismatch. Data loss is
  a test failure, never a progress path.

Phases 1–4 and 6 write code, tests, and the pipeline/app outputs only;
every phase's gate includes the two guards above.

## The mechanisms this plan keeps

An independent inventory of the codebase's safeguards was checked
against the model. Everything live is kept; the only deliberate
deaths are the settled ones (the strip stage, the declared-content
import, the demo path, the batch *stored state*, the layout concept).
Anything live that is not here is a bug in this plan, not a deletion:

- **Data-safety**: the superseding sidecar version chain and
  tombstones (deletion is a superseding status, files stay forever);
  `atomic_write` (temp + fsync + replace) on every publication;
  the append-only store (edits refused; path-escape guard); the
  RLock'd read-modify-write with no-op-writes-nothing; save ordering
  (sidecar first, content versioned with it); the gap check
  (a missing middle version fails loudly); the proposed-queue
  discipline; the pipeline store's versioned append-only writes;
  `sync.py`'s rotate journal + crash recovery, Outbox catch-up, and
  `record_confirmation` write seam; adopt's content fingerprinting
  (confirmed transcriptions never auto-cleared); scan staging + atomic
  rename; publish ordering (assets first, JSONs last); the narrator's
  draft auto-save (debounce, keepalive, abandon tombstone); the
  memory review's second-pass + deterministic violation checks.
- **Identity and integrity**: sha fingerprints with stale detection
  (the `.vlm.json` input-sha skip, the boundaries inputs check, the
  stage markers); the records validation seam (closed vocabularies,
  resolving refs, unique ids); record-id and filename guards;
  `sync.py`'s batch/page-name charset guards; the server's CSRF origin
  guard; the layout gates (a failing layout is never written or
  served); the projection's ref validation and dedup; the attestation
  gap check; the `check_review_posted` merge gate.
- **Performance**: the input-sha skip (unchanged pages cost zero
  tokens); prompt-cache prefix reuse; bounded `read_prefix` reads;
  the `byId` projection index.
- **Access and privacy**: Google OAuth (web + device flows, verified
  tokens, signed cookies, replay guards); `/data` gating; the
  narrator-from-session minting; env-only API keys; the PII marker
  guards (the public repo ships no family identity); sensitive items
  kept off serendipity surfaces; the markdown renderer (text nodes
  only).
- **Observability and verification**: token accounting per read (the
  honest sum across fallbacks); the orientation arbiter's audit trail;
  box/word provenance flags (dashed = positional, conf-0 flagged); the
  self-report flag pass; `walk_review` contact sheets; the eval
  harnesses (`eval_*`) with their cached fixtures.

`tools/vlm_cache.py` is the one apparently-live mechanism that is not
kept: the inventory shows it has no production caller — the `.vlm.json`
sidecar does its job — so the model names the sidecar as the cache and
the dead module retires.

**Phase 1 — delete the dead architecture.** The strip layout stage
(`layout_stage`, `layout_detect`, `segment_page`, `strip_measure`,
`GroupedRead`, `CallOptions`, and its wiring in `tools/pipeline.py`
**and `tools/sync.py`**) dies — **the row machinery this leaves
behind is tested but unwired** (no production caller since the
single-pass cutover): the redirect is a **revival**, wiring the tested
`Ink`/`Marks`/`Words`/`Rows` machinery into the pipeline as the
reading path, not a pointer swap. `sync.py`'s **mechanisms are
retained** — the Outbox, the rotate journal + crash recovery,
`record_confirmation`, the job-state markers: only the `Batch` class
and the session ledger die, never the review server's write seam.
The declared-content import dies: `document_capture`, the
`capture_document`/`capture_demo_documents` machinery, `demo_data`,
`cmd_capture_document`, the `email_*`/`record_*` accessors, and the
pinned tests (deleted or re-pointed to the archive tables). The batch
machinery's **stored state** dies: `pipeline.BatchContext` and
`sync.Batch` — and nothing else of the ingest: **the scanner ingest
code is retained** (documents arrive as scan runs; the run stores
nothing beyond its folder). The `imports-*.json` session ledger and
the `_ensure_import_session`/pending-sessions view are **deferred, not
deleted** — they keep the front page working until Phase 6's
remaining-work view replaces them; deleting the ledger while its
reader lives would starve the display.
Verify: gates; a smoke run of the reading on a **copy of a sample
batch**, outputs to a temp work dir, still produces rows.

**Phase 2 — the GEDCOM island.** `GedcomDocument` rework (parses into
itself; the read produces wire shapes from its own state; `to_text`).
`loft gedcom import <file> <folder>` — the record files into the folder,
refuse existing-non-empty, all entries created at import (places
included), `1 _LOFT_STATUS pending` read from the source, unmarked =
not pending. `loft gedcom export <import-folder> <path>` — confirmed
only, the four swap-refusals. The `maximal70.ged` fixture + round-trip
tests (both directions, status faithfulness, double-import refusal);
the `gedcom7code/test-files` corpus (51 files) backs feature isolates
where `maximal70.ged` doesn't cover a construct the import must
round-trip.
Verify: the fixture tests; gates.

**Phase 3 — the word/row model.** One implementation (today
`tools/boxrows.py`; the five parallel modules retire into per-class
files, still under `tools/` — the `loft/document/` move is Phase 6's);
`Ink.from_image` (pixels), `Marks.from_ink`, `Ruler.from_marks`
(**`pagescale` retires into `Ruler` here — the Ruler is born with its
name, no later rename**), `Words.from_marks(marks, ruler.scale)`,
`Rows.from_words`, `rows.adjust(lines)`; `_split_by_size` kept; per-row
text + R7 stages stored with the rows; the gold fixture extended (each
row's kind and insertion points), hand-validated by the user before it
counts — **the fixture tests the correction path (`rows.adjust`), not
the chain: the chain's own grouping is measured against it (48 vs 41
rows), never asserted equal**.
Verify: the fixture's adjust-path tests; the retired modules' tests
move with them (same cases, new homes); gates.

**Phase 4 — the renames.** `NumberedWords`, `FocusView`, `DashPattern`,
`BoxAudit` (boxjig), `Memory`, `Vlm` + `VlmOptions`.
Renames land with their callers (`lsp rename`),
no aliases. Verify: the renames' tests re-point unchanged; gates.


**Phase 5 — the migration of the live archive's storage.** **This
phase converts the live archive**: the existing `assets/<id>/` layout
becomes the date-partitioned tree below — it is the migration, and the
only phase allowed to touch the live archive's data. Documents as confirmed records
(the grouping scorer proposes; the review confirms — the existing
confirmation survives from before this phase); the date-partitioned
tree (All Time; N = 200; median split; `Before <date>` / `On or after
<date>` labels; ranged and date-less rules above); sidecars beside the
never-moving images, no registry; the single write seam,
`DocumentDateIndex`, the verify step; the migration from
`assets/<id>/` — **only this phase may touch the live archive, and
only through the Archive-safety contract**: opt-in `loft migrate`,
dry-run first, backup-precondition, verify-loudly. **The app-side
dependents (`item_ids` readers — the projection, the server) re-point
to the new tree in this phase**, and the per-phase "box working" check
is part of the verify. The 91/61 count is an item-2 docs correction,
not this phase's concern. A pre-allocation image's readings ride in
its sidecar; once its document is confirmed, the reading lives with
the document in the tree — one home at a time, stated here as the
rule.
Verify: the dry-run report is the operation list the execute applies
(post-state equals the dry-run's reported operations); a broken
reference resolves by the same search; the app reads the new tree;
gates.
**Phase 6 — the package restructure to `loft/`.** The five packages
(archive, document, pipeline, app, cli) with one-class-per-file; the
review/memory/archive machinery moves — **including the review
unification: `ReviewChat` becomes the one conversation for memories
and documents (try the single conversation first), and
`RecordMemoryChat` (loft/app) is built here**; the per-surface app
classes; the scanner-box CLI surface; `ai_client` at the `loft/`
the pending-sessions display. Verify: the moved packages' tests arrive
intact (same cases); gates; the two-box smoke — the
pipeline box runs the reading, the app box serves the review.

## Settled — the word/row model: one implementation

Two parallel implementations of the same five types once existed: the
five modules (`page.py`, `rectangle.py`, `row.py`, `word.py`,
`verdict.py`) and the single module `tools/boxrows.py`. Measured
against the adjudicated rows (page-01, 41 rows over 364 words, ink-only
grouping with the same spacing): the single-module implementation
builds 48 rows with 6 orphans and keeps 76% of the adjudicated word
groupings; the five-module set builds 71 with 14 orphans and keeps 64%.
It is also the iteratively refined fork — 12 commits against the user's
rulings; the five modules landed in one commit each. Ruling: **one
implementation — the five modules retire**; the model names the types
(`Word`, `Row`, `Page`, `Verdict`, `Rectangle`), and the package holds
them one class per file. The local-smallness step (`_split_by_size`) is
**kept** — it moves with the rest.

## Settled — the word/row model's home: a `Document` package

The document-side model moves into a `Document` package, one class per
file named after the class (the Archive package ruling applies here too):
`Page`, `Word`, `Row`, `Verdict`, and the geometry record `Rectangle`
(the word/row types — `tools/boxrows.py`, their current home, splits
into these per-class files), plus whatever the `Document` class itself
becomes — today
"document" exists only as `boundaries` data (the page grouping from
`tools/grouping.py`: a page opens a document at a greeting, closes it at
a sign-off). Package contents: settled — the document chain above and the
packages layout below name every class and its file.

## The object model — diagram

```mermaid
classDiagram
    direction LR

    namespace "loft" {
        class ChatClient
    }
    namespace "loft/archive" {
        class Archive {
            +entities: Entities
            +register(Image), per-image ops
            +publish(): Projection
        }
        class Entity { id, status, validation }
        class Person
        class Place
        class Org
        class Item
        class Theme
        class Relationship { a, b, kind }
        class ReviewChat {
            the one review: a Memory or a Document, depth the only difference
        }
        class Memory { the narrator's account }
        class GedcomDocument
        class Projection
        class ReviewContext
    }
    namespace "loft/document" {
        class Document {
            +pages
            +render_review()
        }
        class Page {
            +Ruler ruler
            +Ink ink, Marks, Words, Rows, Transcript
            +render(), render_focus(), case render
        }
        class Transcript { the page's text: the rows' texts (R7 stages per row) }
        class Ruler { x-height, spacing, line ratio; from_marks(marks) }
        class Ink
        class Marks { from_ink(ink) }
        class Words { from_marks(marks, scale); wire formats }
        class Rows { from_words(words, page); adjust(lines); text + stage per row }
        class Rectangle
        class Verdict
        class Vlm { transcribe, orientation, kinds, selfreport }
        class VlmOptions
    }
    namespace "loft/pipeline" {
        class Pipeline { wiring for the UI: remaining work, stage drivers }
    }
    namespace "loft/app" {
        class Auth
        class Capture
        class Transcription
        class Insertion
        class RecordMemoryChat { the memory-capture surface: receives the
            narrator's account, saves the Memory, runs the assessment chat }
        class Assets
        class Browse
    }
    namespace "loft/cli" {
        class Cli { the command surface }
    }
    namespace "tools" {
        class BoxAudit { the box-invariant check }
    }

    Entity <|-- Person
    Entity <|-- Place
    Entity <|-- Org
    Entity <|-- Item
    Entity <|-- Theme
    Document o-- "1..*" Page
    Page --> Ruler : owns
    Page --> Ink : owns
    Page --> Transcript : owns
    Ink --> Marks : from_ink
    Marks --> Words : from_marks
    Marks --> Ruler : from_marks
    Words --> Rows : from_words
    Rows --> Page : ruled by page

    Pipeline --> Document : drives the readings
    Pipeline --> Archive : drives per-image ops
    Transcription --> Archive : reads the persisted rows
    ReviewChat --> ChatClient
    ReviewChat --> ReviewContext : the facts context
    ReviewChat --> Entity : the review outcomes (attested/…)
    Vlm --> Page : reads
    Vlm --> VlmOptions : constructor config

    Item "1" <-- Relationship : links
    Place "1" <-- Relationship : links
```

## References

- The rule's wording: `lucidlint` latent-class messages.
- The parser the fixture exercises: `gedcom7` (python-gedcom7).
- Import rules incl. Rule S: `docs/PRD/IMPORT-PRD.md`.