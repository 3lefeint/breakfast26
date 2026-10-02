import json
import sqlite3

import pytest
from breakfast.stats import StatsDB


def _open(db, match_id="m1", mode="X01", pts=501):
    db.open_match(match_id, mode, pts)


def _turn(db, match_id="m1", player="alice", leg=1, turn=1,
          remaining_before=501, score=100, is_bust=False, is_checkout=False,
          darts=None):
    if darts is None:
        darts = [("T20", 60, 441), ("T19", 57, 384), ("S3", score - 117, 384 - (score - 117))]
    db.insert_turn(match_id, player, leg, turn, remaining_before,
                   score, is_bust, is_checkout, darts)


class TestStatsDB:
    def test_empty_db_returns_no_players(self, db):
        assert db.all_players_stats() == []

    def test_insert_turn_and_session_stats(self, db):
        _open(db)
        db.insert_turn("m1", "alice", 1, 1, 501, 177, False, False,
                       [("T20", 60, 441), ("T20", 60, 381), ("T19", 57, 324)])
        stats = db.session_stats("m1")
        assert stats["alice"]["turns"] == 1
        assert stats["alice"]["avg3"] == 177.0

    def test_checkout_co_hits(self, db):
        _open(db)
        db.insert_turn("m1", "alice", 1, 1, 32, 32, False, True, [("D16", 32, 0)])
        stats = db.session_stats("m1")
        assert stats["alice"]["co_hits"] == 1
        assert stats["alice"]["co_pct"] == 100.0

    def test_bust_not_checkout(self, db):
        _open(db)
        db.insert_turn("m1", "alice", 1, 1, 20, 0, True, False, [("5", 5, 15)])
        stats = db.session_stats("m1")
        assert stats["alice"]["co_hits"] == 0
        assert stats["alice"]["co_pct"] == 0.0

    def test_checkout_attempt_counted(self, db):
        _open(db)
        # remaining_before=32 (≤ 40) → dart1 was thrown at a double
        db.insert_turn("m1", "alice", 1, 1, 32, 20, False, False, [("20", 20, 12)])
        rows = db.all_players_stats()
        alice = next(r for r in rows if r["player"] == "alice")
        assert alice["co_attempts"] == 1

    def test_checkout_hit_counted(self, db):
        _open(db)
        # checkout with remaining_before=32 (≤ 40) → dart1 was a double hit
        db.insert_turn("m1", "alice", 1, 1, 32, 32, False, True, [("D16", 32, 0)])
        rows = db.all_players_stats()
        alice = next(r for r in rows if r["player"] == "alice")
        assert alice["co_hits"] == 1
        assert alice["co_pct"] == 100.0

    def test_all_players_stats_multiple_players(self, db):
        _open(db)
        db.insert_turn("m1", "alice", 1, 1, 501, 100, False, False,
                       [("T20", 60, 441), ("T13", 39, 402), ("S1", 1, 401)])
        db.insert_turn("m1", "bob", 1, 1, 501, 60, False, False,
                       [("20", 20, 481), ("20", 20, 461), ("20", 20, 441)])
        rows = db.all_players_stats()
        names = {r["player"] for r in rows}
        assert "alice" in names
        assert "bob" in names

    def test_total_score_in_stats(self, db):
        _open(db)
        db.insert_turn("m1", "alice", 1, 1, 501, 180, False, False,
                       [("T20", 60, 441), ("T20", 60, 381), ("T20", 60, 321)])
        rows = db.all_players_stats()
        alice = next(r for r in rows if r["player"] == "alice")
        assert alice["total_score"] == 180

    def test_leaderboard_avg_order(self, db):
        _open(db, "m1")
        _open(db, "m2")
        db.insert_turn("m1", "alice", 1, 1, 501, 180, False, False,
                       [("T20", 60, 441), ("T20", 60, 381), ("T20", 60, 321)])
        db.insert_turn("m2", "bob", 1, 1, 501, 60, False, False,
                       [("20", 20, 481), ("20", 20, 461), ("20", 20, 441)])
        board = db.leaderboard("avg3")
        assert board[0]["player"] == "alice"
        assert board[1]["player"] == "bob"

    def test_leaderboard_invalid_metric(self, db):
        with pytest.raises(ValueError):
            db.leaderboard("invalid_metric")

    def test_recent_matches_excludes_empty(self, db):
        db.open_match("m-empty", "X01", 501)
        db.open_match("m-with", "X01", 501)
        db.insert_turn("m-with", "alice", 1, 1, 501, 60, False, False,
                       [("20", 20, 481), ("20", 20, 461), ("20", 20, 441)])
        matches = db.recent_matches()
        ids = [m["match_id"] for m in matches]
        assert "m-empty" not in ids
        assert "m-with" in ids

    def test_delete_player_removes_turns(self, db):
        _open(db)
        db.insert_turn("m1", "alice", 1, 1, 501, 60, False, False,
                       [("20", 20, 481), ("20", 20, 461), ("20", 20, 441)])
        db.insert_turn("m1", "bob", 1, 1, 501, 60, False, False,
                       [("20", 20, 481), ("20", 20, 461), ("20", 20, 441)])
        db.delete_player("alice")
        rows = db.all_players_stats()
        names = [r["player"] for r in rows]
        assert "alice" not in names
        assert "bob" in names

    def test_record_leg_win(self, db):
        _open(db)
        db.record_leg_win("m1", 1, "alice")
        db.record_leg_win("m1", 2, "bob")
        db.record_leg_win("m1", 3, "alice")
        won = db.legs_won_by_player("m1")
        assert won["alice"] == 2
        assert won["bob"] == 1

    def test_record_leg_win_null_winner(self, db):
        _open(db)
        db.record_leg_win("m1", 1, None)
        won = db.legs_won_by_player("m1")
        assert won == {}   # NULL winner not counted

    def test_recent_matches_includes_legs_won(self, db):
        _open(db)
        db.insert_turn("m1", "alice", 1, 1, 501, 60, False, False,
                       [("20", 20, 481), ("20", 20, 461), ("20", 20, 441)])
        db.record_leg_win("m1", 1, "alice")
        db.record_leg_win("m1", 2, "bob")
        matches = db.recent_matches()
        m = next(r for r in matches if r["match_id"] == "m1")
        assert m["legs_won"]["alice"] == 1
        assert m["legs_won"]["bob"] == 1
        assert m["legs_total"] == 2


