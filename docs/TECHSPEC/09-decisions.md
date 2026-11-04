# Decisions

> Component of `docs/TECHSPEC.md`. Status: **register**. The live-system
> decisions (D1–D41) are proposed; the pre-§17 decisions (§12/§15) are
> history.

## The register

Each live decision carries a tag:

- `[shape]` — depends on the deployment table in `00-deployments.md`.
- `[domain]` — survives a change of deployment.
- `[schema]` — depends on the database/typed-table choice.
- `[interface]` — depends on the code layout.

A change of shape revisits `[shape]`; a change of database revisits
`[schema]`; a change of code layout revisits `[interface]`. The `[domain]`
decisions survive all three. The blast radius is at the bottom.

### 17.13 Decisions

- **D1 [shape, schema] — The database is the system of record.** The plain-text archive
  is the nightly, lossless, human-readable export.
- **D2 [shape] — One host writes.** The laptop's Loft service is the only writer
  of domain state, and every write goes through its seam inside a
  `BEGIN IMMEDIATE` transaction. The worker and the sync agent are
  clients, not second writers; the Cloudflare backend never writes domain state.
- **D3 [shape] — Remote writes are commands.** Immutable, UUID-keyed,
  `entity_version`-checked, applied idempotently by the laptop.
- **D4 [shape] — The Cloudflare backend is replaceable for reads.** The published
  read model plus the caller's pending commands. It is the only copy of
  commands not yet pulled, so the outbox table is durable, replicated and
  never trimmed.
- **D5 [shape] — Originals stay home; the words and view images do not.**
  Scan pixels and full-resolution images stay on the big disk. Transcripts,
  stories, memories and review chat live in the Cloudflare backend behind
  family auth. The remote site serves **one view image per page**, readable
  and row-checkable; the same image is the reader's and the reviewer's.
  There is no separate review tier and no thumbnail-only policy. The
  resolution is signed off before the remote review surface ships.
- **D6 [shape] — Nightly, tiered, verified.** Nightly dumps and archive export;
  retention by tier; the export must be able to rebuild the DB.
- **D7 [schema] — SQLite at home.** No server database on the laptop;
  `synchronous=FULL` because the corpus is irreplaceable.
- **D8 [domain] — The archive stays append-only and scannable.** The DB and the
  snapshot are derived, gitignored, and never in the no-PII guard's
  layer.
- **D9 [domain] — No transaction spans slow work.** A model call, a file write or
  a network hop never holds the write lock; state-plus-work commands
  enqueue a job and commit their result separately.
- **D10 [domain] — One entity version, one export cursor.** `entity_version` for
  commands; `exported_through` for the export.
- **D11 [shape] — The outbox is permanent.** Progress is the laptop's
  `applied_through` cursor; the `command/applied` event is the idempotency
  marker. The cursor alone cannot protect an append-only decision.
- **D12 [domain] — A failed nightly is visible.** `last_verified_export_at` is
  shown on both surfaces, with a banner after N missed nights.
- **D13 [shape] — The backup contract is explicit and drilled.** Truth and domain
  projections rebuild from the operational backup; operational tables are
  reseeded; a monthly restore-and-compare is a gate.
### 18.11 Decisions

- **D14 [schema] — The truth is three append-only stores.** `events`, `content`,
  `schema_migrations`; everything else is a projection or operational.
- **D15 [domain] — Events are immutable.** A correction is a new event; a delete is a
  tombstone event; a repair is a compensation plus a withdrawal event.
- **D16 [schema] — The rebuild is a tested gate.** Drop, replay, compare; a
  projection that cannot be rebuilt is a bug.
- **D17 [shape] — Commands are events.** `received`/`applied`/`rejected`; the
  `applied` event is the idempotency marker.
- **D18 [schema] — Migrations are additive, nullable, and non-destructive.**
  Destructive changes are new tables plus rebuilds.
- **D19 [domain] — Item/document/page text is content-addressed.** A correction is a
  new sha; the old bytes stay. Short log lines may be inline in the
  immutable event.
- **D20 [shape] — The human archive is the viewer-facing current state.** Every
  browsable item, identity, theme and relationship; no version chains, no
  drafts, no proposed records. The operational backup carries the full event
  log and content store.
- **D21 [domain] — Stable flat item folders and generated indexes.** The path is the
  id; `INDEX.md`/`PEOPLE.md`/`PLACES.md` provide the browse.
- **D22 [shape] — The backup contract is explicit.** Truth + domain projections
  rebuild from the operational backup; operational tables are reseeded; the
  monotonic guard stops a backwards backup.
