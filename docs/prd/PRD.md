# Family History Album — Product Requirements Document

**Purpose.** This document is the product's **requirements and user needs
only** — what the family needs and why, in the user's terms. It is not an
implementation document: it does not say how the app is built. The
mechanics (the data model, the API, the build) live in `../TECH-SPEC.md`;
the slice sequencing lives in `../plans/PLAN.md`; the presentation conventions
in `../UI.md`. A requirement earns its place here only when it states a
user need or a behavior the family experiences. Anything that names a
technology, a field, or an internal mechanism belongs in TECH-SPEC, not
here (2026-08-09).

Working title: **The Loft** (approved by the user, 2026-08-02; revisitable before launch).

- **Sequencing:** `../plans/PLAN.md` — thin slices, feature inventory, urgency knobs.

- **Status:** Draft v0.10
- **Length note:** this canonical requirements document runs past the
  150–200 line ceiling in `docs/writing-documentation.md` — an explicit,
  documented exception for the requirements doc itself.
- **Date:** 2026-08-02
- **Platform:** Tablet-first web app (HTML/CSS/JS), any modern browser — **product is family-agnostic; content is family-specific**
- **Requirement history (sanitised — family-instance facts live in the private interview records):**
  - **v0.2:** elders cannot be interviewed; the youngest children are the future users; narrators fade
  - **v0.3 (story-harvest session 1):** artifacts may be voluminous and repetitive — the story lives in accumulation; themes are the doors, evidence is the room; transcription = pattern discovery; physical deadlines on the collection; post-run witnesses (ledgers, a medical letter, notes, photos that show only the happy surface)
  - **v0.4 (session 1 complete):** felt experience — explorable, draws you in, never editorial; anti-censorship default; OCR drafts (Should); map as a first-class door; interleaving vision; full interview record kept private
  - **v0.5:** generational longevity (§18) — the artifacts outlast the app; capture facts resolved (photo volume, back-writing, recordings)
  - **v0.6:** story harvest & testimonies (§19, G7) — record / self-record / type; narrators are actors in the story, not editors; testimonies first-class with embeddings; the preservation rule
  - **v0.7:** names/aliases as first-class identity; everything-to-everything graph at scale; open questions resolved (vanilla nuance, TV/show mode, ML appetite); prototype shipped — sequencing in `../plans/PLAN.md`
  - **v0.8:** Show mode; proposed-status UI; acceptance flows F7–F8
  - **v0.9 (requirements review):** no single-narrator bottleneck (elders contribute via prompts); family-agnostic requirements with abstract user stories; kids and people with dementia alike have fun exploratory experiences; testimony of the involved is a JTBD; §18.3 split (privacy/control + recoverable-without-credentials); accounts required (TBD); ML face/pet/boat labeling and OCR are Should; no public sharing of anything; no camera capture (scanners only); letters link sender+recipient; display priority facts→reader→others; the app never reads Drive at runtime; model-proposed alt text
  - **v0.10:** sanitised — the PRD states requirements only; family-instance facts (names, dates, exact counts, who has what) live in the private interview records and the content
  - **v0.11:** import-flow design (PLAN Phase 1): colour 300 DPI capture; a phone scan app is allowed for odd-sized originals (§7 amendment); addresses and dates come from the letter itself, not envelopes

---

## 1. North Star

> **The archive is a folder; the app is a lens.**

Turn a family's boxes — letters, photographs, documents, and heirlooms — into a **family museum that anyone in the family can walk through on a tablet**: chronological, personal, warm, and private. The product is deliberately **family-agnostic**: same schema, screens, and flows for anyone's archive; only the content is the family's own. The data lives as plain files on disk and outlives the app; the app is replaceable. The pattern to serve: large runs of dated, personal artifacts whose accumulated voice carries lives the family never met.

The deadline gives it shape: the narrators fade, and the physical collection may carry its own deadlines (a move, a sale, a clearing-out). So the app must **run and gather data without any single narrator — or techie — as a bottleneck**: it prompts the narrators it has, including elders with dementia, and never depends on one person. It is being built so the next generation can meet the people in the archive as they were: a child can meet a grandparent they never knew, or a parent as a young person before children.

---

## 2. Problem & Scale

**The problem.** The collection is a shoebox at the scale of a room: enormous, unstructured, and undocumented. The stories live in people's heads, not on the paper. A photo grid shows *what*; a museum shows *why it matters*. This family needs a walk, not a grid.

**The stories have deadlines.** The narrators can still contribute — prompted, and sometimes with dementia — but their memories are time-bound, and the physical collection may itself be at risk (a move, a sale, a clearing-out). Digitization races a physical clock as well as an emotional one. The good news is structural: the artifacts are written *voices*. The product's job is to harvest that voice — via transcription, narration, and curation — while the narrators who can still decode it are here. **No single person is the bottleneck:** the app must run and gather data with no techie in the loop.

**The shape of the collection:** artifacts may be voluminous and repetitive — dry weekly accounts rather than set pieces — with the emotional register living outside the record (in calls and conversations never captured). No single artifact is a showstopper; **the story lives in the accumulation** — the slow drift across years. The narrative mechanism is the *long view*: sequence, repetition, pattern. The hole at the center is respected, never filled with invented emotion. Witnesses beyond the main run — account ledgers, medical records, standalone notes, photographs that show only the happy surface — may carry the story's later chapters.

**The scale (confirmed):**

| Item | Estimate | Note |
|---|---|---|
| Letters | **800+** | dated weekly accounts over a ~15-year run; envelopes; several pages each |
| Photographs (physical) | ~hundreds | to scan; thousands of digital photos (later generations) gated by human curation |
| Documents / ephemera | ~100s | certificates, cards, receipts, programmes |
| Heirlooms / objects | dozens | each needs a photo set + provenance story |

**Design target:** handle **10,000 items / 50,000 images** without architectural change. The timeline must render 800+ dated letters *densely but readably*.

**Current state:** the collection is physical; digitization has not begun. The PRD therefore includes a **capture workflow** (§7) as first-class scope, not logistics.

---

## 3. Goals & Non-Goals

### Goals
- **G1 — Engage:** a family member opens the app *unprompted* and stays. Driven by "today in family history", curated stories, and wander.
- **G2 — Orient:** any artifact findable in **≤ 3 taps** from the right entry point (timeline / people / places / story / search).
- **G3 — Remember:** the emotionally loaded artifacts are surfaced without being told twice — they become the first stories.
- **G4 — Capture with zero friction:** one person digitizes the full collection (thousands of items) with ≤ 30 seconds of effort per item.
- **G5 — Endure across generations:** the digital artifacts must outlast the app — and outlast everyone alive today (user requirement, 2026-08-02). The archive is a folder of plain, open, self-describing files; backup = 3-2-1 across households; the app is a replaceable lens. "Within reason": boring formats, no migration treadmill, no credentials needed to read the files (see §18).
- **G6 — Gather the stories, with no bottleneck:** narration is captured *with* capture from every actor who can contribute — including elders, prompted (perhaps with dementia). **No single narrator or techie is a bottleneck:** the app prompts, records, and runs on its own. Every artifact touched gets its line of story, its transcription where it matters, and the people get bios. The app must be self-explanatory to a stranger in ten years, with no narrator to ask.
- **G7 — Testimony is first class:** recordings, self-recordings, and typed accounts from the people who lived the story are first-class archive artifacts — attributed to the speaker, embedded and semantically searchable, and preserved the session they are told. The app never interprets; the actors testify (§19).

### Non-goals (v1)
- **No public sharing of anything whatsoever** — all access is family-only; the mechanism is TBD (accounts, §15).
- No social feeds; no public publishing.
- No destructive operations in the UI (no delete/edit of artifacts; corrections via "edit metadata", never delete).
- **The archive file store is append-only (requirement, 2026-08-03):** nothing in the underlying file store is ever edited or deleted — a change is a new file that *supersedes* the old one, and the old file stays forever. Mechanism in `TECH-SPEC.md` §3; tests enforce it via a fake filesystem that fails on any write to an existing file. **One documented exception (2026-08-05):** the proposed-queue reject path deletes the *proposed* record file — a transient review work item that has never been published, not an artifact; everything that has ever shipped stays append-only. Rejecting deletes the file so a refused proposal cannot linger as a proposed record.