class TestPlayersTable:
    def test_insert_turn_auto_links_player(self, db):
        _open(db)
        db.insert_turn("m1", "alice", 1, 1, 501, 60, False, False,
                       [("20", 20, 481), ("20", 20, 461), ("20", 20, 441)])
        rows = db._conn.execute("SELECT name FROM players WHERE name='alice'").fetchall()
        assert len(rows) == 1

    def test_upsert_player_sets_hidden(self, db):
        db.upsert_player("alice")
        assert db.list_players() == ["alice"]
        db.upsert_player("alice", hidden=True)
        row = db._conn.execute("SELECT hidden FROM players WHERE name='alice'").fetchone()
        assert row["hidden"] == 1

    def test_list_players_includes_every_known_player_by_default(self, db):
        _open(db)
        db.insert_turn("m1", "online_opponent", 1, 1, 501, 60, False, False,
                       [("20", 20, 481), ("20", 20, 461), ("20", 20, 441)])
        db.upsert_player("alice")
        assert set(db.list_players()) == {"online_opponent", "alice"}

    def test_list_players_excludes_hidden(self, db):
        _open(db)
        db.insert_turn("m1", "alice", 1, 1, 501, 60, False, False,
                       [("20", 20, 481), ("20", 20, 461), ("20", 20, 441)])
        db.upsert_player("alice", hidden=True)
        assert db.list_players() == []

    def test_delete_player_cascades_to_players_table(self, db):
        _open(db)
        db.insert_turn("m1", "alice", 1, 1, 501, 60, False, False,
                       [("20", 20, 481), ("20", 20, 461), ("20", 20, 441)])
        db.delete_player("alice")
        rows = db._conn.execute("SELECT name FROM players WHERE name='alice'").fetchall()
        assert rows == []

    def test_hidden_player_excluded_from_all_players_stats(self, db):
        _open(db)
        db.insert_turn("m1", "alice", 1, 1, 501, 60, False, False,
                       [("20", 20, 481), ("20", 20, 461), ("20", 20, 441)])
        db.upsert_player("alice", hidden=True)
        assert db.all_players_stats() == []

    def test_hidden_player_still_visible_in_player_stats(self, db):
        _open(db)
        db.insert_turn("m1", "alice", 1, 1, 501, 60, False, False,
                       [("20", 20, 481), ("20", 20, 461), ("20", 20, 441)])
        db.upsert_player("alice", hidden=True)
        assert db.player_stats("alice") is not None

    def test_hidden_player_excluded_from_leaderboard(self, db):
        _open(db)
        db.insert_turn("m1", "alice", 1, 1, 501, 180, False, False,
                       [("T20", 60, 441), ("T20", 60, 381), ("T20", 60, 321)])
        db.upsert_player("alice", hidden=True)
        assert db.leaderboard("avg3") == []

    def test_hidden_players_lists_only_hidden(self, db):
        db.upsert_player("alice", hidden=True)
        db.upsert_player("bob", hidden=False)
        assert db.hidden_players() == ["alice"]

    def test_unhide_removes_from_hidden_players(self, db):
        db.upsert_player("alice", hidden=True)
        db.upsert_player("alice", hidden=False)
        assert db.hidden_players() == []

    def test_list_players_is_alphabetical_case_insensitive(self, db):
        for name in ["charlie", "Alice", "bob"]:
            db.upsert_player(name)
        assert db.list_players() == ["Alice", "bob", "charlie"]


class TestElimination:
    def test_insert_elimination_turn_auto_links_player(self, db):
        db.open_match("e1", "Elimination", 3)
        db.insert_elimination_turn("e1", "alice", 3)
        rows = db._conn.execute("SELECT name FROM players WHERE name='alice'").fetchall()
        assert len(rows) == 1

    def test_record_elimination_result_and_win_counts(self, db):
        db.open_match("e1", "Elimination", 3)
        db.record_elimination_result("e1", [("alice", 1, 2), ("bob", 2, None)])
        assert db.win_counts() == {"alice": 1}

    def test_x01_win_counts_excludes_elimination(self, db):
        _open(db, "m1")
        _turn(db, "m1", "alice")
        _turn(db, "m1", "bob")
        db.set_winner("m1", "alice")
        _open(db, "m2")
        _turn(db, "m2", "alice")
        _turn(db, "m2", "bob")
        db.set_winner("m2", "alice")
        db.open_match("e1", "Elimination", 3)
        db.record_elimination_result("e1", [("bob", 1, 2)])
        db.set_winner("e1", "bob")
        assert db.x01_win_counts() == {"alice": 2}

    def test_x01_win_counts_excludes_solo_practice_matches(self, db):
        _open(db, "m1")
        _turn(db, "m1", "alice")
        db.set_winner("m1", "alice")
        _open(db, "m2")
        _turn(db, "m2", "alice")
        _turn(db, "m2", "bob")
        db.set_winner("m2", "alice")
        assert db.x01_win_counts() == {"alice": 1}

    def test_set_winner(self, db):
        db.open_match("e1", "Elimination", 3)
        db.set_winner("e1", "alice")
        row = db._conn.execute("SELECT winner FROM matches WHERE match_id='e1'").fetchone()
        assert row["winner"] == "alice"

    def test_recent_matches_includes_elimination_matches(self, db):
        db.open_match("e1", "Elimination", 3)
        db.insert_elimination_turn("e1", "alice", 3)
        matches = db.recent_matches()
        ids = [m["match_id"] for m in matches]
        assert "e1" in ids

    def test_close_match_picks_up_elimination_turns_players(self, db):
        db.open_match("e1", "Elimination", 3)
        db.insert_elimination_turn("e1", "alice", 3)
        db.insert_elimination_turn("e1", "bob", 2)
        db.close_match("e1")
        row = db._conn.execute("SELECT players FROM matches WHERE match_id='e1'").fetchone()
        assert set(json.loads(row["players"])) == {"alice", "bob"}


class TestMatchesWinnerMigration:
    def test_winner_column_added_to_pre_existing_db(self, tmp_path):
        db_path = str(tmp_path / "legacy.db")
        # Simulate an old DB file from before the `winner` column existed.
        raw = sqlite3.connect(db_path)
        raw.execute("""
            CREATE TABLE matches (
                match_id TEXT PRIMARY KEY, started_at TEXT NOT NULL,
                ended_at TEXT, game_mode TEXT, points_start INTEGER, players TEXT
            )
        """)
        raw.execute(
            "INSERT INTO matches (match_id, started_at) VALUES ('m1', 'now')"
        )
        raw.commit()
        raw.close()

        db = StatsDB(db_path)
        cols = {r["name"] for r in db._conn.execute("PRAGMA table_info(matches)")}
        assert "winner" in cols
        db.set_winner("m1", "alice")
        row = db._conn.execute("SELECT winner FROM matches WHERE match_id='m1'").fetchone()
        assert row["winner"] == "alice"


class TestBackfillX01WinnerMigration:
    def test_backfills_winner_from_last_leg_on_existing_x01_matches(self, tmp_path):
        db_path = str(tmp_path / "legacy.db")
        db = StatsDB(db_path)
        db.open_match("m1", "X01", 501)
        db.record_leg_win("m1", 1, "alice")
        db.record_leg_win("m1", 2, "bob")
        db.record_leg_win("m1", 3, "alice")  # alice won the deciding leg
        # Elimination matches must be left alone (they get `winner` from
        # elimination.py directly, not from `legs`).
        db.open_match("e1", "Elimination", 3)

        # Re-opening the same DB file simulates the app restarting against
        # pre-existing history recorded before StatsTracker started calling
        # set_winner() for X01 matches at all.
        db2 = StatsDB(db_path)
        row = db2._conn.execute("SELECT winner FROM matches WHERE match_id='m1'").fetchone()
        assert row["winner"] == "alice"
        e_row = db2._conn.execute("SELECT winner FROM matches WHERE match_id='e1'").fetchone()
        assert e_row["winner"] is None

    def test_does_not_override_an_already_set_winner(self, tmp_path):
        db_path = str(tmp_path / "legacy.db")
        db = StatsDB(db_path)
        db.open_match("m1", "X01", 501)
        db.record_leg_win("m1", 1, "bob")
        db.set_winner("m1", "alice")  # e.g. forward-recorded by match-won

        db2 = StatsDB(db_path)
        row = db2._conn.execute("SELECT winner FROM matches WHERE match_id='m1'").fetchone()
        assert row["winner"] == "alice"


