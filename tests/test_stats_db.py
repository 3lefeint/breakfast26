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

    def test_double_attempt_counted(self, db):
        _open(db)
        # remaining_before=32 (≤ 40) → dart1 was thrown at a double
        db.insert_turn("m1", "alice", 1, 1, 32, 20, False, False, [("20", 20, 12)])
        rows = db.all_players_stats()
        alice = next(r for r in rows if r["player"] == "alice")
        assert alice["dbl_attempts"] == 1

    def test_double_hit_counted(self, db):
        _open(db)
        # checkout with remaining_before=32 (≤ 40) → dart1 was a double hit
        db.insert_turn("m1", "alice", 1, 1, 32, 32, False, True, [("D16", 32, 0)])
        rows = db.all_players_stats()
        alice = next(r for r in rows if r["player"] == "alice")
        assert alice["dbl_hits"] == 1
        assert alice["dbl_pct"] == 100.0

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

    def test_performance_summary_best_checkout(self, db):
        _open(db, "m1")
        db.insert_turn("m1", "alice", 1, 1, 32, 32, False, True, [("D16", 32, 0)])
        db.insert_turn("m1", "alice", 1, 2, 80, 80, False, True,
                       [("T20", 60, 20), ("D10", 20, 0)])
        perf = db.player_performance_summary("alice")
        assert perf["best_checkout"] == 80

    def test_scoring_buckets(self, db):
        _open(db, "m1")
        db.insert_turn("m1", "alice", 1, 1, 501, 45, False, False,
                       [("15", 15, 486), ("15", 15, 471), ("15", 15, 456)])
        db.insert_turn("m1", "alice", 1, 2, 456, 180, False, False,
                       [("T20", 60, 396), ("T20", 60, 336), ("T20", 60, 276)])
        buckets = db.player_scoring_buckets("alice")
        assert buckets["under_60"] == 1
        assert buckets["170_plus"] == 1

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

    def test_game_type_ratio(self, db):
        _open(db, "m1")
        db.insert_turn("m1", "alice", 1, 1, 501, 60, False, False,
                       [("20", 20, 481), ("20", 20, 461), ("20", 20, 441)])
        db.open_match("e1", "Elimination", 3)
        db.insert_elimination_turn("e1", "alice", 3)
        ratio = db.player_game_type_ratio("alice")
        assert ratio == {"x01": 1, "elimination": 1}

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

    def test_player_dashboard_includes_elimination(self, db):
        assert db.player_dashboard("nobody")["elimination"]["games"] == 0

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
            "activity", "activity_by_date", "performance", "scoring_buckets",
            "avg_by_date", "checkout_pct_by_date", "win_loss", "game_type_ratio", "elimination",
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
