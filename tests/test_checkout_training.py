import random

import pytest

from breakfast import checkout_routes as routes
from breakfast.checkout_training import CheckoutTrainingController, CheckoutTrainingGame, outcome
from breakfast.stats import StatsDB
from breakfast.turn_game import parse_field
from tests.test_target_battle import FakeMqttPub


def th(field):
    t = parse_field(field)
    t["segment"]["name"] = field
    return t


def game(score=40, attempts=3, db=None, **kw):
    g = CheckoutTrainingGame("ana", FakeMqttPub().client, "autodarts", attempts=attempts, stats_db=db,
                             rng=random.Random(4), **kw)
    g.score = score
    return g


def attempt(g, *fields, pull=True):
    for i in range(1, len(fields) + 1):
        g.on_board_state(i, [th(f) for f in fields[:i]])
    if pull:
        g.on_board_state(0, [])


class TestOutcome:
    def test_a_finish_on_a_double_ends_the_attempt_at_that_dart(self):
        assert outcome(40, ["D20"]) == (1, "finished")
        assert outcome(100, ["T20", "D20", "S1"]) == (2, "finished")      # a dart after the finish is ignored
        assert outcome(50, ["50"]) == (1, "finished")

    def test_a_bust_ends_it_too(self):
        assert outcome(40, ["S20", "S20"]) == (2, "bust")                 # zero without a double
        assert outcome(40, ["T20"]) == (1, "bust")                        # below zero
        assert outcome(41, ["S20", "S20"]) == (2, "bust")                 # leaves one

    def test_without_a_finish_or_bust_it_is_open_after_three_darts(self):
        assert outcome(170, ["T20", "T20", "S1"]) == (3, "open")
        assert outcome(40, ["0", "0", "0"]) == (3, "open")
        assert outcome(40, []) == (0, "open")


class TestSetup:
    def test_it_needs_a_player_a_playable_range_and_attempts(self):
        for kw in ({"player": ""}, {"low": 1}, {"high": 171}, {"low": 60, "high": 50}, {"attempts": 0},
                   {"attempts": 101}, {"low": 169, "high": 169}):
            args = {"player": "ana", "low": 2, "high": 170, "attempts": 5, **kw}
            with pytest.raises(ValueError):
                CheckoutTrainingGame(args.pop("player"), FakeMqttPub().client, "autodarts", **args)

    def test_the_first_score_is_a_finishable_one_inside_the_range(self):
        for seed in range(30):
            g = CheckoutTrainingGame("ana", FakeMqttPub().client, "autodarts", low=101, high=110,
                                     attempts=3, rng=random.Random(seed))
            assert 101 <= g.score <= 110 and routes.finishable(g.score)


class TestAttempts:
    def test_a_finish_counts_and_the_next_score_comes_whatever_happened(self):
        g = game(40)
        attempt(g, "D20")
        assert [r["success"] for r in g.results] == [True] and g.results[0]["darts"] == 1
        assert g.state == "playing" and g.attempt == 2 and routes.finishable(g.score)
        g.score = 81
        attempt(g, "T19", "S20", "S1")
        assert [r["success"] for r in g.results] == [True, False] and g.results[1]["darts"] == 3

    def test_an_attempt_ends_when_the_darts_are_pulled_not_before(self):
        g = game(40)
        attempt(g, "D20", pull=False)
        assert g.results == [] and g.snapshot()["live"] == {"darts": 1, "state": "finished", "rest": 0}
        g.on_board_state(0, [])
        assert len(g.results) == 1

    def test_pulling_early_without_a_finish_is_a_miss(self):
        g = game(80)
        attempt(g, "T20", "S1")
        assert g.results[0]["success"] is False and g.results[0]["darts"] == 2

    def test_a_dart_after_the_finish_does_not_count_as_a_dart_of_the_attempt(self):
        g = game(100)
        attempt(g, "T20", "D20", "S5")
        assert g.results[0]["darts"] == 2 and g.results[0]["fields"] == ["T20", "D20"]

    def test_pulling_without_a_dart_is_no_attempt(self):
        g = game(40)
        g.on_board_state(0, [])
        assert g.results == []

    def test_the_last_attempt_ends_the_run_with_a_summary(self):
        g = game(40, attempts=2)
        attempt(g, "D20")
        g.score = 170
        attempt(g, "T20", "T20", "S5")
        assert g.state == "finished" and g.completed
        assert g.result["attempts"] == 2 and g.result["successes"] == 1 and g.result["rate"] == 0.5
        assert g.result["missed"] == [{"score": 170, "route": ["T20", "T20", "50"]}]
        assert g.snapshot()["current_player"] is None

    def test_finishing_early_keeps_what_was_finished(self):
        g = game(40, attempts=5)
        assert g.finish_early() is False
        attempt(g, "D20")
        assert g.finish_early() is True
        assert g.state == "finished" and g.completed is False and g.result["attempts"] == 1


