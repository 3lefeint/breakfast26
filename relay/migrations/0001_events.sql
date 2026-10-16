-- The usage reports of Breakfast installations. `data` holds the fields of the event besides type and ts.
CREATE TABLE events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  received_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  install_id TEXT NOT NULL,
  version TEXT NOT NULL,
  platform TEXT NOT NULL,
  type TEXT NOT NULL,
  ts TEXT NOT NULL,
  data TEXT NOT NULL
);
CREATE INDEX events_type_received ON events (type, received_at);
CREATE INDEX events_install_received ON events (install_id, received_at);
