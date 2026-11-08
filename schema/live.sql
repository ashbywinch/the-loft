-- The live store schema (SQLite).
-- The concepts are docs/TECHSPEC/05-schema.md; the one table definition is this file.

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

-- 18.10 The schema, table by table
-- Shared state columns on every state table:
--   version INTEGER NOT NULL, event_no INTEGER NOT NULL,
--   event_seq INTEGER NOT NULL, updated_at TEXT NOT NULL
-- Status/type vocabularies are validated by the write seam against the
-- domain class; CHECKs are reserved for vocabularies that will not grow
-- without a migration.

CREATE TABLE items (
  item_id            TEXT PRIMARY KEY,
  type               TEXT NOT NULL,
  title              TEXT NOT NULL,
  date_json          TEXT,                 -- the DateValue source
  date                TEXT,                 -- derived: ISO from
  date2              TEXT,                 -- derived: ISO to
  date_precision     TEXT,                 -- derived: exact/month/year/approx/before/after/between/period/phrase
  status             TEXT NOT NULL,
  source             TEXT,
  description        TEXT,
  provenance         TEXT,
  sensitive          INTEGER NOT NULL DEFAULT 0 CHECK (sensitive IN (0, 1)),
  created            TEXT,
  identified         INTEGER NOT NULL DEFAULT 0,
  date_mentions_json TEXT,
  extra_json         TEXT,
  version            INTEGER NOT NULL,
  event_no           INTEGER NOT NULL,
  event_seq          INTEGER NOT NULL,
  updated_at         TEXT NOT NULL
) STRICT;

CREATE TABLE item_refs (
  item_id   TEXT NOT NULL,
  ref_kind  TEXT NOT NULL CHECK (ref_kind IN ('person', 'place', 'org', 'theme', 'item')),
  ref_id    TEXT NOT NULL,
  status    TEXT NOT NULL,
  date_json TEXT,                 -- the DateValue source
  date      TEXT,                 -- derived
  date2     TEXT,                 -- derived
  date_precision TEXT,            -- derived
  basis_json TEXT,
  event_seq INTEGER NOT NULL,
  PRIMARY KEY (item_id, ref_kind, ref_id)
) STRICT;

CREATE TABLE item_assets (
  item_id  TEXT NOT NULL,
  asset_id TEXT NOT NULL,
  kind     TEXT NOT NULL,
  caption  TEXT,
  ordinal  INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (item_id, asset_id)
) STRICT;

CREATE TABLE item_content (
  item_id TEXT NOT NULL,
  kind    TEXT NOT NULL CHECK (kind IN ('story', 'transcription', 'other')),
  sha256  TEXT NOT NULL,
  trust   TEXT NOT NULL CHECK (trust IN ('draft', 'confirmed')),
  PRIMARY KEY (item_id, kind)
) STRICT;

CREATE TABLE people (
  person_id        TEXT PRIMARY KEY,
  name             TEXT NOT NULL,
  years            TEXT,
  relation         TEXT,
  bio              TEXT,
  email            TEXT,
  pronouns         TEXT,
  hue              TEXT,
  status           TEXT NOT NULL,
  dob_json         TEXT,
  dod_json         TEXT,
  aliases_json     TEXT,
  occupations_json TEXT,
  basis_json       TEXT,
  version          INTEGER NOT NULL,
  event_no         INTEGER NOT NULL,
  event_seq        INTEGER NOT NULL,
  updated_at       TEXT NOT NULL
) STRICT;

CREATE TABLE person_residences (
  person_id TEXT NOT NULL,
  place_id  TEXT NOT NULL,
  date_json TEXT,                 -- the DateValue source (a period)
  from_date TEXT,                 -- derived
  to_date   TEXT,                 -- derived
  from_precision TEXT,            -- derived
  to_precision   TEXT,            -- derived
  status    TEXT NOT NULL,
  basis_json TEXT,
  PRIMARY KEY (person_id, place_id, from_date)
) STRICT;

CREATE TABLE places (
  place_id     TEXT PRIMARY KEY,
  name         TEXT NOT NULL,
  note         TEXT,
  precision    TEXT,
  lat          REAL,
  lng          REAL,
  x            INTEGER,
  y            INTEGER,
  address      TEXT,
  status       TEXT NOT NULL,
  aliases_json TEXT,
  basis_json   TEXT,
  version      INTEGER NOT NULL,
  event_no     INTEGER NOT NULL,
  event_seq    INTEGER NOT NULL,
  updated_at   TEXT NOT NULL
) STRICT;

