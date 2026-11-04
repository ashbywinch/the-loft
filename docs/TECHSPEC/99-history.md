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
