<!-- Component of docs/TECHSPEC.md. See the index for the status. -->

Status: **normative** for §0–§2; §14 is deferred. §3–§4 live in `02-archive-and-capture.md` and describe the legacy file format.

## 0. What this document decides

It makes the architectural calls the PRD left open, with rationale. The decision register is `09-decisions.md`. It deliberately does **not** re-argue the PRD — it implements it.

---

## 1. Principles (inherited)

- **P1 — Folder-first.** The archive is a folder; the app is a lens over it.
- **P2 — Boring stack.** Vanilla HTML/CSS/JS, no framework, no build step, no database in the browser. Files + `fetch`; the live store is SQLite on the laptop (§17).
- **P3 — Generational durability (PRD §18).** Open formats, sidecar metadata, a README written for a reader in 2060, 3-2-1 backups across households, the app disposable by design.
- **P4 — Propose/confirm.** ML/OCR never assert; everything enters as `proposed` until a human confirms.
- **P5 — Privacy by default.** No accounts, no analytics, no third-party CDNs for family content. Single exception: street-view imagery (§6).
- **P6 — Performance at scale.** 10,000 items / 50,000 images; incremental loading; ≤ 100 KB initial payload.

---

## 2. Stack

- **Vanilla ES modules** — no framework, no build step, no `package.json` runtime dependency. The app is a set of `.js`/`.css`/`.html` files that work forever. (Vanilla means no framework or build step — not no classes: `class` is ES2015 and allowed; see docs/coding-standards.md.)
- **Hash-based routing** (`#/timeline`, `#/item/letter-1963-05-14-01`, `#/themes/t-the-boats`) — works on any static host, no server rewrite rules.
- **PWA:** `manifest.webmanifest` + `sw.js` — installable ("Add to Home Screen"), offline shell + cached archive content (§9).
- **Tools** (`tools/`, optional at runtime): Python. Used for thumbnails, index rebuild, archive checks, CSV export, fake-data generation.
- **Serving:** the app shell is static on **Cloudflare Pages**; the published read model (JSON + view images) is in **R2**; no full-res leaves the house. The archive lives at home on the big disk; the local service is the writer; the remote is a static app plus a small serverless backend (§17).
- **Why this stack:** durability (files outlive any framework — P3), the payload budget (P6), hostability anywhere, and the entire surface is ~10 screens.

---
## 14. Deliberately deferred (seams only)

OCR transcription drafts, photo labeling, theme/entity discovery, TTS — the `proposed`/`confirmed` status exists in the schema (P4). **Models are called through the family's gateway; there is no requirement to run them locally.**

**Cousin contributions (not built, not ruled out):** The D1 accounts list covers invite-level access; a future merge/import tool (per-contributor folders, ID namespacing) adds uploads without schema change — people are already first-class in the model.

---
