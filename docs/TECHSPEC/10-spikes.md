<!-- Component of docs/TECHSPEC.md. See the index for the status. -->

# Spikes

> Component of `docs/TECHSPEC.md`. Status: **register**. Every spike names
> the component it belongs to; the section numbers are the original §
> references, kept for cross-linking.

## The live system (`04-live-system.md`)

### 17.12 Spikes required

1. **Static app + managed backend.** Prove the static app serves the review
   UI from the published read model, has no server code, refuses every write
   except the outbox, and swaps to a new read model atomically.
2. **Outbox semantics.** Prove an applied-twice command is a no-op, a
   stale command parks, and a crash mid-apply leaves no partial state.
3. **Export/restore round trip.** Prove export → wipe → restore
   reproduces the truth and domain projections exactly (the `07-exports.md`
   backup contract list), and that a second export of unchanged records writes nothing.
4. **Derivative boundary.** Prove a remote review page never requests an
   original, and that the full-resolution path is LAN-only.
5. **Retention.** Prove the trimmed set still restores both the newest
   and the oldest retained dump.
6. **Command taxonomy and lock hold time.** Prove no transaction holds
   the write lock across a model call, a file write or a network hop; a
   re-read enqueues a job and the result lands in a second transaction.
7. **One entity version, one export cursor.** Prove a nightly export
   advances `exported_through` without changing `entity_version`, and a
   command authored before the export still applies.
8. **Export completeness.** Prove the export/restore comparison covers the
   `07-exports.md` backup contract list, that operational tables rebuild empty, and that a
   rejected proposal does not resurrect.
9. **Threat model.** Prove a forged command is rejected at the backend and
   again at the laptop; a staged upload cannot be fetched by an
   unauthorised actor; a signed URL expires.
10. **Snapshot cadence at scale.** Measure the publish cost at the PRD's
    ceiling (10,000 items / 50,000 images) and prove the projection
    rebuild is off the request path.

The schema-specific spikes — append-only proof, withdrawal drill,
hash/migration, draft exclusion, command rebuild — follow.

## The schema (`05-schema.md`, `06-schema-ddl.md`)

### 18.12 Spikes required

1. **Append-only proof.** `UPDATE`, `DELETE`, `INSERT OR REPLACE` and
   `INSERT OR IGNORE` abort with the triggers and with the pragma **off**
   (the `BEFORE INSERT` duplicate trigger is the schema-level guard); the
   seam cannot emit `OR REPLACE`/`OR IGNORE`; `loft verify` checks the
   triggers and the pragma.
2. **Withdrawal drill.** A release writes 2,000 bad edits, including one
   create and one entity edited afterwards; withdraw it with and without
   `--force`; the later edit is merged or listed in `needs_attention`, the
   create is tombstoned, the reader tree and history are correct, and a
   non-specialist does it in under 30 minutes from the README.
3. **Drop-and-replay equality.** Rebuild every projection from `events` +
   `content` and compare the exact backup contract list.
4. **Backup/restore contract.** Rebuild truth + domain from the backup;
   `jobs` rebuilds from `job/*`, `sync_state` is reseeded; every hash
   verifies.
5. **Monotonic backup.** A restore to an older dump refuses to write until
   the history is re-imported; the backup never regresses.
6. **Content-addressed text.** A bad release cannot replace a blob under an
   existing sha; a correction creates a new one.
7. **Ten-year log.** Size, segment count, verify time and manifest time at
   50,000 images.
8. **Great-grandchild walkthrough.** A person with no app finds a confirmed
   item by date, by person and by `grep`, reads it and verifies the manifest;
   a catalogued item whose transcription is still a draft has no
   `transcription.txt` and says so; a sensitive item is in `INDEX.md` like
   any other.
9. **FTS5 fallback.** `schema-truth.sql` restores on a SQLite without FTS5;
   the projections rebuild when FTS5 is available.
10. **Lock-hold budget.** A 2,000-event batch is one transaction; no other
    writer sees "database is locked"; the FTS projector is off the lock.
11. **Migration lint.** Destructive DDL and a `NOT NULL` column without a
    default are refused.
12. **Merge/alias.** A ref to a merged id resolves to the survivor and
    publishes.
