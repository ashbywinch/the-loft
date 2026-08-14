# Family History Album — Tech Spec & Architecture

- **Status:** v0.3 — **for review** · §16 Import flow added (plans/PLAN.md Phase 1 draft, 2026-08-02)
- **Date:** 2026-08-02 · Companion to `prd/PRD.md` v0.5
- **After approval:** prototype with fake content (`tools/fake-data`), per §13.

---

## 0. What this document decides

It makes the architectural calls the PRD left open, with rationale. Section 12 lists the decisions that need *your* confirmation. It deliberately does **not** re-argue the PRD — it implements it.

---

## 1. Principles (inherited)

- **P1 — Folder-first.** The archive is a folder; the app is a lens over it.
- **P2 — Boring stack.** Vanilla HTML/CSS/JS, no framework, no build step, no database. Files + `fetch`.
- **P3 — Generational durability (PRD §18).** Open formats, sidecar metadata, a README written for a reader in 2060, 3-2-1 backups across households, the app disposable by design.
- **P4 — Propose/confirm.** ML/OCR never assert; everything enters as `proposed` until a human confirms.
- **P5 — Privacy by default.** No accounts, no analytics, no third-party CDNs for family content. Single exception: street-view imagery (§6).
- **P6 — Performance at scale.** 10,000 items / 50,000 images; incremental loading; ≤ 100 KB initial payload.

---

## 2. Stack

- **Vanilla ES modules** — no framework, no build step, no `package.json` runtime dependency. The app is a set of `.js`/`.css`/`.html` files that work forever. (Vanilla means no framework or build step — not no classes: `class` is ES2015 and allowed; see docs/coding-standards.md.)
- **Hash-based routing** (`#/timeline`, `#/item/letter-1963-05-14-01`, `#/themes/t-the-boats`) — works on any static host, no server rewrite rules.
- **PWA:** `manifest.webmanifest` + `sw.js` — installable ("Add to Home Screen"), offline shell + cached archive content (§9).
- **Tools** (`tools/`, optional at runtime): Node **or** Python — one choice, made in §12. Used for thumbnails, index rebuild, archive checks, CSV export, fake-data generation.
- **Serving:** a free static host (Cloudflare/Netlify/GitHub Pages) serves the app **plus a published projection** — metadata, thumbnails, stories; no full-res by default (§5). **Google Drive is the archive's home**, accessed through its official API — the phone stores nothing and nothing is hosted in the house. Performance: Google/static CDN for browsing; Drive API for review reads.
- **Why this stack:** durability (files outlive any framework — P3), the payload budget (P6), hostability anywhere, and the entire surface is ~10 screens.

---

## 3. Archive layout (the canonical data)

```
archive/
  README.md              # for a reader in 2060 — what this is, who these people are, how to open it
  people.json            # identity table: the cast (ids, names, years, bios) + relationships
  places.json            # identity table: places (names, optional coords, street-view refs)
  themes.json            # identity table: themes/stories (definitions + ordered items)
  assets/
    <id>/
      item.json          # sidecar — metadata only (the truth); item-2.json, … supersede it
      story.txt          # primary content: the narrator's own words (stories)
      transcription.txt  # primary content: a letter/document's transcription draft
      page-01.jpg        # primary content: originals, open formats only
      thumbs/            # derived thumbnails (pipeline output)
```

