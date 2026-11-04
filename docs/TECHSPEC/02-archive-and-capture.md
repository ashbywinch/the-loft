<!-- Component of docs/TECHSPEC.md. See the index for the status. -->

Status: **mixed** — §3–§4 are the legacy file format (superseded by the human archive in `07-exports.md`); §5–§11 are current.

## 3. Archive layout (the legacy file format)

> This is the pre-database layout, kept for the migration and the historical
> record. The live schema is `05-schema.md`/`06-schema-ddl.md`; the human
> archive export is `07-exports.md`. Do not treat this layout as canonical.

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
- **Primary vs derived (requirement).** *Primary data* — scans, photos, story text, testimonies, anything a user provides or states directly through the UI — lives in the archive as content files plus sidecars, in a form a reader in 2060 can open. *Derived data* — descriptions, identified people/places/themes/pronouns, the links between documents and people/places, relationships, the index and transcripts — is computed by one shared engine (`tools/projection.py`) from the primary data **only**, and is never hand-edited: not in the projection, and never the only copy. The engine runs in the batch publish path, in scan import, and in the site-capture save path — one implementation, three entry points, no duplication.
- **Append-only (requirement):** no file in the archive is ever edited or deleted — a change is a new file that supersedes the old one, and the old file stays forever. **One documented exception:** the proposed-queue reject path (`reject_proposed_person`/`reject_proposed_place`) deletes the *proposed* record file via the store's single `delete` — a proposed record is a transient review work item that has never been published, not an artifact; everything that has ever shipped stays append-only. A sidecar's first version is `item.json`; a supersession is a new self-contained file `item-2.json`, `item-3.json`, … (the full metadata again, plus `supersedes: "<previous file>"`). Primary content files version with their sidecar (v1 → `story.txt`, v2 → `story-2.txt`). Publish/rebuild tooling resolves the highest version; deletion is a supersession with `status: "deleted"`. The identity tables (`people.json`, `places.json`, `themes.json`) follow the same rule when written. The derived files (`index.json`, `transcripts.json`, `app/data/*`, thumbs) are regenerable caches — they are rebuilt, never treated as canonical, and hand-editing them is a bug (a test fails the committed projection against publish). All writes go through one append-only store (`tools/store.py`); tests inject a fake filesystem that fails on any write to an existing file. The identity tables live in the archive — never only in the derived projection — and the projection is regenerated from them.
- **Database vs project content.** The database is the archive: items, sidecars, people, places, themes, relationships, testimonies — everything the app renders. Project content — code, docs (PRD, TECHSPEC, PLAN, PRECEDENT), the private interview records, tests — records decisions and process; a fact becomes database content only as an attributed item (sidecar, testimony, person record), never by living in a doc. Interview transcripts enter the database as dated, attributed, verbatim story items (`told_by` the narrator, `source` the session, one item per session) — the project keeps its own working records under whatever names, but the archive never holds a doc called INTERVIEW.md. The same rule applies to code: real content never lives in a tool — `tools/demo_data.py` is the fictional demo generator (docs/coding-standards.md), and a test guards that the real family's names never appear in it.
- **The object model lives in one module:** `tools/records.py` defines Person, Place, Org, Relationship, Item and every closed vocabulary (relationship kinds, date precisions, item types/statuses); `archive.save_item` validates sidecars against the Item record at the write seam — a developer reads the model in one place, and the archive and the model can never drift.
- **The indexing posture (superseded by §17):** no server database — the folder is the store, and every derived layer (index, transcripts, hashes, search, future embeddings) regenerates from the sidecars. The derived layers upgrade as needed (pre-built search index, queue as a derived view); SQLite-as-*cache* (never the store — regenerable, so it preserves the invariant, but costs tooling) is the revisitable knob past ~100k items or if SQL queries are genuinely needed. **`edits.jsonl`** — an append-only, plain-text audit log (timestamp, item, field, old → new, who) for every write; the one truth file that is a log, not a cache, and the answer to the no-history gap (corrections currently overwrite silently).
- **IDs are stable forever:** `letter-1963-05-14-01`, `photo-1972-06-01`. Never renamed, never reused.

---

## 4. Data model (JSON)

> The record wire shape. The database schema is `05-schema.md` and
> `06-schema-ddl.md`.

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

