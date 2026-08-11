# Letter Import — Feature PRD

- **Status:** draft — proposed, review pending (2026-08-05)
- **Source:** the import-interview session record §9 — interview findings, 2026-08-05 (the import attempt *is* the interview; the record stays private)
- **Normative home:** `docs/TECH-SPEC.md` §16 (draft). **Parity partner:** `docs/prd/MEMORIES.md` (the story flow)
- **Companions:** the private interview records (family facts) and the private worked-example review (real-import lessons)

## 1. Purpose

Scanned pages arrive from the scanner or phone app; the machine reads the scan(s) and proposes the full identification of the letter — people, organisations, places, dates, memorabilia — and the reviewer accepts, edits, or drops them **in the same flow**. Import is the artifact-reading counterpart of the story flow (`MEMORIES.md`): the same depth, the same review-as-gate discipline, plus memorabilia and organisations as first-class entities. Nothing asserted unreviewed (P4); nothing blocks capture.

## 2. Flow requirements

### 2.1 Review-as-gate (parity with the story flow)

- The machine proposes every identification (bucket + reason); the reviewer reviews in the same flow — **kept = confirmed, dropped = gone**.
- No separate confirmation gate. An abandoned session stays `draft` with `proposed` refs; a completed reviewed import is `catalogued` with `confirmed` refs.
- The one structural difference from stories is the source: stories elicit from a narrator (open-ended closure → targeted questions); import reads an artifact — there is no narrator, so the machine proposes directly from the scan + standing knowledge, and **the review is the elicitation**.

### 2.2 Staged presentation

Proposals are presented one stage at a time, confirmed between each, back always allowed:

| # | Stage | Behaviour |
|---|---|---|
| 0 | Item fields | type (proposed from the criteria: from one person to another, dated, scanned physical page, not an email printout) + title (agent-proposed from date + type; confirm or edit — never typed from scratch). *Placement open — the user's enumeration starts at to/from.* |
| 1 | To/from | sender + recipient proposed **as assumptions** (each may be a person or an organisation). Every proposed match offers: accept · pick a different existing entity · create a new one (the "different Owen" case) |
| 2 | Other people & organisations | every mentioned person/org, each proposed with reason. Resolvable against standing knowledge → proposed straight away (Rule A); strangers → proposed + "how are they connected?" question |
| 3 | Places | proposed place records. A house/flat record triggers the **household rule** (Rule C): who lived there (alone, for adults); proposals age-bounded to the item's date. **Every newly geocoded place is presented as a point to verify (Rule O): "near X" — accept / adjust / drop — before it can render on the map.** A place the geocoder cannot pin enters the **research step (Rule S)**: web/archival search → evidence item (Rule R) → re-geocode on the anchor → review. |
| 4 | Dates | **item date = the earliest date the item is attested** (consistent across types — Rule K), honest precision (typed date → exact); the origin/first-encounter question rides with it (Q7); referenced dates via the dates-mentions seam |
| 5 | Memorabilia | attested objects and attested items not in evidence, each proposed with its evidence named (the reply is the evidence for the submission) |

After the stages: the story line (encouraged, never blocking) → done. The item is `draft` until the phone session catalogues it.

### 2.3 Rules settled this session

