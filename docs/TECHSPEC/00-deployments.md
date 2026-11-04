# The deployments

> Component of `docs/TECHSPEC.md`. Status: **normative**. This is the one
> statement of the deployment shape; a component that implies a different
> shape is wrong.

There are **four code deployments and four managed services**. No server
we operate runs off-site; the remote backend is a serverless function.

| Deployment | Runs | Owns |
|---|---|---|
| **Local web service** (laptop) | `loft serve` — FastAPI, `LiveStore`, the write seam | the SQLite database, the LAN API, capture/review/browse |
| **Local OS daemon** (laptop) | `loft work --watch`, `loft sync`, `loft export` | scan pickup, the pipeline, the outbox drain, the nightly human archive and operational backup |
| **Remote static web app** (Cloudflare Pages) | HTML/JS/CSS + the published read model | browse, the review surface; reads the model; writes commands to the backend; **no server code** |
| **Remote backend app** (Cloudflare Worker + D1) | one small API: chat/identify, command outbox, auth validation | the working state and the model calls; **no server to operate** |

| Managed service | Role |
|---|---|
| **Cloudflare Access** | family-only auth (Google); no auth code |
| **Cloudflare D1** | the tiny database: outbox, chat sessions, accounts |
| **Cloudflare R2** | the view images (readable and row-checkable) |
| **Cloudflare AI Gateway** | the model gateway; the key lives in the Worker |

## The remote backend app

It is a **Worker**, not a server: it holds the model key, accepts commands
into D1, runs the chat and identify calls over the published facts, and
serves the laptop's outbox pull. It does not write the archive; the laptop
is still the only writer of domain state. The static app is separate and
has no server code.

The Worker is the piece that makes chat and remote writes work while the
laptop is off. The laptop applies the queued commands and republishes the
read model when it returns.

**The backend app is TS.** The existing chat/identify logic is ported to
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
  If the archive outgrows it, the answer is a more efficient encode or an
  explicit product decision — never a thumbnail-only site.

Images are served from R2 (behind Access or short-lived signed URLs), not
proxied through the Worker: the Worker's 100k requests/day is for commands
and chat, not image bytes.

## The local web service and the local daemon are separate processes

They share one laptop and one `LiveStore`:

- the **service** is the only writer of domain state; it serves the LAN API
  and the at-home surfaces;
- the **daemon** never serves HTTP; it scans, runs the pipeline, drains the
  outbox and writes the nightly exports.

The service never runs the pipeline. The daemon never opens a socket. Both
use the same persistence boundary (`08-code-organisation.md`).

## Nouns, grouped by the deployment that owns them

| Noun | Owner |
|---|---|
| `LiveStore`, `Change`, the event log, the projections, the content store | Local web service |
| Worker, reconciler, scanner | Local OS daemon |
| Sync agent, exporter, retention, derivative generation | Local OS daemon |
| `Snapshot` / read model | Cloudflare Pages/R2 |
| `Outbox` (commands), chat sessions, accounts | Cloudflare D1 |
| `Backend` (chat/identify, auth validation) | Cloudflare Worker |
| `Derivative` (the view image), `Asset` bytes | Cloudflare R2 |
| `Auth` | Cloudflare Access |
| `Model` calls | Cloudflare AI Gateway |
| The human archive, the operational backup | Local OS daemon writes; the big disk stores |

A noun that is not in this table does not exist. The `[shape]` decisions in
`09-decisions.md` are the ones tied to this table; the `[domain]` decisions
survive a change of deployment.

## Blast radius

| Change | Revisit |
|---|---|
| The remote backend leaves Cloudflare | `[shape]`: D3, D4, D11, D17, D20, D22; the Worker/D1 adapters; the Access/signed-URL image path |
| The managed services are replaced | `[shape]`: D4, D5, D11, D13; the static app's SDK/API calls; the image URLs |
| The laptop becomes a home server | the deployment table; the daemon/service split; `[shape]` D2, D6, D12 |
| The database is replaced (SQLite → Postgres) | `[schema]`: D1, D7, D14, D16, D18, D27; `05-schema.md`/`06-schema-ddl.md` |
| The code layout moves to `loft/` | `[interface]`: D31–D36; `08-code-organisation.md` |

The domain decisions (D8–D10, D15, D19, D21, D23–D26, D28–D30) are
independent of the deployment shape.
