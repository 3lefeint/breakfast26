import sqlite3
from datetime import datetime, timedelta, timezone

from breakfast.stats import StatsDB, load_timezone


class TestCreatedAt:
    def test_an_x01_turn_stores_the_time_it_was_played(self):
        db = StatsDB(":memory:")
        db.open_match("m1", "X01", 501)
        before = datetime.now(timezone.utc)
        db.insert_turn("m1", "ana", 1, 1, 501, 60, False, False, [("T20", 60, 441)])
        stored = db._conn.execute("SELECT created_at FROM turns").fetchone()[0]
        assert before <= datetime.fromisoformat(stored) <= datetime.now(timezone.utc)

    def test_an_elimination_turn_stores_the_time_it_was_played(self):
        db = StatsDB(":memory:")
        db.open_match("e1", "Elimination", 0)
        before = datetime.now(timezone.utc)
        db.insert_elimination_turn("e1", "ana", 3, score=30, target=0, freipass=True, passed=True, lives_before=3)
        stored = db._conn.execute("SELECT created_at FROM elimination_turns").fetchone()[0]
        assert before <= datetime.fromisoformat(stored) <= datetime.now(timezone.utc)


class TestMigration:
    def _old_database(self, path):
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE matches (match_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, ended_at TEXT,
                                  game_mode TEXT, points_start INTEGER, players TEXT);
            CREATE TABLE turns (id INTEGER PRIMARY KEY AUTOINCREMENT, match_id TEXT NOT NULL,
                player TEXT NOT NULL, leg INTEGER NOT NULL DEFAULT 1, turn INTEGER NOT NULL,
                remaining_before INTEGER NOT NULL, score INTEGER NOT NULL DEFAULT 0,
                is_bust INTEGER NOT NULL DEFAULT 0, is_checkout INTEGER NOT NULL DEFAULT 0,
                darts_count INTEGER NOT NULL DEFAULT 0,
                dart1 TEXT, dart1_val INTEGER, dart1_rem INTEGER,
                dart2 TEXT, dart2_val INTEGER, dart2_rem INTEGER,
                dart3 TEXT, dart3_val INTEGER, dart3_rem INTEGER);
            CREATE TABLE elimination_turns (id INTEGER PRIMARY KEY AUTOINCREMENT, match_id TEXT NOT NULL,
                player TEXT NOT NULL, darts_count INTEGER NOT NULL, score INTEGER, target INTEGER,
                freipass INTEGER, passed INTEGER, lives_before INTEGER);
            CREATE TABLE dart_positions (id INTEGER PRIMARY KEY AUTOINCREMENT, match_id TEXT NOT NULL,
                game_mode TEXT NOT NULL, player TEXT NOT NULL, leg INTEGER NOT NULL DEFAULT 1,
                turn INTEGER NOT NULL, dart_number INTEGER NOT NULL, field TEXT, x REAL NOT NULL,
                y REAL NOT NULL, entry TEXT, corrected INTEGER NOT NULL DEFAULT 0);
            INSERT INTO matches VALUES ('e1', '2026-10-01T10:00:00+00:00', NULL, 'Elimination', 0, NULL);
            INSERT INTO elimination_turns (match_id, player, darts_count) VALUES ('e1', 'ana', 3);
            INSERT INTO turns (match_id, player, turn, remaining_before) VALUES ('e1', 'ana', 1, 501);
            INSERT INTO dart_positions (match_id, game_mode, player, turn, dart_number, field, x, y, corrected)
                VALUES ('e1', 'Elimination', 'ana', 1, 1, 'T20', 0.0, 0.6, 0),
                       ('e1', 'Elimination', 'ana', 1, 2, 'S5', 0.1, 0.2, 1);
        """)
        conn.commit()
        conn.close()

    def test_an_old_database_gets_the_new_columns_and_keeps_its_rows(self, tmp_path):
        path = str(tmp_path / "old.db")
        self._old_database(path)
        db = StatsDB(path)
        assert db._conn.execute("SELECT created_at FROM turns").fetchone()[0] is None
        assert db._conn.execute("SELECT created_at FROM elimination_turns").fetchone()[0] is None
        rows = db._conn.execute("SELECT corrected, misread FROM dart_positions ORDER BY id").fetchall()
        assert [tuple(r) for r in rows] == [(0, 0), (1, 1)]    # what was corrected stays untrusted

    def test_a_later_start_does_not_distrust_darts_set_by_hand(self, tmp_path):
        path = str(tmp_path / "old.db")
        self._old_database(path)
        first = StatsDB(path)
        first._conn.execute(
            "INSERT INTO dart_positions (match_id, game_mode, player, turn, dart_number, field, x, y,"
            " corrected, misread) VALUES ('e1', 'Elimination', 'ana', 2, 1, 'D16', 0.1, 0.2, 1, 0)")
        first._conn.commit()
        second = StatsDB(path)
        assert second._conn.execute("SELECT misread FROM dart_positions WHERE turn = 2").fetchone()[0] == 0


class TestTimezone:
    STORED = "2026-10-04T05:30:00+00:00"

    def test_the_default_is_utc(self):
        assert StatsDB(":memory:").local_time(self.STORED).hour == 5

    def test_a_stored_time_is_converted_to_the_configured_zone(self):
        db = StatsDB(":memory:", tz="Europe/Zurich")
        assert db.local_time(self.STORED).hour == 7          # summer time, UTC+2
        assert db.local_time("2026-01-04T05:30:00+00:00").hour == 6

    def test_an_unknown_name_falls_back_to_utc(self, caplog):
        db = StatsDB(":memory:", tz="Mars/Base")
        assert db.local_time(self.STORED).utcoffset() == timedelta(0)
        assert "Mars/Base" in caplog.text

    def test_load_timezone_accepts_none(self):
        assert str(load_timezone(None)) == "UTC"