- **A — propose when obvious:** identity resolvable from standing knowledge is proposed straight away; ask only when it genuinely doesn't resolve.
- **B — to/from as assumptions:** the proposal states FROM and TO separately, as assumptions, apart from the *mentioned* list.
- **C — household rule:** new house/flat places → "who lived there?" (alone for adults); proposals from known relationships, age-bounded to the item's date (only alive, born-before): under-18s → parents + siblings; adults → spouse + alive under-18 kids. Deduction is proposed, never asserted.
- **Never ask "is this the whole item?"** — the item is what's scanned; missing pages are possible; future material arrives as its own scan and is connected then.
- **Page association** — multi-page letters scanned together (a folder of images) need a "these pages are one letter" mechanism (the boundary review pass). Required; mechanism deferred.
- **Title/type** — agent-proposed, confirm/edit.
- **D — care-of addresses:** a "c/o" address triggers an ad hoc residency question **before** household proposals — the named person may not live there (the 1973 statement's care-of hid a boat on the Grand Union).
- **E — date noise:** many uninteresting mention dates → ask verbally whether to keep them; a "no" keeps only the interesting ones. **Every item must carry a date, even ridiculously vague.**
- **F — mobile objects:** a constantly mobile thing has no location — never ascribe proposed locations or dates without attestation (a home mooring, direct evidence of presence).
- **Story line = a proposal to confirm** — an attested fact about the item, self-contained (no dangling references); verbatim narrator words are raw material, never the story field itself.
- **Language:** there is no "the curator" — everyone is a curator; the reviewing user is simply "the reviewer".
- **M — tabular markdown (was I):** scans with tabular content (registers, statements) extract as an order-preserving, layout-preserving markdown table proposal — marginalia noted by position — and **the table is the review/correction surface**, after orientation (J). The *semantic reinterpretation* of content (clean Name|Event|Date tables) is dropped: it silently discarded layout and hallucinated. (Demonstrated 2026-08-05: a table rendering surfaced systematic decade drift — 1808/23 vs 1868/73 — that the reviewer's eyes settled.)
- **J — orientation pipeline:** a cheap model answers "which way up is the text?" first; the scan is rotated upright; only then does the full reading model see it. Rotated readings are hallucination-prone (demonstrated 2026-08-05: sideways page B read as "Gallow Church, Salisbury" — upright it reads "tallow chandler"). **The canonical orientation prompt (2026-08-05 — the clockwise/counter-clockwise labels proved unreliable; a positional answer does not need the model's rotation vocabulary):** *"Where is the top of the page's content — the first line of text (for a photo: the sky/ceiling/floor) — relative to the image edges? Answer with exactly one of: TOP, BOTTOM, LEFT, RIGHT."* Mapping: TOP → as-is; **RIGHT → rotate 90° counter-clockwise**; LEFT → rotate 90° clockwise; BOTTOM → 180°.
- **K — item date = first attestation:** an item's date is the first date on which **the item itself** is attested to exist — a letter: its date; a statement: its own date; a house: earliest deed/mention; a record book: its dedication (not the earlier event dates written in it — the book didn't exist at those times). In multi-date cases the flow asks the origin question (Q7): **the origin's date is the item date.** Consistent across types. **Spanning documents carry per-ref involvement dates (2026-08-06):** when the item is written into over time (a family record, a guest book, a logbook, an annotated map), each ref — person, place, object, org — states when *that* entry/signature/annotation was made, and person/place pages and filtered views place the item by it. The flow proposes these dates from the entries' own content (a birth entry is dated by the birth; a signature by its date) and the reviewer confirms — the item's own date stays the first attestation (the record sits in the 1940s on Nora's page, at 1868 on the general timeline). (Reconciliation with E and F: **E + K together** — every item carries a date, its first attestation, even when that is ridiculously vague; **F** forbids un-attested *locations* and fabricated dates, it never leaves an item dateless — the boat has date 1973 approx (its first attestation, the narrator's account) and no location.)
- **L — transcript gate:** the machine's transcript is checked and fixed by the reviewer **before** any proposal is built on it (identification inherits transcript errors). **A transcription is the document's text, verbatim — nothing added, nothing removed** (2026-08-10, user: "transcriptions should be literal exact transcriptions"); structure is preserved — tables stay tables, lines stay lines (Rule M). A summary or paraphrase is not a transcription, and no sentence of an unverified (draft) transcription is ever quoted as the document's own words (the 2001 email's draft transcription was a summary of the census findings — the review was quoting the transcriber, not the email). The machine's reading stays `transcription_status: draft` until the reviewer's eyes settle it.
- **Q — the re-description pass (after every session):** descriptions must always reflect what the archive now knows — new evidence can make an old description wrong or stale (a person first described as "some bozo she met in a bar" who later turns out to be her husband must be re-described, not kept as the old line). After an import session, the flow presents **every entity the session touched** — the item itself and every person/place/org it references — with its current description and asks *"does this still best reflect what we know?"* — accept or edit, in the same flow. Descriptions are evidence-faithful: a description must never assert what the current evidence contradicts, and when the evidence changes the description changes with it (supersede, never edit in place). (2026-08-05: the first import wrote 8 place notes and the cast's bios in one pass; nothing re-checked them after the next letter arrived — the bozo case is the reason this rule exists.)
- **R — research evidence imports like a scan:** findings made during research — a web page, a directory entry, a blue plaque, a photograph — are imported as items exactly like scans: the source citation goes in provenance, downloaded images become assets, people and places are proposed under the standing rules, and the geocoding attempt proposes coordinate + precision together. The evidence chain stays intact: the item is the attestation and the entity's note cites it (2026-08-05, the Lark Inn: a blue-plaque search found the building still stands — the premises became Walton's Yard and the surviving building is 5 Walton Yard; a Places-API geocode pinned it and the place's coordinate went from an unverified town-centre guess to an attested, exact point, with the research item carrying the photographs). **A web-page capture is dated by its access day** — the item is *our* capture of the page, so Rule K's first attestation is the day we took it, not the page's publication date; and the page is hyperlinked from the item (a `sources` list: url + title + accessed date), so a reader can click through and see how old the capture is. **Serendipity is a feature**: a research detour becomes a first-class, dated, mapped artifact that future readers land on exactly as they'd land on a letter — the same door, the same depth.
- **S — unlocatable places get research, not a silent fallback:** when a place fails specific geocoding — a named building, farm or house the geocoder cannot pin, often because it no longer exists *under that name* — the flow does not park it at settlement precision. It enters the research step: a web/archival search for the place's name + region + era (heritage-society pages, plaques, directories, OS maps, successor businesses). A finding is imported as an evidence item (Rule R), the geocoding is re-attempted on the anchor it provides (a successor's address, a plaque's location), and the reviewer accepts or drops the chain. Still nothing? Only then the settlement fallback, and the note records that the search was attempted. (2026-08-05, the Lark Inn: it fails to geocode under its own name because it no longer exists as an inn — but a blue-plaque search found the premises became Walton's Yard, whose surviving building (5 Walton Yard, now the Century Chinese restaurant) geocodes exactly. Without the research step, Rule P alone would have parked it at town level.)
- **The evidence discipline — what counts:** (1) **Sourced** — every finding names its source (URL, book, directory, plaque). (2) **Cross-checked** — the finding must agree with standing knowledge (era, people, place): a search for "Lark Inn" returns Kendal, Elland, Thirsk and Bingley too; only the one matching the record book's Market Square and Giles Hazeldene is evidence. A same-name match without the cross-check is a trap, not a find. (3) **Granular** — the finding attests exactly what it attests: the plaque page attests the premises became Walton's Yard; the coordinate is the surviving building *within* the premises, not the historical footprint — and the description says precisely that. (4) **Reviewed** — nothing is auto-applied: the chain (finding → evidence item → re-geocode → coordinate) is proposed link by link and the reviewer accepts, adjusts or drops each (P4). (5) **Preserved** — the evidence item stays in the archive and the entity's note cites it, so a future reader can retrace the whole chain.
- **N — consistency checks:** ages vs dates are checked in deterministic code (age + date ⇒ birth year); mismatches are surfaced as review questions, never silently resolved. (Demonstrated 2026-08-05: "aged 6 months at 16 Feb 1870" ⇒ born ~Aug 1869, catching the reviewer's own "1860" reading — the machine's cross-check beat both eyes.)
- **O — geocoding is proposed, verified by the reviewer:** coordinates enter as proposals like any other machine output; a place without a precise street-numbered address (a town, a village, a named house) requires the reviewer's eyes on the point before it is confirmed (2026-08-05). The map never shows an unverified coordinate as fact. **The verification is part of stage 3, not a background assumption:** the stage-3 review presents each newly geocoded place as *"near X" — accept / adjust the point / drop* before the place is confirmed. (Lesson, 2026-08-05: the first import proposed coordinates that the flow never surfaced — the reviewer was never asked, the coordinates sat "verification pending", and the Rule O nulling quietly removed them from the map. A rule without a stage is a trap.)
- **P — precision comes from geocoding, never from the place's type:** every proposed coordinate carries its precision (`exact | street | town | county | region | country | continent`, the closed vocabulary on the Place record). The flow **geocodes the specific place first** — by name and any address in the evidence — and proposes the precision the match honestly supports: a specific match (street-numbered address, a surveyed point) is `exact`; a street/square-level match is `street`; no specific match → the **research step (Rule S)** before any settlement fallback; and only when research finds nothing does the settlement-centre fallback apply at `town` (or the larger area's level). **You cannot know whether a named building is locatable until you look** — and "looking" includes the web, not just the geocoder: a building that no longer exists under its name may still stand under a successor's (2026-08-05, the Lark Inn: a blue-plaque search confirmed the building still stands on Market Square, Stonewick, as the Golden Lark/Walton's Yard, and a Places-API geocode of the surviving building pinned it exactly). The reviewer accepts or adjusts the point and the precision together, and an imprecise point renders as an uncertainty ring, never a pin.