CREATE TABLE orgs (
  org_id       TEXT PRIMARY KEY,
  name         TEXT NOT NULL,
  address      TEXT,
  branch       TEXT,
  note         TEXT,
  status       TEXT NOT NULL,
  aliases_json TEXT,
  version      INTEGER NOT NULL,
  event_no     INTEGER NOT NULL,
  event_seq    INTEGER NOT NULL,
  updated_at   TEXT NOT NULL
) STRICT;

CREATE TABLE themes (
  theme_id  TEXT PRIMARY KEY,
  title     TEXT NOT NULL,
  subtitle  TEXT,
  seeded    INTEGER NOT NULL DEFAULT 0,
  body_json TEXT NOT NULL,
  version   INTEGER NOT NULL,
  event_no  INTEGER NOT NULL,
  event_seq INTEGER NOT NULL,
  updated_at TEXT NOT NULL
) STRICT;

CREATE TABLE theme_items (
  theme_id TEXT NOT NULL,
  item_id  TEXT NOT NULL,
  ordinal  INTEGER NOT NULL,
  PRIMARY KEY (theme_id, item_id)
) STRICT;

CREATE TABLE relationships (
  relationship_id TEXT PRIMARY KEY,
  a_kind   TEXT NOT NULL,
  a_id     TEXT NOT NULL,
  b_kind   TEXT NOT NULL,
  b_id     TEXT NOT NULL,
  kind     TEXT NOT NULL,
  label_a  TEXT,
  label_b  TEXT,
  date_json TEXT,
  basis_json TEXT,
  status   TEXT,
  version  INTEGER NOT NULL,
  event_no INTEGER NOT NULL,
  event_seq INTEGER NOT NULL,
  updated_at TEXT NOT NULL
) STRICT;

CREATE TABLE documents (
  document_id    TEXT PRIMARY KEY,
  item_id        TEXT,
  batch_id       TEXT,
  doc_index      INTEGER,
  title          TEXT,
  date_json      TEXT,                 -- the DateValue source
  date           TEXT,                 -- derived
  date2          TEXT,                 -- derived
  date_precision TEXT,                 -- derived
  status         TEXT NOT NULL,
  greeting       TEXT,
  signoff        TEXT,
  text_sha       TEXT,
  confirmed_at   TEXT,
  version        INTEGER NOT NULL,
  event_no       INTEGER NOT NULL,
  event_seq      INTEGER NOT NULL,
  updated_at     TEXT NOT NULL,
  CHECK (status <> 'confirmed' OR item_id IS NOT NULL)
) STRICT;

CREATE TABLE document_pages (
  document_id TEXT NOT NULL,
  page_id     TEXT NOT NULL,
  ordinal     INTEGER NOT NULL,
  PRIMARY KEY (document_id, page_id)
) STRICT;

CREATE TABLE batches (
  batch_id         TEXT PRIMARY KEY,
  label            TEXT,
  source           TEXT,
  path             TEXT NOT NULL,
  status           TEXT NOT NULL,
  arrived_at       TEXT,
  started_at       TEXT,
  started_pid      INTEGER,
  started_host     TEXT,
  fingerprint_json TEXT,
  content_changed  INTEGER NOT NULL DEFAULT 0,
  version          INTEGER NOT NULL,
  event_no         INTEGER NOT NULL,
  event_seq        INTEGER NOT NULL,
  updated_at       TEXT NOT NULL
) STRICT;

CREATE TABLE scans (
  scan_id   TEXT PRIMARY KEY,
  batch_id  TEXT NOT NULL,
  page_id   TEXT,
  sha256    TEXT NOT NULL,
  path      TEXT NOT NULL,
  ordinal   INTEGER NOT NULL DEFAULT 0,
  created_at TEXT
) STRICT;

CREATE TABLE review_sessions (
  session_id      TEXT PRIMARY KEY,
  kind            TEXT NOT NULL,              -- import | document | memory | identity | integrity
  subject_kind    TEXT NOT NULL,              -- batch | document | item | person | place | ...
  subject_id      TEXT,
  actor_person_id TEXT NOT NULL,
  status          TEXT NOT NULL,
  current_attempt INTEGER,
  closed_at       TEXT,
  version         INTEGER NOT NULL,
  event_no        INTEGER NOT NULL,
  event_seq       INTEGER NOT NULL,
  updated_at      TEXT NOT NULL
) STRICT;

