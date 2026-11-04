# The deployments

> Component of `docs/TECHSPEC.md`. Status: **normative**. This is the one
> statement of the deployment shape; a component that implies a different
> shape is wrong.

There are **four code deployments and four managed services**. No server
we operate runs off-site; the remote backend is a serverless function.

| Deployment | Runs | Owns |
|---|---|---|
| **Local web service** (laptop) | `loft serve` — FastAPI, `LiveStore`, the write seam, Google auth | the SQLite database, the LAN API, capture/review/browse |
| **Local OS daemon** (laptop) | `loft work --watch`, `loft sync`, `loft export` | scan pickup, the pipeline, the outbox drain, the nightly human archive and operational backup |
| **Remote static web app** (Cloudflare Pages) | HTML/JS/CSS; reads the read model from R2 | browse, the review surface; writes commands to the backend; **no server code** |
| **Remote backend app** (Cloudflare Worker + D1) | one small API: chat/identify/re-read, command outbox, auth validation | the working state and the model calls; **no server to operate** |

| Managed service | Role |
|---|---|
| **Cloudflare Access** | family-only auth (Google); no auth code |
| **Cloudflare D1** | the tiny database: outbox, chat sessions, accounts |
| **Cloudflare R2** | the view images and the published read model (versioned releases + `current.json`) |
| **Cloudflare AI Gateway** | the model gateway; the key lives in the Worker |

## The remote backend app

It is a **Worker**, not a server: it holds the model key, accepts commands
into D1, runs the chat, identify and remote re-read calls over the published
facts, and serves the laptop's outbox pull. It does not write the archive; the laptop
is still the only writer of domain state. The static app is separate and
has no server code.

The Worker is the piece that makes chat and remote writes work while the
laptop is off. The laptop applies the queued commands and republishes the
read model when it returns.

## The read model

The remote app's data is published to **R2**, served through **one origin**:

- The app is at `archive.<domain>` (Cloudflare Pages). The Worker answers
  `/api/*` (commands, chat, identify, re-read) and `/img/<sha>` on the same
  hostname. **Cloudflare Access protects the hostname once**; the session
  cookie is first-party, so the app's fetches and its `<img>` requests are
  authorized with no CORS and no signed URL.
- Each publish is a **release**: the laptop uploads the release's JSON and
  images under a versioned prefix (`releases/<seq>/…`), then flips a small
  `current.json` pointer. The Worker reads the pointer and the release from
  R2 through a binding; the app never talks to R2 directly.
- A partial upload never goes live: the pointer still names the previous
  release. A rollback re-points to the previous release.
- **Images are content-addressed and immutable.** The Worker serves
  `/img/<sha>` with `Cache-Control: public, max-age=31536000, immutable` and
  caches the object at the edge (`caches.default`); the browser keeps each
  image after the first view. Repeat views cost neither a Worker request nor
  an R2 read.
- The laptop uses an **R2 API token** for the upload; the outbox pull uses a
  **Cloudflare Access service token**. The app shell is on Pages and changes
  rarely.

**What a release carries.** Two halves:

- **Browse:** `index.json` (the cards), `people.json`, `places.json`,
  `orgs.json`, `themes.json`, `transcripts.json`, the published search index,
  and the view images. Small enough to hold offline after one load.
- **Review:** `review/index.json` (the open claims and the batch/document
  strip) and one `review/<document_id>.json` per open document — its pages,
  rows, boxes and flags. A confirmed document is readable from browse; it is
  not republished as a review payload. To correct one, the reviewer reopens
  it: the command creates a claim, and the next release carries the payload.
  The remote review is the pending queue; the reopen's payload arrives when
  the laptop is on.
- **Never:** originals, the event log, the operational tables.

**The backend app is TS.** The existing chat/identify/re-read logic is ported to
the Worker; the port is accepted, not a reason to add another host. The
laptop's Python service stays the LAN writer.

## Images

The remote site must be **readable and checkable**, not a thumbnail gallery:

- **R2 stores one view image per page.** It is the image the reader opens
  and the image the reviewer checks rows on; there is no separate
  higher-resolution review copy. The resolution is set by the row check:
  if it is high enough to read, it is high enough to check.
