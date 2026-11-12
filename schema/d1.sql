-- The remote store (D1). The concepts are docs/TECHSPEC/05-schema.md §18.13.

CREATE TABLE accounts (
  account_id   TEXT PRIMARY KEY,     -- the invite id
  email        TEXT NOT NULL UNIQUE, -- the invite address
  subject      TEXT UNIQUE,          -- the Google sub, null until first sign-in
  person_id    TEXT,                 -- the archive person, null until linked
  role         TEXT NOT NULL DEFAULT 'curator'
               CHECK (role IN ('owner', 'curator', 'viewer')),
  status       TEXT NOT NULL DEFAULT 'invited'
               CHECK (status IN ('invited', 'active', 'disabled')),
  invited_at   TEXT NOT NULL,
  activated_at TEXT,
  last_seen_at TEXT
);

CREATE TABLE auth_sessions (
  session_id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  revoked_at TEXT
);
CREATE INDEX auth_sessions_account ON auth_sessions (account_id);

CREATE TABLE commands (
  seq              INTEGER PRIMARY KEY AUTOINCREMENT,
  command_id       TEXT NOT NULL UNIQUE,
  actor_account_id TEXT NOT NULL,
  kind             TEXT NOT NULL,
  target_kind      TEXT NOT NULL,
  target_id        TEXT NOT NULL,
  payload_json     TEXT NOT NULL,
  base_version     INTEGER,
  idempotency_key  TEXT NOT NULL,
  outcome          TEXT NOT NULL DEFAULT 'pending'
                   CHECK (outcome IN ('pending', 'applied', 'parked', 'rejected')),
  reason           TEXT,
  received_at      TEXT NOT NULL,
  applied_at       TEXT,
  UNIQUE (actor_account_id, idempotency_key)
);
CREATE INDEX commands_outcome ON commands (outcome);

CREATE TABLE review_sessions (
  session_id       TEXT PRIMARY KEY,
  kind             TEXT NOT NULL,
  subject_kind     TEXT NOT NULL,
  subject_id       TEXT,
  actor_account_id TEXT NOT NULL,
  status           TEXT NOT NULL,
  created_at       TEXT NOT NULL,
  updated_at       TEXT NOT NULL
);

CREATE TABLE messages (
  session_id       TEXT NOT NULL,
  ordinal          INTEGER NOT NULL,
  request_key      TEXT,               -- the Idempotency-Key on the user's message; null on assistant/system rows
  role             TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
  actor_account_id TEXT,
  text             TEXT NOT NULL,
  created_at       TEXT NOT NULL,
  PRIMARY KEY (session_id, ordinal),
  UNIQUE (actor_account_id, request_key)
);
