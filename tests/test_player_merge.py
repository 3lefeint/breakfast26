import asyncio
import json
import sqlite3

import pytest

from breakfast.stats import StatsDB, StatsTracker
from breakfast.web import server


@pytest.fixture
def db(tmp_path):
    return StatsDB(str(tmp_path / "stats.db"))


def run(db, sql, *args):
    with db._lock:
        db._conn.execute(sql, args)
        db._conn.commit()


def one(db, sql, *args):
    return db._conn.execute(sql, args).fetchone()[0]


def add_player(db, name, hidden=0, color=None, created="2026-01-01T00:00:00+00:00"):
    run(db, "INSERT INTO players (name, created_at, hidden, color) VALUES (?, ?, ?, ?)", name, created, hidden, color)


def add_match(db, match_id, players, winner=None, mode="Elimination"):
    run(db, "INSERT INTO matches (match_id, started_at, game_mode, players, winner) VALUES (?, ?, ?, ?, ?)",
        match_id, "2026-02-01T00:00:00+00:00", mode, json.dumps(players), winner)


def add_turn(db, match_id, player):
    run(db, "INSERT INTO turns (match_id, player, leg, turn, remaining_before) VALUES (?, ?, 1, 1, 501)",
        match_id, player)


@pytest.fixture
def two(db):
    add_player(db, "ben", hidden=1, color="#112233", created="2026-03-01T00:00:00+00:00")
    add_player(db, "benny", color="#ffffff", created="2026-05-01T00:00:00+00:00")
    add_player(db, "carl")
    return db


