-- Matches that a registered location opened, so linked locations can list and join them. A row lives as long as the
-- code (10 minutes) and is dropped when the match is no longer in its lobby.
CREATE TABLE open_matches (
  code TEXT PRIMARY KEY,
  location_id TEXT NOT NULL,
  site TEXT,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);
CREATE INDEX open_matches_location ON open_matches (location_id);
