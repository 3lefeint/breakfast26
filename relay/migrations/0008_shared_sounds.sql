-- Scenes and achievement sounds shared in the circle (see PROTOCOL.md, "Circle"). A sound file is stored once per hash (its
-- bytes in R2 under `sounds/<hash>`); a scene or an achievement entry names the files it plays by hash. A change gets a new
-- `seq` (the row is replaced), the sites catch up by it. Times are epoch milliseconds.
CREATE TABLE circle_sounds (
  hash TEXT PRIMARY KEY,
  size INTEGER NOT NULL,
  origin TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE TABLE circle_scenes (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  scene_id TEXT NOT NULL,
  origin TEXT NOT NULL,
  name TEXT NOT NULL,
  graph TEXT NOT NULL,
  sounds TEXT NOT NULL,
  deleted INTEGER NOT NULL DEFAULT 0,
  updated_at INTEGER NOT NULL,
  UNIQUE (origin, scene_id)
);
CREATE TABLE circle_achievement_sounds (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  achievement TEXT NOT NULL,
  origin TEXT NOT NULL,
  files TEXT NOT NULL,
  deleted INTEGER NOT NULL DEFAULT 0,
  updated_at INTEGER NOT NULL,
  UNIQUE (origin, achievement)
);
