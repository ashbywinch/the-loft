<!-- Component of docs/TECHSPEC.md. See the index for the status. -->

Status: **history** — superseded designs, kept for the record. Never implement from this file.

## 13. Prototype build plan (next, after your approval)

- **Fake data:** `tools/fake-data` → 24 letters (lorem-ipsum, period-flavored filler, dated 1962–77), 12 CC0 photos (picsum / Wikimedia Commons, or the designer agent fakes them), 6 people, 4 places, 3 themes, 1 story ("The boats"), 1 street-view card stub. *(The projection is real content only — the lorem filler and invented photos are gone; the timeline's empty 1962–77 years are the honest state until the letters are scanned.)*
- **Files:** `index.html`, `app.js` (router + views), `styles.css`, `manifest.webmanifest`, `sw.js`, `data/` (generated).
- **Screens:** Home (today-in-history, wander, the doors), Timeline (decade→year→week), Item viewer (zoom + transcription toggle), Themes, one Story in reader mode, Cast, Places (cards + stub map), Search.
- **Test:** serve the folder, open on the **Android phone first** (the curation surface), then a tablet for browse; walk the D8 protocol from `DISCOVERY.md` — watch, don't ask.

---
### 16.12 The live system: multi-user store & corpus generation (direction)

The single-curator assumption is dead — **multiple family members curate**. Flat-file last-write-wins does not hold for concurrent editors, and a flat JSON index is the wrong shape for corpus-scale work (stories, bios, themes generated from the whole archive; embeddings; aggregations). Three layers, preserving the durable contract:

1. **The folder (unchanged)** — sidecars + assets, always complete and current, written through on every committed change; backup = copy; the 2060 contract; the app replaceable. The folder is the durable materialization — the data is always resurrectable from it.
2. **A real store for the live system** — transactions, multi-user conflict handling, the queue, sessions, audit, queries. Managed cloud, consistent with the Drive precedent (a family Google account already holds the archive). Recommendation: **managed Postgres + pgvector** (Supabase/Neon) — full-text search, vector search and multi-user in one place. *Not a lock:* the folder can rebuild it, and it materializes the folder — both directions.
3. **The generation layer** — embeddings + vector similarity, and the LLM work (stories, themes, bios over the corpus) as **batch, local** jobs — PRD §12: ML runs locally, never third-party cloud processing of family content. Output enters via propose/confirm; the session's honesty rules apply (generated text is proposed, disputed facts omitted, attributed).

**What changes vs §5:** the reading side stays static; the curation/analysis side gains a managed backend. Hosting stays out of the house; "nothing paid" is revisited (free tiers; the family's own account). SQLite remains right for one job: the laptop's local generation batch (read-only analytics over a pulled copy) — as a live multi-user store it is out, single-writer.

**The story-capture endpoint migrates with the store:** when the hosted
store lands, the same contribution endpoint lives there and the local
story-capture server is deleted — no shims, clean cutover.
### 16.15 The two-app deployment (user: "this is really two separate applications")

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
cloud (the local-only mode remains an option).

**The sync contract (decided direction): the backend owns the write seam;
the frontend proposes, the backend records.** The frontend never writes the
archive. Its confirmed outputs — verified transcriptions, identity
proposals, document boundaries — POST to the backend's sync API; the
backend validates them against the model (the `Item`/`Person`/`Place` write
seam) and appends to the archive (append-only holds in exactly one place),
then re-publishes the projection. The frontend↔backend link rides Tailscale
(the pattern this house already uses). Read path: the projection deploys to
the static host for browse; the interactive flows read the standing
knowledge (identity tables, work-stage texts) via the backend's API. The
server serves `/data/*` from its OWN configured projection directory
(`loft serve --data`), never from the app shell's folder — one source for
what it publishes and what the browser reads.

**The user's requirements:**

*R1 — Live updates.* The user sees their confirmed transcriptions reflected
on the site immediately — the projection re-publishes as part of the
write seam, so the static browse surface picks up the new content on the
next load.

*R2 — No data loss.* A review confirmation survives a connectivity loss or
server crash: the browser stores it in a localStorage outbox before the
POST, and on every subsequent page load the outbox is retried. Mid-typing
edits are also persisted to localStorage per (batch, document) — VR9
resumability. The maximum window of loss is the text currently in an
unfocused input field (a few characters, not a whole line).

*R3 — At-least-once delivery.* The review confirmation is pushed to the
archive ASAP (the browser POSTs on "Confirm & Next"); if the server is
unreachable the outbox retries on every subsequent load. On reconnect
the confirmation arrives within one page load.

*R4 — Idempotency.* Duplicate confirmations are harmless: the write seam
(`record_confirmation`) replaces by pages (boundaries are identified by
their page set, and the item the document became is superseded, not
minted twice). A duplicate POST produces the same final registry state.

*R5 — Long-outage resilience.* The frontend (cloud) also maintains a
**server-side Outbox** (`pipeline/sync.py` `Outbox`) backed by the filesystem
— atomic per entry, survives process restarts. When the home backend is
off (laptop shut, home server offline), cloud-hosted confirmations land
in this server-side Outbox. The home backend pulls them when it comes
back (`GET /api/sync/pending` on the cloud), records them, and marks them
received. Currently (single-server deployment) the server-side Outbox
exists but is not populated — the confirmations route records directly
because frontend and backend are the same process. For the two-app
deployment, the cloud profile stores in the Outbox instead, and the home
runs `loft sync-pull <cloud-url>` to drain it. The browser's localStorage
outbox bridges shorter outages (the cloud itself unreachable) and is the
primary resilience for the single-server deployment; the server-side
Outbox is the cloud's resilience for the two-app topology.

**Current implementation (single-server):**
- Browser confirms → POST /api/sync/confirmations → record_confirmation
  (validated, atomic, idempotent) → archive.publish. The projection
  updates immediately. ✓ R1, R3, R4.
- On POST failure (server off): the browser's localStorage outbox keeps the
  confirmation; retried on every page load. ✓ R2 (max loss: the unfocused
  input buffer — a few chars).
- The server-side Outbox is unwired until the two-app split; for the
  single-server the browser outbox is sufficient (there is no cloud↔home
  hop). ✓ R5 — when the single server is off there is no other server.

Rejected alternatives: the folder-as-sync (Syncthing/cloud bucket — moves
the append-only discipline to sync-time reconciliation and invites
conflicts) and the managed-store middle layer as the sync medium (the
§16.12 direction — right for multi-user *curation* later, too many moving
parts for today's single-curator volume; the folder stays the durable
contract either way, and §16.12's materialization path remains the upgrade
route).

**Pending transcripts and the sync endpoints.** The machine's
drafts and the not-yet-approved transcripts live on the frontend, in the
review surface's store — the backend serves them on demand
(`GET /api/sync/batch/{id}/drafts`: the ocr-guess texts + boundaries), and
the frontend keeps its own copy while they await the reviewer. The
confirmed outputs are pushed in real time to the backend
(`POST /api/sync/confirmations`): validated against the model, the agreed
document minted as an archive item (its `transcription.txt`) with the batch
boundary in the registry (status `confirmed`), the projection re-published. **The catch-up (user: "a sync
endpoint on the website for mopups"):** if the real-time push fails (the
laptop is off), the confirmation stays in the frontend's outbox
(`pipeline/sync.py` `Outbox` — atomic, append-only); the backend pulls
(`GET /api/sync/pending` on the website), appends what it receives, and
the website marks them received. Nothing confirmed is ever lost to a
failed push. The transcription-verification UI itself is a separate
ticket (frontend, third-party review libraries); the seams it consumes
are these endpoints + the CLI review gate's shared write path.

**The identification review (stages 7–8).** A document's agreed text is read
once for the people and places it names. `POST /api/identify/document/{id}`
runs the pass (`pipeline/identify.py`): the model names the entities, the pass
resolves each against the archive's identity tables — a known name links its
record, an unknown one mints a proposed record carrying the document's own
words — and the result lands as refs on the item (existing links kept with
their status, new ones proposed) and proposed records in
`people.json`/`places.json` (an unagreed record sits marked inside the table
it will join, never in a queue of its own). The item's own `identified` flag
keeps the document from being read again; it lives beside the refs it produced,
so a document that pre-dates the pass is read once on its first visit.
`POST /api/identify/decide` records one determination (attested / estimated /
pending / delete): the item's mention and the table record move together, a
confirmed record is never deleted by a mention's delete, and a proposal
another item still names stays. The portal's "Identify people/places" door
counts the documents with a transcription whose entities still wait and opens
the surface (`#/identify/<item id>`).

**Its UX is not settled.** The built surface lists every pending mention with
the four determinations; the agreed experience is the review chat's walk, one
entity at a time (PRD §9 R1, R4; `pipeline-stages-plan.md` — the entities
"enter the review chat"), which is unbuilt. The outstanding work and its
acceptance are WORK-PLAN §2. What is settled is the seam this section
specifies: read once, the determination writes the mention and the table
together, append-only.

---

## The legacy archive and capture

The pre-database file layout and the Drive-era capture, privacy and performance sections. The live architecture is `00-deployments.md` and `04-live-system.md`; this is history.

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


## 7. Privacy & security

- **No PIN — authentication is the archive account; the projection is family-only, not public** (user: "it's a website, not a bank card"; PRD F6: no public surface at all until accounts land, §15 — the earlier "open by design" posture is superseded). The projection carries metadata, **view images**, stories and transcriptions — **transcription hosting is the product** (PRD §6, §10); full-resolution scans stay at home.
- **No analytics, no telemetry, no third-party CDNs** for archive content. System font stack (or self-hosted fonts). Street view is the only external fetch.
- **The archive lives in Google Drive (its home), accessed via Google sign-in to a dedicated family archive account.** Files remain plain and open (PRD §18.8); real authentication gates full-res — stronger than the courtesy PIN on the public projection.
- **Model calls go through the family's chosen gateway** (Cloudflare AI Gateway today). There is no requirement to run models locally; the content is family-only and the family chooses the cloud posture per document. The scanner, originals and image work stay at home because the hardware is there, not because the model must.

---


## 8. Performance budgets (PRD §11)

- First meaningful paint ≤ 2 s on 4G; initial JS/CSS ≤ 100 KB.
- **Timeline:** decade → year rows → week rows; DOM virtualization (only visible rows in the DOM); 60 fps scroll; precision-aware placement.
- **Images:** thumbnails in every list; the **view image** on open; full resolution on the LAN; `loading="lazy"` + `decoding="async"`.
- **Index:** `index.json` (metadata only) loads first; `transcripts.json` (heavy text) lazy-loads when search or reading needs it. Budget: ~2–5 MB index + ~5–10 MB transcripts at 10k items — segmented by decade if it grows beyond.

---
