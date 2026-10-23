-- The profile of a circle player (see PROTOCOL.md, "Circle"): one row per field, `color` or `voice:<pack>`, the value as JSON
-- (NULL once it was cleared) and the time the relay took it in. The latest change wins. Times are epoch milliseconds.
CREATE TABLE circle_profiles (
  player_id TEXT NOT NULL,
  field TEXT NOT NULL,
  value TEXT,
  updated_at INTEGER NOT NULL,
  PRIMARY KEY (player_id, field)
);
