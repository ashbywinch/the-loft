<!-- Component of docs/TECHSPEC.md. See the index for the status. -->

Status: **proposed**; the SQL is in `schema/live.sql`.

## The DDL

The authoritative SQL is [`schema/live.sql`](../../schema/live.sql): the event
log (§18.2), the content store (§18.3), the typed projections, the FTS index
and the triggers (§18.10). The concepts are in `05-schema.md`.

The FTS row's `rowid` is `search_docs.doc_id`; an update is
`DELETE FROM search WHERE rowid = ?` followed by the insert, which is the
indexed path, not a scan by `entity_id`.

**Operational rules.** A rebuilt `running` job returns to `pending` unless a
live lease proves otherwise; `lease_owner`/`lease_until` make that
deterministic. `commands.outcome = 'parked'` is the stale-command
state the remote UI shows as "awaiting the laptop"; the status reaches the
remote on the next published read model, which the UI states.

**Why typed columns, not a generic JSON table.** A generic `entities.payload`
table cannot constrain the domain, turns every query into `json_extract`, and
invites new kinds with no schema. The typed tables keep scalar fields as
columns, small nested records as JSON columns on the same table, and
query-critical edges as child tables. The event `payload` remains JSON
because it is the historical wire record; the typed table is the current
row.
