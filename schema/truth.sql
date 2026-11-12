-- The live store truth: pragmas, the event log, the content store and migrations.
-- The concepts are docs/TECHSPEC/05-schema.md; the projections are schema/projections.sql.

PRAGMA journal_mode = WAL;
PRAGMA synchronous = FULL;
PRAGMA busy_timeout = 5000;
PRAGMA wal_autocheckpoint = 1000;
PRAGMA recursive_triggers = ON;

-- 18.2 The event log
CREATE TABLE events (
  seq            INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id       TEXT    NOT NULL UNIQUE,      -- UUIDv7
  change_id      TEXT    NOT NULL,             -- one user/system action
  entity_kind    TEXT    NOT NULL,             -- person, item, page, command, ...
  entity_id      TEXT    NOT NULL,
  event_no       INTEGER NOT NULL,             -- 1..n per entity, every event
  entity_version INTEGER,                      -- state token; NULL for log-like kinds
  event_type     TEXT    NOT NULL,             -- created, superseded, deleted, ...
  payload        TEXT    NOT NULL,             -- canonical JSON, references content by sha
  payload_schema INTEGER NOT NULL,
  recorded_at    TEXT    NOT NULL,             -- ISO 8601 UTC; not the ordering key
  actor_kind     TEXT    NOT NULL CHECK (actor_kind IN ('person', 'system')),
  actor_id       TEXT    NOT NULL,             -- a person id, or a reserved system id
  command_id     TEXT,                         -- remote command that caused it
  app_version    TEXT    NOT NULL,             -- immutable build id (git sha)
  prev_hash      TEXT,                         -- previous event for this entity
  hash           TEXT    NOT NULL,             -- sha256 of the canonical event
  CHECK (event_no > 0),
  UNIQUE (entity_kind, entity_id, event_no)
) STRICT;

CREATE UNIQUE INDEX events_one_apply
  ON events (command_id) WHERE event_type = 'applied';

CREATE INDEX events_entity   ON events (entity_kind, entity_id, seq);
CREATE INDEX events_change   ON events (change_id);
CREATE INDEX events_command  ON events (command_id);
CREATE INDEX events_release  ON events (app_version);
CREATE INDEX events_recorded ON events (recorded_at);
CREATE INDEX events_actor    ON events (actor_kind, actor_id);

CREATE TRIGGER events_no_duplicate BEFORE INSERT ON events
WHEN EXISTS (
  SELECT 1 FROM events
  WHERE seq = NEW.seq
     OR event_id = NEW.event_id
     OR (entity_kind = NEW.entity_kind
         AND entity_id = NEW.entity_id
         AND event_no = NEW.event_no)
)
BEGIN SELECT RAISE(ABORT, 'event already exists'); END;

CREATE TRIGGER events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;
CREATE TRIGGER events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;

-- 18.3 The content store
CREATE TABLE content (
  sha256     TEXT PRIMARY KEY,
  mime       TEXT NOT NULL,
  size       INTEGER NOT NULL,
  bytes      BLOB,                 -- inline for small text/JSON
  path       TEXT,                 -- relative path for a large blob
  created_at TEXT NOT NULL,
  CHECK ((bytes IS NOT NULL) <> (path IS NOT NULL)),
  CHECK (bytes IS NULL OR length(bytes) = size)
) STRICT;

CREATE TRIGGER content_no_replace BEFORE INSERT ON content
WHEN EXISTS (
  SELECT 1 FROM content c
  WHERE c.sha256 = NEW.sha256
    AND (c.size <> NEW.size OR c.mime <> NEW.mime
         OR c.bytes IS NOT NEW.bytes OR c.path IS NOT NEW.path)
)
BEGIN SELECT RAISE(ABORT, 'content sha already exists with different bytes'); END;

CREATE TRIGGER content_no_update BEFORE UPDATE ON content
BEGIN SELECT RAISE(ABORT, 'content is append-only'); END;
CREATE TRIGGER content_no_delete BEFORE DELETE ON content
BEGIN SELECT RAISE(ABORT, 'content is append-only'); END;

-- 18.10 The schema, table by table
-- events: §18.2
-- content: §18.3

CREATE TABLE schema_migrations (
  version     INTEGER PRIMARY KEY,
  applied_at  TEXT NOT NULL,
  app_version TEXT NOT NULL,
  sql_sha256  TEXT NOT NULL,
  note        TEXT NOT NULL
) STRICT;

CREATE TRIGGER migrations_no_update BEFORE UPDATE ON schema_migrations
BEGIN SELECT RAISE(ABORT, 'schema_migrations is append-only'); END;
CREATE TRIGGER migrations_no_delete BEFORE DELETE ON schema_migrations
BEGIN SELECT RAISE(ABORT, 'schema_migrations is append-only'); END;