class TestDropInRosterMigration:
    def test_in_roster_column_dropped_from_pre_existing_db(self, tmp_path):
        db_path = str(tmp_path / "legacy.db")
        raw = sqlite3.connect(db_path)
        raw.execute("""
            CREATE TABLE players (
                name TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                hidden INTEGER NOT NULL DEFAULT 0, in_roster INTEGER NOT NULL DEFAULT 1
            )
        """)
        raw.execute(
            "INSERT INTO players (name, created_at, in_roster) VALUES ('alice', 'now', 1)"
        )
        raw.commit()
        raw.close()

        db = StatsDB(db_path)
        cols = {r["name"] for r in db._conn.execute("PRAGMA table_info(players)")}
        assert "in_roster" not in cols
        assert db.list_players() == ["alice"]

    def test_missing_in_roster_column_is_a_noop(self, db):
        cols = {r["name"] for r in db._conn.execute("PRAGMA table_info(players)")}
        assert "in_roster" not in cols


class TestPlayerDashboard:
    """Per-player advanced-dashboard query methods."""

    def test_player_activity_combines_x01_and_elimination(self, db):
        _open(db, "m1")
        db.insert_turn("m1", "alice", 1, 1, 501, 60, False, False,
                       [("20", 20, 481), ("20", 20, 461), ("20", 20, 441)])
        db.open_match("e1", "Elimination", 3)
        db.insert_elimination_turn("e1", "alice", 3)
        db.close_match("m1")
        db.close_match("e1")
        activity = db.player_activity("alice")
        assert activity["total_darts"] == 6
        assert activity["total_games"] == 2
        assert activity["total_distance_km"] == round(2 * 4.74 / 1000, 2)

    def test_player_activity_by_date_groups_by_match_start_date(self, db):
        _open(db, "m1")
        db.insert_turn("m1", "alice", 1, 1, 501, 60, False, False,
                       [("20", 20, 481), ("20", 20, 461), ("20", 20, 441)])
        rows = db.player_activity_by_date("alice")
        assert len(rows) == 1
        assert rows[0]["darts"] == 3

    def test_performance_summary_best_avg_and_180s(self, db):
        _open(db, "m1")
        db.insert_turn("m1", "alice", 1, 1, 501, 180, False, False,
                       [("T20", 60, 441), ("T20", 60, 381), ("T20", 60, 321)])
        db.insert_turn("m1", "alice", 1, 2, 321, 60, False, False,
                       [("20", 20, 301), ("20", 20, 281), ("20", 20, 261)])
        perf = db.player_performance_summary("alice")
        assert perf["total_180s"] == 1
        assert perf["best_avg3"] == 120.0  # (180+60)/6*3

    def test_performance_summary_best_leg_darts_only_counts_wins(self, db):
        _open(db, "m1")
        db.insert_turn("m1", "alice", 1, 1, 40, 40, False, True, [("D20", 40, 0)])
        db.record_leg_win("m1", 1, "alice")
        _open(db, "m2")
        db.insert_turn("m2", "alice", 1, 1, 501, 100, False, False,
                       [("20", 20, 481), ("20", 20, 461), ("20", 20, 441)])
        db.record_leg_win("m2", 1, "bob")  # alice didn't win this leg
        perf = db.player_performance_summary("alice")
        assert perf["best_leg_darts"] == 1

    def test_performance_summary_best_leg_501_ignores_other_starts(self, db):
        _open(db, "m1", pts=301)
        db.insert_turn("m1", "alice", 1, 1, 40, 40, False, True, [("D20", 40, 0)])
        db.record_leg_win("m1", 1, "alice")
        _open(db, "m2", pts=501)
        db.insert_turn("m2", "alice", 1, 1, 40, 40, False, True,
                       [("S20", 20, 20), ("D10", 20, 0)])
        db.record_leg_win("m2", 1, "alice")
        perf = db.player_performance_summary("alice")
        assert perf["best_leg_darts"] == 1
        assert perf["best_leg_501_darts"] == 2

    def test_performance_summary_best_leg_501_none_without_501_win(self, db):
        _open(db, "m1", pts=301)
        db.insert_turn("m1", "alice", 1, 1, 40, 40, False, True, [("D20", 40, 0)])
        db.record_leg_win("m1", 1, "alice")
        assert db.player_performance_summary("alice")["best_leg_501_darts"] is None

    def test_performance_summary_best_checkout(self, db):
        _open(db, "m1")
        db.insert_turn("m1", "alice", 1, 1, 32, 32, False, True, [("D16", 32, 0)])
        db.insert_turn("m1", "alice", 1, 2, 80, 80, False, True,
                       [("T20", 60, 20), ("D10", 20, 0)])
        perf = db.player_performance_summary("alice")
        assert perf["best_checkout"] == 80

    def test_win_loss(self, db):
        _open(db, "m1")
        db.insert_turn("m1", "alice", 1, 1, 501, 60, False, False,
                       [("20", 20, 481), ("20", 20, 461), ("20", 20, 441)])
        db.insert_turn("m1", "bob", 1, 1, 501, 40, False, False,
                       [("20", 20, 481), ("20", 20, 461)])
        db.set_winner("m1", "alice")
        _open(db, "m2")
        db.insert_turn("m2", "alice", 1, 1, 501, 60, False, False,
                       [("20", 20, 481), ("20", 20, 461), ("20", 20, 441)])
        db.insert_turn("m2", "bob", 1, 1, 501, 60, False, False,
                       [("20", 20, 481), ("20", 20, 461), ("20", 20, 441)])
        db.set_winner("m2", "bob")
        result = db.player_win_loss("alice")
        assert result == {"wins": 1, "losses": 1}

    def test_win_loss_excludes_solo_practice_matches(self, db):
        _open(db, "m1")
        db.insert_turn("m1", "alice", 1, 1, 501, 60, False, False,
                       [("20", 20, 481), ("20", 20, 461), ("20", 20, 441)])
        db.set_winner("m1", "alice")
        result = db.player_win_loss("alice")
        assert result == {"wins": 0, "losses": 0}

    def test_doubles_by_number_hit_and_miss(self, db):
        _open(db, "m1")
        # Turn 1: checkout hitting D16 (remaining_before=32) — a hit at target 16
        db.insert_turn("m1", "alice", 1, 1, 32, 32, False, True, [("D16", 32, 0)])
        # Turn 2: attempted D16 (remaining_before=32) but busted — an attempt, no hit
        db.insert_turn("m1", "alice", 1, 2, 32, 0, True, False, [("S1", 1, 31)])
        doubles = {d["target"]: d for d in db.player_doubles_by_number("alice")}
        assert doubles[16]["attempts"] == 2
        assert doubles[16]["hits"] == 1

    def test_top_legs_orders_by_fewest_darts_and_only_wins(self, db):
        _open(db, "m1")
        db.insert_turn("m1", "alice", 1, 1, 40, 40, False, True, [("D20", 40, 0)])
        db.record_leg_win("m1", 1, "alice")
        _open(db, "m2")
        db.insert_turn("m2", "alice", 1, 1, 501, 100, False, False,
                       [("20", 20, 481), ("20", 20, 461), ("20", 20, 441)])
        db.insert_turn("m2", "alice", 1, 2, 401, 32, False, True, [("D16", 32, 0)])
        db.record_leg_win("m2", 1, "alice")
        legs = db.top_legs("alice")
        assert legs[0]["darts"] == 1
        assert legs[0]["match_id"] == "m1"

    def test_top_legs_filters_by_points_start(self, db):
        _open(db, "m1", pts=301)
        db.insert_turn("m1", "alice", 1, 1, 40, 40, False, True, [("D20", 40, 0)])
        db.record_leg_win("m1", 1, "alice")
        _open(db, "m2", pts=701)
        db.insert_turn("m2", "alice", 1, 1, 40, 40, False, True, [("D20", 40, 0)])
        db.record_leg_win("m2", 1, "alice")

        legs_301 = db.top_legs("alice", points_start=301)
        assert [l["match_id"] for l in legs_301] == ["m1"]
        legs_701 = db.top_legs("alice", points_start=701)
        assert [l["match_id"] for l in legs_701] == ["m2"]
        legs_all = db.top_legs("alice")
        assert {l["match_id"] for l in legs_all} == {"m1", "m2"}

    def test_match_stats_for_elimination_match_lists_placements(self, db):
        _open(db, "e1", "Elimination", None)
        db.record_elimination_result("e1", [("bob", 1, 2), ("alice", 2, None), ("cara", 3, None)])
        db.insert_elimination_turn("e1", "alice", 3)
        db.insert_elimination_turn("e1", "alice", 2)
        db.insert_elimination_turn("e1", "bob", 3)
        stats = db.match_stats("e1")
        assert list(stats) == ["bob", "alice", "cara"]
        assert stats["bob"] == {"placement": 1, "lives_left": 2, "turns": 1, "avg_darts_per_turn": 3.0}
        assert stats["alice"]["placement"] == 2
        assert stats["alice"]["turns"] == 2
        assert stats["alice"]["avg_darts_per_turn"] == 2.5
        assert stats["cara"] == {"placement": 3, "lives_left": None, "turns": 0, "avg_darts_per_turn": None}

    def test_match_stats_for_unfinished_elimination_match_has_no_placement(self, db):
        _open(db, "e1", "Elimination", None)
        db.insert_elimination_turn("e1", "alice", 3)
        assert db.match_stats("e1") == {
            "alice": {"placement": None, "lives_left": None, "turns": 1, "avg_darts_per_turn": 3.0},
        }

    def test_match_stats_for_x01_match_is_unchanged(self, db):
        _open(db, "m1")
        db.insert_turn("m1", "alice", 1, 1, 501, 60, False, False,
                       [("20", 20, 481), ("20", 20, 461), ("20", 20, 441)])
        assert "avg3" in db.match_stats("m1")["alice"]

    def test_player_elimination_stats(self, db):
        _open(db, "e1", "Elimination", None)
        _open(db, "e2", "Elimination", None)
        _open(db, "e3", "Elimination", None)
        db.record_elimination_result("e1", [("alice", 1, 2), ("bob", 2, None), ("cara", 3, None)])
        db.record_elimination_result("e2", [("bob", 1, 1), ("alice", 2, None)])
        db.record_elimination_result("e3", [("bob", 1, 3), ("cara", 2, None), ("dan", 3, None), ("alice", 4, None)])
        db.insert_elimination_turn("e1", "alice", 3)
        db.insert_elimination_turn("e1", "alice", 2)
        stats = db.player_elimination_stats("alice")
        assert stats["games"] == 3
        assert stats["wins"] == 1
        assert stats["win_pct"] == 33.3
        assert stats["placements"] == {"first": 1, "second": 1, "third": 0, "other": 1}
        assert stats["avg_darts_per_turn"] == 2.5

    def test_player_elimination_stats_without_games(self, db):
        stats = db.player_elimination_stats("nobody")
        assert stats["games"] == 0
        assert stats["win_pct"] == 0.0
        assert stats["avg_darts_per_turn"] is None

    def test_x01_points_start_values_excludes_elimination(self, db):
        _open(db, "m1", pts=301)
        _open(db, "m2", pts=501)
        db.open_match("e1", "Elimination", 3)
        assert db.x01_points_start_values() == [301, 501]

    def test_top_checkouts_ordered_by_score_desc(self, db):
        _open(db, "m1")
        db.insert_turn("m1", "alice", 1, 1, 32, 32, False, True, [("D16", 32, 0)])
        db.insert_turn("m1", "alice", 1, 2, 100, 100, False, True,
                       [("T20", 60, 40), ("D20", 40, 0)])
        checkouts = db.top_checkouts("alice")
        assert checkouts[0]["score"] == 100
        assert checkouts[0]["targets"] == ["T20", "D20"]

    def test_player_dashboard_bundles_everything(self, db):
        _open(db, "m1")
        db.insert_turn("m1", "alice", 1, 1, 501, 60, False, False,
                       [("20", 20, 481), ("20", 20, 461), ("20", 20, 441)])
        dashboard = db.player_dashboard("alice")
        assert set(dashboard.keys()) == {
            "activity", "activity_by_date", "performance", "score_histogram", "avg_by_match",
            "dart_hits", "dart_positions", "bust_by_remaining", "checkout_by_match", "win_loss", "elimination_records",
            "doubles", "top_legs", "top_checkouts", "leg_modes", "selected_points_start",
        }

    def test_player_dashboard_defaults_to_501_when_available(self, db):
        _open(db, "m1", pts=301)
        _open(db, "m2", pts=501)
        dashboard = db.player_dashboard("alice")
        assert dashboard["leg_modes"] == [301, 501]
        assert dashboard["selected_points_start"] == 501

    def test_player_dashboard_falls_back_to_lowest_mode_when_501_absent(self, db):
        _open(db, "m1", pts=301)
        _open(db, "m2", pts=701)
        dashboard = db.player_dashboard("alice")
        assert dashboard["selected_points_start"] == 301

    def test_player_dashboard_respects_explicit_points_start(self, db):
        _open(db, "m1", pts=301)
        db.insert_turn("m1", "alice", 1, 1, 40, 40, False, True, [("D20", 40, 0)])
        db.record_leg_win("m1", 1, "alice")
        dashboard = db.player_dashboard("alice", points_start=301)
        assert dashboard["selected_points_start"] == 301
        assert len(dashboard["top_legs"]) == 1