13. **Migration and hash.** Apply every migration, then re-verify the whole
    event chain: the frozen column list keeps historical hashes valid.
14. **Draft exclusion.** The human archive contains no draft transcription,
    proposed identity or `thinking` blob; the backup contains them; the
    human archive's manifest lists only confirmed files.
15. **Command outcome rebuild.** Drop `commands`, replay `command/*`, and
    get the same pending/applied/needs_attention/rejected list.
16. **Snapshot content atomicity.** A read-model pointer never goes live
    before every referenced content sha is present; a retry re-uses the
    object.
17. **Projection coverage.** Every `entity_kind` in the vocabulary has a
    typed table and a projector; a new kind without one fails the gate. A
    rebuild with a missing table fails, never silently skips.
18. **Typed projection queries.** The timeline, person page, place page and
    review queue are plain SQL joins on the typed tables at 10,000 items,
    with no `json_extract` on the hot path.
19. **Human archive vs backup.** The human archive verifies and reads
    without SQLite; the backup restores the full DB; neither is mistaken
    for the other, and a draft never appears in the human archive.
20. **Attribution.** Every human event's `actor_id` is a person id (proposed
    or confirmed); machine events use a reserved system id; the human
    archive contains no accounts or emails; a contributor with no cast
    record gets a proposed person.
21. **Review state.** A row's `trust`, reviewer tick, orientation and
    insertion links survive a device switch and a rebuild; `row_checks` is
    per reviewer.
22. **Claims closure.** An import, a document, an unfinished memory and a
    failed integrity check each produce a claim; resolving every claim
    closes the queue; a reopen creates a new claim.
23. **Merge/unmerge.** Withdrawing a merge removes the alias and old refs
    resolve to the original id; a withdrawn create lists its dependents.
24. **Document authority.** A confirmed document without an item fails; a
    document cache that disagrees with the published text fails the export
    comparison.

---

## The code boundary (`08-code-organisation.md`)

### 19.10 Spikes required

1. **Import boundary.** Extend `tests/test_architecture_layers.py`
   (ArchUnitPython) with `domain`, `persistence` and `surfaces`;
   `sqlite3` only under `loft/archive/live/`; the new rule lands with the
   package, not as a skipped placeholder.
2. **Memory store.** The contract suite passes against `MemoryLiveStore`.
3. **Batch change.** 2,000 saves in one transaction, read-your-writes,
   rollback on failure, no lock held across a model call.
4. **Stale.** `StaleVersion` carries the current item; a surface can merge or
   show the conflict.
5. **Export view.** The exporter builds the human archive and the backup from
   `ExportView` without SQL.
6. **Read models at scale.** Timeline, person page, review queue and search
   at 10,000 items, with cursor pagination.

## The Cloudflare backend (`00-deployments.md`, `04-live-system.md`)

25. **Worker model parity.** The remote chat, identify and remote re-read on
    the Worker match the laptop's Python review on the tested cases; the
    prompt/context is shared or ported; the model key stays in the Worker; the
    laptop re-validates every applied result.

26. **Home auth.** A LAN request and a tailnet request both require Google
    sign-in; the family allowlist gates both; the account mirror resolves the
    person; the cookies are `HttpOnly`/`Secure`/`SameSite=Strict`; CSRF and
    the session revocation hold; a first remote sign-in creates a provisional
    person the laptop confirms.

27. **Read-model publish.** Upload a release, flip `current.json`; a partial
    upload leaves the old pointer; the app reads the new release; a rollback
    re-points; the R2 CORS/Access credentials hold.

28. **View-image transcription.** One 300 DPI handwriting page: the VLM's
    per-row text on the view image vs the original. Acceptance: the view image
    (start at 2000px long edge, WebP/AVIF) reads and checks rows at 100 % on
    the landscape phone; the VLM's per-row text matches the original; the
    archive's page count fits the 10 GB budget, or the derivative is tuned. If
    the view does not hold, the page waits for the laptop — there is no second
    review tier.

29. **One-origin Access and image caching.** Put the Pages app and the
    Worker routes on one hostname behind Access; sign in once; load an image
    through `/img/<sha>`; confirm the cookie authorizes both the API and the
    `<img>`, the immutable header caches at the edge and in the browser, and a
    second view costs no Worker request. Confirm the free request budget holds
    for a day's family use.
