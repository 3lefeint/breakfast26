-- Mailboxes of the members of a location (PROTOCOL.md, "Mailboxes"): the devices that may use a mailbox, the one-time
-- invitations of a member (only the hash of the token is stored) and the index of the records. The ciphertext of a record
-- lives in R2 (binding RECORDS) under `<mailbox>/<channel>/<match id>/<revision>`. Times are epoch milliseconds.
CREATE TABLE mailboxes (
  id TEXT PRIMARY KEY,
  location_id TEXT NOT NULL,
  up_enabled INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL
);
CREATE INDEX mailboxes_location ON mailboxes (location_id);

CREATE TABLE mailbox_invitations (
  token_hash TEXT PRIMARY KEY,
  mailbox_id TEXT NOT NULL,
  expires_at INTEGER NOT NULL,
  used_at INTEGER
);
CREATE INDEX mailbox_invitations_mailbox ON mailbox_invitations (mailbox_id);

CREATE TABLE devices (
  id TEXT PRIMARY KEY,
  mailbox_id TEXT NOT NULL,
  public_key TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE INDEX devices_mailbox ON devices (mailbox_id);

CREATE TABLE records (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  mailbox_id TEXT NOT NULL,
  channel TEXT NOT NULL,
  match_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  game_mode TEXT NOT NULL,
  deleted INTEGER NOT NULL DEFAULT 0,
  size INTEGER NOT NULL,
  hash TEXT NOT NULL,
  envelope_version INTEGER NOT NULL,
  writer TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE UNIQUE INDEX records_key ON records (mailbox_id, channel, match_id, revision);
CREATE INDEX records_cursor ON records (mailbox_id, channel, seq);
CREATE INDEX records_writer ON records (writer, created_at);