class TestStatsByMode:
    """X01 and Elimination numbers can be separated for the Stats tab's chips."""

    def _both_modes(self, db):
        db.open_match("x1", "X01", 501)
        db.insert_turn("x1", "alice", 1, 1, 501, 60, False, False, [("S20", 20, 481), ("S20", 20, 461), ("S20", 20, 441)])
        db.insert_turn("x1", "bob", 1, 1, 501, 30, False, False, [("S10", 10, 491), ("S10", 10, 481), ("S10", 10, 471)])
        db.close_match("x1")
        db.open_match("e1", "Elimination", 3)
        db.insert_elimination_turn("e1", "alice", 3)
        db.insert_elimination_turn("e1", "alice", 2)
        db.insert_elimination_turn("e1", "bob", 3)
        db.record_elimination_result("e1", [("alice", 1, 2), ("bob", 2, None)])
        db.set_winner("e1", "alice")
        db.close_match("e1")

    def test_recent_matches_can_be_limited_to_one_mode(self, db):
        self._both_modes(db)
        assert {m["game_mode"] for m in db.recent_matches()} == {"X01", "Elimination"}
        assert [m["match_id"] for m in db.recent_matches(mode="x01")] == ["x1"]
        assert [m["match_id"] for m in db.recent_matches(mode="elimination")] == ["e1"]

    def test_the_limit_counts_per_mode(self, db):
        self._both_modes(db)
        db.open_match("x2", "X01", 301)
        db.insert_turn("x2", "alice", 1, 1, 301, 60, False, False, [("S20", 20, 281)])
        assert [m["match_id"] for m in db.recent_matches(limit=1, mode="elimination")] == ["e1"]

    def test_activity_is_split_by_mode_and_adds_up(self, db):
        self._both_modes(db)
        x01, elim, both = (db.player_activity("alice", m) for m in ("x01", "elimination", "all"))
        assert (x01["total_darts"], elim["total_darts"]) == (3, 5)
        assert both["total_darts"] == 8
        assert (x01["total_games"], elim["total_games"], both["total_games"]) == (1, 1, 2)

    def test_activity_by_date_is_split_by_mode(self, db):
        self._both_modes(db)
        darts = lambda mode: sum(r["darts"] for r in db.player_activity_by_date("alice", mode))
        assert (darts("x01"), darts("elimination"), darts("all")) == (3, 5, 8)

    def test_dashboard_mode_reaches_activity_and_win_loss(self, db):
        self._both_modes(db)
        elim = db.player_dashboard("alice", mode="elimination")
        assert elim["activity"]["total_darts"] == 5
        assert elim["win_loss"] == {"wins": 1, "losses": 0}
        assert db.player_dashboard("alice", mode="x01")["activity"]["total_darts"] == 3
        assert db.player_dashboard("alice")["activity"]["total_darts"] == 8

    def test_all_elimination_stats_lists_every_player_with_a_result(self, db):
        self._both_modes(db)
        rows = {r["player"]: r for r in db.all_elimination_stats()}
        assert set(rows) == {"alice", "bob"}
        assert rows["alice"]["wins"] == 1 and rows["alice"]["win_pct"] == 100.0
        assert rows["bob"]["placements"]["second"] == 1
        assert rows["alice"]["avg_darts_per_turn"] == 2.5

    def test_all_elimination_stats_skips_hidden_players(self, db):
        self._both_modes(db)
        db.upsert_player("bob", hidden=True)
        assert [r["player"] for r in db.all_elimination_stats()] == ["alice"]

    def test_all_elimination_stats_matches_the_per_player_numbers(self, db):
        self._both_modes(db)
        for r in db.all_elimination_stats():
            single = db.player_elimination_stats(r["player"])
            assert {k: r[k] for k in single} == single


