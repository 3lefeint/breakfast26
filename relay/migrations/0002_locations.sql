-- Locations (registered installations), the one-time invitations between them and the links they create.
-- Only the hash of an invitation token is stored. `kind` of a link is "play" for now.
CREATE TABLE locations (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  public_key TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE invitations (
  token_hash TEXT PRIMARY KEY,
  location_id TEXT NOT NULL,
  expires_at INTEGER NOT NULL,
  used_at INTEGER
);
CREATE INDEX invitations_location ON invitations (location_id);

CREATE TABLE links (
  id TEXT PRIMARY KEY,
  location_a TEXT NOT NULL,
  location_b TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'play',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX links_a ON links (location_a);
CREATE INDEX links_b ON links (location_b);
