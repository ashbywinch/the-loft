# The Object Model — the domain nouns and the document chain

The object model: what each class is, what it is named, and which file it
lives in. This is the techspec the code is held to — a class in a file
named after the class; methods that operate on a class's objects are
members of that class, its collection classes owning their factories
(`Words.from_marks`, `Rows.from_words`); a module named after anything
that is not a domain concept does not survive — the word/row types are
`Word`, `Page`, `Row`, `Verdict`, `Rectangle`, whatever module they
currently sit in (today `tools/boxrows.py`, a code name, not a
concept).

Status: **current**. The live architecture — the DB, the pipeline, the
export and the code layout — is `docs/TECHSPEC/00`, `04`, `05`, `07`, `08`
and `11`; this document names the domain objects and their chain.

## The rule that started this

`latent-class` findings: "introduce a record named with a domain noun, with
named fields". A name made by nouning a verb is not a domain noun. Generic
suffixes (`Options`, `Context`, `Style`) are allowed only when the suffix is
the honest noun for the object.

## Settled — item 1: GEDCOM read/import
- **`GedcomDocument` holds the records.** It becomes a real document object:
  parses text into itself, and the read produces wire shapes from its own
  state. The im/export working class is not part of the model; the
  document's records are its state.
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
- **One status schema.** The review speaks **attested / pending / delete**
  with a basis and confidence; the record stores **proposed / confirmed /
  rejected** plus `basis_json`. `estimated` is a display (confirmed +
  recollection/inference below certain). The mapping is `05` §18.2.
  GEDCOM carries it in the custom tag `1 _LOFT_STATUS pending` (user tags
  start `_`); the import reads it.
- **Export emits confirmed, never proposed.** The confirmed record carries
  its basis and confidence; the GEDCOM adapter maps the recollection basis
  to `EST`/`QUAY`. Round trip is exact on that subset; proposed records are
  not expected to match across an export.
- **The record set is closed by round-trip fidelity.** The import writes a
  record for every construct the file carries that export must re-emit:
  people, families, relationships, places, residences; events, dates,
  name parts, notes as their record data. The mapping is pinned by the
  `maximal70.ged` round-trip — a construct the fixture exercises and the
  export re-emits must have its record; nothing is dropped as a
  parse-time convenience.
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
  pages by each scan's id and sha256. Loading a document verifies the
  image's current sha against the recorded one — a moved, renamed, or
  replaced file is re-found by sha/phash, never silently detached.

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
confidence beyond a flag. The per-page **reading blob** is the read
record and the cache: input-sha skip (a page whose image is unchanged is
never re-read), token usage per page, alongside the page itself.
`VlmOptions` is the constructor config: model, base URL, prompt,
timeouts, cache toggles.

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

## The scan, the page and the document

**The batch is a row.** A scan run is a `batches` row (label, path, status,
fingerprint) with its `scans` rows (page sha and path). There is no sidecar
and no folder record: the scan original stays in the user's scan area, and
`scans` is the registry. A moved scan is re-found by sha256/phash.

**The image never moves; the row points at it.** A page is a `pages` row
(category, rotation, revision, status) over a `scans` row. The reading is a
content blob referenced by `readings`; `page_rows` is its queryable
projection. The date-partitioned tree is the **export**, not the live store.

**`Entity`**: the base class for the archive's typed records — `Person`,
`Place`, `Org`, `Item`, `Theme` (id, status, validation live here;
`Relationship` is a link between entities, not an entity).
**`Relationship(a, b, kind)` may link ANY two entity kinds** —
person↔person (family links), person↔place ("lived at", "worked at"),
person↔item ("owned"), theme↔item (curated), and any other pair — the
`kind` names the relation, recorded as-is when the link is made.
**`status` is the record disposition for every entity kind** — `proposed |
confirmed | rejected` — with `basis_json` holding the basis and confidence;
the review responses map through `05` §18.2 and `estimated` is a display. No `Entities` collection class: the
collections are per type and the **`Archive`** class exposes them
(people, places, orgs, items, themes); `tools/memory.py`'s `Knowledge`
is not a second view. The record classes move into a `loft/archive/` package, one
class per file named after the class. `ReviewChat` reads a `Memory` or
a `Document` with the raw projection as its facts context (through
`ReviewContext`) and produces the review outcomes;
the memory and the document reviews are the same conversation.

**Archive**: the exporter/importer. `LiveStore` owns the live data and
the paths; `Archive` materialises the export and imports the old tree.
The per-image operations (**rows**, **transcribe**, **orientation**,
**rotate**) are the pipeline's. The document boundaries are not part of
the model call — the grouping scorer proposes them, the review confirms.

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

The batch is a `batches`/`scans` row; the review session is
`review_sessions`/`claims`; the pipeline's remaining-work view reads the
stage rows.

## The chats and their interfaces

Every conversational class is named `XChat`; every chat's interface is
its contract — what it takes in and what it hands back.

| Chat | Home | The interface |
|---|---|---|
| `ChatClient` | `loft/` root (`ai_client`) | The LLM client: `chat(system, user, *, thinking) -> str` — one call, the caller owns the conversation (messages in, the reply out) |
| `ReviewChat` | `loft/archive/` (the review machinery) | The review conversation over a source — a `Memory` or a `Document`: takes the source and the facts context (the standing collections, through `ReviewContext`), runs the read-only tool harness and the verdict loop (the digs + correction turns; the model-call-is-a-conversation rule; depth is the only per-source difference), hands back the `ReviewDecision` responses (attested / pending / delete per entity, with basis and confidence; `estimated` is a display) and the `Message` log |
## The export's document tree

The human archive's document leg is the date-partitioned tree: `All Time`,
N = 200, the median split, `Before <date>` / `On or after <date>` labels, a
document with no date in `All Time`, a date correction re-files the leaf.
The full rules are `docs/TECHSPEC/07-exports.md` §18.8; the file→DB
migration is `docs/TECHSPEC/11-migration.md`. The tree holds the record and
the text; the page images stay in the scan area, linked by sha256 and phash.

## Class names

Keep list (true nouns, no change): `Colour`, `CropWindow`, `SplitCase`,
`_Sheet`, `_Jig`, `ExportSet`, `StoryRefs`, `StoryFacts`, `PageFlags`,
`LineFrame`, `_UnionFind`, `PageGeometry`, `ClipSeam`, `AnchoredSource`,

`_TextBounds`, `HalfRegion`, `WordBox`, `MapView`, `ContentBounds`,
`CropExtent`, `PageRef`, `ToolHarness`, `PageClassification`,
`GuessArtifacts`, `PageArtifacts`, `Chip`.

## Settled — the word/row model: one implementation

One implementation: the `document/` package's `Page`, `Word`, `Row`,
`Verdict` and `Rectangle`, one class per file. `tools/boxrows.py` is
retired. The local-smallness step (`_split_by_size`) stays.

## Settled — the word/row model's home: a `Document` package

The document-side model is the `document/` package, one class per file:
`Page`, `Word`, `Row`, `Verdict`, `Rectangle`, and `Document`. The
`Document` class owns the grouping (a page opens a document at a
greeting, closes it at a sign-off); the review confirms it.

## The object model — diagram

```mermaid
classDiagram
    direction LR

    namespace "loft" {
        class ChatClient
    }
    namespace "loft/archive" {
        class Archive {
            exporter/importer
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