class TestEliminationTurnDetails:
    def test_old_database_gets_the_new_columns_and_keeps_its_rows(self, tmp_path):
        import sqlite3
        path = str(tmp_path / "old.db")
        old = sqlite3.connect(path)
        old.executescript("""
            CREATE TABLE elimination_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT, match_id TEXT NOT NULL,
                player TEXT NOT NULL, darts_count INTEGER NOT NULL);
            INSERT INTO elimination_turns (match_id, player, darts_count) VALUES ('m', 'alice', 3);
        """)
        old.commit()
        old.close()
        db = StatsDB(path)
        cols = {r["name"] for r in db._conn.execute("PRAGMA table_info(elimination_turns)")}
        assert {"score", "target", "freipass", "passed", "lives_before"} <= cols
        row = db._conn.execute("SELECT * FROM elimination_turns").fetchone()
        assert (row["darts_count"], row["score"], row["passed"]) == (3, None, None)
        db.insert_elimination_turn("m", "bob", 2, score=7, target=5, freipass=False, passed=True, lives_before=3)
        assert db._conn.execute("SELECT COUNT(*) as n FROM elimination_turns").fetchone()["n"] == 2

    def test_insert_without_details_still_works(self, db):
        db.open_match("e1", "Elimination", 3)
        db.insert_elimination_turn("e1", "alice", 3)
        row = db._conn.execute("SELECT score, passed FROM elimination_turns").fetchone()
        assert (row["score"], row["passed"]) == (None, None)


class TestEliminationOverview:
    def _finished(self, db, match_id, results, minutes=None, started="2026-07-06T10:00:00+00:00"):
        from datetime import datetime, timedelta
        db.open_match(match_id, "Elimination", 3)
        db._conn.execute("UPDATE matches SET started_at = ? WHERE match_id = ?", (started, match_id))
        db.record_elimination_result(match_id, results)
        if minutes is not None:
            end = datetime.fromisoformat(started) + timedelta(minutes=minutes)
            db._conn.execute("UPDATE matches SET ended_at = ? WHERE match_id = ?", (end.isoformat(), match_id))
        db._conn.commit()

    def test_expected_wins_weigh_each_game_by_its_player_count(self, db):
        self._finished(db, "e1", [("alice", 1, 2), ("bob", 2, None)])                       # 2 players
        self._finished(db, "e2", [("alice", 1, 1), ("bob", 2, None), ("carol", 3, None)])   # 3 players
        rows = {r["player"]: r for r in db.all_elimination_stats()}
        assert rows["alice"]["expected_wins"] == 0.83    # 1/2 + 1/3
        assert rows["bob"]["expected_wins"] == 0.83
        assert rows["carol"]["expected_wins"] == 0.33
        assert rows["alice"]["wins"] == 2

    def test_summary_counts_finished_games_and_their_length(self, db):
        self._finished(db, "e1", [("alice", 1, 2), ("bob", 2, None)], minutes=4)
        self._finished(db, "e2", [("alice", 1, 2), ("bob", 2, None)], minutes=10, started="2026-07-07T10:00:00+00:00")
        db.open_match("e3", "Elimination", 3)          # abandoned: no result
        summary = db.elimination_summary()
        assert summary["games"] == 2
        assert summary["total_minutes"] == 14.0
        assert summary["avg_minutes"] == 7.0
        assert summary["longest_minutes"] == 10.0

    def test_summary_without_end_times_has_no_lengths(self, db):
        self._finished(db, "e1", [("alice", 1, 2), ("bob", 2, None)])
        summary = db.elimination_summary()
        assert (summary["games"], summary["avg_minutes"], summary["longest_minutes"]) == (1, None, None)

    def test_summary_ignores_x01_matches(self, db):
        db.open_match("x1", "X01", 501)
        db.insert_turn("x1", "alice", 1, 1, 501, 60, False, False, [("S20", 20, 481)])
        assert db.elimination_summary()["games"] == 0


