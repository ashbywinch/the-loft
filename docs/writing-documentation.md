# Writing Documentation — The Loft

Conventions for documentation in this repo. Full guidance: `skill://write-documentation`.

## Principles

- **Context-efficient:** a reader should get the answer in the first screenful.
  Density over ceremony; bullets over paragraphs; tables over prose where a
  table is the answer.
- **~150–200 line ceiling per doc.** If a doc outgrows it, split it — the
  ceiling is a health check, not a hard limit. **Exception: the canonical
  requirements document (`docs/prd/PRD.md`) is allowed to exceed it** — a
  requirements doc is one artifact and splitting it would scatter the
  contract.
- **Link, don't copy.** One canonical statement of a fact; other docs
  reference it (`see PRD §10`) instead of restating it.
- **The reader in 2060 counts.** The archive's README is written for someone
  who has never seen the app (`PRD §18`). Code comments explain *why*, not
  *what* — the code says what.
- **Status honesty.** Docs carry a status line; resolved decisions are marked
  RESOLVED with date + who; open questions stay visibly open.

## Where things go

| Content | File |
|---|---|
| Product requirements | `prd/PRD.md` |
| Architecture + decision record | `TECH-SPEC.md` |
| The story-capture flow spec | `prd/MEMORIES.md` |
| The artifact-import flow spec | `prd/IMPORT-PRD.md` |
| Real-import lessons (worked example) | private — kept out of the public tree |
| Interview/discovery records + working drafts | `DISCOVERY.md`; session records stay private |
| Precedent research | `PRECEDENT.md` |
| UI / chat conventions | `UI.md`, `CHAT-UX.md` |
| UX loop working log | `plans/ux-fixes-plan.md` |
| Code/test/doc conventions | `coding-standards.md`, `testing-standards.md`, `writing-documentation.md` |

The routing tables in `AGENTS.md` and `README.md` are the find-it copies for
their audiences; this table is the canonical home for deciding where content
goes.

## Product-law phrasing (do not weaken)

- The app arranges evidence; it never interprets it.
- Nothing is asserted unreviewed (propose/confirm).
- No censorship by default; sensitive timing is a family decision.