class TestScreens:
    def test_the_snapshot_shows_the_live_attempt_and_the_route_if_asked_for(self):
        g = game(81, show_route=True)
        snap = g.snapshot()
        assert snap["score"] == 81 and snap["route"] == ["T19", "D12"] and snap["live"] is None
        g.on_board_state(1, [th("T19")])
        snap = g.snapshot()
        assert snap["live"] == {"darts": 1, "state": "open", "rest": 24}
        assert snap["rest_route"] == ["D12"]

    def test_without_the_setting_no_route_is_shown(self):
        snap = game(81).snapshot()
        assert snap["route"] is None and snap["rest_route"] is None

    def test_a_bust_is_shown_as_one(self):
        g = game(40)
        g.on_board_state(1, [th("T20")])
        assert g.snapshot()["live"] == {"darts": 1, "state": "bust", "rest": 40}

    def test_the_result_of_the_last_attempt_is_in_the_snapshot(self):
        g = game(40)
        attempt(g, "S20", "S20")
        last = g.snapshot()["last"]
        assert last["score"] == 40 and last["success"] is False and last["route"] == ["D20"]


class TestCorrections:
    def test_a_corrected_dart_decides_the_attempt(self):
        g = game(40)
        g.on_board_state(1, [th("S20")])                 # misread: it was the double
        g.correct_current_dart(0, "D20")
        g.on_board_state(0, [])
        assert g.results[0]["success"] is True

    def test_undo_takes_the_attempt_back_and_the_score_with_it(self):
        db = StatsDB(":memory:")
        g = game(40, attempts=3, db=db)
        attempt(g, "D20")
        drawn = g.score
        assert g.undo() is True
        assert g.results == [] and g.score == 40 and drawn != 40 or g.score == 40
        assert db._conn.execute("SELECT COUNT(*) FROM checkout_training_turns").fetchone()[0] == 0

    def test_undoing_the_last_attempt_reopens_a_finished_run(self):
        db = StatsDB(":memory:")
        g = game(40, attempts=1, db=db)
        attempt(g, "D20")
        assert g.state == "finished"
        assert g.undo() is True
        assert g.state == "playing" and g.result is None
        row = db._conn.execute("SELECT ended_at FROM matches WHERE match_id = ?", (g.match_id,)).fetchone()
        assert row["ended_at"] is None


