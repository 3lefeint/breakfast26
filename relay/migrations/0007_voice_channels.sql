-- Voice chat channels of the circle (see PROTOCOL.md, "Voice channels"): the channels the admin made and which sites see which
-- channel. Times are epoch milliseconds.
CREATE TABLE voice_channels (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE UNIQUE INDEX voice_channels_name ON voice_channels (lower(name));

CREATE TABLE voice_channel_sites (
  channel_id TEXT NOT NULL,
  location_id TEXT NOT NULL,
  PRIMARY KEY (channel_id, location_id)
);
CREATE INDEX voice_channel_sites_location ON voice_channel_sites (location_id);