- **D23 [domain] — The human archive is the complete viewer-facing dataset.** Every
  browsable item, identity, theme and relationship; confirmed text but no
  drafts, proposals or model reasoning; sensitive items included and indexed;
  accounts and emails excluded. The hosted browse applies the family's
  visibility rule, not the archive. The Cloudflare backend holds the
  working state behind family auth.
- **D24 [domain] — A bad release is contained by withdrawal and compensation, not by
  a restore.** The nightly backup is the fallback.
- **D25 [domain] — Originals and previews are copied, never hardlinked.**
- **D26 [domain] — The human archive is readable without SQLite.** The backup carries
  `schema-truth.sql`, the event log and `content/` for the restore; FTS is
  optional.
- **D27 [schema] — The current state is typed.** Every `entity_kind` has its own
  projection table; scalar fields are columns, small nested records are
  JSON columns on that table, and query-critical edges are child tables.
  There is no generic entity table.
- **D28 [domain] — The review queue is claims.** A session has a subject and an
  actor; a decision names its subject; the queue closes only when no claim
  is open for the origin. Unfinished memories and failed integrity checks
  are claims.
- **D29 [domain] — The actor is a person.** `events.actor_id` is a person id, or a
  reserved system id for machine work. An account is an optional login
  attached to a person; the event log never stores an email.
- **D30 [domain] — Rows are the grain.** The confirmed `page_rows` are the letter's
  words; document text is a cache; a confirmed document must have an item,
  and the export compares the cache to the published text.
### 19.9 Decisions

- **D31 [interface] — One SQL package.** `loft/archive/live/` is the only code that
  imports `sqlite3`; every other layer uses `LiveStore`.
- **D32 [interface] — One write path.** `Change` is the unit of work; saves derive
  events; no caller builds an event payload.
- **D33 [interface] — Product-shaped reads.** Queries return paginated view records, not
  rows or `dict`s.
- **D34 [interface] — Domain errors at the boundary.** No `sqlite3` exception escapes.
- **D35 [interface] — A memory store proves the interface.** The same contract suite runs
  against SQLite and memory.
- **D36 [interface] — Export and sync use read views.** They never open the database or
  write SQL.
- **D37 [shape] — Logins are Google on both surfaces.** D1 is the login
  authority; SQLite mirrors accounts. The remote edge is Cloudflare Access;
  the home service uses Google OAuth with the family allowlist, HTTPS, secure
  cookies, CSRF and short sessions. Tailscale is the home network boundary,
  not the app auth.
- **D38 [domain] — The canonical chat transcript is SQLite.** D1 holds the
  live session; each message has a UUID; the laptop writes exactly one
  `review_messages` row.
- **D39 [shape] — The read model is an R2 release plus a pointer.** The laptop
  uploads `releases/<seq>/` then flips `current.json`; the app reads the
  pointer. The laptop uses an R2 API token; the outbox pull uses an Access
  service token.
- **D40 [shape] — The Worker runs chat, identify and remote re-read.** The
  initial row generation and transcription stay on the laptop; the Worker
  re-reads corrected rows from the published view image and queues the text.
  Identify reads the transcript, not the scan. The laptop applies every
  result.
- **D41 [shape] — The remote is one origin; the Worker serves the images.**
  Pages serves the app at `archive.<domain>`; the Worker answers `/api/*` and
  `/img/<sha>` on the same hostname; Access protects it once, so cookies are
  first-party and there is no CORS or signed URL. Images are content-addressed,
  served `immutable`, and cached at the edge and in the browser. The free
  Worker request budget is ample at family scale, and repeat views are free.


## Blast radius

| Change | Revisit |
|---|---|
| The remote becomes a server | `[shape]`: D1–D6, D11, D13, D17, D20, D22; `04-live-system.md` §17.5–17.6, §17.11 |
| The Cloudflare backend/services are replaced | `[shape]`: D4, D5, D11, D13; the static app's API calls; the outbox and read-model adapters |
| The laptop becomes a home server | `[shape]`: D2, D6, D12; `00-deployments.md` |
| SQLite becomes Postgres | `[schema]`: D1, D7, D14, D16, D18, D27; `05-schema.md`, `06-schema-ddl.md` |
| The code layout moves to `loft/` | `[interface]`: D31–D36; `08-code-organisation.md` |

---

## History — the pre-§17 decisions (superseded by §17.14)

These are kept for the record: the 2060 reader, the sidecar rationale, the
old hosting choice. They are not the live design. Where they disagree with
D1–D41, the live decision wins.
## 12. Decisions to confirm (your review)