class TestEliminationForm:
    def _game(self, db, match_id, results, started):
        db.open_match(match_id, "Elimination", 3)
        db._conn.execute("UPDATE matches SET started_at = ? WHERE match_id = ?", (started, match_id))
        db.record_elimination_result(match_id, results)
        db._conn.commit()

    def _history(self, db):
        # alice: 1st, 1st, 2nd, 1st   (bob and carol fill the other places)
        self._game(db, "e1", [("alice", 1, 2), ("bob", 2, None)], "2026-07-01T10:00:00+00:00")
        self._game(db, "e2", [("alice", 1, 1), ("bob", 2, None), ("carol", 3, None)], "2026-07-02T10:00:00+00:00")
        self._game(db, "e3", [("bob", 1, 1), ("alice", 2, None)], "2026-07-03T10:00:00+00:00")
        self._game(db, "e4", [("alice", 1, 3), ("carol", 2, None)], "2026-07-04T10:00:00+00:00")

    def test_games_are_oldest_first_with_placement_and_opponents(self, db):
        self._history(db)
        games = db.elimination_form()["alice"]["games"]
        assert [g["placement"] for g in games] == [1, 1, 2, 1]
        assert [g["date"] for g in games] == ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04"]
        assert games[1]["size"] == 3 and games[1]["opponents"] == ["bob", "carol"]
        assert games[3]["opponents"] == ["carol"]

    def test_streaks(self, db):
        self._history(db)
        form = db.elimination_form()
        assert (form["alice"]["current_streak"], form["alice"]["best_streak"]) == (1, 2)
        assert (form["bob"]["current_streak"], form["bob"]["best_streak"]) == (1, 1)   # last game won
        assert (form["carol"]["current_streak"], form["carol"]["best_streak"]) == (0, 0)  # never won

    def test_only_the_last_games_are_returned_but_streaks_cover_all(self, db):
        self._history(db)
        form = db.elimination_form(limit=2)["alice"]
        assert [g["placement"] for g in form["games"]] == [2, 1]
        assert form["best_streak"] == 2

    def test_hidden_players_are_left_out(self, db):
        self._history(db)
        db.upsert_player("carol", hidden=True)
        assert "carol" not in db.elimination_form()

    def test_unfinished_matches_do_not_count(self, db):
        db.open_match("e1", "Elimination", 3)
        db.insert_elimination_turn("e1", "alice", 3)
        assert db.elimination_form() == {}


class TestEliminationHeadToHead:
    def _game(self, db, match_id, results):
        db.open_match(match_id, "Elimination", 3)
        db.record_elimination_result(match_id, results)

    def test_two_player_games_count_for_the_winner(self, db):
        self._game(db, "e1", [("bob", 1, 2), ("alice", 2, None)])
        self._game(db, "e2", [("alice", 1, 1), ("bob", 2, None)])
        self._game(db, "e3", [("alice", 1, 3), ("bob", 2, None)])
        assert db.elimination_head_to_head() == [{"a": "alice", "b": "bob", "a_ahead": 2, "b_ahead": 1, "games": 3}]

    def test_a_three_player_game_counts_all_three_pairs(self, db):
        self._game(db, "e1", [("carol", 1, 2), ("alice", 2, None), ("bob", 3, None)])
        pairs = {(p["a"], p["b"]): (p["a_ahead"], p["b_ahead"]) for p in db.elimination_head_to_head()}
        assert pairs == {("alice", "bob"): (1, 0), ("alice", "carol"): (0, 1), ("bob", "carol"): (0, 1)}

    def test_most_shared_games_come_first(self, db):
        self._game(db, "e1", [("alice", 1, 2), ("bob", 2, None)])
        self._game(db, "e2", [("alice", 1, 2), ("carol", 2, None)])
        self._game(db, "e3", [("alice", 1, 2), ("carol", 2, None)])
        assert [(p["a"], p["b"]) for p in db.elimination_head_to_head()] == [("alice", "carol"), ("alice", "bob")]

    def test_hidden_players_and_unfinished_matches_are_left_out(self, db):
        self._game(db, "e1", [("alice", 1, 2), ("bob", 2, None)])
        db.upsert_player("bob", hidden=True)
        db.open_match("e2", "Elimination", 3)
        db.insert_elimination_turn("e2", "alice", 3)
        assert db.elimination_head_to_head() == []


class TestEliminationGameLengths:
    def _game(self, db, match_id, lives, results, minutes, started="2026-07-06T10:00:00+00:00"):
        from datetime import datetime, timedelta
        db.open_match(match_id, "Elimination", lives)
        end = datetime.fromisoformat(started) + timedelta(minutes=minutes)
        db._conn.execute("UPDATE matches SET started_at = ?, ended_at = ? WHERE match_id = ?",
                         (started, end.isoformat(), match_id))
        db.record_elimination_result(match_id, results)
        db.set_winner(match_id, results[0][0])

    def test_each_finished_game_with_lives_length_players_and_winner(self, db):
        self._game(db, "e1", 3, [("alice", 1, 2), ("bob", 2, None)], 4.5)
        self._game(db, "e2", 1, [("bob", 1, 1), ("alice", 2, None), ("carol", 3, None)], 2, started="2026-07-07T09:00:00+00:00")
        assert db.elimination_game_lengths() == [
            {"match_id": "e1", "date": "2026-07-06", "lives": 3, "minutes": 4.5, "size": 2, "winner": "alice"},
            {"match_id": "e2", "date": "2026-07-07", "lives": 1, "minutes": 2.0, "size": 3, "winner": "bob"},
        ]

    def test_games_without_a_result_or_end_time_and_x01_are_left_out(self, db):
        self._game(db, "e1", 3, [("alice", 1, 2), ("bob", 2, None)], 4)
        db.open_match("e2", "Elimination", 3)              # abandoned
        db.open_match("x1", "X01", 501)
        db.record_elimination_result("e3", [("alice", 1, 2), ("bob", 2, None)])   # result but never closed
        assert [g["match_id"] for g in db.elimination_game_lengths()] == ["e1"]


class TestEliminationRecords:
    def _turn(self, db, match_id, player, score, target, passed, started="2026-07-06T10:00:00+00:00"):
        if not db._conn.execute("SELECT 1 FROM matches WHERE match_id = ?", (match_id,)).fetchone():
            db.open_match(match_id, "Elimination", 3)
            db._conn.execute("UPDATE matches SET started_at = ? WHERE match_id = ?", (started, match_id))
            db._conn.commit()
        db.insert_elimination_turn(match_id, player, 3, score=score, target=target, freipass=False,
                                   passed=passed, lives_before=3)

    def test_highest_score_and_highest_score_that_lost_a_life(self, db):
        self._turn(db, "e1", "alice", 150, 100, True)
        self._turn(db, "e1", "bob", 118, 150, False)          # 118 against 150: lost a life
        self._turn(db, "e1", "alice", 90, 60, True)
        self._turn(db, "e2", "bob", 140, 160, False, started="2026-07-07T10:00:00+00:00")
        records = db.elimination_records()
        assert records["highest_score"] == {"score": 150, "target": 100, "player": "alice", "date": "2026-07-06"}
        assert records["highest_lost_score"] == {"score": 140, "target": 160, "player": "bob", "date": "2026-07-07"}

    def test_a_tie_goes_to_the_first_time_it_was_reached(self, db):
        self._turn(db, "e1", "alice", 100, 90, True)
        self._turn(db, "e2", "bob", 100, 90, True, started="2026-07-07T10:00:00+00:00")
        assert db.elimination_records()["highest_score"]["player"] == "alice"

    def test_turns_without_a_score_do_not_count(self, db):
        db.open_match("e1", "Elimination", 3)
        db.insert_elimination_turn("e1", "alice", 3)          # recorded before scores were stored
        assert db.elimination_records() == {"highest_score": None, "highest_lost_score": None}

    def test_hidden_players_are_left_out(self, db):
        self._turn(db, "e1", "alice", 150, 100, True)
        self._turn(db, "e1", "bob", 90, 100, False)
        db.upsert_player("alice", hidden=True)
        records = db.elimination_records()
        assert records["highest_score"]["player"] == "bob"

    def test_records_can_be_looked_up_for_one_player(self, db):
        self._turn(db, "e1", "alice", 150, 100, True)
        self._turn(db, "e1", "bob", 118, 150, False)
        self._turn(db, "e1", "bob", 90, 60, True)
        records = db.elimination_records("bob")
        assert records["highest_score"]["score"] == 118
        assert records["highest_lost_score"] == {"score": 118, "target": 150, "player": "bob", "date": "2026-07-06"}
        assert db.elimination_records("carol") == {"highest_score": None, "highest_lost_score": None}

    def test_a_players_records_come_with_the_dashboard_even_when_hidden(self, db):
        self._turn(db, "e1", "alice", 150, 100, True)
        db.upsert_player("alice", hidden=True)
        assert db.player_dashboard("alice", mode="elimination")["elimination_records"]["highest_score"]["score"] == 150


