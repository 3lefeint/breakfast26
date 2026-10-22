-- The circle (sharing across the installations of a group of friends, see PROTOCOL.md, "Circle"): the sites the admin
-- approved, the circle players, which player of a site is which circle player, which sites get the data of a player, and the
-- index of the match records. The records themselves are plain JSON in R2 (binding RECORDS, object `circle/<match id>`).
-- Times are epoch milliseconds.
CREATE TABLE circle_sites (
  location_id TEXT PRIMARY KEY,
  approved INTEGER NOT NULL DEFAULT 0,
  approved_at INTEGER,
  last_seen INTEGER,
  version TEXT,
  players TEXT NOT NULL DEFAULT '[]',
  state TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE circle_players (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  created_at INTEGER NOT NULL
);

CREATE TABLE circle_mappings (
  location_id TEXT NOT NULL,
  local_name TEXT NOT NULL,
  player_id TEXT NOT NULL,
  PRIMARY KEY (location_id, local_name)
);
CREATE INDEX circle_mappings_player ON circle_mappings (player_id);

CREATE TABLE circle_rules (
  player_id TEXT NOT NULL,
  location_id TEXT NOT NULL,
  PRIMARY KEY (player_id, location_id)
);
CREATE INDEX circle_rules_location ON circle_rules (location_id);

CREATE TABLE circle_records (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  match_id TEXT NOT NULL UNIQUE,
  revision INTEGER NOT NULL,
  origin TEXT NOT NULL,
  game_mode TEXT NOT NULL,
  deleted INTEGER NOT NULL DEFAULT 0,
  size INTEGER NOT NULL,
  hash TEXT NOT NULL,
  players TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE INDEX circle_records_origin ON circle_records (origin, created_at);
