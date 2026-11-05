# Family History Album — Tech Spec & Architecture

**Status:** v0.4 — the deployments and the live-system shape are settled; the
schema and the code boundary are under review. **This file is the index.**
The components live in `docs/TECHSPEC/`.

## Read this first: the deployments

There are **four code deployments and four managed services**:

- **Local web service** (laptop) — FastAPI, `LiveStore`, the only writer of
  domain state; serves the LAN.
- **Local OS daemon** (laptop) — scanner pickup, the pipeline, the outbox
  drain, the nightly human archive and operational backup.
- **Remote static web app** (Cloudflare Pages) — HTML/JS/CSS and the
  published read model; **no server code**.
- **Remote backend app** (Cloudflare Worker + D1) — the chat/identify calls,
  the command outbox and auth validation; serverless, no server to operate.
- **Managed services** (Cloudflare) — D1 (the tiny database), the Worker's Google OAuth (auth),
  R2 (browse images), AI Gateway (the model).

No server we operate runs off-site. The remote static app is exactly that;
the backend app is one small serverless function. The full table, the noun
ownership and the blast radius: **`docs/TECHSPEC/00-deployments.md`**.

## Status vocabulary

- **Normative** — implement this; the code and tests are held to it.
- **Proposed** — under review; may change before implementation.
- **Deferred** — a seam, not built.

The status is per component; a component can be normative in its deployment
statement and proposed in its details.

## The normative copy

A fact lives in one component. Other components link to it; they do not
restate it.

| Topic | The one copy |
|---|---|
| Deployments, noun ownership, topology blast radius | [00-deployments.md](TECHSPEC/00-deployments.md) |
| Principles, stack, deferred seams | [01-foundations.md](TECHSPEC/01-foundations.md) |
| The record wire shape, maps, PWA, search, tools (the legacy file layout/capture/privacy/performance are in `99`) | [02-archive-and-capture.md](TECHSPEC/02-archive-and-capture.md) |
| The capture pipeline, reading path and review surface (the import flow is a record) | [03-import-and-pipeline.md](TECHSPEC/03-import-and-pipeline.md) |
| The live system's shape, the remote API, command/read flow, failure modes | [04-live-system.md](TECHSPEC/04-live-system.md) §17 |
| The schema's concepts, event log, content, projections, migrations, withdrawal; the D1 store | [05-schema.md](TECHSPEC/05-schema.md) §18.1–18.7, §18.13 |
| The schema DDL — events, content and projections, the one table definition | [06-schema-ddl.md](TECHSPEC/06-schema-ddl.md) |
| The nightly job, the human archive (the dated document tree + the scan image leg), the operational backup | [07-exports.md](TECHSPEC/07-exports.md) |
| Code organisation and the persistence boundary | [08-code-organisation.md](TECHSPEC/08-code-organisation.md) §19 |
| The one-time migration from the file archive to the database | [11-migration.md](TECHSPEC/11-migration.md) |
| Decisions (D1–D45 and the legacy decisions), with blast radius | [09-decisions.md](TECHSPEC/09-decisions.md) |
| Spikes | [10-spikes.md](TECHSPEC/10-spikes.md) |

The write path has two topics, not two copies: **[04-live-system.md](TECHSPEC/04-live-system.md) §17.5**
is the remote command flow (browser → managed outbox → local sync agent);
**[05-schema.md](TECHSPEC/05-schema.md) §18.5** is the transaction that applies a change. The DDL is
only in [06-schema-ddl.md](TECHSPEC/06-schema-ddl.md). The hash recipe is only in [05-schema.md](TECHSPEC/05-schema.md) §18.2.
The export/backup procedure is only in [07-exports.md](TECHSPEC/07-exports.md).

## Components