class TestX01Overview:
    def _leg(self, db, match_id, leg, player, darts, start_remaining=301):
        """One won leg in `darts` darts: three-dart turns ending in a checkout."""
        turns = (darts + 2) // 3
        for i in range(turns):
            last = i == turns - 1
            n = darts - 3 * i if last else 3
            db.insert_turn(match_id, player, leg, i + 1, start_remaining, 30 if not last else 40,
                           False, last, [("S10", 10, 0)] * n)
        db.record_leg_win(match_id, leg, player)

    def test_empty_database(self, db):
        overview = db.x01_overview()
        assert overview["summary"] == {"matches": 0, "legs": 0, "darts": 0, "playtime_hours": 0}
        assert overview["records"] == {"highest_turn": None, "highest_checkout": None,
                                       "best_leg": None, "best_average": None}

    def test_summary_counts_x01_only(self, db):
        _open(db, "m1", pts=301)
        self._leg(db, "m1", 1, "alice", 12)
        db.open_match("e1", "Elimination", 3)
        db.insert_elimination_turn("e1", "alice", 3)
        summary = db.x01_overview()["summary"]
        assert (summary["matches"], summary["legs"], summary["darts"]) == (1, 1, 12)

    def test_records(self, db):
        _open(db, "m1", pts=301)
        db._conn.execute("UPDATE matches SET started_at = '2026-07-06T10:00:00+00:00' WHERE match_id = 'm1'")
        self._leg(db, "m1", 1, "alice", 15)
        self._leg(db, "m1", 2, "bob", 12)
        db.insert_turn("m1", "alice", 3, 1, 301, 126, False, False, [("T20", 60, 241), ("T20", 60, 181), ("S6", 6, 175)])
        db.insert_turn("m1", "bob", 3, 1, 170, 170, False, True, [("T20", 60, 110), ("T20", 60, 50), ("BULL", 50, 0)])
        records = db.x01_overview()["records"]
        assert records["highest_turn"] == {"score": 170, "player": "bob", "date": "2026-07-06"}
        assert records["highest_checkout"]["score"] == 170
        assert records["highest_checkout"]["targets"] == ["T20", "T20", "BULL"]
        assert records["best_leg"] == {"darts": 12, "player": "bob", "date": "2026-07-06", "points_start": 301}

    def test_best_leg_uses_the_most_played_starting_score(self, db):
        _open(db, "m1", pts=301)
        _open(db, "m2", pts=501)
        self._leg(db, "m1", 1, "alice", 18)
        self._leg(db, "m1", 2, "alice", 15)
        self._leg(db, "m2", 1, "alice", 9, start_remaining=501)        # shorter, but a 501 leg
        best = db.x01_overview()["records"]["best_leg"]
        assert (best["darts"], best["points_start"]) == (15, 301)

    def test_best_average_needs_enough_darts(self, db):
        _open(db, "m1")
        db.insert_turn("m1", "alice", 1, 1, 501, 180, False, False, [("T20", 60, 441)] * 3)     # 3 darts only
        assert db.x01_overview()["records"]["best_average"] is None
        for turn in range(2, 7):
            db.insert_turn("m1", "alice", 1, turn, 501, 60, False, False, [("S20", 20, 481)] * 3)
        assert db.x01_overview()["records"]["best_average"]["player"] == "alice"

    def test_records_leave_out_hidden_players_but_totals_keep_them(self, db):
        _open(db, "m1", pts=301)
        self._leg(db, "m1", 1, "alice", 12)
        db.upsert_player("alice", hidden=True)
        overview = db.x01_overview()
        assert overview["records"]["highest_turn"] is None and overview["records"]["best_leg"] is None
        assert overview["summary"]["darts"] == 12


class TestScoreHistogram:
    def _turn(self, db, score, turn, darts=3, player="alice"):
        db.insert_turn("m1", player, 1, turn, 501, score, False, False, [("S1", 1, 500)] * darts)

    def test_bins_of_ten_with_180_in_the_last_one(self, db):
        _open(db, "m1")
        for i, score in enumerate([0, 9, 10, 45, 49, 100, 170, 179, 180], start=1):
            self._turn(db, score, i)
        histogram = db.player_score_histogram("alice")
        bins = histogram["bins"]
        assert len(bins) == 19
        assert (bins[0], bins[1], bins[4], bins[10], bins[17], bins[18]) == (2, 1, 2, 1, 2, 1)
        assert sum(bins) == histogram["turns"] == 9

    def test_average_is_per_three_darts_like_the_rest_of_the_stats(self, db):
        _open(db, "m1")
        self._turn(db, 60, 1)
        self._turn(db, 30, 2, darts=1)               # a checkout with one dart
        assert db.player_score_histogram("alice")["avg3"] == round(90 * 3.0 / 4, 1)

    def test_a_player_without_turns(self, db):
        assert db.player_score_histogram("nobody") == {"bins": [0] * 19, "turns": 0, "avg3": None}


class TestAverageByMatch:
    def test_one_average_per_match_oldest_first_per_three_darts(self, db):
        _open(db, "m2", pts=301)
        _open(db, "m1", pts=501)
        db._conn.execute("UPDATE matches SET started_at = '2026-07-01T10:00:00+00:00' WHERE match_id = 'm1'")
        db._conn.execute("UPDATE matches SET started_at = '2026-07-02T10:00:00+00:00' WHERE match_id = 'm2'")
        db.insert_turn("m1", "alice", 1, 1, 501, 60, False, False, [("S20", 20, 481)] * 3)
        db.insert_turn("m1", "alice", 1, 2, 441, 30, False, False, [("S10", 10, 431)] * 3)
        db.insert_turn("m2", "alice", 1, 1, 301, 100, False, False, [("S20", 20, 281)] * 3)
        db.insert_turn("m2", "bob", 1, 2, 301, 9, False, False, [("S3", 3, 298)] * 3)
        result = db.player_avg_by_match("alice")
        assert [(r["match_id"], r["avg3"], r["darts"], r["points_start"]) for r in result] == [
            ("m1", 45.0, 6, 501), ("m2", 100.0, 3, 301)]

    def test_player_without_turns(self, db):
        assert db.player_avg_by_match("nobody") == []


