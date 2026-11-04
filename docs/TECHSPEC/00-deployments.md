# The deployments

> Component of `docs/TECHSPEC.md`. Status: **normative**. This is the one
> statement of the deployment shape; a component that implies a different
> shape is wrong.

There are **three code deployments and one managed dependency**. No
application server runs off-site.

| Deployment | Runs | Owns |
|---|---|---|
| **Local web service** (laptop) | `loft serve` — FastAPI, `LiveStore`, the write seam | the SQLite database, the LAN API, capture/review/browse |
| **Local OS daemon** (laptop) | `loft work --watch`, `loft sync`, `loft export` | scan pickup, the pipeline, the outbox drain, the nightly human archive and operational backup |
| **Remote static web app** (CDN/static host) | HTML/JS/CSS + the published read model | browse and the remote review surface; **no server code** |
| **Managed backend** (dependency: Supabase) | Postgres, Storage, Auth, Realtime | the published read model, the command outbox, auth, staged uploads |

## The remote deployment is a static web app

It does not run FastAPI, does not answer reads from a live server, and does
not receive uploads itself. It:

- reads the **published read model** through the managed backend's SDK;
- writes commands to the managed backend's **outbox table**;
- sends uploads to the managed backend's **storage**;
- authenticates through the managed backend's **Google OAuth**.

No service code we operate runs off-site. The managed backend is a
dependency, not a deployment of our code. If the managed backend is
replaced, the static app's SDK calls change; the local service and the
daemon do not.

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
| Sync agent, exporter, retention | Local OS daemon |
| `Snapshot` / read model, `Outbox` table, derivatives, staged uploads, auth | Managed backend |
| The static app, the remote review surface | Remote static web app |
| The human archive, the operational backup | Local OS daemon writes; the big disk stores |

A noun that is not in this table does not exist. The `[shape]` decisions in
`09-decisions.md` are the ones tied to this table; the `[domain]` decisions
survive a change of deployment.

## Blast radius

| Change | Revisit |
|---|---|
| The remote stops being static (a server appears) | `[shape]`: D3, D4, D11, D17, D20, D22; `04-live-system.md` §17.5–17.6, §17.11 |
| The managed backend is replaced | `[shape]`: D4, D5, D11, D13; the SDK calls in the static app; the outbox and read-model adapters |
| The laptop is replaced by a home server | the deployment table; the daemon/service split; `[shape]` D2, D6, D12 |
| The database is replaced (SQLite → Postgres) | `[schema]`: D1, D7, D14, D16, D18, D27; `05-schema.md`/`06-schema-ddl.md` |
| The code layout moves to `loft/` | `[interface]`: D31–D36; `08-code-organisation.md` |

The domain decisions (D8–D10, D15, D19, D21, D23–D26, D28–D30) are
independent of the deployment shape.
