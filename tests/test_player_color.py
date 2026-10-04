import sqlite3

import pytest
from starlette.testclient import TestClient

from breakfast.stats import StatsDB, StatsTracker
from breakfast.web import server


class TestStoredColor:
    def test_a_player_has_no_color_until_one_is_set(self, db):
        db.upsert_player("ana")
        assert db.player_colors() == {}

    def test_a_color_is_stored_in_lowercase_and_can_be_cleared(self, db):
        db.upsert_player("ana")
        assert db.set_player_color("ana", "#FF8800") is True
        assert db.player_colors() == {"ana": "#ff8800"}
        assert db.set_player_color("ana", None) is True
        assert db.player_colors() == {}

    def test_only_players_with_a_color_are_listed(self, db):
        db.upsert_player("ana")
        db.upsert_player("bo")
        db.set_player_color("bo", "#00ff00")
        assert db.player_colors() == {"bo": "#00ff00"}

    @pytest.mark.parametrize("value", ["red", "#fff", "#ggg000", "ff8800", "#ff88000", ""])
    def test_a_value_that_is_not_rrggbb_is_rejected(self, db, value):
        db.upsert_player("ana")
        with pytest.raises(ValueError):
            db.set_player_color("ana", value)
        assert db.player_colors() == {}

    def test_an_unknown_player_is_reported(self, db):
        assert db.set_player_color("nobody", "#ff8800") is False

    def test_deleting_a_player_removes_the_color(self, db):
        db.upsert_player("ana")
        db.set_player_color("ana", "#ff8800")
        db.delete_player("ana")
        assert db.player_colors() == {}

    def test_an_old_database_gets_the_column_and_keeps_its_players(self, tmp_path):
        path = str(tmp_path / "old.db")
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE players (name TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                                  hidden INTEGER NOT NULL DEFAULT 0);
            INSERT INTO players (name, created_at) VALUES ('ana', '2026-10-01T10:00:00+00:00');
        """)
        conn.commit()
        conn.close()
        db = StatsDB(path)
        assert db.set_player_color("ana", "#123456") is True
        assert db.player_colors() == {"ana": "#123456"}


class TestColorEndpoint:
    @pytest.fixture
    def client(self, tmp_path):
        db = StatsDB(str(tmp_path / "s.db"))
        db.upsert_player("ana")
        server.wire(None, None, stats_tracker=StatsTracker(db))
        yield TestClient(server.app), db
        server.wire(None, None)

    def test_a_color_can_be_set_and_cleared(self, client):
        c, db = client
        assert c.patch("/api/players/ana/color", json={"color": "#ABCDEF"}).json() == {"ok": True}
        assert db.player_colors() == {"ana": "#abcdef"}
        assert c.patch("/api/players/ana/color", json={"color": None}).json() == {"ok": True}
        assert db.player_colors() == {}

    def test_a_bad_value_and_an_unknown_player_come_back_as_errors(self, client):
        c, db = client
        assert "error" in c.patch("/api/players/ana/color", json={"color": "red"}).json()
        assert c.patch("/api/players/nobody/color", json={"color": "#ffffff"}).json() == {"error": "unknown player"}
        assert db.player_colors() == {}

    def test_the_colors_are_part_of_the_state(self, client):
        c, db = client
        db.set_player_color("ana", "#ff0000")
        assert server._build_payload()["player_colors"] == {"ana": "#ff0000"}

    def test_without_a_stats_database_there_is_nothing_to_set(self):
        server.wire(None, None)
        res = TestClient(server.app).patch("/api/players/ana/color", json={"color": "#ff0000"})
        assert res.json() == {"error": "stats not enabled"}
        assert server._build_payload()["player_colors"] == {}
