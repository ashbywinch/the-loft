# The record format, browsing surfaces and tools

<!-- Component of docs/TECHSPEC.md. See the index for the status. -->

Status: **current for §4, §6, §9–§11** (the record wire shape, maps, PWA, search, tools). The legacy file layout, Drive-era capture, privacy and performance are in `99-history.md`.

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


## 9. PWA & offline

- Manifest + service worker. Cache: app shell (always), index/people/places/themes (first load), thumbnails (LRU), view images (on demand).
- **Honest boundary:** the site's projection — metadata + view images — is cacheable, so the whole *browsable* archive works offline on any device. Full-res originals exist only in the archive at home. The review path is network-first: while the laptop is off it reads the published read model (view images + rows) and queues its writes as commands.

---

## 10. Search

- **SQLite FTS5** in the live DB is the search index; it is part of the published read model, so remote search works on the published state. Regenerable from the projections like every derived layer.
- Fields: title, description, story, transcription, people, places, themes, source.
- **Transcription search is pattern discovery** (PRD §6): "migraine" across 830 letters surfaces the drift. This is a headline feature, not an afterthought — the search screen earns its place on Home.
- Ranking: exact > prefix > fuzzy; results filterable by type / decade / person / place.
- **Semantic search over testimony embeddings** (`embeddings.json`, derived and regenerable): "what did people say about the boats?" — the testimony items are the first real corpus for the ML seam.

---

## 11. Tools (`tools/` — no runtime dependency)

- `make scan-docs` / `make scan-photos` — the scanner into the inbox (label at scan time).
- `make adopt` — register a folder in place as a batch.
- `make ingest` / `make pipeline ARGS="process|review|printed <batch>"` — the capture pipeline per batch; `review` is the confirmation gate.
- `./loft publish` — regenerates the published projection from the archive: identity tables + sidecars + content files → index, people, places, themes, transcripts, assets, avatars; deterministic, tested, the only writer of the projection.
- `./loft serve` — the app and the API at home.
- `./loft work` — the worker: one sweep, `--watch`, `--plan`, `--batch <id>`.
- `./loft capture-memory` — capture a narrator's memory.
- `./loft gedcom` — GEDCOM 7.0 import/export.
- `make verify` — the archive-quality data checks (`-m archive`); `make evals` — the real-model evals (`-m eval`).
- Dev serving: `make serve`.

---