- **Primary content is files, not fields.** A story item's text is `story.txt` in its folder, a letter/document's transcription is `transcription.txt` — referenced by the sidecar's `assets` (`{"kind": "story"|"transcription", "file": …}`), versioned with the sidecar. The sidecar JSON never carries the text; the projection's items embed it again at publish (the projection is derived, so embedding is fine there).
- **References carry a status** — `confirmed` | `proposed`. That is the ML seam (P4): models write `proposed`; humans flip to `confirmed` with one tap. No schema change when OCR/labeling arrive.
- **Dates:** ISO + `date_precision` (`exact | month | year | approx`). Approx renders at range start with a subtle marker; filters treat it honestly.
- **Person:** `{"id","name","years","relation","bio","photo"}` — thin bios are honest (PRD §4); never padded.
- **Person IDs are name-based** (p-alex, p-nora, p-owen) — first-name-only for the main characters where unambiguous; on a name clash the ID qualifies with the surname (p-harper-hale). IDs never change once catalogued.
- **Place:** `{"id","name","aliases","note","lat","lng"}` — `aliases` are the short forms the reader hyperlinks ("Dunmoor" → Dunmoor Primary School); the same alias seam as people (§16.4).
- **Relationships — RESOLVED (user):** `people.json` (the archive's people identity table) carries typed edges `{"a", "b", "kind", "label_a", "label_b"}` (`spouse | parent | sibling | inlaw | teacher`) — `label_a` is what B is to A. Person pages show a "Related" block; the family tree view (`#/tree`) renders generations from the edges. **Labels are gender-neutral by design** (`child`, not `son` — the model never assumes gender; the family's own gendered words live in the free-text `relation`/bio where the family itself used them). No runtime library; `tools/export-gedcom` remains future work for interop. **Relationships are derived, regenerable content:** the family structure is stated in the primary data (the interview answers: "Mum was Nora… Dad is Owen Hale. Mum's mum was Fern… Dad's sister is Miriam… His aunt is Wilma Hale", "Wilma is Miles's sister", "Harper… married Owen's brother Dale", "Owen's parents Miles and Vera") plus the letters, and the shared engine must be able to regenerate the edges from those artifacts (with the propose/confirm seam for what inference cannot prove). The archive is the only home of the table, and `tests/test_publish.py` fails if the projection ever drifts from it again.
- **Bios are derived, source-attributed text** — rebuilt when evidence changes (new letters, testimonies); disputed facts are omitted from generated text, never adjudicated (§16.9).
- **Aliases require attribution** — a form attested in an artifact's text ("mamie" in the 1977 letter, "Lex" in the 1990 one, "BF" — the reviewer's own word) or in a stored verbatim comment. Agent-invented forms ("Daddy", "Auntie", "Mummy") are not aliases. The canonical name always matches; actual names are not listed as aliases (§16.4).
- **`pronouns` (optional)** — only where the archive evidences them, never guessed: the person's own statement is the gold standard (Alex: they/them — the narrator's own words), then attested text by others (Nora/Owen via the narrator's interviews, Harper via the 1977 letter's "She's brought the three kids"). No attestation → no field. Rendered on the person page next to "Known as".
- **`dob` (optional, future seam)** — ISO date, discovered politely in interviews. Birth dates disambiguate presence by date: Eli is not at the Isle of Seagate because he was born after the trips stopped — an inferred presence the 1977-style attribution rule alone cannot catch (user).
- **A dated, attributed comment (testimony) is a story item**: `date` + `told_by` (the speaker) + verbatim text + `source` (WhatsApp, letter, recording) + `people[]` links to its subjects (PRD §19, G7) + `comment_on` (the artifact it responds to — reverse-looked-up and rendered as that item's "Responses"). Testimonies have no scans.
- **Theme/story:** `{"id","title","subtitle","items":[{"id","note"}]}` — the door, plus the arranged evidence in order. The app renders the arrangement; it never interprets (PRD §10).

- **Event items:** `type: "event"` with a closed `kind`
  (`birth | marriage | death | other`) — an attested happening (a concert a
  letter mentions) that flows through the item pipeline (timeline, filters,
  search). Person life events — a person's `dob` is a birth, `dod` a death,
  a dated spouse edge a marriage — are **derived at render time**, never
  stored as items (the identity tables stay the single source of truth).
- **Relationship dates:** a spouse edge may carry
  `date: {date, precision}` — the marriage date, the derive's input.
- **Clarification / reflection flags:** story items may carry
  `clarification: true` (an identity fact; must name people/items refs) or
  `reflection: true` (perspective; no events' date — dated by its told day;
  must name people/places refs), never both. The `published()` seam (data.js)
  excludes both from every discovery surface; they render only in their
  blocks on the pages they attest/mention (see PRD/MEMORIES.md).
- **Evidence flag:** a found record — a web capture, a
  directory page — is `evidence: true` (non-story types only; must name
  people/places/items refs). It is not a family happening: the `published()`
  seam excludes it from the timeline, and it renders on the pages it attests
  (the plaque capture lives on the Lark Inn's page). The recognition
  principle: the timeline shows only things someone in the family would
  recognise as having happened to the family at that time.
- **Sources:** a web-page document carries
  `sources: [{url, title?, accessed}]` (validated: http(s) url + access
  date) — rendered as hyperlinks on the item page. A web capture is dated by
  its **access day** (Rule K: the item is our capture).
- **Place coordinate precision:** `precision ∈ {"", exact,
  street, town, county, region, country, continent}` — the coarsest level the
  stored point honestly represents; the map draws an uncertainty ring for
  anything coarser than a pin. The import flow's geocoding proposes the
  precision (IMPORT-PRD Rule P).
- **Person↔place links require attestation:** a person is at a
  place only when the item's place ref names them in its per-place `people`
  list — co-mention in an item is not presence (the 2001 email's 91 people
  and 8 places link nobody). The map's person filter, the person page's
  Places row and the place page's People row all read through this one rule.
- **Person↔person links, same test:** a person page's People
  row shows the attested relationship edges only — co-mentioned names never
  render (the recognition principle: a person reading their own page would
  recognise everyone on it). Derived life events only place on the spine
  from point precisions (exact/month/year/approx) — "died after 1917" is not
  a 1917 happening; the fact stays on the person page.
- **Involvement dates:** a long-lived document (a family record,
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
- **The timeline spine:** entries (items + derived life
  events) pack into **count-sized, year-aligned periods** (~20 entries),
  rendered newest-first, each titled with its range plus a **theme hook**
  when one theme covers ≥2 items and a fifth of the period's items; a period
  never splits a year, and a year alone over the target is its own period.
  Counts are honest: "N periods, M items · K events".
- **Archive-quality evals (tests/):** the drift guard
  (projection ≡ publish) is joined by guards the system runs every gate:
  letter/document descriptions are specific and correspondence-distinct
  (test_descriptions), place notes never carry process jargon
  (test_place_notes), no catalogued story is dated by its told day without
  the narrator's words (test_story_dates), and **everything catalogued is
  visible somewhere** — timeline items' dates parse, fragments name existing
  targets (test_completeness).
- **Render once per page:** an item never appears twice on the
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

**Bulk scanning (sheet-fed + slide/photo scanners — user):** scanner output lands on a laptop; `tools/import` (Python) uploads to Drive with auto-naming; the reviewer tags on the phone. The phone camera is the ad-hoc path only; scanner output is the quality path (300 DPI).

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

- **Places door, v1:** curated place cards (the period, the artifacts from that era, dates) plus a **map view built on Leaflet + OpenStreetMap raster tiles** — free, no API key, standard attribution (user-approved). The prototype ships this; the non-tile dot view is the offline / tile-failure fallback — cards and text always remain.
- **Street-view cards** (PRD §10, Should): public imagery, not family content — Google Maps embed iframes (no key) or static images; degrade gracefully offline. Approved with the map (user).
- **Map modes (future — recorded, not built):** explicit all-places / date-range / person-subset views, and remembering where a returning user was looking last. The first-visit default already shows the whole archive — full date range, every place, world viewport — until the user narrows via the slider (the ±WINDOW window) or person chips (PRD §15).
- **Open: vague or unknown dates.** An item dated "circa 1972" has a dot whose year is a guess — the slider window must place it honestly via `date_precision` (never silently excluded, review: silent exclusion).
- **Person chips list only people who can appear on the map** (requirement): a person with no place-linked item (e.g. Jude — his only item is a placeless testimony) never gets a chip, because selecting them would filter the map to nothing.
- **A person's map = the places they are AT, per-place** (requirement): an item's `places[]` entry may carry an optional `people` list — the people who are *at* that place in the item's context; without one, everyone in the item's `people[]` is taken to be there (single-participant items). Never the places of items the person merely *told* — telling a story about someone else's location is not a link to it. **A letter's places are its participants' own geography, not the recipient's**: the 1977 letter's gigs (Aldgate, Walthamhollow) are Nora's, the knees-up (Easthaven) is Owen's, Marlock is Miles & Vera's house, Tornia is Harper & Dale's — and the recipient (Fern, "Chère mamie") is at none of them (user). A place listed without textual evidence is removed, not annotated (Marlock dropped from the Aldgate-addresses story, whose verbatim text never mentions it). **Being named in a family story — or sharing a surname — is not being at its places** (user): the Hale-family story's own claim is that "the people who Harper saw in Marlock are Owen's parents Miles and Vera" — Owen and Dale are reference points there, so Marlock belongs to Harper/Miles/Vera only; and Halfway's Marlock link was a guess (the canal passes through the town, but the boat is evidenced at Innisfree), so it was removed.
- **Attribution:** OSM + Leaflet credits on the map view; Google's terms for the embed. Both are public map imagery — the same privacy posture as street view, never family content.
- **Scale-aware markers** (requirement): no dots or labels at overview zoom — the heat map stands alone; dots appear at regional zoom (≥ 8), labels at street zoom (≥ 12), and a lone active place always gets its dot and label. The offline dot view always shows labels — its primary device is a tablet (no hover, PRD §11) and it has no heat map to protect (review). Rationale: at country zoom a red dot is a meaningless pixel and a label a blob — both obscure the heat map (user).

---

## 7. Privacy & security

- **No PIN — authentication is the archive account; the projection is family-only, not public** (user: "it's a website, not a bank card"; PRD F6: no public surface at all until accounts land, §15 — the earlier "open by design" posture is superseded). The projection carries metadata, thumbnails, stories and transcriptions — **transcription hosting is the product** (PRD §6, §10); full-res scans sit behind Google sign-in with the family's archive account.
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

- A **derived inverted index** (`search.json`, emitted by `tools/rebuild-index` with offline tf-idf weights) loads fast and deterministically — the browser no longer builds the index from raw text at load. Regenerable from sidecars like every derived layer.
- Fields: title, description, story, transcription, people, places, themes, source.
- **Transcription search is pattern discovery** (PRD §6): "migraine" across 830 letters surfaces the drift. This is a headline feature, not an afterthought — the search screen earns its place on Home.
- Ranking: exact > prefix > fuzzy; results filterable by type / decade / person / place.
- **Semantic search over testimony embeddings** (`embeddings.json`, derived and regenerable): "what did people say about the boats?" — the testimonies from §19 become the first real corpus for the ML seam.

---

## 11. Tools (`tools/` — no runtime dependency)

- `make-thumbs` — thumbnail pipeline.
- `rebuild-index` — derive `index.json` + `transcripts.json` from sidecars (folded into `publish` in the current implementation).
- `check-archive` — schema validation, dangling references, missing assets; the durability health check (PRD §18.9).
- `publish` — regenerates `app/data` from the archive: identity tables + sidecars + primary content files → index, people, places, themes, transcripts, assets, avatars; deterministic, tested, the only writer of the derived projection.
- `derive` — the shared derivation engine (`tools/projection.py`): resolved items, identity tables, index and transcripts. Used by publish (batch), import (scan ingest), and the capture server (site stories) — one implementation, never duplicated.
- `export-csv` — human-readable metadata + transcription export; part of the annual 3-2-1 export ritual (PRD §18.6).
- `fake-data` — the **demo** projection generator (fictional content only — a demo family, invented places and letters; no real names, guarded by a test). The real family's content lives in the archive and is published by `loft publish`.
- `import` — inbox → archive: assets + sidecars + thumbs + index; the minimal date prompt (§16.3).
- `upload-drive` — mirror the local archive to the dedicated Google Drive account (§16.6).
- `resolve-mentions` — transcription/address mentions → proposed people/places in sidecars (§16.4).
- Dev serving: `python3 -m http.server` or `npx serve` — zero install.

---