class TestDartHits:
    def _turn(self, db, turn, darts, player="alice"):
        db.insert_turn("m1", player, 1, turn, 501, 0, False, False, [(d, 0, 0) for d in darts])

    def test_hits_per_field_misses_per_sector_and_the_rest(self, db):
        _open(db, "m1")
        self._turn(db, 1, ["S20", "S20", "T20"])
        self._turn(db, 2, ["M1", "m1", "BULL"])
        self._turn(db, 3, ["25", "MISS", "D16"])
        hits = db.player_dart_hits("alice")
        assert hits["darts"] == 9
        assert hits["fields"] == {"S20": 2, "T20": 1, "BULL": 1, "25": 1, "D16": 1}
        assert hits["misses"] == {"1": 2}
        assert hits["no_sector_misses"] == 1

    def test_only_the_players_own_darts_count(self, db):
        _open(db, "m1")
        self._turn(db, 1, ["S20"], player="alice")
        self._turn(db, 2, ["S5", "S5"], player="bob")
        assert db.player_dart_hits("alice")["fields"] == {"S20": 1}

    def test_a_player_without_darts(self, db):
        assert db.player_dart_hits("nobody") == {"darts": 0, "fields": {}, "misses": {}, "no_sector_misses": 0}


class TestBustByRemaining:
    def _turn(self, db, turn, remaining, bust, player="alice"):
        db.insert_turn("m1", player, 1, turn, remaining, 0 if bust else 10, bust, False, [("S1", 1, remaining - 1)])

    def test_turns_and_busts_land_in_the_band_of_their_starting_score(self, db):
        _open(db, "m1")
        for i, (remaining, bust) in enumerate(
                [(2, True), (10, False), (11, True), (40, True), (41, False), (170, False), (171, False), (501, False)], start=1):
            self._turn(db, i, remaining, bust)
        result = db.player_bust_by_remaining("alice")
        by_label = {b["label"]: (b["turns"], b["busts"]) for b in result["bands"]}
        assert by_label == {"≤ 10": (2, 1), "11–20": (1, 1), "21–30": (0, 0), "31–40": (1, 1),
                            "41–60": (1, 0), "61–100": (0, 0), "101–170": (1, 0), "> 170": (2, 0)}
        assert (result["turns"], result["busts"]) == (8, 3)

    def test_only_the_players_own_turns(self, db):
        _open(db, "m1")
        self._turn(db, 1, 20, True, player="alice")
        self._turn(db, 2, 20, True, player="bob")
        assert db.player_bust_by_remaining("alice")["busts"] == 1

    def test_a_player_without_turns_has_all_bands_empty(self, db):
        result = db.player_bust_by_remaining("nobody")
        assert len(result["bands"]) == 8 and (result["turns"], result["busts"]) == (0, 0)


class TestCheckoutByMatch:
    def _turn(self, db, match_id, turn, remaining, checkout=False, player="alice"):
        db.insert_turn(match_id, player, 1, turn, remaining, remaining if checkout else 10, False, checkout,
                       [("S1", 1, 0)])

    def test_hits_over_the_darts_thrown_at_a_double_per_match(self, db):
        _open(db, "m2", pts=301)
        _open(db, "m1", pts=301)
        db._conn.execute("UPDATE matches SET started_at = '2026-07-01T10:00:00+00:00' WHERE match_id = 'm1'")
        db._conn.execute("UPDATE matches SET started_at = '2026-07-02T10:00:00+00:00' WHERE match_id = 'm2'")
        for i, (remaining, checkout) in enumerate([(301, False), (170, False), (40, False), (32, True)], start=1):
            self._turn(db, "m1", i, remaining, checkout)
        self._turn(db, "m2", 1, 40, True)
        result = db.player_checkout_by_match("alice")
        assert [(r["match_id"], r["attempts"], r["hits"], r["co_pct"]) for r in result] == [
            ("m1", 2, 1, 50.0), ("m2", 1, 1, 100.0)]

    def test_matches_without_a_turn_in_checkout_range_are_left_out(self, db):
        _open(db, "m1")
        self._turn(db, "m1", 1, 501)
        assert db.player_checkout_by_match("alice") == []

    def test_only_the_players_own_turns(self, db):
        _open(db, "m1")
        self._turn(db, "m1", 1, 40, player="alice")
        self._turn(db, "m1", 2, 40, player="bob")
        assert [r["attempts"] for r in db.player_checkout_by_match("alice")] == [1]


class TestCheckoutIsCountedPerDart:
    """A checkout dart is a dart thrown at a score a double can finish (even up to 40, or 50),
    the way Autodarts counts its checkout %. Ten turns of a real 501 leg ending on D7."""

    def _play(self, db):
        _open(db)
        turns = [
            (106, 106 - 41, [("S1", 1, 105), ("S20", 20, 85), ("S20", 20, 65)]),
            (65, 20, [("S13", 13, 52), ("S12", 12, 40), ("S20", 20, 20)]),
            (20, 6, [("M0", 0, 20), ("S6", 6, 14), ("M0", 0, 14)]),
            (14, 14, [("D7", 14, 0)]),
        ]
        for n, (before, score, darts) in enumerate(turns, start=1):
            db.insert_turn("m1", "anna", 1, n, before, score, False, n == 4, darts)

    def test_match_stats_count_one_of_five(self, db):
        self._play(db)
        s = db.match_stats("m1")["anna"]
        assert (s["co_hits"], s["co_attempts"], s["co_pct"]) == (1, 5, 20.0)

    def test_session_stats_count_one_of_five(self, db):
        self._play(db)
        s = db.session_stats("m1")["anna"]
        assert (s["co_hits"], s["co_attempts"]) == (1, 5)

    def test_player_and_leaderboard_stats_agree(self, db):
        self._play(db)
        p = db.player_stats("anna")
        assert (p["co_hits"], p["co_attempts"]) == (1, 5)
        a = db.all_players_stats()[0]
        assert (a["co_hits"], a["co_attempts"]) == (1, 5)

    def test_per_match_value_agrees(self, db):
        self._play(db)
        r = db.player_checkout_by_match("anna")[0]
        assert (r["hits"], r["attempts"], r["co_pct"]) == (1, 5, 20.0)

    def test_a_dart_at_an_odd_score_is_no_attempt(self, db):
        _open(db)
        db.insert_turn("m1", "anna", 1, 1, 39, 0, False, False, [("M0", 0, 39)])
        assert db.match_stats("m1")["anna"]["co_attempts"] == 0

    def test_a_dart_at_fifty_is_an_attempt(self, db):
        _open(db)
        db.insert_turn("m1", "anna", 1, 1, 50, 50, False, True, [("BULLSEYE", 50, 0)])
        s = db.match_stats("m1")["anna"]
        assert (s["co_hits"], s["co_attempts"]) == (1, 1)

    def test_the_finishing_dart_is_not_counted_twice(self, db):
        # a one-dart checkout stores 0 as the remaining after the dart; that must not be
        # read as a further dart thrown at a double
        _open(db)
        db.insert_turn("m1", "anna", 1, 1, 14, 14, False, True, [("D7", 14, 0)])
        assert db.match_stats("m1")["anna"]["co_attempts"] == 1