| File | Scope | Status |
|---|---|---|
| [00-deployments.md](TECHSPEC/00-deployments.md) | the deployment shape, the nouns each owns, the blast radius | **normative** |
| [01-foundations.md](TECHSPEC/01-foundations.md) | §0–§2 principles/stack, §14 deferred seams | **normative**, with superseded notes |
| [02-archive-and-capture.md](TECHSPEC/02-archive-and-capture.md) | §4, §6, §9–§11 the record wire shape, maps, PWA, search, tools | current |
| [03-import-and-pipeline.md](TECHSPEC/03-import-and-pipeline.md) | §16.13–§16.17 the capture pipeline, reading path and review surface; §16.1–§16.11 the import-flow record | current for the pipeline; the import-flow record is not the live architecture |
| [04-live-system.md](TECHSPEC/04-live-system.md) | §17 the live system — shape, command/read flow, failure modes, technology choices | **proposed**; the deployment shape is normative in `00` |
| [05-schema.md](TECHSPEC/05-schema.md) | §18.1–18.7 the schema concepts: append-only stores, event log, content, projections, write transaction, migrations, withdrawal; §18.13 the D1 store | **proposed** |
| [06-schema-ddl.md](TECHSPEC/06-schema-ddl.md) | §18.2, §18.3, §18.10 the DDL — the one table definition | **proposed** |
| [07-exports.md](TECHSPEC/07-exports.md) | §17.9 + §18.8–18.9 the nightly job, the human archive, the operational backup | **proposed** |
| [08-code-organisation.md](TECHSPEC/08-code-organisation.md) | §19 the layers and the persistence boundary | **proposed** |
| [11-migration.md](TECHSPEC/11-migration.md) | the one-time file-store → DB import: what maps, order, idempotency, verification, cutover | **proposed** |
| [09-decisions.md](TECHSPEC/09-decisions.md) | §17.13, §18.11, §19.9 the decision register | register |
| [10-spikes.md](TECHSPEC/10-spikes.md) | §17.12, §18.12, §19.10 the spike register | register |

## Section map

| Section | Component |
|---|---|
| §0–§2, §14 | [01-foundations.md](TECHSPEC/01-foundations.md) |
| §4, §6, §9–§11 | [02-archive-and-capture.md](TECHSPEC/02-archive-and-capture.md) |

| §16.1–§16.11 (import-flow record), §16.13–§16.14.2, §16.16–§16.17 | [03-import-and-pipeline.md](TECHSPEC/03-import-and-pipeline.md) |
| §17.1–§17.8, §17.10–§17.11 | [04-live-system.md](TECHSPEC/04-live-system.md) |
| §17.9 | [07-exports.md](TECHSPEC/07-exports.md) |
| §17.12 | [10-spikes.md](TECHSPEC/10-spikes.md) |
| §17.13 | [09-decisions.md](TECHSPEC/09-decisions.md) |
| §18.1–§18.7, §18.13 | [05-schema.md](TECHSPEC/05-schema.md) (concepts and the D1 store; the DDL is in `06`) |
| §18.8–§18.9 | [07-exports.md](TECHSPEC/07-exports.md) |
| §18.10 | [06-schema-ddl.md](TECHSPEC/06-schema-ddl.md) |
| §18.11 | [09-decisions.md](TECHSPEC/09-decisions.md) |
| §18.12 | [10-spikes.md](TECHSPEC/10-spikes.md) |
| §19.1–§19.8 | [08-code-organisation.md](TECHSPEC/08-code-organisation.md) |
| §19.9 | [09-decisions.md](TECHSPEC/09-decisions.md) |
| §19.10 | [10-spikes.md](TECHSPEC/10-spikes.md) |
| The file-store migration | [11-migration.md](TECHSPEC/11-migration.md) |

## How to change this document

1. Find the component that owns the fact (the normative-copy table).
2. Change it there; update the components that link to it, not their copies.
3. A new decision goes in [09-decisions.md](TECHSPEC/09-decisions.md) with a `[shape]`, `[domain]`,
   `[schema]` or `[interface]` tag; a new spike goes in [10-spikes.md](TECHSPEC/10-spikes.md) with
   its component.
4. If a change alters the deployment shape, update [00-deployments.md](TECHSPEC/00-deployments.md) first
   and then every `[shape]` decision it names. That is the blast radius.