class TestStats:
    def _play(self, db, player="ana"):
        g = CheckoutTrainingGame(player, FakeMqttPub().client, "autodarts", low=2, high=170, attempts=3,
                                 stats_db=db, rng=random.Random(1))
        for score, fields in ((40, ["D20"]), (81, ["T19", "S20", "S1"]), (170, ["T20", "T20", "50"])):
            g.score = score
            attempt(g, *fields)
        return g

    def test_a_run_is_stored_with_its_attempts_and_the_match_is_closed(self):
        db = StatsDB(":memory:")
        g = self._play(db)
        rows = db._conn.execute("SELECT attempt_no, score, success, darts_count, finish_field"
                                " FROM checkout_training_turns ORDER BY attempt_no").fetchall()
        assert [(r["attempt_no"], r["score"], r["success"], r["darts_count"], r["finish_field"]) for r in rows] == [
            (1, 40, 1, 1, "D20"), (2, 81, 0, 3, None), (3, 170, 1, 3, "50")]
        match = db._conn.execute("SELECT game_mode, ended_at FROM matches WHERE match_id = ?", (g.match_id,)).fetchone()
        assert match["game_mode"] == "Checkout Training" and match["ended_at"] is not None
        game_row = db._conn.execute("SELECT low, high, attempts, completed FROM checkout_training_games").fetchone()
        assert tuple(game_row) == (2, 170, 3, 1)

    def test_the_overview_gives_rates_by_range_by_score_and_the_weakest_scores(self):
        db = StatsDB(":memory:")
        self._play(db)
        self._play(db)
        o = db.checkout_training_overview()["players"][0]
        assert o["player"] == "ana" and o["attempts"] == 6 and o["successes"] == 4 and o["rate"] == 0.667
        ranges = {(r["low"], r["high"]): (r["attempts"], r["successes"]) for r in o["by_range"]}
        assert ranges == {(2, 40): (2, 2), (41, 100): (2, 0), (101, 170): (2, 2)}
        assert [(r["score"], r["attempts"], r["successes"]) for r in o["by_score"]] == [(40, 2, 2), (81, 2, 0), (170, 2, 2)]
        assert [r["score"] for r in o["weakest"]] == [81]
        assert o["weakest"][0]["route"] == ["T19", "D12"]
        assert len(o["runs"]) == 2

    def test_a_hidden_player_has_no_statistics_and_other_modes_are_untouched(self):
        db = StatsDB(":memory:")
        self._play(db, "ghost")
        db.upsert_player("ghost", hidden=True)
        assert db.checkout_training_overview() == {"players": []}
        assert [m["game_mode"] for m in db.recent_matches(mode="checkout_training")] == ["Checkout Training"]
        assert db.recent_matches(mode="checkout_training")[0]["range"] == [2, 170]
        assert db.recent_matches(mode="x01") == []

    def test_the_match_stats_and_the_player_delete(self):
        db = StatsDB(":memory:")
        g = self._play(db)
        stats = db.match_stats(g.match_id)
        assert stats["attempts"] == 3 and stats["successes"] == 2 and stats["low"] == 2 and stats["high"] == 170
        db.delete_player("ana")
        assert db._conn.execute("SELECT COUNT(*) FROM checkout_training_turns").fetchone()[0] == 0
        assert db._conn.execute("SELECT COUNT(*) FROM checkout_training_games").fetchone()[0] == 0

    def test_the_run_gives_no_achievements(self):
        from breakfast.achievements import AchievementEngine
        db = StatsDB(":memory:")
        db.set_achievements_start("2000-01-01T00:00:00")
        earned = []
        AchievementEngine(db, on_earned=lambda c: earned.append(c)).attach()
        self._play(db)
        assert earned == [] and db.earned_for_player("ana") == []


class TestController:
    def test_start_begins_a_run_and_a_start_command_works(self):
        ctrl = CheckoutTrainingController(FakeMqttPub(), "autodarts")
        ctrl.start("ana", low=41, high=100, attempts=4, show_route=True)
        assert ctrl.active and ctrl.game.low == 41 and ctrl.game.show_route is True
        ctrl.stop()
        ctrl._command_start({"player": "bo", "range": "high", "attempts": 2})
        assert ctrl.game.player == "bo" and (ctrl.game.low, ctrl.game.high) == (101, 170)
        with pytest.raises(ValueError):
            ctrl.start("", 2, 170, 5)