| # | Decision | Recommendation |
|---|---|---|
| 1 | **Vanilla-first — RESOLVED (user)** | A framework adds no value at this scale and hand-rolling stays manageable. Not "React or nothing": small JS or a CSS framework (degrading well) remains acceptable; revisit during development if things get messy (§15) |
| 2 | **Drive is the archive's home (dedicated family account, official API, thin-client phone); site = published projection (metadata/thumbnails/stories); annual export is the durability ritual** | Yes — nothing stored on the phone, nothing hosted in the house |
| 3 | **Sidecar-first layout** (`item.json` canonical, index derived) | Yes — one bad file loses one item (P3.4) |
| 4 | **Street view + Leaflet/OSM map — RESOLVED (user)** | Public imagery only; OSM attribution; degrades offline |
| 5 | **Tools language — RESOLVED:** Python (user) | — |
| 6 | **Hosting target** — free static host for the app; archive home = Google Drive free tier | Cloudflare Pages (or Netlify / GitHub Pages) + Drive; nothing paid, nothing self-hosted |
| 7 | **Working title — RESOLVED:** "The Loft" (user approved) | — |
| 8 | **No PIN on the projection — open by design** (the archive account is the gate) | **SUPERSEDED (§7/F6):** no public surface at all until accounts land — the projection is family-only; nothing deploys before the F6 gate (PLAN/PLAN.md) |
| 9 | **Family relationships** — typed edges in `people.json`; person pages show relationship labels; `#/tree` renders generations | **RESOLVED (user)** — built in the prototype. **Alignment:** no genealogy *tooling* (the PRD anti-pattern) is not the same as no object-model standard — **GEDCOM X** is adopted as the object-model reference (person/relationship/agent/event/place/source vocabulary; **residence events replace the place-household field** — the standard's model is better); **date precision extended** with `before`/`after`/`between` so the mapping is lossless; `tools/export-gedcom` targets **GEDCOM 7.0** with a documented one-to-one mapping (excludes proposed links and proposed residence; stories shoehorn as NOTES on the people they reference); **`tools/import-gedcom`** is the inverse (ids recovered via REFN, places by name) and the round-trip is exact — verified by tests and on the real archive; both sides parse-verified with `gedcom7` (strict ABNF grammar) |
| 10 | **Live system store** — multi-user curation and corpus-scale generation need a real store; the folder stays the durable materialized contract | **RESOLVED (user)** — Supabase (Postgres + pgvector); small family-user set; generation on the reviewer's laptop; tenant isolation is a far-future seam (§14), not built |

---
## 15. Decision rationale (for future reviewers)

**Why no framework (user asked):** 1) *Durability* — the app is disposable but its code shouldn't be: vanilla files are readable in any editor in fifty years; a framework means `node_modules`, a build system, and a toolchain that rots. 2) *The budget* — 100 KB initial payload (P6); React + router + state is 300–500 KB before a line of our code. 3) *The app is small* — ~10 screens, no multiuser state, no real-time; frameworks pay off when state grows big enough to fight you. 4) *Zero maintenance tax* — no `npm install`, no lockfile churn, no build step to re-run; `python3 -m http.server` serves it. The honest counterpoint: at 40 screens with interdependent state, or with hired developers, a framework would win; the discipline that substitutes for it is small focused ES modules plus a ~50-line router. **Recorded decision (user):** a framework is judged to add no value at this scale, and hand-rolling complexity is not expected to overwhelm maintainability. Explicitly *not* "React or nothing": a small JS library or a CSS framework — especially one that degrades gracefully — may be adopted if it earns its place. Revisit during development if the code starts to get messy. The decision targets frameworks and build steps; it never ruled out classes (native ES2015) — the app has few value types so far, and the date model's JS twin (`PreciseDate`) will be the first (docs/coding-standards.md).

**Sidecar tradeoffs (user asked):** each item is a folder; `item.json` sits beside the scans; `index.json` is derived, not canonical. *Gains:* one corrupt file loses one item, never the archive; the index is a cache — always rebuildable; cousin merges are folder merges, no database conflict; the archive is human-readable without the app (the 2060 test); no migrations ever. *Costs:* metadata exists twice (trivial — JSON is cheap); bulk edits need an index rebuild (automated); cross-archive queries read the index so it must be fresh (two simultaneous editors is the only race, rare, last-write-wins acceptable). *Alternatives rejected:* one big `index.json` (every write rewrites the whole file; one corruption is catastrophic; merges fight) and SQLite (fastest queries, but binary — a tool must read it, bad for 2060 — and it is the database lock-in the PRD refuses). Sidecars are the durability-first middle.

**Why no PIN (user):** the PIN was a courtesy lock inherited from a pre-auth architecture; once real authentication (the archive account) gates everything intimate, the projection contains nothing sensitive — a PIN is ceremony with nothing behind it. Removed everywhere.

**Why scanners:** the sheet-fed scanner and slide/photo scanner are the bulk quality path (300 DPI legibility — upgrades R3); the phone camera is ad-hoc only; tagging stays on the phone.

---