class TestMerge:
    def test_everything_of_the_source_moves_to_the_target(self, two):
        db = two
        add_match(db, "m1", ["ben", "carl"], winner="ben", mode="X01")
        add_match(db, "m2", ["benny", "carl"], winner="carl")
        add_turn(db, "m1", "ben")
        add_turn(db, "m2", "benny")
        run(db, "INSERT INTO legs (match_id, leg, winner) VALUES ('m1', 1, 'ben')")
        run(db, "INSERT INTO elimination_results (match_id, player, placement) VALUES ('m1', 'ben', 1)")
        run(db, "INSERT INTO killer_events (turn_id, match_id, player, kind, victim, dart_no) "
                "VALUES (1, 'm1', 'carl', 'hit', 'ben', 1)")
        run(db, "INSERT INTO killer_events (turn_id, match_id, player, kind, victim, dart_no) "
                "VALUES (1, 'm1', 'ben', 'hit', 'carl', 2)")
        run(db, "INSERT INTO field_training_games (match_id, player, field, darts) VALUES ('f1', 'ben', 20, 30)")
        run(db, "INSERT INTO dart_positions (match_id, game_mode, player, turn, dart_number, x, y) "
                "VALUES ('m1', 'X01', 'ben', 1, 1, 0.1, 0.2)")

        res = db.merge_players("ben", "benny")

        assert res["matches"] == 2 and res["achievements"] == 0 and "error" not in res
        for table in ("turns", "elimination_results", "field_training_games", "dart_positions"):
            assert one(db, f"SELECT COUNT(*) FROM {table} WHERE player = 'ben'") == 0
        assert one(db, "SELECT COUNT(*) FROM turns WHERE player = 'benny'") == 2
        assert one(db, "SELECT winner FROM legs") == "benny"
        assert one(db, "SELECT winner FROM matches WHERE match_id = 'm1'") == "benny"
        assert json.loads(one(db, "SELECT players FROM matches WHERE match_id = 'm1'")) == ["benny", "carl"]
        events = {(r["player"], r["victim"]) for r in db._conn.execute("SELECT player, victim FROM killer_events")}
        assert events == {("carl", "benny"), ("benny", "carl")}

    def test_the_source_is_removed_and_the_target_keeps_its_settings(self, two):
        two.merge_players("ben", "benny")
        rows = {r["name"]: r for r in two._conn.execute("SELECT * FROM players")}
        assert set(rows) == {"benny", "carl"}
        assert rows["benny"]["color"] == "#ffffff" and rows["benny"]["hidden"] == 0
        assert rows["benny"]["created_at"] == "2026-03-01T00:00:00+00:00", "the earlier of the two"

    def test_a_name_that_is_in_the_same_match_list_twice_is_listed_once(self, two):
        add_match(two, "m1", ["ben", "benny"])
        # both in one match is refused, so only a list that names the source and the target is built by hand
        run(two, "UPDATE matches SET players = ? WHERE match_id = 'm1'", json.dumps(["ben", "carl", "benny"]))
        run(two, "DELETE FROM turns")
        assert two.merge_players("ben", "benny").get("error") is None
        assert json.loads(one(two, "SELECT players FROM matches")) == ["benny", "carl"]

    def test_an_achievement_both_earned_is_kept_once_with_the_earlier_date(self, two):
        run(two, "INSERT INTO achievements_earned (player, achievement_id, tier, earned_at, match_id) "
                 "VALUES ('ben', 'a', 0, '2026-04-01', 'early')")
        run(two, "INSERT INTO achievements_earned (player, achievement_id, tier, earned_at, match_id) "
                 "VALUES ('benny', 'a', 0, '2026-06-01', 'late')")
        run(two, "INSERT INTO achievements_earned (player, achievement_id, tier, earned_at, match_id) "
                 "VALUES ('ben', 'b', 1, '2026-04-02', 'only')")
        res = two.merge_players("ben", "benny")
        assert res["achievements"] == 2
        rows = {(r["achievement_id"], r["tier"]): (r["player"], r["earned_at"], r["match_id"])
                for r in two._conn.execute("SELECT * FROM achievements_earned")}
        assert rows == {("a", 0): ("benny", "2026-04-01", "early"), ("b", 1): ("benny", "2026-04-02", "only")}

    def test_a_copy_of_the_database_is_made_first(self, two):
        add_match(two, "m1", ["ben"])
        add_turn(two, "m1", "ben")
        res = two.merge_players("ben", "benny")
        copy = sqlite3.connect(res["backup"])
        try:
            assert copy.execute("SELECT COUNT(*) FROM turns WHERE player = 'ben'").fetchone()[0] == 1
            assert copy.execute("SELECT COUNT(*) FROM players WHERE name = 'ben'").fetchone()[0] == 1
        finally:
            copy.close()

    @pytest.mark.parametrize("source,target,text", [
        ("ben", "ben", "different"), ("nobody", "benny", "unknown"), ("ben", "nobody", "unknown")])
    def test_what_cannot_be_merged_is_refused(self, two, source, target, text):
        res = two.merge_players(source, target)
        assert text in res["error"]
        assert one(two, "SELECT COUNT(*) FROM players") == 3

    def test_two_players_of_the_same_match_are_refused(self, two):
        add_match(two, "m1", ["ben", "benny"])
        add_turn(two, "m1", "ben")
        add_turn(two, "m1", "benny")
        res = two.merge_players("ben", "benny")
        assert "same matches" in res["error"]
        assert one(two, "SELECT COUNT(*) FROM turns WHERE player = 'ben'") == 1

    def test_the_preview_counts_what_would_move(self, two):
        add_match(two, "m1", ["ben"])
        add_turn(two, "m1", "ben")
        run(two, "INSERT INTO achievements_earned (player, achievement_id, tier, earned_at) VALUES ('ben', 'a', 0, 'x')")
        assert two.merge_preview("ben", "benny") == {"matches": 1, "achievements": 1}
        assert one(two, "SELECT COUNT(*) FROM players") == 3, "nothing changed"


class TestEndpoint:
    @pytest.fixture
    def wired(self, two):
        server.wire(None, None, stats_tracker=StatsTracker(two))
        yield two
        server.wire(None, None)

    def test_merges_and_reports_what_moved(self, wired):
        add_match(wired, "m1", ["ben"])
        add_turn(wired, "m1", "ben")
        res = asyncio.run(server.merge_players(server.MergeBody(source="ben", target="benny")))
        assert res["matches"] == 1 and "backup" in res
        assert one(wired, "SELECT COUNT(*) FROM players WHERE name = 'ben'") == 0

    def test_is_refused_while_a_game_is_running(self, wired, monkeypatch):
        class Running:
            active = True
        monkeypatch.setattr(server, "_elim_ctrl", Running())
        res = asyncio.run(server.merge_players(server.MergeBody(source="ben", target="benny")))
        assert "running game" in res["error"]
        assert one(wired, "SELECT COUNT(*) FROM players WHERE name = 'ben'") == 1

    def test_the_preview_is_served(self, wired):
        assert asyncio.run(server.merge_players_preview("ben", "benny")) == {"matches": 0, "achievements": 0}
