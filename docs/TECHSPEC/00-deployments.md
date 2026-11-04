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
| **Cloudflare R2** | the browse images, thumbnails and review derivatives |
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

**The backend app is JS/TS.** The existing chat/identify logic is Python;
it is ported to the Worker or shared as prompt/context data. The laptop's
Python service stays the LAN writer. That is the code cost of the Cloudflare
shape; a Python serverless host is the alternative if reusing the prompt
code matters more than one vendor and one free tier.

## Images

The remote site must be **readable**, not a thumbnail gallery:

- **R2 stores the usable browse image for every item** — the page at a
  reading resolution, not a thumbnail.
- **Thumbnails** are the grid preview only; opening an item loads the
  browse image.
- **The review queue** gets a higher-resolution derivative for the pages in
  progress (row review needs to see the writing).
- **Full-resolution originals stay on the big disk at home.**
- R2's free tier is **10 GB**. The laptop measures the browse derivatives
  and sizes them to fit (WebP/AVIF, a reading resolution that still reads).
  If the archive outgrows it, the answer is a more efficient derivative or
  an explicit product decision — never a thumbnail-only site.

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
| `Derivative`, `Asset` bytes | Cloudflare R2 |
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