CREATE TABLE claims (
  claim_id     TEXT PRIMARY KEY,
  origin_kind  TEXT NOT NULL,   -- batch | document | item | memory | identity | integrity
  origin_id    TEXT NOT NULL,
  subject_kind TEXT NOT NULL,
  subject_id   TEXT,
  phase        TEXT NOT NULL,
  state        TEXT NOT NULL CHECK (state IN ('open', 'resolved', 'dismissed', 'blocked')),
  evidence_sha TEXT,
  event_seq    INTEGER NOT NULL
) STRICT;
CREATE INDEX claims_open ON claims (state, origin_kind, origin_id);
CREATE INDEX claims_subject ON claims (subject_kind, subject_id);

CREATE INDEX items_date ON items (date);
CREATE INDEX items_type_date ON items (type, date);
CREATE INDEX people_name ON people (name);
CREATE INDEX item_refs_target ON item_refs (ref_kind, ref_id);
CREATE INDEX person_residences_place ON person_residences (place_id);
CREATE INDEX document_pages_page ON document_pages (page_id);
CREATE INDEX documents_batch ON documents (batch_id, doc_index);
CREATE INDEX relationships_a ON relationships (a_kind, a_id);
CREATE INDEX relationships_b ON relationships (b_kind, b_id);
CREATE INDEX theme_items_item ON theme_items (item_id);

CREATE TABLE pages (
  page_id        TEXT PRIMARY KEY,
  image_asset_id TEXT NOT NULL,
  sha256         TEXT NOT NULL,
  revision       INTEGER NOT NULL,
  rotation       INTEGER NOT NULL DEFAULT 0,   -- applied orientation relative to the original
  category       TEXT NOT NULL DEFAULT '',
  status         TEXT NOT NULL,
  event_seq      INTEGER NOT NULL
) STRICT;

CREATE TABLE page_rows (
  page_id         TEXT NOT NULL,
  ordinal         INTEGER NOT NULL,
  source          TEXT NOT NULL CHECK (source IN ('machine', 'human')),
  trust           TEXT NOT NULL CHECK (trust IN ('raw', 'guess', 'confirmed')),
  text            TEXT NOT NULL,
  box             TEXT NOT NULL,
  kind            TEXT NOT NULL,
  orientation     INTEGER,
  revision        INTEGER NOT NULL,
  event_seq       INTEGER NOT NULL,
  PRIMARY KEY (page_id, ordinal)
) STRICT;

CREATE TABLE page_row_links (
  link_id       TEXT PRIMARY KEY,
  page_id       TEXT NOT NULL,
  insertion_row INTEGER NOT NULL,
  target_row    INTEGER,
  char_offset   INTEGER,
  state         TEXT NOT NULL CHECK (state IN ('proposed', 'unset', 'confirmed')),
  event_seq     INTEGER NOT NULL
) STRICT;

CREATE TABLE row_checks (
  page_id            TEXT NOT NULL,
  ordinal            INTEGER NOT NULL,
  reviewer_person_id TEXT NOT NULL,
  state              TEXT NOT NULL CHECK (state IN ('checked', 'unchecked')),
  at                 TEXT NOT NULL,
  event_seq          INTEGER NOT NULL,
  PRIMARY KEY (page_id, ordinal, reviewer_person_id)
) STRICT;

CREATE TABLE readings (
  page_id       TEXT PRIMARY KEY,
  reading_sha   TEXT NOT NULL,
  corrected_sha TEXT NOT NULL DEFAULT '',
  rows          INTEGER NOT NULL,
  words         INTEGER NOT NULL,
  event_seq     INTEGER NOT NULL
) STRICT;

CREATE TABLE row_adjustments (
  page_id    TEXT PRIMARY KEY,
  sha256     TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  event_seq  INTEGER NOT NULL
) STRICT;

CREATE TABLE review_messages (
  session_id      TEXT NOT NULL,
  ordinal         INTEGER NOT NULL,
  role            TEXT NOT NULL,
  actor_person_id TEXT,
  text            TEXT NOT NULL,
  thinking_sha    TEXT,
  at              TEXT NOT NULL,
  event_seq       INTEGER NOT NULL,
  PRIMARY KEY (session_id, ordinal)
) STRICT;

