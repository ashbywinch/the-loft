# Long-lived personal software — research summary

Date: 2026-08-09. Research question: who else is building software meant to
outlive its creators by decades, and what are the established patterns?

Context: this archive must survive ~2046 with minimal skilled human
intervention, stay plain-text/append-only (the no-PII guard scans tracked
files; the archive is diffable, greppable, GEDCOM-adjacent), and be easy to
reason about under concurrency.

---

## 1. Who is building this

### 1.1 The plain-text "forever format" movement

The closest philosophical kin. Plain text (UTF-8) is the format that has been
readable on essentially every computer since the 1980s, is not tied to any
company or subscription, and converts to anything.

- Derek Sivers, *Write plain text files* (sive.rs/plaintext) — "plain text is
  reliable, portable, readable on any device now and in the future".
- Desmond Rivet's 16-year plain-text-blog durability case study
  (desmondrivet.com/2023/09/14/plain-text) — text files survive hardware and
  software changes; database-backed blogs rot.
- **The Life Archive Format (openlaf.org)** — an open standard for exactly
  this: a portable folder of Markdown/JSON/metadata + media, "not a database
  or cloud service", explicitly designed for "decades of longevity". Its
  founding rule: **separate content (the archive) from software** — the
  folder is the archive; tools come and go.

### 1.2 The local-first research community

Ink & Switch's *Local-first software* (inkandswitch.com/essay/local-first/,
with Kleppmann et al.) — longevity is a first-class design goal, stated as
preventing a "digital Dark Age". Their concrete guidance:

- prefer widely supported archival formats (**plain text, PDF, JSON,
  SQLite**);
- **exportability is the longevity mechanism** — the hedge is the ability to
  emit standard formats, not the storage engine;
- robust local storage + independent backups; offline operation.

### 1.3 The genealogy software world — the cautionary tale in our own domain

- **Personal Ancestral File (PAF)**, the LDS Church's free genealogy program
  (1984–2013), was abandoned by its vendor and survives only via GEDCOM
  export to other tools (FamilySearch blog; tamurajones.net).
- **The entire reason GEDCOM (plain text) exists is that proprietary
  genealogy formats rot with their vendors.** Our archive's deliberate
  GEDCOM-adjacency is the domain's own established longevity answer,
  validated by the industry's history.

### 1.4 SQLite — the most deliberate long-lived format project in existence

- D. Richard Hipp, *SQLite as an application file format*
  (sqlite.org/appfileformat.html) and *Long Term Support*
  (sqlite.org/lts.html): backwards compatible with 2004, bit-identical files
  across 32/64-bit and endiannesses, a stated commitment to support through
  2050, **recognized by the US Library of Congress as a recommended storage
  format**, replicated/cryptographically protected source history as
  "disaster planning".

### 1.5 Permacomputing

A community ("computing for hundreds of years") with concrete longevity
criteria (permacomputing.net): avoid black-box dependencies, offline
tolerance, FLOSS, mature technologies ("build on solid ground" — minimize
obsolescence), reproducible builds, and the analysis that **software rot
comes from unstable environments, not old code**.

### 1.6 Logseq — the closest working analogue, with a history that matters

A local-first knowledge base whose store IS plain-text Markdown files ("you
own your data", openable in any editor). After years of file-based graphs,
Logseq is building a **database version** for reliability/performance/
collaboration, keeping the Markdown files as a *derived mirror* (ADR 0016:
"the DB is the source of truth; the mirror is derived output for external
tools, backups, indexing, and inspection").

That is our exact question played out for real: file-based store (contention,
reliability at scale) → DB as truth + plain-text mirror.

## 2. The established patterns

1. **Plain text as the archival substrate** — UTF-8 outlives formats and
   companies; content separated from software (LAF's founding rule).
2. **Exportability is the longevity mechanism** — the hedge is emitting
   standard formats (Ink & Switch, Sivers, Logseq's mirror).
3. **Source of truth + derived mirror** — the writable store may be a DB
   while the human/guard-readable form is a mirror (Logseq ADR; our existing
   `loft publish`).
4. **Vendor-independent interchange for the domain** — GEDCOM proves
   genealogy specifically converges on plain text because software dies.
5. **Verification as a durability duty** — checksums/verify, `integrity_check`
   (SQLite), "solid ground" (permacomputing).
6. **Deliberate format stability** — if you own the format, you owe it
   documentation + a decades-long stability commitment (SQLite LTS is the
   gold standard).
7. **Minimal dependency surface** — stdlib-only is the permacomputing sweet
   spot; `sqlite3` IS Python stdlib.

## 3. What it means for us

- The plain-text-as-source path (a simple append-only log, one file per
  session, whole lines) is a recognized pattern (LAF, Logseq-files, GEDCOM)
  and the most repairable by a 2046 non-specialist.
- SQLite carries the strongest documented longevity guarantee in existence
  (LoC, 2050 commitment, bit-stability, `integrity_check`), and Logseq's
  migration is a real data point that a mature project facing our exact
  contention problem chose DB-as-truth + plain-text-mirror.
- Either way, every source agrees: **checksums + a verify command, a
  documented format, and plain-text exportability are non-negotiable.**

## 4. Sources

- sive.rs/plaintext — Derek Sivers, *Write plain text files*
- openlaf.org — Life Archive Format
- desmondrivet.com/2023/09/14/plain-text — *On the Durability of Plain Text*
- inkandswitch.com/essay/local-first/ — *Local-first software* (Ink & Switch)
- familysearch.org — *Personal Ancestral File (PAF) is discontinued*;
  tamurajones.net — *FamilySearch officially abandons PAF*
- sqlite.org/appfileformat.html; sqlite.org/lts.html — SQLite as an
  application file format / long-term support
- permacomputing.net — permacomputing, software rot, build on solid ground
- discuss.logseq.com — *Why the database version and how it's going*;
  logseq ADR 0016 (Markdown mirror)