- **No thumbnail-only tier.** The app's card/list preview is a rendering
  detail, not a second archive policy.
- **Full-resolution originals stay on the big disk at home.**
- R2's free tier is **10 GB**. The laptop measures the view images and
  sizes them to fit (WebP/AVIF at a resolution that still reads and checks).
  Start at **2000px on the long edge**; the view-image spike measures
  legibility and the archive's page count, then sets the final size. If the
  archive outgrows the budget, the answer is a more efficient encode or an
  explicit product decision — never a thumbnail-only site.

**Images are served by the Worker on the same origin**, at `/img/<sha>`,
from R2. That is one authorized hostname (Access once), no CORS, and no
signed URL to mint or expire. The immutable cache header plus the browser
cache means the first view of an image is the only one that touches the
Worker.

## Authentication

**Remote:** Cloudflare Access (Google) in front of the one hostname (Pages
and the Worker's routes); the family allowlist is the Access policy.

**Home:** the local service uses Google OAuth with the same family allowlist —
HTTPS, `HttpOnly`/`Secure`/`SameSite=Strict` cookies, CSRF, short sessions
with server-side revocation, body caps and rate limits. **Tailscale is the
remote network boundary, not the app auth**: the service is reachable on the
LAN and the tailnet, and every request still signs in with Google. The LAN is
not trusted.

**Logins:** D1 is the login authority. SQLite mirrors the accounts for LAN
auth, attribution and backup. A first remote sign-in while the laptop is off
creates a provisional account/person in D1; the laptop confirms it.

## The local web service and the local daemon are separate processes

They share one laptop and one database, and **only the service holds it**:

- the **service** is the only process that opens the database; it serves the
  LAN API, the at-home surfaces and the local write seam;
- the **daemon** never touches the database; it scans, runs the pipeline,
  drains the outbox and writes the nightly exports, calling the service's
  local API for every domain read and write.

The service never runs the pipeline. The daemon never listens; it is an HTTP
client of the service on localhost. The two are supervised together: if the
service is down the daemon's projection step waits and retries — the work
files are still written, but no domain write bypasses the seam.
`08-code-organisation.md` is the only code that speaks SQL.

## Nouns, grouped by the deployment that owns them

| Noun | Owner |
|---|---|
| `LiveStore`, `Change`, the event log, the projections, the content store | Local web service |
| Worker, reconciler, scanner | Local OS daemon |
| Sync agent, exporter, retention, derivative generation | Local OS daemon |
| `Snapshot` / read model | Cloudflare R2 (versioned releases + `current.json`) |
| `Outbox` (commands), chat sessions, accounts | Cloudflare D1 |
| `Backend` (chat/identify/re-read, auth validation) | Cloudflare Worker |
| `Derivative` (the view image), `Asset` bytes | Cloudflare R2 |
| `Auth` | Cloudflare Access (remote); Google OAuth + Tailscale (home) |
| `Model` calls | Cloudflare AI Gateway |
| The human archive, the operational backup | Local OS daemon writes; the big disk stores |

A noun that is not in this table does not exist. The `[shape]` decisions in
`09-decisions.md` are the ones tied to this table; the `[domain]` decisions
survive a change of deployment.

## Blast radius

| Change | Revisit |
|---|---|
| The remote backend leaves Cloudflare | `[shape]`: D3, D4, D11, D17, D20, D22; the Worker/D1 adapters; the Access + `/img` path |
| The managed services are replaced | `[shape]`: D4, D5, D11, D13; the static app's SDK/API calls; the image URLs |
| The auth provider changes | `[shape]`: D37, D38; the Access policy, the home Google client, the account mirror |
| The laptop becomes a home server | the deployment table; the daemon/service split; `[shape]` D2, D6, D12 |
| The database is replaced (SQLite → Postgres) | `[schema]`: D1, D7, D14, D16, D18, D27; `05-schema.md`/`06-schema-ddl.md` |
| The code layout moves to `loft/` | `[interface]`: D31–D36; `08-code-organisation.md` |

The domain decisions (D8–D10, D15, D19, D21, D23–D26, D28–D30) are
independent of the deployment shape.