CREATE TABLE review_decisions (
  session_id      TEXT NOT NULL,
  ordinal         INTEGER NOT NULL,
  subject_kind    TEXT NOT NULL,
  subject_id      TEXT,
  decision        TEXT NOT NULL,
  basis_json      TEXT,
  actor_person_id TEXT NOT NULL,
  at              TEXT NOT NULL,
  event_seq       INTEGER NOT NULL,
  PRIMARY KEY (session_id, ordinal)
) STRICT;

CREATE TABLE assets (
  asset_id      TEXT PRIMARY KEY,
  sha256        TEXT NOT NULL,
  kind          TEXT NOT NULL,
  mime          TEXT NOT NULL,
  size          INTEGER NOT NULL,
  path          TEXT NOT NULL,      -- relative to the content store
  derivative_of TEXT,
  event_seq     INTEGER NOT NULL
) STRICT;

CREATE TABLE aliases (
  loser_kind    TEXT NOT NULL,
  loser_id      TEXT NOT NULL,
  survivor_kind TEXT NOT NULL,
  survivor_id   TEXT NOT NULL,
  event_seq     INTEGER NOT NULL,
  PRIMARY KEY (loser_kind, loser_id)
) STRICT;

CREATE TABLE withdrawals (
  withdrawal_id          TEXT PRIMARY KEY,
  target_kind            TEXT NOT NULL CHECK (target_kind IN ('change', 'release', 'event')),
  target_ref             TEXT NOT NULL,
  affected_change_ids    TEXT NOT NULL,   -- JSON array
  compensation_change_id TEXT NOT NULL,
  needs_attention        TEXT,            -- JSON array of entity ids
  reason                 TEXT NOT NULL,
  at                     TEXT NOT NULL,
  event_seq              INTEGER NOT NULL
) STRICT;

CREATE TABLE commands (
  command_id   TEXT PRIMARY KEY,
  actor_kind   TEXT NOT NULL CHECK (actor_kind IN ('person', 'system')),
  actor_id     TEXT NOT NULL,
  kind         TEXT NOT NULL,
  received_at  TEXT NOT NULL,
  base_version INTEGER,
  payload_json TEXT,
  outcome      TEXT NOT NULL DEFAULT 'pending'
               CHECK (outcome IN ('pending', 'applied', 'parked', 'rejected')),
  event_seq    INTEGER,
  reason       TEXT
) STRICT;
CREATE INDEX commands_outcome ON commands (outcome);

CREATE TABLE jobs (
  job_id      TEXT PRIMARY KEY,
  kind        TEXT NOT NULL,
  entity_kind TEXT NOT NULL,
  entity_id   TEXT NOT NULL,
  status      TEXT NOT NULL CHECK (status IN ('pending', 'running', 'done', 'failed')),
  attempts    INTEGER NOT NULL DEFAULT 0,
  lease_owner TEXT,
  lease_until TEXT,
  last_error  TEXT,
  event_seq   INTEGER NOT NULL,
  updated_at  TEXT NOT NULL
) STRICT;

CREATE TABLE sync_state (
  name  TEXT PRIMARY KEY,
  seq   INTEGER,               -- applied_through, projected_through, exported_through
  at    TEXT NOT NULL,
  value TEXT                   -- last_verified_export_at, etc.
) STRICT;

CREATE TABLE accounts (
  account_id  TEXT PRIMARY KEY,       -- mirror of the D1 login authority
  person_id   TEXT NOT NULL,          -- the person the login belongs to
  email       TEXT UNIQUE,            -- the sign-in identity
  role        TEXT NOT NULL CHECK (role IN ('owner', 'curator', 'viewer')),
  created_at  TEXT NOT NULL,
  disabled_at TEXT
) STRICT;
CREATE INDEX accounts_person ON accounts (person_id);

CREATE TABLE search_docs (
  doc_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_kind TEXT NOT NULL,
  entity_id   TEXT NOT NULL,
  UNIQUE (entity_kind, entity_id)
) STRICT;

CREATE VIRTUAL TABLE search USING fts5(
  title,
  body,
  tokenize = 'unicode61'
);