- **Sidecar-first (P3.4) — what it means:** each item folder holds its content (scans, the story text, the transcription draft) *plus* a small JSON file sitting alongside them (a *sidecar* — the term comes from photography's XMP files) with that item's metadata. There is no single database blob: `index.json` and `transcripts.json` are derived summaries, regenerable from the sidecars. One corrupt file loses one item, never the archive — and merging a cousin's archive later is just merging sidecar folders.
- **Primary vs derived (requirement, 2026-08-04).** *Primary data* — scans, photos, story text, testimonies, anything a user provides or states directly through the UI — lives in the archive as content files plus sidecars, in a form a reader in 2060 can open. *Derived data* — descriptions, identified people/places/themes/pronouns, the links between documents and people/places, relationships, the index and transcripts — is computed by one shared engine (`tools/projection.py`) from the primary data **only**, and is never hand-edited: not in the projection, and never the only copy. The engine runs in the batch publish path, in scan import, and in the site-capture save path — one implementation, three entry points, no duplication.
- **Append-only (requirement, 2026-08-03, enforced in the archive 2026-08-04):** no file in the archive is ever edited or deleted — a change is a new file that supersedes the old one, and the old file stays forever. **One documented exception (2026-08-05):** the proposed-queue reject path (`reject_proposed_person`/`reject_proposed_place`) deletes the *proposed* record file via the store's single `delete` — a proposed record is a transient review work item that has never been published, not an artifact; everything that has ever shipped stays append-only. A sidecar's first version is `item.json`; a supersession is a new self-contained file `item-2.json`, `item-3.json`, … (the full metadata again, plus `supersedes: "<previous file>"`). Primary content files version with their sidecar (v1 → `story.txt`, v2 → `story-2.txt`). Publish/rebuild tooling resolves the highest version; deletion is a supersession with `status: "deleted"`. The identity tables (`people.json`, `places.json`, `themes.json`) follow the same rule when written. The derived files (`index.json`, `transcripts.json`, `app/data/*`, thumbs) are regenerable caches — they are rebuilt, never treated as canonical, and hand-editing them is a bug (a test fails the committed projection against publish). All writes go through one append-only store (`tools/store.py`); tests inject a fake filesystem that fails on any write to an existing file. The regression that motivated this: the relationships table lived only in the derived projection, got hand-edited, and was lost in a merge — the archive now holds the identity tables, and the projection is regenerated from them.
- **Database vs project content (2026-08-02).** The database is the archive: items, sidecars, people, places, themes, relationships, testimonies — everything the app renders. Project content — code, docs (PRD, TECH-SPEC, PLAN, PRECEDENT), the private interview records, tests — records decisions and process; a fact becomes database content only as an attributed item (sidecar, testimony, person record), never by living in a doc. Interview transcripts enter the database as dated, attributed, verbatim story items (`told_by` the narrator, `source` the session, one item per session) — the project keeps its own working records under whatever names, but the archive never holds a doc called INTERVIEW.md. The same rule applies to code: real content never lives in a tool — `tools/demo_data.py` is the fictional demo generator (docs/coding-standards.md), and a test guards that the real family's names never appear in it.
- **The object model lives in one module (2026-08-05):** `tools/records.py` defines Person, Place, Org, Relationship, Item and every closed vocabulary (relationship kinds, date precisions, item types/statuses); `archive.save_item` validates sidecars against the Item record at the write seam — a developer reads the model in one place, and the archive and the model can never drift.
- **The indexing posture (2026-08-03):** no server database — the folder is the store, and every derived layer (index, transcripts, hashes, search, future embeddings) regenerates from the sidecars. The derived layers upgrade as needed (pre-built search index, queue as a derived view); SQLite-as-*cache* (never the store — regenerable, so it preserves the invariant, but costs tooling) is the revisitable knob past ~100k items or if SQL queries are genuinely needed. **`edits.jsonl`** — an append-only, plain-text audit log (timestamp, item, field, old → new, who) for every write; the one truth file that is a log, not a cache, and the answer to the no-history gap (corrections currently overwrite silently).
- **IDs are stable forever:** `letter-1963-05-14-01`, `photo-1972-06-01`. Never renamed, never reused.

---

## 4. Data model (JSON)

**Item** (core fields):

```json
{
  "id": "letter-1963-05-14-01",
  "type": "letter",
  "title": "A week in the flat",
  "date": "1963-05-14",
  "date_precision": "exact",
  "people":  [{"id": "p-mum", "status": "confirmed"}],
  "places":  [{"id": "pl-aldgate-kensington", "status": "confirmed"}],
  "themes":  [{"id": "t-the-flat-search", "status": "proposed"}],
  "source": "Box 3 — Letters 1963",
  "description": "",
  "provenance": "",
  "sensitive": false,
  "status": "catalogued",
  "assets": [{"kind": "page", "file": "page-01.jpg", "caption": ""}],
  "created": "2026-08-02"
}
```

- **Primary content is files, not fields (2026-08-04).** A story item's text is `story.txt` in its folder, a letter/document's transcription is `transcription.txt` — referenced by the sidecar's `assets` (`{"kind": "story"|"transcription", "file": …}`), versioned with the sidecar. The sidecar JSON never carries the text; the projection's items embed it again at publish (the projection is derived, so embedding is fine there).
- **References carry a status** — `confirmed` | `proposed`. That is the ML seam (P4): models write `proposed`; humans flip to `confirmed` with one tap. No schema change when OCR/labeling arrive.
- **Dates:** ISO + `date_precision` (`exact | month | year | approx`). Approx renders at range start with a subtle marker; filters treat it honestly.
- **Person:** `{"id","name","years","relation","bio","photo"}` — thin bios are honest (PRD §4); never padded.
- **Person IDs are name-based** (p-alex, p-nora, p-owen) — first-name-only for the main characters where unambiguous; on a name clash the ID qualifies with the surname (p-harper-winch). IDs never change once catalogued (2026-08-03).
- **Place:** `{"id","name","aliases","note","lat","lng"}` — `aliases` are the short forms the reader hyperlinks ("Dunmoor" → Dunmoor Primary School); the same alias seam as people (§16.4).
- **Relationships — RESOLVED (user, 2026-08-02):** `people.json` (the archive's people identity table) carries typed edges `{"a", "b", "kind", "label_a", "label_b"}` (`spouse | parent | sibling | inlaw | teacher`) — `label_a` is what B is to A. Person pages show a "Related" block; the family tree view (`#/tree`) renders generations from the edges. **Labels are gender-neutral by design** (`child`, not `son` — the model never assumes gender; the family's own gendered words live in the free-text `relation`/bio where the family itself used them). No runtime library; `tools/export-gedcom` remains future work for interop. **Relationships are derived, regenerable content (2026-08-04):** the family structure is stated in the primary data (the interview answers: "Mum was Nora… Dad is Owen Hale. Mum's mum was Fern… Dad's sister is Miriam… His aunt is Wilma Hale", "Wilma is Miles's sister", "Harper… married Owen's brother Dale", "Owen's parents Miles and Vera") plus the letters, and the shared engine must be able to regenerate the edges from those artifacts (with the propose/confirm seam for what inference cannot prove). The complete edge set was recovered from git history on 2026-08-04 after a merge dropped it from the projection — the archive is now the only home of the table, and `tests/test_publish.py` fails if the projection ever drifts from it again.
- **Bios are derived, source-attributed text** — rebuilt when evidence changes (new letters, testimonies); disputed facts are omitted from generated text, never adjudicated (§16.9).
- **Aliases require attribution** — a form attested in an artifact's text ("mamie" in the 1977 letter, "Lex" in the 1990 one, "BF" — the reviewer's own word) or in a stored verbatim comment. Agent-invented forms ("Daddy", "Auntie", "Mummy") are not aliases. The canonical name always matches; actual names are not listed as aliases (§16.4).
- **`pronouns` (optional, 2026-08-03)** — only where the archive evidences them, never guessed: the person's own statement is the gold standard (Alex: they/them — the narrator's own words), then attested text by others (Nora/Owen via the narrator's interviews, Harper via the 1977 letter's "She's brought the three kids"). No attestation → no field. Rendered on the person page next to "Known as".
- **`dob` (optional, future seam, 2026-08-03)** — ISO date, discovered politely in interviews. Birth dates disambiguate presence by date: Eli is not at the Isle of Seagate because he was born after the trips stopped — an inferred presence the 1977-style attribution rule alone cannot catch (user, 2026-08-03).
- **A dated, attributed comment (testimony) is a story item**: `date` + `told_by` (the speaker) + verbatim text + `source` (WhatsApp, letter, recording) + `people[]` links to its subjects (PRD §19, G7) + `comment_on` (the artifact it responds to — reverse-looked-up and rendered as that item's "Responses"). Testimonies have no scans.
- **Theme/story:** `{"id","title","subtitle","items":[{"id","note"}]}` — the door, plus the arranged evidence in order. The app renders the arrangement; it never interprets (PRD §10).

- **Event items (2026-08-05):** `type: "event"` with a closed `kind`
  (`birth | marriage | death | other`) — an attested happening (a concert a
  letter mentions) that flows through the item pipeline (timeline, filters,
  search). Person life events — a person's `dob` is a birth, `dod` a death,
  a dated spouse edge a marriage — are **derived at render time**, never
  stored as items (the identity tables stay the single source of truth).
- **Relationship dates (2026-08-05):** a spouse edge may carry
  `date: {date, precision}` — the marriage date, the derive's input.
- **Clarification / reflection flags (2026-08-06):** story items may carry
  `clarification: true` (an identity fact; must name people/items refs) or
  `reflection: true` (perspective; no events' date — dated by its told day;
  must name people/places refs), never both. The `published()` seam (data.js)
  excludes both from every discovery surface; they render only in their
  blocks on the pages they attest/mention (see prd/MEMORIES.md).
- **Evidence flag (2026-08-06):** a found record — a web capture, a
  directory page — is `evidence: true` (non-story types only; must name
  people/places/items refs). It is not a family happening: the `published()`
  seam excludes it from the timeline, and it renders on the pages it attests
  (the plaque capture lives on the Lark Inn's page). The recognition
  principle: the timeline shows only things someone in the family would
  recognise as having happened to the family at that time.
- **Sources (2026-08-06):** a web-page document carries
  `sources: [{url, title?, accessed}]` (validated: http(s) url + access
  date) — rendered as hyperlinks on the item page. A web capture is dated by
  its **access day** (Rule K: the item is our capture).
- **Place coordinate precision (2026-08-05):** `precision ∈ {"", exact,
  street, town, county, region, country, continent}` — the coarsest level the
  stored point honestly represents; the map draws an uncertainty ring for
  anything coarser than a pin. The import flow's geocoding proposes the
  precision (IMPORT-PRD Rule P).
- **Person↔place links require attestation (2026-08-05):** a person is at a
  place only when the item's place ref names them in its per-place `people`
  list — co-mention in an item is not presence (the 2001 email's 91 people
  and 8 places link nobody). The map's person filter, the person page's
  Places row and the place page's People row all read through this one rule.
- **Person↔person links, same test (2026-08-06):** a person page's People
  row shows the attested relationship edges only — co-mentioned names never
  render (the recognition principle: a person reading their own page would
  recognise everyone on it). Derived life events only place on the spine
  from point precisions (exact/month/year/approx) — "died after 1917" is not
  a 1917 happening; the fact stays on the person page.
- **Involvement dates (2026-08-06):** a long-lived document (a family record,
  a guest book, a logbook) involves different entities at different times.
  **Any ref may carry an involvement date** (`date: {date, precision}`, the
  dated-fact shape, validated at the write seam): when that entry/signature/
  annotation was made — written by the import flow from the entries' own
  content, confirmed by the reviewer. **Placement rule:** on a person's page,
  a person-filtered timeline, and a place page, the item is placed by the
  ref's involvement date; without one, the derived floor — an involvement
  can't predate the item, nor (for a person) their birth, so `max(item.date,
  person.dob)` puts the Kendall–Pryce record in the 1940s on Nora's page
  (her birth entry), never the 1860s. The dob floor is exact for
  birth-linked records and a lower bound elsewhere — the attested date is the
  general mechanism, the derivation a convenience. The item's own date stays
  Rule K (first attestation); only the per-entity placement shifts.
- **The timeline spine (2026-08-05/06):** entries (items + derived life
  events) pack into **count-sized, year-aligned periods** (~20 entries),
  rendered newest-first, each titled with its range plus a **theme hook**
  when one theme covers ≥2 items and a fifth of the period's items; a period
  never splits a year, and a year alone over the target is its own period.
  Counts are honest: "N periods, M items · K events".
- **Archive-quality evals (2026-08-05/06, tests/):** the drift guard
  (projection ≡ publish) is joined by guards the system runs every gate:
  letter/document descriptions are specific and correspondence-distinct
  (test_descriptions), place notes never carry process jargon
  (test_place_notes), no catalogued story is dated by its told day without
  the narrator's words (test_story_dates), and **everything catalogued is
  visible somewhere** — timeline items' dates parse, fragments name existing
  targets (test_completeness).
- **Render once per page (2026-08-06):** an item never appears twice on the
  same page. The Memories/Responses blocks own the stories; an artifact list
  beside them excludes stories (`artifacts()` in connections.js — the place
  page's "N items from X" counts artifacts only), and the memories block
  takes `exclude` (ids already rendered) so a curated arrangement or a
  Nearby list can never re-show them. A new page that lists items next to a
  stories block must use one of the two seams — the block is the shared
  component, the rule is enforced there, not per page.

---

## 5. Capture & curation (review mode)

Capture: `<input type="file" capture>` or MediaDevices; auto-sequence naming (`letter-1963-05-14-01.jpg`); envelope first, per the PRD ritual. Curation: 3 fields + story line; `draft` → `catalogued`; edit metadata; **never delete** (PRD §3). **Streamlined capture sessions (phone-first):** enter once, photograph many items back-to-back; the app **suggests date+7 for weekly letters**; title/story accept **speech-to-text** (Android Web Speech API); people/places tagged later in batch.

**The phone is a thin client; Drive is the archive's home (user constraints: work from the phone, store nothing heavy on it, host nothing in the house).** The app talks to Google Drive through its official API — Google sign-in (Google Identity Services, PKCE, no server) against a **dedicated family *Loft archive* account**; the app lists, reads, writes, and uploads the archive folder. Captures upload immediately; nothing of the archive accumulates on the phone beyond browser cache. No FSA, no synced folder, no local copy — and nothing runs inside the house.

**Write path:** OAuth (archive account) → Drive API `files.create/update` for sidecars and images, `media` upload for captures, thumbnail URLs served from Google's CDN for browsing. Desktop Chrome does the bulk box-digitization the same way — same client, bigger screen.

**Bulk scanning (sheet-fed + slide/photo scanners — user, 2026-08-02):** scanner output lands on a laptop; `tools/import` (Python) uploads to Drive with auto-naming; the reviewer tags on the phone. The phone camera is the ad-hoc path only; scanner output is the quality path (300 DPI).

**What lives where (the two surfaces):**

| Surface | Contents | Runtime |
|---|---|---|
| **The archive (Google Drive)** | full-res scans, sidecars, transcriptions, derived files (index, future embeddings) — the family's dedicated account | Drive API via Google sign-in; full-res read only when authenticated |
| **The site** (browsable) | app + published projection: metadata, thumbnails, stories, transcriptions | static CDN — fast, **family-only behind F6 accounts** (PRD §11; no public surface at all until they land), no full-res |

**Where curated data lives:** primary content (transcription, story text, scans) sits in each item's folder as **files** (`story.txt`, `transcription.txt`, `page-01.jpg`); captions and links sit in the **sidecar** (`assets/<id>/item.json`, plain JSON) inside the archive. Derived data — the search index, and future **embeddings** — are regenerable files (`index.json`, later `embeddings.json`), never the only copy. `loft publish` (Python, laptop step) regenerates the projection from the archive for the static host; free-tier file-count caps bound it to thumbnails + metadata — which is also the privacy posture: **the intimate full-res layer is never public** (480px letter thumbnails aren't readable documents).

**Durability is export-driven:** Drive holds the live archive; the **annual full export** (folder download + CSV, `tools/export-csv`) to external media and the brother is the load-bearing 3-2-1 ritual (PRD §18.6). Files stay plain and open; if Google ever changes terms, the folder downloads whole.

**Performance, answered directly:** browsing rides the static projection (fast); review reads ride the Drive API with Google's thumbnail pipeline; the phone stores nothing. The one honest dependency: the reviewer path requires Google identity — accepted consciously, mitigated by the export ritual and the 2060 README (§18).

---

## 6. Maps & street view

- **Places door, v1:** curated place cards (the period, the artifacts from that era, dates) plus a **map view built on Leaflet + OpenStreetMap raster tiles** — free, no API key, standard attribution (user-approved, 2026-08-02). The prototype ships this; the non-tile dot view is the offline / tile-failure fallback — cards and text always remain.
- **Street-view cards** (PRD §10, Should): public imagery, not family content — Google Maps embed iframes (no key) or static images; degrade gracefully offline. Approved with the map (user, 2026-08-02).
- **Map modes (future, 2026-08-03 — recorded, not built):** explicit all-places / date-range / person-subset views, and remembering where a returning user was looking last. The first-visit default already shows the whole archive — full date range, every place, world viewport — until the user narrows via the slider (the ±WINDOW window) or person chips (PRD §15).
- **Open: vague or unknown dates.** An item dated "circa 1972" has a dot whose year is a guess — the slider window must place it honestly via `date_precision` (never silently excluded, review: silent exclusion).
- **Person chips list only people who can appear on the map** (requirement, 2026-08-03): a person with no place-linked item (e.g. Jude — his only item is a placeless testimony) never gets a chip, because selecting them would filter the map to nothing.
- **A person's map = the places they are AT, per-place** (requirement, 2026-08-03): an item's `places[]` entry may carry an optional `people` list — the people who are *at* that place in the item's context; without one, everyone in the item's `people[]` is taken to be there (single-participant items). Never the places of items the person merely *told* — telling a story about someone else's location is not a link to it. **A letter's places are its participants' own geography, not the recipient's**: the 1977 letter's gigs (Aldgate, Walthamhollow) are Nora's, the knees-up (Easthaven) is Owen's, Marlock is Miles & Vera's house, Tornia is Harper & Dale's — and the recipient (Fern, "Chère mamie") is at none of them (user, 2026-08-03). A place listed without textual evidence is removed, not annotated (Marlock dropped from the Aldgate-addresses story, whose verbatim text never mentions it). **Being named in a family story — or sharing a surname — is not being at its places** (user, 2026-08-03): the Hale-family story's own claim is that "the people who Harper saw in Marlock are Owen's parents Miles and Vera" — Owen and Dale are reference points there, so Marlock belongs to Harper/Miles/Vera only; and Halfway's Marlock link was a guess (the canal passes through the town, but the boat is evidenced at Innisfree), so it was removed.
- **Attribution:** OSM + Leaflet credits on the map view; Google's terms for the embed. Both are public map imagery — the same privacy posture as street view, never family content.
- **Scale-aware markers** (requirement, 2026-08-03): no dots or labels at overview zoom — the heat map stands alone; dots appear at regional zoom (≥ 8), labels at street zoom (≥ 12), and a lone active place always gets its dot and label. The offline dot view always shows labels — its primary device is a tablet (no hover, PRD §11) and it has no heat map to protect (review, 2026-08-03). Rationale: at country zoom a red dot is a meaningless pixel and a label a blob — both obscure the heat map (user, 2026-08-03).

---

## 7. Privacy & security

- **No PIN — authentication is the archive account; the projection is family-only, not public** (user, 2026-08-02: "it's a website, not a bank card"; PRD F6: no public surface at all until accounts land, §15 — the earlier "open by design" posture is superseded). The projection carries metadata, thumbnails, stories and transcriptions — **transcription hosting is the product** (PRD §6, §10); full-res scans sit behind Google sign-in with the family's archive account.
- **No analytics, no telemetry, no third-party CDNs** for archive content. System font stack (or self-hosted fonts). Street view is the only external fetch.
- **The archive lives in Google Drive (its home), accessed via Google sign-in to a dedicated family archive account.** Files remain plain and open (PRD §18.8); real authentication gates full-res — stronger than the courtesy PIN on the public projection.
- **Future ML/OCR runs locally** — on-device or the household server. No third-party cloud processing of family content, ever.

---

## 8. Performance budgets (PRD §11)

- First meaningful paint ≤ 2 s on 4G; initial JS/CSS ≤ 100 KB.
- **Timeline:** decade → year rows → week rows; DOM virtualization (only visible rows in the DOM); 60 fps scroll; precision-aware placement.
- **Images:** thumbnails in every list; full-res swap on open; `loading="lazy"` + `decoding="async"`.
- **Index:** `index.json` (metadata only) loads first; `transcripts.json` (heavy text) lazy-loads when search or reading needs it. Budget: ~2–5 MB index + ~5–10 MB transcripts at 10k items — segmented by decade if it grows beyond.

---

## 9. PWA & offline

- Manifest + service worker. Cache: app shell (always), index/people/places/themes (first load), thumbnails (LRU), full-res images (on demand).
- **Honest boundary:** the site's projection — metadata + thumbnails — is fully cacheable, so the whole *browsable* archive works offline on any device. Full-res exists only in the archive (Drive), read via API when authenticated. The review path needs network — it is a cloud client by design.

---

## 10. Search

- A **derived inverted index** (`search.json`, emitted by `tools/rebuild-index` with offline tf-idf weights) loads fast and deterministically — the browser no longer builds the index from raw text at load (2026-08-03). Regenerable from sidecars like every derived layer.
- Fields: title, description, story, transcription, people, places, themes, source.
- **Transcription search is pattern discovery** (PRD §6): "migraine" across 830 letters surfaces the drift. This is a headline feature, not an afterthought — the search screen earns its place on Home.
- Ranking: exact > prefix > fuzzy; results filterable by type / decade / person / place.
- **Semantic search over testimony embeddings** (`embeddings.json`, derived and regenerable): "what did people say about the boats?" — the testimonies from §19 become the first real corpus for the ML seam.

---

## 11. Tools (`tools/` — no runtime dependency)

- `make-thumbs` — thumbnail pipeline.
- `rebuild-index` — derive `index.json` + `transcripts.json` from sidecars (folded into `publish` in the current implementation).
- `check-archive` — schema validation, dangling references, missing assets; the durability health check (PRD §18.9).
- `publish` — regenerates `app/data` from the archive (exists 2026-08-04): identity tables + sidecars + primary content files → index, people, places, themes, transcripts, assets, avatars; deterministic, tested, the only writer of the derived projection.
- `derive` — the shared derivation engine (`tools/projection.py`): resolved items, identity tables, index and transcripts. Used by publish (batch), import (scan ingest), and the capture server (site stories) — one implementation, never duplicated.
- `export-csv` — human-readable metadata + transcription export; part of the annual 3-2-1 export ritual (PRD §18.6).
- `fake-data` — the **demo** projection generator (fictional content only — a demo family, invented places and letters; no real names, guarded by a test). The real family's content lives in the archive and is published by `loft publish`.
- `import` — inbox → archive: assets + sidecars + thumbs + index; the minimal date prompt (§16.3).
- `upload-drive` — mirror the local archive to the dedicated Google Drive account (§16.6).
- `resolve-mentions` — transcription/address mentions → proposed people/places in sidecars (§16.4).
- Dev serving: `python3 -m http.server` or `npx serve` — zero install.

---

## 12. Decisions to confirm (your review)

| # | Decision | Recommendation |
|---|---|---|
| 1 | **Vanilla-first — RESOLVED (user, 2026-08-02)** | A framework adds no value at this scale and hand-rolling stays manageable. Not "React or nothing": small JS or a CSS framework (degrading well) remains acceptable; revisit during development if things get messy (§15) |
| 2 | **Drive is the archive's home (dedicated family account, official API, thin-client phone); site = published projection (metadata/thumbnails/stories); annual export is the durability ritual** | Yes — nothing stored on the phone, nothing hosted in the house |
| 3 | **Sidecar-first layout** (`item.json` canonical, index derived) | Yes — one bad file loses one item (P3.4) |
| 4 | **Street view + Leaflet/OSM map — RESOLVED (user, 2026-08-02)** | Public imagery only; OSM attribution; degrades offline |
| 5 | **Tools language — RESOLVED:** Python (user, 2026-08-02) | — |
| 6 | **Hosting target** — free static host for the app; archive home = Google Drive free tier | Cloudflare Pages (or Netlify / GitHub Pages) + Drive; nothing paid, nothing self-hosted |
| 7 | **Working title — RESOLVED:** "The Loft" (user approved, 2026-08-02) | — |
| 8 | **No PIN on the projection — open by design** (the archive account is the gate) | **SUPERSEDED (2026-08-03, §7/F6):** no public surface at all until accounts land — the projection is family-only; nothing deploys before the F6 gate (plans/PLAN.md) |
| 9 | **Family relationships** — typed edges in `people.json`; person pages show relationship labels; `#/tree` renders generations | **RESOLVED (user, 2026-08-02)** — built in the prototype. **Alignment (2026-08-05):** no genealogy *tooling* (the PRD anti-pattern) is not the same as no object-model standard — **GEDCOM X** is adopted as the object-model reference (person/relationship/agent/event/place/source vocabulary; **residence events replace the place-household field** — the standard's model is better); **date precision extended** with `before`/`after`/`between` so the mapping is lossless; `tools/export-gedcom` targets **GEDCOM 7.0** with a documented one-to-one mapping (excludes proposed links and proposed residence; stories shoehorn as NOTES on the people they reference); **`tools/import-gedcom`** is the inverse (ids recovered via REFN, places by name) and the round-trip is exact — verified by tests and on the real archive; both sides parse-verified with `gedcom7` (strict ABNF grammar) |
| 10 | **Live system store** — multi-user curation and corpus-scale generation need a real store; the folder stays the durable materialized contract | **RESOLVED (user, 2026-08-03)** — Supabase (Postgres + pgvector); small family-user set; generation on the reviewer's laptop; tenant isolation is a far-future seam (§14), not built |

---

## 13. Prototype build plan (next, after your approval)

- **Fake data:** `tools/fake-data` → 24 letters (lorem-ipsum, period-flavored filler, dated 1962–77), 12 CC0 photos (picsum / Wikimedia Commons, or the designer agent fakes them), 6 people, 4 places, 3 themes, 1 story ("The boats"), 1 street-view card stub. *(2026-08-03: the lorem filler and invented photos were removed once real data existed — the projection is real content only; the timeline's empty 1962–77 years are the honest state until the letters are scanned.)*
- **Files:** `index.html`, `app.js` (router + views), `styles.css`, `manifest.webmanifest`, `sw.js`, `data/` (generated).
- **Screens:** Home (today-in-history, wander, the doors), Timeline (decade→year→week), Item viewer (zoom + transcription toggle), Themes, one Story in reader mode, Cast, Places (cards + stub map), Search.
- **Test:** serve the folder, open on the **Android phone first** (the curation surface), then a tablet for browse; walk the D8 protocol from `DISCOVERY.md` — watch, don't ask.

---

## 14. Deliberately deferred (seams only)

OCR transcription drafts, photo labeling, theme/entity discovery, TTS — the `proposed`/`confirmed` status already exists in the schema (P4); models plug in later, locally. **No ML in the shipped v1** (PRD §12).

**Cousin contributions (not built, not ruled out):** Drive sharing covers invite-level access today; a future merge/import tool (per-contributor folders, ID namespacing) adds uploads without schema change — people are already first-class in the model.

---

## 15. Decision rationale (for future reviewers)

**Why no framework (user asked, 2026-08-02):** 1) *Durability* — the app is disposable but its code shouldn't be: vanilla files are readable in any editor in fifty years; a framework means `node_modules`, a build system, and a toolchain that rots. 2) *The budget* — 100 KB initial payload (P6); React + router + state is 300–500 KB before a line of our code. 3) *The app is small* — ~10 screens, no multiuser state, no real-time; frameworks pay off when state grows big enough to fight you. 4) *Zero maintenance tax* — no `npm install`, no lockfile churn, no build step to re-run; `python3 -m http.server` serves it. The honest counterpoint: at 40 screens with interdependent state, or with hired developers, a framework would win; the discipline that substitutes for it is small focused ES modules plus a ~50-line router. **Recorded decision (user, 2026-08-02):** a framework is judged to add no value at this scale, and hand-rolling complexity is not expected to overwhelm maintainability. Explicitly *not* "React or nothing": a small JS library or a CSS framework — especially one that degrades gracefully — may be adopted if it earns its place. Revisit during development if the code starts to get messy. The decision targets frameworks and build steps; it never ruled out classes (native ES2015) — the app has few value types so far, and the date model's JS twin (`PreciseDate`) will be the first (docs/coding-standards.md).

**Sidecar tradeoffs (user asked, 2026-08-02):** each item is a folder; `item.json` sits beside the scans; `index.json` is derived, not canonical. *Gains:* one corrupt file loses one item, never the archive; the index is a cache — always rebuildable; cousin merges are folder merges, no database conflict; the archive is human-readable without the app (the 2060 test); no migrations ever. *Costs:* metadata exists twice (trivial — JSON is cheap); bulk edits need an index rebuild (automated); cross-archive queries read the index so it must be fresh (two simultaneous editors is the only race, rare, last-write-wins acceptable). *Alternatives rejected:* one big `index.json` (every write rewrites the whole file; one corruption is catastrophic; merges fight) and SQLite (fastest queries, but binary — a tool must read it, bad for 2060 — and it is the database lock-in the PRD refuses). Sidecars are the durability-first middle.

**Why no PIN (user, 2026-08-02):** the PIN was a courtesy lock inherited from a pre-auth architecture; once real authentication (the archive account) gates everything intimate, the projection contains nothing sensitive — a PIN is ceremony with nothing behind it. Removed everywhere.

**Why scanners:** the sheet-fed scanner and slide/photo scanner are the bulk quality path (300 DPI legibility — upgrades R3); the phone camera is ad-hoc only; tagging stays on the phone.

---

## 16. Import flow (capture → archive → app)

**Status:** draft — plans/PLAN.md Phase 1 deliverable, reviewed via the import interview (2026-08-05). The flow is specified in `docs/prd/IMPORT-PRD.md` (rules A–N, questions Q1–Q7, the staged review, the landed model additions); this section stays the normative home and the private worked-example review remains the real-import baseline. Decisions resolved with the reviewer 2026-08-02; family-instance facts live in the private interview records, referenced here.

### 16.1 The loop

```
boxes → the user's scan area (their folders — adopted by hash, §16.13)
      → workspace/work/<batch>/ (oriented → raw OCR → OCR guess → confirmed)
      → tools/import  [prompt: date] → archive/assets/<id>/ (sidecars + JPEGs + thumbs)
      → tools/upload-drive            → Google Drive (the archive's home)
      → loft publish                 → app/data projection → static host → phone
```

- **Curator mode (phone, Slice 2):** 3 fields + story line; `draft` → `catalogued`; dates refined with date+7 suggestions. Import never catalogues — **the curation gate** is: a human selected the originals (scanning *is* the selection), import catalogs them as `draft`, and they appear only when the phone session confirms. Digital photos from younger members are human-curated before import, never bulk-imported (PRD §7).
- **The app never reads Drive at runtime** — all reading rides the projection (§5). Import and upload are the only writers to the archive.

### 16.2 Scanner conventions (resolved, user 2026-08-02)

- **Operator:** the reviewer alone, at home, own pace. Supersedes plans/PLAN.md's brother-scanner-day assumption.
- **Gear:** an **Epson FastFoto FF-680W** (2026-08-13) — sheet-fed ADF for letters *and* photos, duplex, 600 dpi optical, WiFi (eSCL) + USB; no flatbed, so 35 mm slides remain uncovered; Android phone scan app for odd sizes.

| Requirement | Why |
|---|---|
| Sheet-fed: duplex ADF | letters are written on both sides |
| Sheet-fed: 300 DPI optical, colour | quality floor (PRD §7); colour chosen over grayscale |
| Sheet-fed: scan-to-folder | the output shape (per-job PDF or image set) is irrelevant — separators mark letters |
| Sheet-fed: ADF ≥ 12 pages, duplex, WiFi (eSCL) + USB | 3–5-page letters, duplex → up to 10 pages, laptop connection |
| Prints: photo ADF, 300+ DPI | hundreds of prints feed the FF-680W's photo ADF; 35 mm slides uncovered (no flatbed) |
| Phone app: per-page JPEG export | odd sizes (airmail, cards) — PRD §7 no-camera amendment (user, 2026-08-02) |

- **Sheet flow (2026-08-03):** the letters are in **stacks** and feed continuously — one letter is not one scan job, and there are **no separator sheets**. The letters carry their own structure: a letter's first page holds the address block, the date and the salutation ("as from: 31 Pinewood Court… Wed 12th Jan. '77… Chère mamie"), and continuation pages are often numbered. Boundaries are therefore a **review pass, not a detection problem**: import concatenates every job in the inbox into one ordered page sequence, walks it letter by letter, and the worksheet prompt confirms where each letter ends — the reviewer has the physical letter in hand, and the structure makes the pass easy. Duplex; sheet order = reading order (page-01 = sheet 1 front, page-02 = sheet 1 back, …). The 50-sheet ADF caps a single feed at ~10–12 letters, so a stack feeds as several sub-jobs — job boundaries are irrelevant. A vision-read boundary *proposal* can join later via the ML seam (Slice 4); the review pass is the Slice 1 mechanism. **No envelopes** in this collection — the letter carries its own address and date (`INTERVIEW.md` addendum) — so envelope-first does not apply here; the ritual still supports it for other families.
- **Image spec:** 300 DPI colour, JPEG quality ~88. Calibrated on real scans (§16.8): handwritten ink on white compresses to ~1 MB/page — colour is ~3× grayscale and still fits the free tier.
- **Scan command (2026-08-13):** `make scan-docs ARGS="--label …"` / `make scan-photos ARGS="--label …"` → the user's scan area (`tools/loft_paths.py` `USER_SCAN_AREA` — `<…>/scans/<batch-id>/<batch-id>-NN.jpg`, 300 DPI colour, JPEG q88, label in the registry record) via `tools/scan.py`; the FF-680W is added to the user SANE config (`~/.config/sane/airscan.conf`) by IP because mDNS discovery on the BT Smart Hub is unreliable, and the airscan backend is enabled in the user `dll.conf` (the Ubuntu package ships it disabled). The scanner answers direct eSCL jobs even when discovery/status checks fail — the phone app's "Not Ready but scans work" is that behaviour (2026-08-13).
- **Odd sizes:** phone scan app → export per-letter page JPEGs into a job folder → the same `tools/import` pipeline.

### 16.3 tools/import (Python CLI, reviewer-operated)

- `tools/import <inbox> --box "Box — Letters 1977" --type letter` — one box at a time; `--box` becomes `source` and pre-fills the year.
- **Stages:** ingest → prompt → catalog → **read (machine transcription draft + prompt pre-fills, §16.7)** → thumbs → index. Resumable: processed folders are marked in their sidecars — the inbox folders are never moved (MULTI-DOC-IMPORT-PRD §3.5); a crash re-runs cleanly. Fail-fast on unreadable images, duplicate IDs, page-count anomalies.
- **The minimal prompt** (per item). The plan's "filename / EXIF / minimal prompt" question resolves to the prompt: filenames carry no dates, and scanner EXIF stamps scan-time, not letter dates — the date is handwritten.

| Prompt field | Behaviour |
|---|---|
| date | pre-filled from box year, or date+7 from the previous letter **in the same stack** (stacks are chronological within themselves); one Enter accepts, or correct — unordered stacks (e.g. Dad's boat letters) get manual dates |
| precision | `exact / month / year / approx` — never force a fake exact date (PRD §6) |
| page count | sanity check vs duplex expectation; odd counts flagged |
| run defaults | sender + recipient, asked **once per stack** (Nora → Fern for the main run; Dad's boat letters differ); one Enter accepts |

- **IDs:** assigned at import from the prompt date (`letter-1977-01-12-01`, `-02` on same-date collision) or box year alone (`letter-1977-01`); **never renamed afterwards** — later precision refinement updates metadata only (§3, "IDs are stable forever").
- **Output:** `archive/assets/<id>/item.json` (sidecar, status `draft`) + `page-NN.jpg` + `thumbs/`; `index.json`/`transcripts.json` rebuilt; `check-archive` passes. The local archive lives **outside the repo** (AGENTS.md — scans are never committed), in our workspace on the 3.7 TB Seagate — the workspace sibling holds registry, work stages, archive and projection (§16.13); the user's scan area (`scans/`) stays theirs.

### 16.4 The resolution seam (import doing real work)

- **The identity tables are archive content.** `archive/people.json` (people + relationships), `archive/places.json` and `archive/themes.json` are the single source; `app/people.js` renders their aliases and the shared engine (`tools/projection.py`) carries the matcher. `tools/resolve-mentions` runs the same matcher over transcriptions and address lines, writing `people[]`/`places[]` entries as `proposed` into sidecars — one alias source, three consumers (reader links, import proposals, publish regeneration). No second convention.
- **Place records carry `aliases` too**; the reader hyperlinks place mentions exactly like people mentions — a mention without a record stays plain text (F7).
- Mentions without a record stay verbatim text (PRD F7): nothing is linked, the suggestion sits in the queue.
- **Worked-example finding:** the real letter salutes "Chère mamie" — Fern's aliases lack `mamie`; alias content is the reviewer's call (the dataset), flagged in the private worked-example review. Initialisms ("BF") are deliberately not auto-resolved — too noisy; they go to the queue as manual proposals.

### 16.5 The propose/confirm queue

- **No new derived file.** The queue is a review-mode view (Slice 2) over sidecar state: items carrying `proposed` refs, a draft transcription, or proposed alt text. Confirm = supersede the sidecar with the flipped status + re-publish. One tap.
- **Place-mention candidates sit in the queue.** The criterion for a place record is not recurrence — it is *is it an actual place the family engaged with?* (Easthaven because Dad went to the Mayor's knees-up, not because it recurs; "a turkey" the dinner is not a place, "Tornia" where Dale and Harper lived is). "Hyperlink later" costs nothing: the render follows the record, so adding the record later lights every link.
- **The queue's import-time shape is the curation worksheet (§16.9):** proposals and open questions in one list, answered once while the letter is in hand.
- **Schema extension** (for OCR drafts): `transcription_status: none | draft | confirmed` alongside `transcription`. Drafts render with a visible "draft" marker and search with a draft flag; promotion is correction + status flip.

### 16.6 Publish and the phone path

- **Sync:** `tools/upload-drive` mirrors the local archive to the dedicated family account (exists — user, 2026-08-02). Split from import (which §5 bundled) so a dropped connection never loses catalog work.
- **Publish:** `loft publish` regenerates `app/data` from the local archive (identity tables + sidecars + primary content files — metadata, thumbnails, stories, transcriptions); the static host serves it. Drafts appear in the projection (the owner's drafts surface reads them, 2026-08-03) and are filtered from the archival views by `catalogued()`; tombstoned items never publish. **Hard gate (2026-08-03, review):** the publish path refuses (non-zero exit) to target a public host until F6 accounts exist — the release gate in plans/PLAN.md — so the projection's transcriptions can never leak to a public deployment by accident; the only override is an explicit flag for a family-only host. The gate guards the deploy path; the current `loft publish` targets the local projection only.
- **Phone (Slice 2):** Google Identity Services PKCE against the archive account; `files.create/update` for sidecars, `media` upload for captures; the phone writes byte-compatible sidecars (same schema, same fields). Full-res read only when authenticated (§5).
- **PWA** caches the projection (Slice 6); the whole browsable archive is cacheable.

### 16.7 Transcription draft loop

- **Machine-read only — the reviewer does not type letters (2026-08-03).** Transcriptions enter as machine drafts from two backends behind a quality gate:
  - **Scanner-bundled OCR** (the Epson's software, ABBYY-class) — free and local, print-oriented: ledgers, typeset documents, typed memoirs.
  - **Vision model** (env-configured `LOFT_OCR_*` endpoint) — token-costing, handwriting-capable: the letters themselves (proven in the worked example — it read the 1977 page's date, address, salutation and content).
  - **Calibration gate (Slice 1):** one real letter read both ways; the better backend wins per document type. Expect the vision path to carry handwritten letters.
- Drafts enter with `transcription_status: draft` (the lens already renders the marker); correct → confirmed → searchable (correction lands on Slice 2's review surface, §16.6). Drafts are searchable from day one (pattern discovery, PRD §6) with a draft flag.
- The same machine reading pre-fills the prompt (date/address/salutation — proposed) and, once the draft exists, `resolve-mentions` (§16.4) populates proposed people/places — the resolution seam does its first real work in Slice 1.
- The propose/confirm seam (P4) is unchanged: machine output never asserts.

### 16.8 Storage math (colour letters — user, 2026-08-02)

Calibration from real captures: a 3.1 MP colour handwriting page = 402 KB; a 1.5 MP page = 147 KB. Scaled to 300 DPI letter (2480×3508, 8.7 MP) → **~1.0–1.3 MB per page**.

| Layer | Volume | Est. size |
|---|---|---|
| Letters (830 × 3–5 pp) | ~3,300 pp | 3–4.5 GB |
| Slides (~100–600) | — | 0.3–1.8 GB |
| Prints (~200–600) | — | 0.2–0.6 GB |
| Business ledgers (9 y) | ~200–800 pp | 0.2–0.9 GB |
| Memoirs (handwritten) | ~100–500 pp | 0.1–0.6 GB |
| Documents / ephemera | ~100s | 0.1–0.5 GB |
| Objects (4–8 shots each) | ~40 | ~0.3 GB |
| Thumbs + index (derived) | — | < 0.1 GB |
| **Total** | | **~4–9 GB (mid ~6.5 GB)** |

- **The estimate is a floor.** The user reports at least this much again in miscellaneous letters, accounts and photos (2026-08-02) — realistic total **8–18 GB (mid ~13 GB)**.
- **Decision (user, 2026-08-02): an external hard drive is bought** — the annual 3-2-1 export target (PRD §18.6) and the overflow store.
- **Open decision:** the archive's home is Drive (PRD §7) and the free tier caps at 15 GB — at ~13 GB mid-estimate it may not hold. Options: Google One 100 GB (~£1.6/mo, keeps the architecture) or the hard drive becoming the primary home with Drive as a partial mirror (breaks the "Drive is the home" principle). Recommendation: Google One; not pre-empted until the real volume is known.

### 16.9 The curation worksheet — connecting a letter

The two-letter exercise (2026-08-02) taught that linking is a *process*, not a batch step. Import classifies every mention into one of four buckets; the reviewer works the worksheet once, at import, while the letter is in hand; every answer teaches the standing knowledge so the next letter starts smarter. Extends §16.3's minimal prompt and shapes the queue (§16.5).

**The four buckets** (applied to every mention — people, places, themes, relationships, text links):

| Bucket | What it is | Decided by | Action |
|---|---|---|---|
| **Identified** | named in the text and unambiguous against the standing cast/places (writer, recipient, "Mrs Hartley" in the salutation) | import, from run defaults + the alias table | link `confirmed` — zero taps |
| **Proposed** | an inference worth one tap (BF→Owen, a place mention that might be a record, a theme the letter belongs to) | import, from heuristics (referential density, alias matches) | link `proposed` — one tap |
| **Question** | needs the reviewer's knowledge, not a tap (Harper's surname, who the Marlock people are, what "Lex" means, is the date right) | the reviewer | a bounded per-letter question list, asked at import while the letter is in hand |
| **Unresolved** | stays text (F7) — no record, no link | the machine, by absence | recorded as a known-unknown; recurrence is the trigger to revisit |

**Cross-checks against standing knowledge** (the machine's job, run before the questions):

- **Chronology check.** Place the letter on the known timeline (marriages, moves, births, the letters' era). A theme that contradicts confirmed chronology is a *flag*, not a proposal — the 1977 "courtship" failure was a chronology error, not a tagging error.
- **Standing cast.** Named-without-introduction = long-established actor (referential density) → `proposed`, plus a question when the identity itself is unknown.
- **Precision.** Prefer the specific over the general: Dunmoor Primary School over Dunmoor; Harrowgate over Tynefield. Ask for precision when the text is ambiguous (the house in Marlock, address unknown).
- **Broader place identification (2026-08-03).** Informal or referential names are place candidates, not just proper names — "the old ford" is a place (PRD §19, requirement 6).
- **Actuality, not recurrence.** A mention becomes a place record when it is an actual place the family engaged with ("a turkey" is dinner; "Tornia" is where Dale and Harper lived). Recurrence decides later re-checks, never admission.
- **Co-occurrence ≠ relationship.** A person written about from a place is not *at* the place (Harper and Pinewood Court). Connections render co-mention, never implication. **Requirement (2026-08-03):** never make the conflation mistake again — a comment mentioning both a person and a place does not link them. Example: the comment "Wilma is Miles's sister. Mrs Hartley was my teacher in year 2 at Dunmoor" placed Wilma and Miles at Dunmoor with no evidence (the place belonged to Mrs Hartley's fact only). The fix was removing the place ref, not the people: a comment's `places[]` must belong to the comment's own claim.
- **Presence attribution — person ↔ place (2026-08-03).** The co-occurrence rule is the general case of a family of bugs this session shipped and fixed; the machine must run all of them when proposing `people[]`/`places[]` links (this is what the per-place `people` list on a `places[]` entry is for — §4):
  - **In-the-item ≠ at-the-place.** A person in `people[]` — writer, recipient, mentioned — is not automatically at the item's places. Attribution is per-place; the item-level fallback (no `people` on the place) applies only to genuinely single-participant items. (Fern, the 1977 letter's recipient, was at none of its six places.)
  - **A letter's geography belongs to its participants, not its recipient.** Default: the writer is at the letter's places; the recipient is at one only when the text puts them there. Role is never itself evidence — in either direction: Fern got everything she shouldn't, and Mrs Hartley lost Dunmoor she should have had ("remembering times spent in your class"). The text decides; the worksheet confirms.
  - **Presence is date-bounded.** A proposed person↔place link must survive the chronology: was the person alive, born, or still living there at the item's date? (Eli "proposed" on the Sunlight photo, 1982 — not born until after the trips stopped.) The machine flags date-contradicting proposals as *questions*, never silently drops them — the chronology check's rule. This is why `dob` is a schema seam (§4) and interviews politely discover it (PRD §19, req 9).
  - **Geography ≠ presence.** A route, region, or proximity does not put a person at a place: the Grand Union passes through Marlock, but Halfway is evidenced at Innisfree. Nearby/on-route/same-region matches are *questions*, not proposals.
  - **Family membership ≠ presence.** Named in a family story, sharing a surname, or related to someone at a place is not being there — the Hale-family story places Harper, Miles and Vera at Marlock ("the people who Harper saw in Marlock"), and Owen and Dale are only reference points.
  - **Unattested links are removed, not annotated.** A place the text doesn't support is dropped from the item (Marlock from the Aldgate-addresses story), never kept "with a note" — the note becomes a claim the text never made.
  - **Ask, don't guess.** When presence is genuinely ambiguous — a group photo, an event spanning years, several plausible people — the worksheet's **Question** bucket is the answer, not a `proposed` link: "who was actually there?" is a bounded per-item question (PRD §19, req 8). `proposed` is for a confident inference worth one tap; ambiguous presence is a question.

**The learn step.** Every review answer updates the standing knowledge the next letter resolves against: aliases (Lex, mamie, BF), relationships (Miles–Wilma), place precision (Marlock = the Hales' house), chronology (long married by 1977). The worksheet is how the archive gets smarter as it is curated — the identity tables are content, and curation is their author. No new schema: the buckets map onto the existing `confirmed`/`proposed` statuses plus a queue question type (Slice 2). **Regeneration (requirement, 2026-08-04):** the derived tables — including the relationships — must be regenerable programmatically from the artifacts: the family structure is stated verbatim in the dated, attributed interview answers ("Mum was Nora…", "Wilma is Miles's sister", "Owen's parents Miles and Vera") and the letters, so the shared engine runs extraction + the propose/confirm seam over the primary data in the batch path, at import, and at capture — never hand-maintained, never hardcoded (the 2026-08-04 regression: the relationships lived only in the projection and a merge dropped them; the archive now holds the table and the tests fail on drift).

**Disputed evidence.** When a new dated, attributed comment conflicts with a generated assertion (Harper's own account, 2026, vs the 1977 letter's "nervous breakdown or similar"), the assertion leaves the generated text (bios, captions); both accounts remain in the archive, each attributed to its source. The app arranges evidence; it never adjudicates (PRD §10).

**Open question — testimony provenance (2026-08-03).** The interview curation surfaced it: the narrator's judgemental asides are authentic but risk family arguments, and hearsay is not evidence. Should the worksheet/queue mark each testimony's epistemic status — *evidenced* (artifact-backed), *first-hand*, *commentary*, *guess*, *second- or third-hand* — and should interviews probe for that distinction at capture time? (Canonical requirements: PRD §19 — interview-module requirements.)

### 16.10 Dedupe & integrity hashes (2026-08-03)

- **Per asset**, the sidecar stores `hash` (SHA-256 of the file bytes) and `phash` (perceptual hash — a rescan at different settings or a slight crop still matches). Transcription text, when it exists, adds `content_hash` (SHA-256 of the text) — a re-typed duplicate letter matches on content.
- **Derived `hashes.json`** — regenerable from sidecars, maps asset path → `{sha256, phash}`; the fast path for archive-wide scans and the 2060 integrity check (a reader in 2060 can verify every file).
- **Letter-level fingerprints** — the sorted list of a letter's page hashes identifies the whole letter, so dedupe works at both the page and letter level (an accidental rescan of one page vs a re-imported whole letter).
- **Policy (2026-08-03):** exact sha256 match → the file is byte-identical → skip silently and report (first import wins; nothing deleted). Perceptual match above threshold → show both scans to the reviewer with their observable properties (resolution, blur, crop, lighting) and let them pick: if one is clearly better it is the one imported (the rejected scan never enters the archive, so nothing is deleted); if they are equivalent, keep the first without asking; if the comparison is genuinely ambiguous, ask. Dedupe runs (a) within the batch, (b) against the archive at ingest, (c) as a standing report in `tools/check-archive`.
- **Deps:** pillow + imagehash (dev-only, uv-managed).

### 16.11 Import admin & resumability (2026-08-03)

**The reviewer's import surface is the web app, not a terminal.** `tools/import serve` runs a localhost API; the existing app gains an admin view (`#/import`) that drives the worksheet, dedupe and OCR review with the same logic the CLI uses — one core, two clients. The API listens on localhost only; the deployed app has no API, so the admin view renders a "import server not reachable" card — the admin surface is laptop-local by construction, never part of the static host.

**Scan-ahead: the inbox is an append-only drop zone.** Scanning (possibly by someone else) outpaces processing by design. The pipeline is stage-decoupled so nothing blocks the scanner:

- **ingest** — fast, idempotent: normalize pages, hash them, detect new jobs; never modifies the inbox — catalogued batches are marked in their sidecars (MULTI-DOC-IMPORT-PRD §3.5).
- **worksheet** — human-paced: boundaries, dates, defaults, dedupe; resumable mid-stack.
- **catalog** — atomic sidecar writes (temp + rename).
- **read** — an async OCR queue: items pending reading sit in the queue and fill in as the backend processes them (batch/rate-aware); status per item `pending → reading → draft`.
- **publish** — lags; runs on demand.

**The session journal** makes the worksheet crash-safe and resumable: per-batch `state.json` in a work dir records which pages are seen, which boundaries/dates/defaults are decided, and each letter's status; written atomically after every confirmed letter. Re-running resumes exactly where the session stopped — new scans append, never re-prompt. Processing order is arrival order.

### 16.12 The live system: multi-user store & corpus generation (direction, 2026-08-03)

The single-curator assumption is dead — **multiple family members curate** (2026-08-03). Flat-file last-write-wins does not hold for concurrent editors, and a flat JSON index is the wrong shape for corpus-scale work (stories, bios, themes generated from the whole archive; embeddings; aggregations). Three layers, preserving the durable contract:

1. **The folder (unchanged)** — sidecars + assets, always complete and current, written through on every committed change; backup = copy; the 2060 contract; the app replaceable. The folder is the durable materialization — the data is always resurrectable from it.
2. **A real store for the live system** — transactions, multi-user conflict handling, the queue, sessions, audit, queries. Managed cloud, consistent with the Drive precedent (a family Google account already holds the archive). Recommendation: **managed Postgres + pgvector** (Supabase/Neon) — full-text search, vector search and multi-user in one place. *Not a lock:* the folder can rebuild it, and it materializes the folder — both directions.
3. **The generation layer** — embeddings + vector similarity, and the LLM work (stories, themes, bios over the corpus) as **batch, local** jobs — PRD §12: ML runs locally, never third-party cloud processing of family content. Output enters via propose/confirm; the session's honesty rules apply (generated text is proposed, disputed facts omitted, attributed).

**What changes vs §5:** the reading side stays static; the curation/analysis side gains a managed backend. Hosting stays out of the house; "nothing paid" is revisited (free tiers; the family's own account). SQLite remains right for one job: the laptop's local generation batch (read-only analytics over a pulled copy) — as a live multi-user store it is out, single-writer.

### 16.13 The capture pipeline — the two-zone workspace (2026-08-13)

Requirements: `docs/prd/MULTI-DOC-IMPORT-PRD.md` (R1–R9). Supersedes the
older §16.1/§16.3 conventions of an "inbox" of our job folders: the user's
scan area is **theirs** (R1) — we adopt its folders by content, never by
path convention.

**The two zones.** The user's scan area (on the big disk: `scans/` — PhotoScan, and whatever the user creates) is read-only to us. Our workspace is the sibling folder **`Loft`** at the disk root (decided 2026-08-13 — alongside the user's `scans/`, not inside it) holding everything we produce:

```
Loft/
  registry/<batch-id>.json         one record per adopted user folder
  work/<batch-id>/                 derived stages, in trust order
    oriented/page-NN.jpg           correct way up (Rule J, before any reading)
    ocr-raw/page-NN.txt            engine OCR, unverified
    ocr-guess/page-NN.txt          machine draft (transcription_status: draft)
    ocr-confirmed/page-NN.txt      user-verified; archived on confirmation
  archive/                         the durable knowledge (confirmed only)
    assets/<item-id>/              item.json + page-NN.jpg + transcription.txt + thumbs
    people.json places.json orgs.json themes.json items.json ...
  projection/                      deployable: reduced-res images + derived JSON
```

Paths: `tools/loft_paths.py` — `USER_SCAN_AREA` (`scans/`), `WORKSPACE`
(`Loft/`), `REGISTRY_DIR`, `WORK_DIR`, `ARCHIVE_DIR`, `PROJECTION_DIR`. The
archive relocated from `scans/Loft/archive/` to `Loft/archive/` (2026-08-13,
558 files, size-verified). Register-in-place (decided 2026-08-13): adopted
external folders are hashed where they sit — never copied into the
workspace; the raw scans stay single-source.

**Registry records.** `registry/<batch-id>.json` (batch id is ours and
stable; never the user's folder name): `path_last_known`, `fingerprint`
(sorted page hashes), `label` (curator-entered, free text), `status`
(`pending → importing → done | superseded`), `boundaries` (item/page
mapping once decided). The label never appears in the user's folder name.

**Re-association after user reorganisation.** Each run re-verifies every
registered folder: fingerprint found at a new path → re-link (automatic);
fingerprint split/merged across folders → semi-automatic with a manual
fallback; pages added → fingerprint grows, new pages adopted; pages
removed → flag for review; folder not found → flag; reviewer points or
supersedes (archive copies remain). Nothing in the user's area is ever
written.

**Hashes & dedupe (extends §16.10).** Two duplicate kinds, two mechanisms:
duplicate *file* = exact `sha256`; duplicate *scan* (same document
re-captured) = `phash` similarity above threshold. Per page: sha256 +
phash, the phash taken on the **oriented** form so rotation/re-encode does
not defeat it. Per batch and per item: fingerprint = sorted page hashes
(batch identity for re-association; item identity for whole-letter
duplicates). Dedupe runs at adoption and at catalog against the whole
known universe (user area + work stages + archive). Policy (§16.10):
exact match → skip silently, first wins; phash match → both candidates to
the reviewer with observable properties; never auto-delete or auto-merge.

**Raw-file naming — recovery from reorganisation (2026-08-13).** Every raw
page we produce is named `<batch-id>-NN.jpg` (e.g. `scan-20260813-1850-01.jpg`)
— the batch id is embedded in every file name. If the user renames the
folder, any file still says which batch and position it belongs to, so
re-association can start from names before hashing (the hash fingerprint
confirms). The work stages (`oriented/page-NN.jpg`, …) keep plain page
names — they are ours, never reorganised. External files keep their own
names; adoption hashes them.

**Write-then-rename everywhere.** No component publishes a file a reader
could see half-written: every produced file (registry records, stage
outputs, archive sidecars) is written to a temp sibling, flushed, then
renamed — `tools/atomic.py` `atomic_write`, the one helper, used by the
store's `write_new` and by every component (2026-08-13). The batch folder
itself appears atomically (staging dir rename).

### 16.14 The pipeline components (2026-08-13)

The capture pipeline is a chain of components, each owning one stage; the
**workspace filesystem is the interface between them** — a component reads
its input stage (the user's folder or a `work/<batch>/` stage dir + the
registry record) and writes its output stage + the registry status. No
component calls another; no shared in-memory state; each is independently
runnable, resumable, and replaceable.

| Component | Input → Output | Status effect |
|---|---|---|
| `capture` (tools/scan.py) | scanner → pages in the user area + registry record (label, hashes) | `pending` |
| `adopt` | an external/preexisting folder → registry record (register-in-place) | `pending` |
| `orient` | user pages → `work/<batch>/oriented/` (Rule J) | `importing` |
| `ocr-raw` | oriented pages → `work/<batch>/ocr-raw/` (tesseract) | `importing` |
| `ocr-guess` | ocr-raw → `work/<batch>/ocr-guess/` (vision model draft) | `importing` |
| `review` | oriented + ocr-guess → `ocr-confirmed/` + `boundaries` (the IMPORT-PRD flow, user-paced) | `review` |
| `catalog` | confirmed pages + transcript → `archive/assets/<id>/` (draft items) | `done` |
| `publish` | archive → `projection/` (reduced-res) | — |

**Parallelism.** Batches are independent; stages within a batch are
sequential (orient before any reading; ocr-raw before ocr-guess). The
driver walks the registry and fans out per-batch stage jobs, so capture
runs while orient/OCR process earlier batches (scan-ahead, §16.11) and the
user reviews batch *N* while the machine works *N+1*. Each component
re-runs idempotently (its output stage is a cache; re-running regenerates
it) and never touches the user's area.

**Content routing (2026-08-13, requirements R10–R12).** Batches are mixed:
cursive letters, print, photographs, drawings. A `classify` stage runs
FIRST (before orientation — photos need neither orientation nor OCR): a
local zero-shot image classifier (open_clip, MobileCLIP-S0) decides
photo/drawing vs text page; within text, the orientation stage's tesseract
strong-word density (rotations.json) decides print vs cursive (real data:
cursive pages 7–58 strong words, the printed reference 1185). Photos and
drawings are flagged as image items and never transcribed. Orientation and
OCR run only on text pages.

**The HTR stage uses the field's tooling, not hand-rolled line detection
(2026-08-13, user: "is there not prior art?").** Cursive pages are read by
the established historical-document stack — kraken (7.x, PP-OCRv6-based
models trained on historical handwritten AND printed text) with the orli
layout model for text-line baselines and reading order. The user's layout
cases (a corner text box, a `}` joining two lines with an annotation,
marginal notes, a printed form filled in cursive) are precisely what
trained layout detection exists for; a projection-based line splitter is
the naive approach and is not used. The pipeline order becomes:
`classify → orient (text pages) → route → htr (cursive) / tesseract
(print) → guess → review`.

**The transcription backend decision (2026-08-14, user: "let's stop
there, this is good enough").** After an evidence comparison on the
family's own pages, the default transcription backend for cursive/mixed
pages is the **vision-language model** (`tools/vlm.py`, the opencode-go
vision role mimo-v2.5) — not the local TrOCR stack and not a specialist
OCR API. The evidence on real pages: near-perfect pure-cursive and
mixed-layout transcription (page-03's callout box, postmark, address and
salutation all read correctly); ~85% word accuracy on the medal card's
hardest element (handwritten digits in a dense form); ~11K tokens/page
(~$2–15 per 1,000 pages at mid-tier rates). The local orli+TrOCR stack
(segmentation OK, recognition garbage on the test pages) and the
specialist OCR APIs (Azure Read `tools/ocr_azure.py` — client ready,
untested on real pages; Transkribus — UI-bound on individual plans,
~10× the price) remain as alternatives behind the same seam
(`LOFT_HTR_BACKEND=vlm|local`, env-selected). The per-page VLM output
is recorded in a sidecar (`ocr-raw/<stem>.vlm.json`, the token usage) so
re-runs skip transcribed pages and the cost is auditable.

**Scan UX (decided direction).** The capture command identifies the job at
scan time: `make scan-docs ARGS="--label 'Box 1 — Letters 1977'"`, or a
prompt when no `--label` is given ("Envelope/pile label — what's written
on it?"). The label is written into the registry record at scan time
(never into the folder name) and rides through to the review prompts.


**Decisions — RESOLVED (user, 2026-08-03):** managed Postgres + pgvector on **Supabase**; **a small number of family curators** (a simple per-field last-write-wins + audit-log conflict story suffices; the far-future possibility of hosting *other families* that must never see our content is a tenant-isolation seam — the existing contributor-ID namespacing, §14 — and is not built now); the generation batch runs on **the reviewer's laptop**.

### 16.15 The two-app deployment (2026-08-14, user: "this is really two separate applications")

The system is two applications, one codebase, two deployment profiles. The
heavyweight offline backend runs at home (where the scanner and the durable
disk are); the frontend — viewing, transcription verification, and the
identity-extraction chat — is hosted cheaply in the cloud. The split maps
onto what already exists: `tools/` is the backend; `app/` + the review/chat
server is the frontend; `loft publish` is the bridge.

**Backend (home):** the capture pipeline (scan → adopt → classify → orient →
transcribe → guess), the archive (the durable folder), `loft publish`, and
the archive's write seam. The scanner and the 3.2 TB disk live here, so the
pipeline stays close to both.

**Frontend (cloud, cheap):** the static browse surface (the projection) on a
static host, plus a small API server for the interactive surfaces —
transcription verification (the review gate) and the identity-extraction
chat (IMPORT-PRD / INGEST-PRD flows). The family content is accepted in the
cloud (the local-only mode remains an option, 2026-08-14).

**The sync contract (decided direction): the backend owns the write seam;
the frontend proposes, the backend records.** The frontend never writes the
archive. Its confirmed outputs — verified transcriptions, identity
proposals, document boundaries — POST to the backend's sync API; the
backend validates them against the model (the `Item`/`Person`/`Place` write
seam) and appends to the archive (append-only holds in exactly one place),
then re-publishes the projection. The frontend↔backend link rides Tailscale
(the pattern this house already uses). Read path: the projection deploys to
the static host for browse; the interactive flows read the standing
knowledge (identity tables, work-stage texts) via the backend's API.

Rejected alternatives: the folder-as-sync (Syncthing/cloud bucket — moves
the append-only discipline to sync-time reconciliation and invites
conflicts) and the managed-store middle layer as the sync medium (the
§16.12 direction — right for multi-user *curation* later, too many moving
parts for today's single-curator volume; the folder stays the durable
contract either way, and §16.12's materialization path remains the upgrade
route).

**Pending transcripts and the sync endpoints (2026-08-14).** The machine's
drafts and the not-yet-approved transcripts live on the frontend, in the
review surface's store — the backend serves them on demand
(`GET /api/sync/batch/{id}/drafts`: the ocr-guess texts + boundaries), and
the frontend keeps its own copy while they await the reviewer. The
confirmed outputs are pushed in real time to the backend
(`POST /api/sync/confirmations`): validated against the model, appended to
the work dir's ocr-confirmed + registry (status `confirmed`), the
projection re-published. **The catch-up (2026-08-14, user: "a sync
endpoint on the website for mopups"):** if the real-time push fails (the
laptop is off), the confirmation stays in the frontend's outbox
(`tools/sync.py` `Outbox` — atomic, append-only); the backend pulls
(`GET /api/sync/pending` on the website), appends what it receives, and
the website marks them received. Nothing confirmed is ever lost to a
failed push. The transcription-verification UI itself is a separate
ticket (frontend, third-party review libraries); the seams it consumes
are these endpoints + the CLI review gate's shared write path.