---

## 4. Personas

| Persona | Who | Needs | Constraints |
|---|---|---|---|
| **The Curator** | The organiser who knows every box | Capture fast and frictionless; **narrate as you go**; tell the stories right | Not the only narrator — the app must never bottleneck on one person; all work on the phone (Android); minimal typing |
| **The Elders** | Living memory, possibly with dementia | **Reminisce with prompts**; contribute memories and stories in their own words; explore the past | The app prompts them; they are users, never a dependency; dementia-friendly: calm, large, one obvious path |
| **The Young Kids** | Children of the family — pre-readers and early readers | A **fun, exploratory experience now** — not just later | The app must be usable by kids and by people with dementia alike; no reading required to wander |
| **The Voices in the Archive** | The people who wrote the artifacts — the letters' writers, the document authors; the generic model covers any writer | The app lets them speak: transcription, dates, context | No interviews possible (dementia); fidelity is on the living narrators |
| **The Next Generation** | The family's children — the archive's future audience | Meet a grandparent they never knew, or a parent as a young person before children | Cannot tell us anything; the app must be legible with **no living narrator to ask** |

The load-bearing tension: **the same screens must serve a young child's wandering, an elder's prompted reminiscence, and a teenager's first encounter with strangers.** That means big type, one obvious path, zero hover-dependent UI, and — because narrators fade — *the stories must be written into the app itself*.

**Requirements, not design notes:** young kids and people with dementia alike must be able to use the app and have a fun, exploratory experience. Elders contribute through prompts and are never a dependency.

---

## 5. Jobs to Be Done

1. "When we have family over, I want to **show them** what our grandparents' courtship was like." → stories + timeline
2. "I want to **find that one letter** a grandparent wrote from [place]." → search/filter
3. "I want to **feel close to them again** on a quiet evening." → on-this-day, wander, timeline
4. "I want the **next generation to know their grandparents** — starting with the youngest." → cast pages + stories + bios
5. "I want to **know what's actually in the boxes** and not lose it." → catalog completeness, museum, backup
6. "I want the **people in the archive to keep speaking** after they can't." → transcription + narration + stories (G6)
7. "I want to **record the memories, stories, and commentary of the people involved** — including the elderly, perhaps with dementia — before they're gone." → testimony + prompting (G6/G7)
8. "Let a **child meet a grandparent they never knew**, when they're older." → cast + stories + testimonies
9. "Let kids meet the **younger, pre-kid versions of their own parents**." → the letters' era, timeline
10. "Let someone **with dementia reminisce about the past, prompted**, and explore it." → prompt-driven browse + testimonies
11. "Let the app **run and gather data with no techie in the loop**." → no-single-bottleneck requirement (G6)

---

## 6. Content Model

### Artifact types
| Type | Digitized as |
|---|---|
| `letter` | several pages; page scans in sequence, envelope/address first, postmark is an artifact; date, **sender and recipient** are both linked (≥2 people per letter) |
| `photo` | front + back (writing on back is an artifact); album page when relevant; **35mm slides** (lightbox capture — a common format for 1960s–70s travel) |
| `document` | certificate, card, receipt, programme, news clipping; **memoirs/manuscripts** (multi-page, sequenced like letters) |
| `object` | heirloom — 4–8 photos (overview, detail, maker marks, base/stamp) + provenance story |
| `ephemera` | tickets, labels, odds and ends |
| `audio` / `video` | real for testimonies (voice memos, self-recordings); other media future-proofed |
| `story` | **testimony** — audio recording, self-recording, or typed account, attributed to the speaker (an actor in the story), with transcription (propose/confirm); first-class: embedded, searchable, connectable (§19) |

