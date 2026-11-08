# Project Plan — The Loft

- **Status:** v0.1 — approved shape, sequencing open to adjustment
- **Status update:** Slice 1 delivered — the inventory's
  "built" rows now run on the real archive; Slices 2 and 4 partially
  landed, 3/5/6 unstarted (per-slice status under Phase 2).
- **Current work:** the remaining work on the active subset lives in
  `WORK-PLAN.md`; the target store's failing-test list is `WORK-PLAN.md` §5;
  the folder's map is `README.md`.
- **Date:** 2026-08-02 · Companion to `docs/PRD/PRD.md` v0.6 and `TECHSPEC.md` v0.2

## The urgency

Dad's dementia is worsening, and the house is being sold. The plan is ordered
by **time to value**: capture the irreplaceable first — the scans, the
transcriptions, the stories — before any ornamental functionality. Every slice
ships something usable that week, on the real collection, not the fake one.

## Principles

1. **Thin vertical slices.** Each slice is a narrow but *real* path, end to end —
   never a horizontal layer (all models, then all views). No stubs.
2. **Time to value.** A slice is done when it's usable on the phone, not when
   it's complete.
3. **Capture first.** The irreplaceable layer is the scans and the told
   stories. Digitization outranks features.
4. **Real data from slice 1.** The fake prototype data moves behind a demo
   flag the moment real items exist.
5. **Green every slice.** Lint + typecheck + tests pass and the browser walk
   confirms the slice before the next begins.
6. **Framework decision is revisitable** if a slice gets messy (`docs/TECHSPEC/01-foundations.md` §2).

## The shape

| Phase | What | State |
|---|---|---|
| 0 | Docs (PRD/TECHSPEC/records), scaffold, prototype with fake data | **Done** |
| 1 | **Import flow sketch** — design of capture → archive → app (TECHSPEC §16 + worked example) | **Reviewed via the import interview (2026-08-05)** — the flow spec is `docs/PRD/IMPORT-PRD.md`; TECHSPEC §16 is the normative home |
| 2 | Slices 1–6, each shippable | Slice 1 delivered; 2–6 per sequencing |

## Feature inventory (prototype → real)

Everything the prototype already does is accounted for below — nothing is lost
between the demo and the real app. "Carried by" names the slice that takes it
from fake-data demo to real-archive feature.

### Built in the prototype (carry on real data)

| Feature | Status | Carried by | Notes |
|---|---|---|---|
| Home — moment card, wander, doors, search box | built | Slice 1 | works on the projection; needs only real data |
| Timeline — year bands, type / person / place filters | built | Slice 1 | 10k virtualization in Slice 6 |
| Item lens — zoom, transcription toggle, mention links, connections | built | Slice 1 (+4) | pattern discovery already live; OCR drafts feed it in Slice 4 |
| Cast & person pages — bios, known-as, connection chips, decade bands | built | Slice 1 | |
| Stories — theme doors, curation notes, reader mode | built | Slice 1 (+4) | testimonies feed it in Slice 4 |
| Museum — object gallery | built | Slice 1 | |
| Places — Leaflet/OSM heatmap, slider, person filter, window travel | built | Slice 1 | tiles need internet; street-view card is a stub (Slice 6) |
| Search — full-text incl. transcriptions | built | Slice 1 | semantic search (embeddings) in Slice 4 |
| First-class people — names, aliases, mention resolution | built | Slice 1 | the alias resolver *is* the import seam |
| Everything-to-everything — aggregated connections, timeline filters | built | Slice 1 | integrity test guards it |
| Design system — scrapbook-warm, 44px targets, focus, reduced motion | built | carry-through | accessibility pass in Slice 6 |
| Fake-data demo flag | built | Slice 1 | real archive replaces it |

### Partial, stubbed, or designed-only (owned by a slice)

| Feature | Status | Owned by | Notes |
|---|---|---|---|
| Curator mode | **stub** | Slice 2 | the remote upload path is the slice's core |
| proposed/confirmed UI | partial — the import review chat confirms proposed people; proposed/estimated still render flatly (per-card R12 open) | Slice 2 | proposed links render like confirmed today |
| Sensitive flags | data-only | Slice 5 | field exists; no UI uses it yet |
| Memory controls (dismiss date/person/memory) | not built | Slice 5 | |
| Testimony recording (voice / self-record / type) | designed (§19) | Slice 4 | |
| Browse-side story & fact capture ("Add your memory") | **live** (text — `app/memories.js`, `tools/memory.py`) | Slice 4 | AI-elicited interview; text v1 (audio stays Slice 4) |
| OCR-assisted transcription | **live** — drafts + the review surface + self-report flags | Slice 4 | drafts via the propose/confirm seam |
| Semantic search (embeddings) | not built | Slice 4 | |
| Street-view cards | **stub** | Slice 6 | embed/static images, graceful offline |
| PWA / offline | not built | Slice 6 | |
| TV / second-screen mode | not built | Slice 6 | |

## Phase 2 — Slices
### Slice status

| Slice | Status |
|---|---|
| 1 — The capture pipeline, end to end | **Delivered** — real archive (the adopt batches), import, transcription drafts + the review surface, publish |
| 2 — Phone capture & curation | **Partial** — Google sign-in (`tools/auth.py`, PKCE) and the import review chat (proposed → confirmed) are live; curator mode is still the stub (`app/views/curator.js`); the remote upload path and phone capture sessions are unbuilt |
| 3 — Show mode for Dad (and gatherings) | **Not started** — no `#/show` route |
| 4 — Testimony at scale | **Partial** — OCR transcription drafts (+ self-report flags) and the story-capture flow (`app/memories.js`, `tools/memory.py`) are live; voice recording and semantic search (embeddings) are unbuilt |
| 5 — Trust & continuity | **Partial** — the nightly export and backup exist; memory controls and the sensitive-flag UI are unbuilt |
| 6 — Scale & polish | **Not started** — no service worker, TV mode, or 10k virtualization |