### 2.4 Model additions (landed in the archive, 2026-08-05)

- **Organisation** — a first-class identity table (`archive/orgs.json`; `tools/records.py` `Org`/`OrgsTable`, `validate_identity("orgs")`; the projection emits `orgs.json`). Sender/recipient refs may be orgs (`orgs[]` on items, ref-validated at publish). Orgs carry an `address` and `branch` — the org's address is the org's, never a place record. Additive: an archive without an orgs table still publishes (empty list).
- **Person fields** — `dob`/`dod` ({date, precision} — honest precision, never a fake exact date) and `occupations` (attested forms, e.g. tallow chandler, telegraphist).
- **Place fields** — `address` (the written form) and `household` (who lived there and when; members {id, from, to, status} — a deduction is proposed, the household rule).
- **Memorabilia refs** — attested objects and attested items with no assets (the submission letter, the design, the book) — `assets: []` items already worked (the 2009 doctor's letter); the import interview created six more. Evidence named in `provenance`/`description`.
- **Dates-mentions seam** — `date_mentions` on items ({date, precision, note}): referenced dates (the 27 Jan 1949 submission, the record's three marriages) live here, beyond the single item `date`.
- **Proposed people live in the table** — the people identity table holds both confirmed and proposed people (`status: proposed`), and relationships resolve against the table **regardless of status** (2026-08-05: the record book's 29 people + 31 family edges are table rows; the proposed/ queue is story-mention staging, not the import flow's home).
- **Proposed-people dedup is dob-aware** — same-named people with distinct birth dates are distinct people (the record book has three Walters, two Claras, two Theos), never collapsed (`people_projection`, queue merge only).
- **Date precision vocabulary extended (GEDCOM alignment, 2026-08-05):** `exact` / `month` / `year` express granularity (a year-only date is exact at year granularity — never uncertainty); `approx` = about; **`before` / `after` / `between`** carry the bounds the artifacts actually state ("Aft. 1917", "Bet. 1880–1881") — `between` holds the upper bound in `date2`. Validated on `Person` dob/dod; round-trips losslessly through the GEDCOM 7 export/importer (ABT / BEF / AFT / BET).

### 2.5 Parity requirement

Organisations and memorabilia are supported by **both** flows — the story flow gains them too. One content model, two capture flows.

### 2.6 Concrete flow — open-ended questions vs UI elements

Two layers, never conflated:

- **Asked (open-ended)** — free-text questions the machine asks the reviewer, generated by a prompt; one at a time, each with a *why*, each skippable.
- **UI (interactive)** — fixed controls for accepting, editing, or dropping proposals. Proposals are structured data rendered as UI; questions are free text rendered as conversation.

**Prompt contract (elicitation layer).** One deterministic prompt per stage (temperature 0, JSON out — the `MEMORIES.md` discipline). Inputs: the machine reading · stage context · current proposals · standing knowledge (cast, places, orgs, themes). Output: `{questions: [{text, why, skippable}], proposals: [...]}` — `questions` render as conversation, `proposals` render as UI. Every question type is prompt-writable from its trigger:

| # | Trigger | Question shape | Why | Skippable |
|---|---|---|---|---|
| Q1 | stranger proposed (stage 2) | "How is [name] connected to the family?" | identity is never guessed | yes |
| Q2 | "c/o" in an address (stage 3, Rule D) | "Did [person] live at [place], or just receive post there?" | care-of implies possible non-residence — asked BEFORE household proposals | yes |
| Q3 | new house/flat (stage 3, Rule C) | "Who lived at [place] in [date]?" (age-bounded proposals accompany) | household is deduction, never asserted | yes |
| Q4 | date noise (stage 4, Rule E) | "[n] mention dates found (e.g. …). Keep them, or keep only the item date?" | uninteresting dates are noise | yes |
| Q5 | end of stages | "Anything worth one line about this one?" | story line encouraged, never blocking | yes |
| Q6 | artifact unconnected to standing knowledge (Rule G) | "What's its significance — and how did you come by it?" (one at a time) | context is never assumed | yes |
| Q7 | every item (stage 0) | "Where did this come from?" — if unknown: "Where did you first encounter it?" | item date = first attestation; provenance is raw material | yes |
| Q8 | a proposal conflicts with another artifact's reading (any stage) | "The [other document] reads [X] — want to check it? It's [position in the transcript]." | the reviewer's eyes settle conflicts; the machine never does (2026-08-05: the 2001 email vs the record book — decade misreads) | yes |

**UI elements per stage:**

| Stage | UI |
|---|---|
| 0 — item fields | type selector (proposal highlighted) · title field (pre-filled, editable) · confirm |
| 1 — to/from | per entity: accept proposed · search-and-pick existing · create new (kind: person/org) |
| 2 — people/orgs | mention list — reason + keep/drop toggle per row; stranger rows surface Q1's answer |
| 3 — places | place picker (accept/pick/create) · address field · household list (keep/drop, age-bounded) |
| 4 — dates | date control (calendar + precision toggle exact/month/year/approx) · referenced-dates keep/drop |
| 5 — memorabilia | object list: accept/edit/drop · location/date fields only when attested (Rule F) |
| story | story field (speech-to-text) · editable proposal |
| done | review summary — every proposal a toggle (kept = confirmed, dropped = gone) · save catalogued / draft |

**UI gap (2026-08-05):** proposed person records carry dob/dod, relationship edges and occupations — the review UI for those fields (beyond accept/pick/create) is not yet designed.

## 3. Non-goals / deferred

- The page-association mechanism for multi-page folders (needed; deferred this session).
- The phone review surface (Slice 2) and the person-record review UI (dob/dod/relationships/occupations beyond accept/pick/create — the flagged UI gap, §2.6).
- OCR/transcription quality (Slice 1, §16.7).

## 4. Acceptance criteria

Given a real scan, the flow:

1. Proposes type + title (confirm/edit, never typed from scratch).
2. Presents to/from as assumptions — accept, pick a different existing entity, or create a new one.
3. Proposes every mentioned person/organisation with a reason; strangers enter as proposed with a "how are they connected?" question.
4. Proposes places; a house/flat triggers the household question with age-bounded proposals (e.g. at Dunhollow only Owen is attested; parents proposed, not asserted).
5. Records the item date with honest precision and referenced dates via the mentions seam.
6. Proposes memorabilia and attested items with their evidence named (e.g. the supersonic design; the 27 Jan 1949 submission letter).
7. Never asks "is this the whole item?" and never asserts anything unreviewed; kept = confirmed, dropped = gone; the item is `draft` until catalogued.
8. Distinguishes the two layers: ad hoc questions (care-of residency, household, date noise, connection) are asked as open-ended prompts; every proposal renders as UI; no proposal is ever typed from scratch.
9. Orientation is normalized before reading (cheap pre-pass + rotate); the transcript is checked/fixed before proposals; the item date is the earliest attestation; the origin/first-encounter question is asked.

## 5. Source material

- The import-interview session record — §9 (proposed flow) and §10 session log (rulings, 2026-08-05; private)
- The private interview records — family facts (cast, places, capture conventions)
- `docs/TECH-SPEC.md` §16 — import flow design (draft; this PRD feeds it)
- `docs/prd/MEMORIES.md` — the story flow this PRD mirrors
- The private worked-example review — real-import lessons (never guess identity; co-occurrence ≠ relationship; actuality not recurrence)