### Fields (per item)
| Field | Required? | Notes |
|---|---|---|
| `id` | yes | auto-generated |
| `type` | yes | from the list above |
| `title` | yes | curator-written, shown large |
| `date` | yes | exact or approximate |
| `date_precision` | yes | `exact` / `month` / `year` / `approx` — the timeline respects this |
| `people[]` | no | person ids → powers Cast pages; links carry a `proposed` / `estimated` / `confirmed` status (2026-08-10: the human's guess, recorded verbatim with its basis, is the third status — R9) so the labeling assist can suggest without asserting |
| `places[]` | no | place names → powers Places + map |
| `themes[]` | no | story-building material |
| `source` | no | provenance of provenance: e.g. `Box 3 — "Letters 1966"` |
| `description` | no | a line of caption |
| `story` | no | **the narrated story** — the curator's telling, shown large; the heart of G6 |
| `sensitive` | no | flagged items (e.g. a medical record, a difficult document) are catalogued and searchable but surfaced only via explicit paths, never in on-this-day/wander; timing for younger readers is a family decision (see §15.11) |
| `provenance` | no | object story: owned by, given by, where it lived |
| `transcription` | no | letter text; toggleable in reader; **full-text search across transcriptions is pattern-discovery** — e.g. a health symptom across a large letter run surfaces the drift |
| `alt` | no | image alt text; the model proposes (propose/confirm), the curator edits — accessibility with the seam (user requirement) |
| `assets[]` | yes | `{kind, file, caption}` — pages in order, front/back, photo set |
| `status` | yes | `draft` → `catalogued` (drafts hidden from browse) |

### Precision dates are a product feature
Most photos say "1964, probably spring". Forcing a fake exact date corrupts the timeline. **Every date carries a precision flag**; the timeline draws approximate items at the start of their range with a subtle marker, and filtering treats them honestly.

### People and places are entities, not strings
Person records carry `name` (canonical), `aliases` (the forms the family uses — Mum, Mummy, Nana…), and a bio; place records carry `name`, coordinates, and street-view references. **Mention resolution** is the identity seam shared by import and reading: "Mum said…" in a transcription resolves via aliases to the person page, entering as `proposed` until confirmed. Names are content, not code — they live in `people.json`; IDs are stable and never renamed.

---

## 7. Capture Workflow (physical boxes → archive)

Because the collection is mostly physical, capture is a **core v1 flow**, not a back-office chore. It must be tablet-native and boring.

**The ritual** (per box): *Import → 3 fields → a line of story → done.*

1. **Import:** scanned pages arrive from the sheet-fed scanner (or digitized slides/photos); the app auto-sequences and auto-names (`letter-1963-05-14-01.jpg`); the user never types a filename. Envelope/address first, postmark included. **No general camera capture — nothing is photographed with a device camera; the phone scan app is the sanctioned exception for odd-sized originals (cards, fragile or non-feeder material) (amendment, 2026-08-02).**
2. **Three fields:** type (pre-set by "start new letter" flow), date (one tap calendar; "approx" toggle), title (suggested from date + type, editable).
3. **One line of story (encouraged, never blocking):** "She wrote at night, after shifts — this one is about the house hunt." Because every narrator fades, a sentence at capture time is worth a session of archaeology later. (G6)
4. **Done:** the item appears on the timeline *in the same session*. Curation debt (people, places, transcription) is deferred — nothing blocks capture.

**The curation gate:** nothing enters the archive uncurated — a human selects, then the app catalogs. Thousands of digital photos exist from the later generations; they are curated first, never bulk-imported. The same gate applies to the ML suggestion layer: nothing is asserted, everything confirmed. **Import resolves identity:** the same alias resolver the reader uses runs at import time — person and place mentions in transcriptions become links, entering as `proposed` until the family confirms. **Capture priority:** the letters are the first layer; the **memoirs** — a writer's later-life reflections on the earlier letters, covering periods the correspondence doesn't — are the archive's own narrator and join the letters at the top.

**Streamlined capture sessions.** The 30-second ritual becomes a session: import many items back-to-back, enter just the date per item — the app **suggests date+7 for weekly letters** — and batch-tag people/places/themes later. Title and the story line accept **speech-to-text** (Android Web Speech API), so nothing requires typing. Thumbnails and the derived index rebuild in-app; nothing blocks capture.

**Bulk scanning (sheet-fed + slide/photo scanners).** The bulk digitization path is scanners: a **sheet-fed scanner** for letters (per-page JPEGs, or one PDF per letter), a **slide/photo scanner** for slides and prints (the travel photography is on slides). Scanner output lands on a laptop; `tools/import` (Python) uploads it into the archive with auto-naming; tagging happens on the phone as usual. Scanner output is the only capture path (proper 300 DPI legibility).

**Quality floor (reading, not archival):** shortest side ≥ ~1500px, flat, daylight, no flash, lens parallel to the page. Originals are kept; the app derives thumbnails.

**Storage layout (the folder):**
```
archive/
  README.md              # written for a reader in 2060 — how to open this archive without any app
  assets/<id>/item.json  # canonical metadata per item (sidecar — one bad file loses one item, not the archive)
  assets/<id>/…          # originals + derived thumbs, open formats (JPEG/PNG)
  index.json             # derived index, regenerable from sidecars (the app's fast path)
```
The app is a viewer over this folder. **Backup = copy the folder.** No database lock-in. Sidecar-first, because the index is a convenience and the sidecars are the truth (§18). **Two surfaces, one archive (user constraints: work from the phone, store nothing heavy on it, host nothing in the house):**
- **The archive = Google Drive (its real home, not a mirror).** A dedicated family *Loft archive* Google account holds the folder — full-res scans, sidecars, transcriptions, derived files. The phone is a **thin client**: it captures and curates via the app, which talks to Drive through the official API (Google sign-in, PKCE). Nothing of the archive is stored on the phone — only browser cache. Nothing is hosted in the house.
- **The site = the family-only projection.** A free static host serves the app + the projection — metadata, thumbnails, stories (full-res placement TBD, §15) — generated by `loft publish` (Python, laptop step, pulls from Drive). **No access is public:** everything is family-only, mechanism TBD (accounts, §15). The app **never reads the Google Drive API at runtime** — all reading rides the projection; Drive is write/sync/backup only (§15).
- **Durability is load-bearing on export:** Drive holds the live archive; the **annual full export** (folder download + CSV) to a second household and external media is the 3-2-1's second and third copies (§18.6). Files stay plain and open — if Google ever changes terms, the folder downloads whole.

---

## 8. Information Architecture & Screens

Four doors + the lens:

```
                    ┌──────────────────────────────┐
                    │  HOME — "today in history"   │
                    │  wander · recent · the doors │
                    └──────────────────────────────┘
        ┌───────────────┬───────────────┬───────────────┐
        ▼               ▼               ▼               ▼
   TIMELINE          CAST (people)    STORIES         MUSEUM (objects)
   decade→year→week   face grid        curated         heirloom
   · filters          · person page    chapters        gallery
                      · mini-timeline  · reader mode   · provenance
        └───────────────────────────────┬───────────────┘
                                        ▼
                                ITEM DETAIL — the lens
                        zoom/pan · transcription · connections
                        · prev/next in context · search
```

| Screen | Purpose | Key behavior |
|---|---|---|
| **Home** | Front door | "This day in family history" moment (from exact-date items); wander button; recent additions; the four doors; search |
| **Timeline** | The spine | **Periods of ~20 entries, newest first** — a period is titled with its date range plus a theme hook when one keynotes it ("1917–1973 · The canal years"); **significant dates appear on the spine** — a person's birth/death (and a dated marriage) are derived life events, and attested happenings (a concert a letter mentions) are event items; filters: type / person / place / theme; precision-aware; counts are honest ("N periods, M items · K events"). Clarification fragments and reflections never appear here (they live on the pages they attest/mention) |
| **Cast (People)** | "Who is this?" | The tree opens on **you** (the narrator) when the app knows who's using it; cards show **how much family is beyond the current view** ("+N more") and **which person leads back to you**; person page: bio, known-as names, connection chips, decade bands, plus **Clarifications and Reflections blocks** for the fragments that mention them |
| **Cast (People)** | "Who is this?" | Face grid → person page: bio, known-as names, connection chips (places / stories / connected people), decade bands |
| **Places** | The geography | **Heatmap over time**: dot size ∝ activity in the slider window; a **timeline slider** (scrub the years) and a **person filter** (who you're tracking) — watch the geography of a life move; markers open place pages with the scrubbed window; place pages group the artifacts of each era; optional current street-view imagery for key locations ("a family home of the era — the street today"). **Scale-aware markers** (2026-08-03): the heat map stands alone at overview zoom — no dots, no labels (a dot at country zoom is a meaningless pixel and its label a blob; both obscure the heat). Dots appear from regional zoom, labels from street zoom, and a lone active place is always labelled; the cards below always list the active places. **A point is never presented as more precise than it is** (2026-08-05): an imprecise place (known only to a street/town/country) draws an uncertainty ring, not a pin. Place pages carry **Reflections** that mention them |
| **Stories** | Guided paths | Curated collections (**auto-suggested** from the archive's patterns, confirmed or edited by users; users can also create their own) with connective text; **reader mode** = page-turn swipe through the items; every story links its artifacts |
| **Museum** | The heirlooms | Object pages: big imagery, provenance narrative, detail shots |
| **Show mode** | Showing, not browsing | Full-screen, no-navigation browse for showing someone the archive — big images, large type, auto-advance; operable by anyone in the room; started from any person or story (../plans/PLAN.md Slice 3 — the urgent one: elders' memory is fading) |
| **Item detail** | The lens | Pinch-zoom scan viewer; **a description line under the title** (the "what is this" that tells a letter apart from the rest of its correspondence — it also renders, two-line clamped, on the cards); transcription toggle with **mention links** into the cast; connections (same people / place / ±1yr); prev/next within current sequence; **web-page documents hyperlink their sources with the access date** ("accessed 2026-08-05"); **Clarifications** that attest the item |
| **Search** | Find *that one letter* | Titles, people, places, themes, transcriptions; filterable results |
| **Curator** | Capture + edit | Scanner import, 3-field form, auto-naming; edit metadata of existing items; never delete |

**Connections at scale (everything → everything).** The entity graph is bidirectional: item ↔ person ↔ place ↔ theme, and entity pages carry counts-first chips for the other entity types. Full enumeration lives on the **Timeline via filters** (`?person=`, `?place=`), which is also the scale story: at 10,000 items no surface renders a raw wall of cards — decade bands, caps, and "see all" paths keep every page bounded (PRD §9 F2, TECH-SPEC §8). **Everything catalogued is visible somewhere** (2026-08-06): every item a reader can search for must actually render — on the timeline, or (for fragments/reflections) on the pages they attest/mention; guarded by the completeness eval (TECH-SPEC §4).

---

## 9. Key Flows + Acceptance Criteria

**F1 — On-this-day (the habit hook)**
- Given the app opens on Home, When today's date has any exact-dated item, Then a moment card appears ("52 years ago this week: a grandparent writes from…").
- Given the moment card, When tapped, Then the letter opens in the viewer with envelope visible.
- Given the viewer, When pinched, Then the page is legible at full zoom. When the transcription toggle is tapped, Then readable text overlays.
- Given the viewer, When "back" is tapped twice, Then Home again. (Never more than 2 taps to escape.)

**F2 — Find "the letters from 1964"**
- Given Timeline, When type=letter + year=1964 filters are set, Then week rows render with density counts.
- Given the filtered rows, When an item is tapped, Then its detail opens. **Total: ≤ 3 taps from Home.**

**F3 — Show a grandkid the courtship**
- Given Stories, When "The Courtship" is opened, Then reader mode starts.
- When swiping, Then pages turn in order with connective captions; exit returns to the story, not the grid.

**F4 — Find everything with Grandma**
- Given Cast, When Grandma is tapped, Then her page shows her items on a mini-timeline.
- When any item is tapped, Then detail opens. **Total: ≤ 3 taps.**

**F5 — Import a letter (≤ 30 s/item)**
- Given Curator → "New letter", When 3 scanned pages are imported, Then they auto-sequence and auto-name as one item.
- When date (one tap) + title are set and saved, Then the item appears on the timeline in the same session, status `catalogued`.

**F6 — Family-only access (replaces the PIN and the open projection)**
- Given a family member opens the site, Then they sign in (accounts — mechanism TBD, §15) and browse.
- Given no account, Then nothing is accessible — there is no public surface at all.
- There are no cookies, no analytics.

**F7 — A name in a letter becomes a person**
- Given a transcribed letter, When "Read the letter" is opened, Then alias mentions (Mum, Dad, Nana…) render as links into the cast.
- Given a mention is tapped, Then the person's page opens with their items, places, and connections. **Total: ≤ 3 taps.**
- Given an alias with no person record, Then nothing is linked — the text stays verbatim, and the import queue holds the suggestion (propose/confirm).

**F8 — The map opens the archive at the right time**
- Given the Places heatmap, When the timeline slider is scrubbed, Then the heat reflects activity in that window and the camera follows the active places.
- Given a glowing marker is tapped, Then the place page opens showing only the items in the scrubbed window (and filtered by the active person).
- Given the person filter is active, When a marker is tapped, Then the windowed items are filtered by that person.
- Given the Places heatmap at overview zoom, Then only the heat layer shows — no dots or labels; zooming in reveals dots, then labels, and a lone glowing place is always labelled (2026-08-03).

**F9 — The family reviews what the machine suggests** (2026-08-09, the import-review loop)
- Given the machine's suggestions awaiting review, When the family opens the review, Then the suggestions are walked one at a time, each about the specific person and relationship — never a question whose answer can't change anything.
- Given a suggestion, When the family answers with their honest confidence — "I'm sure", "I think so", "I don't know", "I think not", "definitely not" — Then each is handled the way the family means it.
- Given a recollection, When the family records it as a guess, Then exactly what they said, who said it, and when are kept — never a machine's version of their words, never a suggested reason.
- Given a statement that conflicts with what the archive already records, When the family makes it, Then the conflict is shown and settled before anything is accepted — the family can be wrong, and the archive catches it.
- Given a paused review, When the family returns to it, Then their decisions and the conversation are kept, and they can see what has been decided so far.
- Given a half-remembered statement, When the family shares it, Then the archive connects it to what it already holds and shows them what it found.
- Given the archive has found something relevant, When the assistant speaks, Then it uses what it found to ask and to verify — the assistant's words are its own, in the documents' terms ("in the war record, X is recorded as…"), never raw tool output injected into the conversation (2026-08-10, R3: the tools inform the conversation, they never lecture).
- Given the assistant's conclusion, When it points to resulting links, Then the family confirms each explicitly — recorded as a recollection or as attested — before anything is accepted.
- Given the family cites a source ("Mum said…", "Grandma used to…"), When the assistant asks about the recollection, Then it asks about the provenance ("did she tell you that personally?") rather than asking what was already said.
- Given the archive is working, When it is thinking or checking, Then its working is visible — no silent waits.
- Given a finished review, When it ends, Then it says what changed — accepted, recorded as a guess, kept aside, or removed — and what to do next.

**The review feature's requirements (R1–R10, agreed 2026-08-10 — the
consolidated user needs from every problem the review loop has hit):**

- **R1 — The review is a conversation with a hired genealogist, not a form.** The assistant reads as a professional researcher the family hired. The family never meets internal vocabulary — statuses (proposed/estimated/confirmed), "the import", "the link", process states — or third-person talk about "the reviewer".
- **R2 — Every claim names its evidence, the way a historian would.** When the assistant presents a proposed link, it names the specific source and presents one piece of evidence a historian would accept: a direct quote from a human's own words (a letter, a story, a recollection recorded verbatim) or a record that is evidence in itself (a birth certificate, a war record, a census, a grave marker). LLM output is never evidence; a paraphrase is never an attestation; "a note was made" is not an attestation; a draft transcription's sentence is not the document's own words. If the documents hold no evidence for the fact, the assistant says so plainly instead of implying one exists.
- **R3 — The assistant uses the archive to inform the conversation, never to lecture.** The assistant may look things up — documents, places, records — to ask better questions and to check what the family says. Raw tool output is never injected into the conversation; what the family sees is always the genealogist's informed words.
- **R4 — One question at a time; the walk always moves forward and concludes.** The review never re-asks a question the family already answered, never loops on the same link, and always reaches an end state — a decision or an honest "we'll leave it for another day". "I don't know" leads to a question about what the family does know, then to the options.
- **R5 — The family understands the consequence of every choice.** Options are offered in plain words that say what will happen: record as a fact, record as a guess (with the family's own words as the reason), leave for later, delete. Options that obviously don't apply are not offered.
- **R6 — Conflicts are surfaced first, and recorded when they're real.** If the family's recollection conflicts with the evidence, the assistant surfaces the conflict before anything is recorded, so the family can decide — or realise they're wrong. If a genuine conflict stands, the disagreement itself is recorded as part of the family record (within GEDCOM's limits, as a note) — never silently overwritten or dropped.
- **R7 — The transcript is exactly what the family saw, exactly once.** Every line — the family's words and the assistant's — is recorded verbatim, in order, without duplication. Refreshing, resuming, or re-rendering never duplicates or rewrites it. The model's internal reasoning and tool use are never shown to the family.
- **R8 — The family's words are never lost or replaced.** Anything the family says is preserved as they said it — never overwritten, never substituted.
- **R9 — The record reflects the family's certainty honestly, everywhere it travels.** A fact the family confirms is a fact; a guess is marked as a guess with the family's words and who said them; the machine's own guesses are never presented as facts. The exported family tree carries the same honesty: estimates are included with their evidence, never silently dropped and never presented as confirmed.
- **R10 — The review is resumable.** The family can leave and come back; the conversation continues from where it stopped, in a new walk, without losing the record of earlier walks.

---

## 10. The Engagement Layer ("really engaging" = time in the past, spent with feeling)

**Felt experience (the user's words): explorable and draws you in; never editorial.** The app is a place you wander into that pulls you deeper — and it never speaks for the artifacts. Every design decision below serves those two sentences.

| Feature | Tier | Why it earns its place |
|---|---|---|
| **On-this-day** | Must | The daily habit hook; letters have exact dates, so the well is deep |
| **Stories** | Must | The museum's curatorial voice; turns hundreds of letters into *a courtship* |
| **Wander** | Must | The shoebox feeling: one tap, random item, zero decisions |
| **Cast pages** | Must | The emotional payload — faces are what people say "oh!" about |
| **Letter reader** | Must | Page-turn + transcription toggle: artifact first, readability on demand |
| **Museum objects** | Must | Heirlooms with provenance = the "wow" gallery |
| **Archive stats** | Should | "You've seen 212 of 1,847 artifacts" — quiet completion pull |
| **Street-view place cards** | Should | The archive meets the living world: key locations show today's street view (public imagery only; family content stays local) |
| **Second-screen / TV mode** | Should | Gatherings: mirror to the TV; fits the private household model |
| **Show mode** | Should | The urgent one: familiar photos, shown now — elders' memory is fading (../plans/PLAN.md Slice 3) |
| **Map — heatmap over time** | Should | Places as a heatmap with a timeline slider and person filter — activity moving across geography as the years scrub; Leaflet/OSM tiles, degrades to the non-tile dot view offline |
| **Family "add a memory"** | Could | Others contribute captions for review — curation was initially single-person, so deferred |

Anti-patterns rejected: streaks, badges, leaderboards, push notifications. A family museum does not nag.

**Presentation is scrapbook-warm, not archival-clean** (PRECEDENT.md §2): rounded frames, handwriting-friendly type, quiet texture — warmth is a feature. **Stories are snackable** — 3–8 items, ~2–5 min to read — matching museum-guide attention budgets (§3). **Serendipity needs boundaries:** on-this-day must be dismissible per date, per person, per memory — the family has dates that are raw, and the D3-E privacy flags feed this control. **Tonal range is allowed:** some letters are funny; stories may be funny or sad, never flattened (§3).

**Themes are the doors, evidence is the room.** With 800+ items, arrangement alone drowns the reader — the app must *actively offer curated themes as the way in* (family-chosen doors: "The music years", "The business years"). Inside a theme, nothing is interpreted — dates, order, facts. **Stories are suggested, not only hand-made:** theme/entity discovery proposes collections from the archive's own patterns; users confirm, edit, or create their own — and every story links its artifacts. **Honesty principle:** the app arranges evidence; it never interprets it — no mood labels, no AI summaries, no "this is when it went wrong". **People testify; the app doesn't.** A narrator's account is testimony from an *actor in the story* — attributed, personal, multi-viewpoint — not editorial; the app presents it as evidence and never reconciles competing accounts into one (§19). **Display priority: facts and the artifact itself come first; the reader's own commentary next; other people's commentary last.** Honesty includes timing: sensitive items live in the archive now and surface when the family decides. **Default is no censorship:** flags are the deliberate exception, never the default; the sensitive-timing decision (doctor's letter and similar) is deferred until the full collection and a working prototype exist (§15.11). And no flattening: the happy photos stay warm, the hard truths stay present, neither erases the other. **Seed content follows the same rule:** theme copy and captions are factual; personal observations are attributed testimony ("The curator: …"), never app prose.

**The machine proposes; the family confirms.** Photo labeling (people, pets, boats) and theme/entity discovery are real asks from the curator — implemented as a *suggestion layer*: models propose labels with `proposed` status, the family accepts with one tap; nothing is asserted unreviewed. Letters are intimate, so the family chooses the privacy posture — the model runs in the mode they pick (the cloud vision model by default with a local-only mode available; the privacy posture is a mode, not a hard constraint — user, 2026-08-14). The schema ships the seam in v1; the models plug in later.

**Machine guesses are proposed, never published** (2026-08-09). The machine's suggestions exist for the family's review and never reach any public surface — nothing the machine guessed, however plausible, appears where anyone outside the family could see it. The family's review is the only door from a guess to the archive, and the archive's public face never shows a guess.

**The archive never claims more certainty than it has** (2026-08-09). Every record carries how sure the archive is — attested by the record, a family member's recollection, or the machine's guess — and the difference is visible wherever that information appears. A guess is never presented as a fact, a recollection is never presented as attested, and the family can always tell which is which.

**The archive never puts words in the family's mouth** (2026-08-09). It records what the family says, verbatim; it never fills in connections they didn't state. When the family is uncertain, that uncertainty is recorded — the archive's job is to hold their words and the evidence, never to improve on either.

**The assistant reads as a hired genealogist, not a computer** (2026-08-09). Every guided conversation — the review of the machine's suggestions, the capture prompts — reads like a friendly but professional genealogist the family has hired: someone DMing the family member and walking them through the paperwork, asking about the person or document the way a researcher would, and confirming the way a colleague would. The family is always talking to a person, never to a system: raw records, internal notes, and system states never appear in what the assistant says — the assistant speaks the family's language about the family's own archive.

### The principles, as learned (2026-08-05/06)

Overarching product principles that emerged from the first UX loop and the
import sessions — they bind every screen and every data decision:

1. **Precision is honesty.** The representation is only ever as precise as
   what attests it: a story's date is the events' date (never the telling
   day); a coordinate carries its granularity and draws an uncertainty ring,
   never a pin, when the point is coarser than the place; a link exists only
   where presence is attested (co-mention in a letter is not being there).
   "You can't know if the Lark Inn is precise or not without looking" —
   the interface never claims more than the evidence supports.
2. **The spine is the subject's time, not the capture's — and only family
   happenings.** The timeline places things by when they happened, not when
   they were told, scanned or saved; the capture stamps (recorded, accessed,
   created) are metadata, visible but never mistaken for the date. A web page
   is dated by its access day because *our capture* is the subject — and a
   found record (a web capture, a directory page) is not a happening at all:
   it attests the family's places, it never appears on the timeline. Neither
   does "died after 1917" sit at 1917 — a non-point fact stays on the person
   page. Someone in the family, reading the timeline, would recognise every
   entry as a thing that happened to the family at that time. **"The family"
   is the archive's own — the found family of the attic** (in-laws, friends,
   teachers, employers, the people the letters actually touch): content about
   them belongs on the spine exactly like blood relations. The exclusion is
   about *happenings*, never about literal kinship.
3. **A link is an assertion.** Every edge (person↔place, alias, identity)
   is attested by an item or the narrator's own words — never inferred from
   proximity. The graph's integrity is the archive's integrity.
   **The recognition test:** a person reading their own page would recognise
   every person and place as immediately relevant to their life — they'd
   have been to all the places, and the people are theirs. Co-mention in a
   letter or a 91-name listing is not being with: a person page shows
   attested relationships, never co-mentioned names.
4. **The reader sees finished statements, never process.** No "verification
   pending", no "open pile", no internal status in reader-facing prose —
   review state lives in the data. ("That should never happen.")
5. **Honest incompleteness is an invitation.** The walk's favourite line was
   "possibly in an unopened box"; the tree's "+N more" and "leads back to
   you" made partial views readable; dead buttons and disagreeing counts
   destroyed trust. Say what the archive can't show, and frame the gap as
   something to find — never as a deficiency, never silently.
6. **The archive is anchored to the reader.** The tree opens on you; the
   path back to you is marked; the narrator is the coordinate system. A
   family archive's "you" is a first-class concept, not a design nicety.
7. **Every narrator utterance is a kind of truth with its own place.** An
   account is events (the timeline), a clarification is identity (the pages
   it attests), a reflection is perspective (the people it mentions). The
   archive distinguishes what happened, who was who, and what we think —
   and each appears exactly where it belongs.

---

## 11. Non-Functional Requirements

**Devices:** Android-first — the phone is the primary **curation** surface; any modern tablet/phone browser for browsing (no iOS requirement). Landscape + portrait. PWA installable ("Add to Home Screen").

**Performance (at 10,000 items / 50,000 images):**
- First meaningful paint ≤ 2 s on 4G; initial JS/CSS payload ≤ 100 KB (vanilla-first stack; a small JS/CSS library is allowed if it degrades well — decision recorded in `TECH-SPEC.md` §15).
- Scrolling at 60 fps; images lazy-loaded as thumbnails, full-resolution swap on open.
- Index loads incrementally (decade/year segments), never one giant fetch.
- Runtime reads ride the family-only projection only — the app **never reads the Google Drive API at runtime** (curator *writes* use the API; full-res placement TBD, §15). The phone stores nothing.

**Offline:** service-worker cache of everything after first visit (Should — home wifi assumed, gatherings are not).

**Touch ergonomics:** targets ≥ 44 px; pinch-zoom on scans; consistent back (top-left + edge swipe); no hover-dependent UI; visible focus; no destructive actions.

**Accessibility:** body type ≥ 17 px, adjustable; WCAG AA contrast; **alt text proposed by the model (propose/confirm) and curator-editable**; `prefers-reduced-motion` respected.

**Privacy:** **no public sharing of anything whatsoever** — all access is family-only; the mechanism is TBD (accounts, §15). Zero analytics. The app **never reads the Google Drive API at runtime**: all reading rides the family-only projection; Drive is write/sync/backup only (§15).

**Durability:** archive = plain files, open formats; per-item sidecars; a README written for a reader in 2060; backup = 3-2-1 with a copy in a second household; **the folder outlives the app — the app is disposable by design (see §18).**

**Resilience — append-only writes are the mechanism (user, 2026-08-07):** a change never overwrites an existing record; it writes the next version. That minimises the blast radius of corruption (a partial or bad write is contained to one version file, and the prior version always survives for recovery) and makes troubleshooting possible (diff any two versions to see exactly what changed, when). The version chain **is** the archive's troubleshooting record — never delete, squash, or "clean up" intermediate versions.

**Long-term readability — plain text, complete snapshots (user, 2026-08-07):** every version is a complete, human-readable table — no deltas, no replay engine, nothing that needs the app or a toolchain to understand. The projection the app serves (`app/data`) is the derived snapshot of the newest version; the chain is the history. When the chain and the projection disagree on size or cleanliness, readability and completeness win: the chain grows by one small text file per change, and git already compresses them. This is the explicit rejection of event-sourcing-style delta storage or snapshot compaction — those trade the 2060 reader's ability to open any version with a text editor for space, against §18's rules.

**Weekly integrity check (user, 2026-08-08):** the live product runs the archive-quality integrity tests — the archive evals (`tests/test_*`: attested edges, descriptions, place notes, story dates, completeness, content language, family membership, projection drift) — **weekly against the real archive**, on the family's running instance. A failed check is family data needing a fix (a supersede, a retranscription, a reconciled edge), never a test update; the same evals skip in the public repo's CI because the dataset never ships there (docs/testing-standards.md).

---

## 12. Roadmap (MoSCoW)

| Priority | Items |
|---|---|
| **Must (v1)** | Timeline (decade→year→week, filters, precision-aware) · item viewer (zoom, transcription, connections) · Home with on-this-day · wander · Cast pages + **person bios** · search · letter reader · capture workflow (**scanner import**, auto-naming, 3-field form, **story line**) · **story/narration fields** · **preservation rule** (nothing told is lost — testimonies land in the archive the session they're told, §19) · static deploy · responsive layout |
| **Should** | Stories + reader mode · Museum object pages · PWA offline · archive stats · second-screen/TV mode · **map as a first-class door** (peer to timeline / theme / person) · bulk metadata editing · import of already-scanned files · **memory controls** (dismiss a date / person / memory from on-this-day) · **sensitive-item handling** (flagged items excluded from serendipity; family-set timing) · **accounts** (family-only access — mechanism TBD, §15) · **ML photo labeling** (faces, pets, boats — machine proposes, family confirms) · **OCR of letters and documents** (drafts via the seam) · **story auto-suggestion** (collections proposed from patterns; confirmed or edited; users create their own) · **alt-text generation** (model proposes, curator edits) · **story-harvest mode** (record / self-record / type; story-anchor prompts; attribution to the speaker; transcription drafts) · **audio playback** (hear recorded testimonies) · **semantic search** over testimony embeddings · **Show mode** (full-screen showing: large type, auto-advance) · **proposed-status UI** (machine suggestions visibly marked until confirmed) |
| **Could** | text-to-speech (hear a letter read aloud) · family "add a memory" with review · print/PDF album export · **age filter on artifacts** (very late stage; how user ages are established is TBD, §15) — **no genealogy tooling** (records, census workflows, homework — the documented anti-pattern, PRECEDENT.md §1; a person-centred family-tree view is in — PRECEDENT.md §5) |
| **Won't (v1)** | Public sharing of any kind · social feeds · ML models in the shipped v1 (the seam ships; models plug in later) · **unreviewed ML output** (no asserted labels, transcriptions, stories, or alt text) · destructive editing |

---

## 13. Success Metrics

| Layer | Metric | Target (direction) |
|---|---|---|
| Activation | App opened at ≥ 1 family gathering/month | ↑ |
| Engagement | Median session ≥ 3 min; items viewed/session ≥ 3; wander sessions ≥ 1/family member/week; story completions | ↑ |
| Content | Items catalogued; % with complete 3-field minimum; transcriptions/week | ↑ (letters first) |
| Durability | Backup copies exist in two households (3-2-1), checked quarterly; **the 2060 test passes** — the archive is understandable with no app at all | ✓ |
| Qualitative proxy | "Did someone tell a story unprompted?" — proxied by session length + story completions + TV-mode use | ↑ |

---

## 14. Risks & Mitigations

| # | Risk | Mitigation |
|---|---|---|
| R1 | **Digitization backlog** — a letter run in the hundreds, several pages each | Capture is a v1 core flow; the app is fully usable while the catalog is partial; letters first, photos second; "reading quality" is the floor, not "archival quality" |
| R2 | **Metadata burden** vs. "minimal effort" | 3 required fields, auto-naming/auto-sequencing, suggestions; defer people/places/transcription; batch tools in Should |
| R3 | **Handwriting legibility** | Scanners are the only capture path (300 DPI, §7 — no device camera); OCR drafts via the seam; transcription for the emotionally loaded letters first |
| R4 | **Timeline density** — a large run of dated letters | Decade/year/week aggregation is designed from day one, not retrofitted |
| R5 | **App longevity** | Folder-first data, open formats, no toolchain lock-in; the lens is replaceable by design |
| R6 | **Privacy breach** (letters are intimate) | Archive-account authentication, no analytics; sending material to a third-party model for transcription is a family-chosen mode (cloud vision model by default, local-only available — user, 2026-08-14) |
| R7 | **Effort stalls after week one** | Capture ritual is 30 s/item; visible progress (stats, timeline filling) is the motivation |
| R8 | **Story loss deadline** — the narrators fade; every stalled month loses fidelity | Story/narration is captured *with* capture (G6); letters first (they are the voices); the discovery plan (§17) front-loads the story harvest |
| R9 | **Physical deadline** — the physical collection is being cleared (a sale, a move); the schedule belongs to the family, not the project | Capture competes with the clearing: sampling happens as items surface; a family collaborator is in the loop (D5); digitize letters first — they are the irreplaceable layer |

---

## 15. Open Questions (from the interview)

1. **App name — RESOLVED (working):** *The Loft* (user approved, 2026-08-02); revisitable before launch.
2. **Hosting — RESOLVED (user, 2026-08-02; revised):** Google Drive (dedicated family archive account) **is** the archive's home, accessed via the official API — the phone is a thin client, nothing stored on it, nothing hosted in the house; a free static host serves the app + a family-only projection (metadata/thumbnails/stories, no full-res); annual export to a second household and external media is the durability ritual. **Cousins:** invite-able later via the accounts mechanism; per-contributor folders / a merge tool is the seam (not built now, not ruled out).
3. **Photo volume — RESOLVED:** hundreds of physical photos to scan; thousands of digital photos exist (younger family members) but are **human-curated before import** (curation gate, §7).
4. **Audio/video — RESOLVED:** some recordings likely exist but probably unrecoverable; **BBC archive is a research lead**; the schema stays future-proofed.
5. **Back-of-photo writing — RESOLVED:** happens but rare → capture default is front-first; back captured when writing is noticed.
6. **TV/second-screen mode — RESOLVED (via plan):** yes — gatherings are the activation metric; Show mode (Slice 3) and TV mode (Slice 6) are planned in `../plans/PLAN.md`.
7. **Technical appetite — RESOLVED (user, 2026-08-02):** vanilla-first, no framework; a small JS/CSS library is allowed if it degrades well; revisit during development if the code gets messy (recorded in `TECH-SPEC.md` §15).
8. **Secondary narrators — OPEN:** a family member is the physical collaborator for the clearing-out; do others hold stories worth harvesting?
9. **The elders and the app — RESOLVED (via plan):** yes — elders may be shown familiar photos, via Show mode (`../plans/PLAN.md` Slice 3); the family decides when, and it is never a dependency. (Sensitive; see §4.)
10. **Private letters** — are any letters/items not for the future user's eyes (e.g., while he's a child), and should the app support per-item privacy flags? (Currently everything is household-private; this is about *within*-family boundaries over time.)
11. **Sensitive-item timing — DEFERRED (decision recorded):** anti-censorship is the default; sensitive items stay catalogued and searchable; *when* they surface for younger readers is decided at prototype stage with the full collection in view (user, 2026-08-02).
12. **ML appetite & hosting — RESOLVED (user; revised 2026-08-14):** photo-labeling (people/pets/boats), theme discovery, and **handwriting OCR for transcription drafts** are wanted; the transcription default uses the vision model (cloud), with a **local-only mode** available when desired (the privacy posture is a mode, not a hard constraint — user, 2026-08-14); imperfect suggestions are accepted with family confirmation (the propose/confirm seam).
13. **Accounts — TBD (required):** family-only access needs accounts; the mechanism is undecided — per-person roles, how ages are established, how elders get in without friction.
14. **Runtime Drive reads — placement TBD:** the app never reads the Google Drive API at runtime; confirm where full-res lives (family-only projection vs archive account) so no read path depends on Drive.
15. **Age filter (late stage):** optional age-filtering of artifacts; establishing user ages is TBD (likely via accounts).
16. **Vague or unknown dates on the timeline and map — OPEN (2026-08-03).** Interview answers and artifacts often carry vague dates ("Ruzia, around the same time"; "probably spring"). The timeline has date_precision; how the map's slider window and the timeline place *vague or unknown* dates — honestly, and never silently excluded — needs a decision. The map should also gain explicit modes: show **all places in the database**, or **a range of dates**, or **a subset of people** (the person filter and slider exist; a true all/range mode does not), and ideally **remember where a returning user was looking last**. (Recorded 2026-08-03 — not built now; the first-visit map default already shows the whole archive.)

---

## 16. Assumption Log

Family-instance facts (names, dates, exact counts, who has what) are recorded in the private interview records; this log holds only generalisable assumptions.

| # | Assumption | Status |
|---|---|---|
| A1 | The collection is large — a letter run of 800+ dated items, envelopes, several pages each | Confirmed (user) |
| A2 | Collection mostly physical; nothing digitized yet | Confirmed (user) |
| A3 | Curation by one person, minimal effort | Confirmed (user) |
| A4 | Family-private; no sharing outside the family | Confirmed (user) |
| A5 | Multiple devices, web access | Confirmed (user) |
| A6 | Photographs comparable in volume to letters; heirlooms dozens | Open |
| A7 | Static-file architecture (folder = archive) is acceptable | Open (recommended) |
| A8 | Scanners are the only capture path — no device camera; 300 DPI is the quality floor | Confirmed (user) — v0.9 · amended 2026-08-02: phone scan app allowed for odd sizes |
| A9 | Family gatherings want a shared screen | Open |
| A10 | Elders' memories fade; told stories are time-bound — capture via prompts while possible | Confirmed (user) — v0.9 |
| A11 | The youngest family members are children now; the archive's future audience arrives over a decade | Confirmed (user) |
| A12 | Multiple narrators exist (siblings; elders can contribute via prompts); no single-narrator bottleneck | Corrected (user) — v0.9 |
| A13 | The artifacts themselves are the primary "voice" source | Design conclusion (v0.2) |
| A14 | The core run is voluminous and near-repetitive; the emotional register lived outside the record (calls never captured) | Confirmed (user) — v0.3 |
| A15 | The story lives in accumulation and pattern, not individual showstoppers | Design conclusion (v0.3) |
| A16 | Post-run witnesses: account ledgers, a medical letter, standalone notes, photos (happy surface only) | Confirmed (user) — v0.3 |
| A17 | The physical collection is being cleared (a sale, a move); items still arriving | Confirmed (user) — v0.3 |
| A18 | A family member is the physical collaborator (secondary-narrator candidate) | Confirmed (user) — v0.3 |
| A19 | A key writer's professional life is richly documented — a sensory anchor (recordings?) | Confirmed (user) — v0.3 |
| A20 | Recurring visual motifs and objects across the collection become ready-made first stories | Confirmed (user) — v0.3 |
| A21 | Some artifacts are known to exist but not yet found — named search targets for the digitiser (e.g. a professional portrait, slides) | Confirmed (user) — v0.3 |
| A22 | Handwriting OCR is feasible for drafts; human correction is expected (Should) | Confirmed (user) — v0.3 |
| A23 | Future direction: younger generations' artifacts interleave into multi-person overlapping stories (model seam already supports it) | Stated direction (user) — v0.3 |
| A24 | **Memoirs exist** — a writer later reflected on the earlier letters, covering periods the correspondence doesn't: the archive's own narrator | Confirmed (user) — v0.4 |
| A25 | Thousands of digital photos exist from later generations; human-curated before import (curation gate) | Confirmed (user) — v0.4 |
| A26 | Back-of-photo writing is rare → front-first capture default | Confirmed (user) — v0.4 |
| A27 | Recordings likely exist but probably unrecoverable; broadcast archives are a research lead | Confirmed (user) — v0.4 |
| A28 | Narration is testimony from an actor in the story, not editorial — attributed, multi-viewpoint; other actors may testify | Confirmed (user) — v0.6 |
| A29 | Testimonies get embeddings — first-class, semantically searchable artifacts | Stated direction (user) — v0.6 |
| A30 | Names/aliases are first-class identity; mention resolution links transcriptions to people; the canonical cast is recorded in the private interview records | Confirmed (user) — v0.7 |
| A31 | Accounts required (family-only access; mechanism TBD); no public sharing of anything; the app never reads Drive at runtime | Confirmed (user) — v0.9 |

---

## 17. Discovery Plan (v0.2 — adapted to constraints)

Discovery is the first roadmap phase, before v1 scope is final. Instruments live in `DISCOVERY.md`. Constraints folded in: elders contribute via prompts; the youngest users are children; no single narrator.

| # | Step | Method | Yields | Who |
|---|---|---|---|---|
| D1 | **Box sampling & inventory** | Sample boxes **as they arrive** (the clearing-out is live); inventory types, dates, gaps, condition, envelope/postmark/back-writing | Honest scale + structure; capture defaults | You + family (I provide the sheet) |
| D2 | **Effort math** | Time one letter end-to-end at real pace; multiply by the sampled run | The #1 product constraint; drives automation vs. patience | You |
| D3 | **Story harvest — curator interview** | Deep interview (record kept private; script: `DISCOVERY.md` §3): narrative arc, cast, places, anchors | The transcription layer's raw material — irreplaceable | You + me |
| D4 | **Artifact mining** | Read a sample of letters as *voices*; extract themes, names, places, arcs | Story seeds for the first collections | Me, from your captures |
| D5 | **Secondary narrators** | Light interview with the family collaborator (confirmed) [OPEN §15.8] | Any other living stories | You/I |
| D6 | **Contextual observation** | Watch the current ritual — how the family shares these things today | Where the product must slot in; moment-ready design | You |
| D7 | **Precedent scan** | FamilySearch, Google Photos, museum apps; the anti-pattern is "metadata homework" (notes: `PRECEDENT.md`) | Avoided mistakes; pattern language | Me |
| D8 | **Prototype with real artifacts** | Clickable prototype + 20–30 real captures; test with whoever's available — **underway**: review walks have landed (heatmap + map, editorial scrub, names, connections) | Legibility (R3), emotional response, navigation | You + family |
| D9 | **Future-user legibility review** | Role-play the 15-year-old: can a stranger understand every screen with no narrator? | The G6 test | You + me |
| D10 | **Longitudinal check** | After 2–3 weeks: did you return? Is the harvest cadence sustainable? | Real engagement signal; resets scope expectations | You |

**Sequencing:** D1 → D2 → D3 first (they shape everything). D4 and D7 run in parallel with D5–D6. D8 needs real captures, so it follows the first capture session. D10 gates the roadmap, not v1.

---

## 18. Generational Longevity (G5 — the requirement)

**The requirement (user, 2026-08-02):** the digital artifacts must last generations — "at least the digital artifacts do, even if the app doesn't make it." Within reason.

**The contract:** the archive outlives the app; the app is disposable by design.

**Rules:**
1. **Open formats only.** JPEG/PNG for images; JSON + UTF-8 text for metadata; plain text/markdown for transcriptions, memoirs, and stories. Nothing proprietary, nothing that needs a license or a living company.
2. **The archive is self-describing.** A `README.md` at the archive root, written for a reader in 2060: what this is, who these people are (one line each), how to open every file without any app.
3. **Privacy and control.** Family content stays private to the family and under their control — achievable without on-prem hosting knowledge (buying a backup disk is enough). Mechanism TBD (accounts, §15); nothing is public.
3b. **Recoverable without credentials.** All data — including metadata — must be recoverable without any credential, maximising the chance that someone can recover the whole system, or something approximating it.
4. **Sidecar-first metadata.** Canonical metadata lives in `assets/<id>/item.json`; one corrupt file loses one item, never the archive; the index is derived and regenerable.
5. **Stable IDs.** An ID never changes; people, places, and story references point at IDs, never at app state.
6. **Backup = 3-2-1, export-driven.** Drive holds the live archive (copy 1); the **annual full export** — folder download + CSV — goes to a second household and external media (copies 2–3, off-site by definition). The export ritual is load-bearing: it is the guarantee that the archive never lives only in one service. The letters and memoirs are the irreplaceable layer.
7. **Human-readable export.** A CSV/plain-text export of all metadata and transcriptions is part of the backup ritual — readable by any spreadsheet or text editor, forever.
8. **"Within reason" boundary.** No format-migration treadmill, no exotic archival storage, no encryption that can lock out descendants. **No proprietary dependency:** the archive lives in Google Drive (the family's choice) but only as plain, portable files — the annual export ritual guarantees it is never trapped in the service. Boring formats that have already outlived decades.
9. **The 2060 test.** Someone who has never seen the app can open the archive and understand it. If they can't, it's not done.

---

## 19. Story Harvest & Testimonies (G7 — the productized interview)

**The insight (user, 2026-08-02):** a narrator's account is not editorial — it is **testimony from an actor inside the story**. The narrators are the people involved — the curator, siblings, and elders, who contribute through prompts (perhaps with dementia): the app never bottlenecks on a single narrator. Other actors have the same standing to record their memories and feelings about any artifact. The app never interprets (the honesty principle, §10); **people testify**. This also honours the hole at the center: recorded voices are the closest the archive can come to the conversations that were never recorded.

**The mechanism — harvest mode (Should):**
1. **Capture, any form:** record a voice memo on the phone, self-record, or type — on any item or person. Story-anchor prompts productize the session-1 interview: "What do you remember about this? Who else was there? What happened next? How did you feel?"
2. **Attribution:** every testimony carries `speaker` (a person id — an actor in the story), `kind` (`audio` | `text`), `recorded` date, and links to the items/people it is about. Voice gets a transcription (machine draft, propose/confirm — the same seam as OCR).
3. **Status:** `proposed` → `confirmed`, exactly like every other contribution. Nothing is asserted unreviewed.
4. **Preservation rule (Must): nothing told is lost.** Every testimony lands in the archive the session it is told. The seed is this session's interview record (kept private) — the source of truth until the app ingests it.
5. **First-class artifacts (G7):** testimonies are artifacts like any other — ids, metadata, connections, embeddable into themes and stories. **Embeddings** are derived for them (`embeddings.json`, regenerable) so semantic search works ("what did people say about this place?") and the ML seam has its first real corpus.
6. **Multi-viewpoint:** the same event may carry several actors' testimonies — the archive interleaves them (A23) and never reconciles them into a single account. The app arranges them side by side; the reader assembles.
7. **Display order:** facts and the artifact first; the reader's own testimony next; other people's testimony last (§10).

**Seed pass:** the session-1 harvest becomes the first real content — cast bios, the museum's three, the flagship story. Partly in the prototype already; the private record is the source of truth.

**Interview-module requirements (2026-08-03, from the session-1 harvest):**

1. **Authentic voice vs. family harmony.** The narrator spoke as if in a private conversation; judgemental remarks were edited or omitted before storage ("being a bum", "after a fight with mum", "a sexist ass", "consistently very mean to"). The tension is real: the archive wants the authentic voice, and it must not start family arguments. The harvest flow must include a narrator review pass before anything is stored — capture fully, then let the narrator approve or redact.
2. **Testimony provenance (OPEN).** Distinguish, at capture, what is evidenced (artifact-backed), what is first-hand experience, what is commentary, what is a guess about what happened, and what is second- or third-hand testimony. Decide whether interviews should probe for this and how the archive marks each.
3. **Descriptions of artifacts (OPEN).** Answers often describe artifacts (the doctor's letter, slides of giraffes, viola trophies). Decide what to do with such descriptions — especially for artifacts that may never be found. A description of an artifact that is never found is still useful: it is testimony that the thing existed. The prototype models it as its own item (`doc-doctor-letter-2009`, "not yet located") that links back to its description when the artifact turns up.
4. **Questions surface where they are relevant.** Interview answers link to the people/places/themes they name, so each answer appears on those entities' pages — a question about the places is reachable from the Places door.
5. **Prod for dates (2026-08-03).** Answers often leave dates vague — the harvest flow should prod for dates, and record precision honestly when the narrator cannot say (PRD §6). How the timeline and map treat vague or unknown dates is open (PRD §15).
6. **Broader place identification (2026-08-03).** Informal or referential place names are place candidates, not just proper names — a local landmark, or a family's nickname for a structure, is a place. The import worksheet and any future ML extraction should catch them.
7. **Places with uncertain locations (2026-08-03).** A place may be identified but not located — identification and location are separate facts; approximate coordinates plus a "location uncertain" marker; refine later. **Ask the narrator in the interview** when a place's location is uncertain — they may be able to clarify (but may not). **Locations must be exactly correct wherever possible** (2026-08-03): geolocations are geocoded, never guessed — exact postcodes via postcodes.io, named places via Nominatim/OSM, and each place records its geocoded source. **No vague locations lying about** (2026-08-03): a county-, country- or continent-level place stays only while an artifact evidences it independently of any more specific place, is marked by a structured `precision` field (never process prose in the note), and is dropped once specific locations replace it — e.g. the Chenzou letters may pin real cities, and then the Chenzou place is removed and items relink to the specifics.
8. **Ask who was present (2026-08-03).** Group artifacts get people attributed by inference — and inference has been wrong: a person was once "proposed" as present at an event that predates their birth. The harvest flow should ask who was actually there when an artifact involves several people or spans years — dates or ages would catch such cases (req 9).
9. **Politely discover dates of birth and ages (2026-08-03).** Birth dates disambiguate presence by date and anchor the timeline; the interviewer may ask, politely, and record what is offered — nothing is required. `dob` is an optional schema field (§4) waiting on this.
10. **Politely discover pronouns (2026-08-03).** The person's own statement is the gold standard; archive text by others is weaker evidence; nothing is guessed. The interviewer may ask, politely, and the person page shows what is attested.

---

## Appendix A — Reusable Interview Guide

Run this with anyone who matters before building. The primary narrator is the curator (elders contribute via prompts; the youngest users are children). Full instruments: `DISCOVERY.md`.

**Method rules**
1. Ask for stories, not features — "Which letter would you show the next generation first?" (features fall out of the answer).
2. Facts come in lists — counts, spans, formats — they set the scale, which sets the architecture.
3. Listen for emotional anchors — they become the first curated stories.
4. Watch, don't ask, for ease of use — observe, don't interview, the tablet.
5. End with durability — who keeps this in 10 years, and in what form?

**Question bank (curator/story-bearer)**
- *Collection:* types + counts; date spans and gaps; what's digitized and at what quality; do letters keep envelopes/postmarks, photos keep back-writing; non-paper items (reels, cassettes, heirlooms)?
- *Story:* who wrote to whom, and the arc; the 3 objects you'd show a stranger first; what a child should understand about their grandparents in 5 minutes; recurring places; the letter that makes you stop.
- *People:* siblings/cousins who hold stories [OPEN]; how the collection is used today (solo, guests, holidays); private letters not for young eyes.
- *Feelings:* the feeling someone should leave with; guided paths vs. open wandering; would "this day in family history" pull you back in.
- *Constraints:* which tablet(s); offline need; who sees what; who tags and where; who keeps it in 10 years.