### Slice 1 — The capture pipeline, end to end
- **Value:** the first box of real letters digitized *now*; real items in the
  app this week; the whole browse surface (Home, Timeline, lens, Cast,
  Stories, Museum, Search, heatmap, mention links, connection graph) stops
  being a demo and starts being the archive.
- **Carries:** every "built" row above — real data replaces the demo flag;
  the alias resolver becomes the import seam.
- **Scope:** `make scan-docs` / `make adopt` / `make pipeline` (classify →
  orient → read → review), `loft publish` (the projection), the live read and
  write surfaces, `make verify`; the app reads the real archive (fake data
  behind a demo flag).
- **Out:** phone capture, PWA, memory controls.
- **Acceptance:** 10 real letter scans → imported with zero manual renaming →
  dated correctly on the timeline → a machine-generated transcription draft
  readable in the lens → mention links work → published → visible on the
  phone.

### Slice 2 — Phone capture & curation
- **Value:** Alex's stated work surface — curation from the phone: capture
  sessions, date+7 suggestion, speech-to-text story lines, metadata editing.
- **Carries:** the review stub becomes real; proposed/confirmed moves from
  data-only to visible UI (proposed links and OCR drafts marked as
  suggestions).
- **Scope:** Google sign-in; the remote app's upload path; the capture flow;
  proposed/confirmed in the UI.
- **Acceptance:** capture a letter on the phone → tagged on the phone → it
  appears in the archive (laptop sync) and on the site.

### Slice 3 — Show mode for Dad (and gatherings)
- **Value:** Dad can be *shown* familiar photos now, while it matters.
  Full-screen, no-navigation browse: big images, large type, auto-advance.
- **Scope:** a `#/show` route + "Start show" on any person/theme; uses the
  projection; works offline after load; operable by anyone in the room.
- **Acceptance:** tap Show on a person → full-screen slideshow, large
  captions; a relative who has never seen the app can run it.

### Slice 4 — Testimony at scale
- **Value:** the phone-call hole starts closing; OCR drafts make 830 letters
  readable and searchable (pattern discovery, PRD §6/§19).
- **Carries:** the story-harvest design (§19) becomes real — voice memos feed
  Stories and Cast pages; OCR drafts feed the transcription toggle; semantic
  search joins the search surface.
- **Scope:** story-harvest mode (record / self-record / type, story-anchor
  prompts, attribution), OCR transcription drafts (propose → correct),
  semantic search over embeddings.
- **Acceptance:** a 60-second voice memo about a photo → in the archive,
  transcribed (draft), linked to the photo, searchable.

### Slice 5 — Trust & continuity
- **Value:** the durability contract (PRD §18) becomes real.
- **Carries:** sensitive flags move from data-only to enforced UI; memory
  controls land on on-this-day/wander.
- **Scope:** annual export ritual tooling (`tools/export-csv` + folder
  snapshot), memory controls (dismiss a date/person/memory), sensitive-item
  surfacing, the README-for-2060.
- **Acceptance:** export runs end to end; a flagged item never appears in
  wander/on-this-day; the 2060 test passes on a fresh copy of the archive
  folder.

### Slice 6 — Scale & polish
- **Value:** gatherings, offline, and the real collection's size.
- **Carries:** street-view cards stop being a stub; the design system gets
  its accessibility pass; the whole surface gets performance-tested at 10k.
- **Scope:** service worker (projection cache), TV/second-screen mode,
  timeline virtualization at 10k items, heatmap refinements.
- **Acceptance:** full browse offline after one visit; a synthetic 10k-item
  archive renders at 60 fps.

## Sequencing logic

- **Release gate — F6 before any public deploy.** Slice 1 publishes the projection (which carries transcriptions — transcription hosting is the product, PRD §6) to the static host; accounts (F6) are Slice 2. The first *public* deploy therefore waits for F6, or the projection deploys to a family-only host until then; until that gate, `make serve` is the only serving surface. (The projection posture lives in TECHSPEC §7.)
- **1 before 2–6:** the scans are the irreplaceable layer; every month risks
  the physical deadline (house sale) and the narrator's fidelity.
- **2 before 3:** the phone is Alex's stated work surface. *Knob:* if a
  gathering or a Dad visit is imminent, slice 3 (show mode) swaps ahead — it
  needs only the projection, not the archive write path.
- **4 before 5:** testimony and transcription outrank trust tooling for value;
  5 is scheduled before any scale work so the archive is never fragile.

## Definition of done — MVP (end of slice 2)

A guest opens the site on any device: **real letters** on the timeline,
transcription toggle with mention links, people/places/stories connecting
everywhere, search finding patterns — all of it already browsable in the
prototype, now running on the real archive. Alex captures and tags a letter
from his phone, end to end. The backup ritual is documented and run once.

## Urgency knobs

- **Dad worsens sharply** → pull slice 3 (show mode) ahead of 2; it needs
  only the projection.
- **House sale accelerates** → the brother runs a scanner day: batch-digitize
  the letters before the boxes scatter; slice 1's import is already first.
- **The narrator's fidelity drops** → slice 4's story-harvest moves up:
  record Alex's voice now; transcription can follow.

## Explicitly deferred (no slice)

Social feeds, public sharing of any kind, family tree view, and the
model-driven suggestions beyond the reading (labels, alt text, story
suggestions). Accounts are the D1 family list; the remote app signs in with
Google (`docs/TECHSPEC/04-live-system.md` §17.5.1).
