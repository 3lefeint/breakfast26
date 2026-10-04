import json
import random

import pytest

from breakfast.killer import KillerController, KillerGame
from breakfast.stats import StatsDB
from tests.test_target_battle import BULL, MISS, FakeMqttClient, FakeMqttPub, hit, play

NUMBERS = {"ana": 20, "bo": 5, "cy": 12}


def new_game(players=("ana", "bo"), db=None, **kw):
    client = FakeMqttClient()
    kw.setdefault("numbers", {p: NUMBERS[p] for p in players})
    game = KillerGame(list(players), client, "autodarts", stats_db=db, **kw)
    game.announce_start()
    return game, client


def player(game, name):
    return next(p for p in game.snapshot()["players"] if p["name"] == name)


def lives(game):
    return {p["name"]: p["lives"] for p in game.snapshot()["players"]}


class TestSetup:
    @pytest.mark.parametrize("players, numbers", [
        ([], None), (["ana"], None), (["ana", "ana"], None),
        (["a%d" % i for i in range(21)], None),
        (["ana", "bo"], {"ana": 20, "bo": 20}),
        (["ana", "bo"], {"ana": 20, "bo": 21}),
        (["ana", "bo"], {"ana": 20}),
    ])
    def test_a_setup_that_cannot_be_played_is_refused(self, players, numbers):
        with pytest.raises(ValueError):
            KillerGame(players, FakeMqttClient(), "autodarts", numbers=numbers)

    def test_every_player_gets_a_different_number_from_1_to_20(self):
        players = [f"p{i}" for i in range(20)]
        game = KillerGame(players, FakeMqttClient(), "autodarts", rng=random.Random(1))
        assert sorted(game.numbers.values()) == list(range(1, 21))

    def test_everybody_starts_with_three_lives_and_nobody_is_a_killer(self):
        game, _ = new_game(("ana", "bo", "cy"))
        snap = game.snapshot()
        assert all(p["lives"] == 3 and not p["killer"] and not p["out"] for p in snap["players"])
        assert snap["current_player"] == "ana" and snap["state"] == "playing"
        assert snap["rules"] == {"own_goal": False, "singles": False}


class TestBecomingAKiller:
    def test_a_double_on_the_own_number(self):
        game, client = new_game()
        play(game, hit(20, 2))
        assert player(game, "ana")["killer"]
        assert [e["player"] for e in client.events("killer")] == ["ana"]

    @pytest.mark.parametrize("dart", [hit(20, 1), hit(20, 3), hit(5, 2), MISS, BULL])
    def test_nothing_else_makes_a_killer(self, dart):
        game, _ = new_game()
        play(game, dart)
        assert not player(game, "ana")["killer"]

    def test_the_status_takes_effect_at_once_for_the_next_dart_of_the_turn(self):
        game, _ = new_game()
        play(game, hit(20, 2), hit(5, 2))
        assert lives(game)["bo"] == 2

    def test_singles_never_make_a_killer_even_when_they_take_lives(self):
        game, _ = new_game(singles=True)
        play(game, hit(20, 1))
        assert not player(game, "ana")["killer"]

    def test_a_dart_before_the_double_does_not_attack(self):
        game, _ = new_game()
        play(game, hit(5, 2), hit(20, 2))
        assert lives(game)["bo"] == 3


class TestAttacking:
    def killer_turn(self, game):
        play(game, hit(20, 2))                 # ana is a killer
        play(game, MISS)                       # bo throws

    def test_a_double_on_an_opponents_number_takes_a_life(self):
        game, client = new_game()
        self.killer_turn(game)
        play(game, hit(5, 2))
        assert lives(game)["bo"] == 2
        assert client.events("hit")[0]["victim"] == "bo"

    def test_the_opponent_does_not_have_to_be_a_killer(self):
        game, _ = new_game()
        self.killer_turn(game)
        play(game, hit(5, 2))
        assert not player(game, "bo")["killer"] and lives(game)["bo"] == 2

    @pytest.mark.parametrize("dart", [hit(5, 1), hit(5, 3), MISS, hit(7, 2)])
    def test_only_a_double_counts_by_default(self, dart):
        game, _ = new_game()
        self.killer_turn(game)
        play(game, dart)
        assert lives(game)["bo"] == 3

    def test_with_singles_on_a_single_takes_a_life_but_a_triple_never(self):
        game, _ = new_game(singles=True)
        self.killer_turn(game)
        play(game, hit(5, 1), hit(5, 3))
        assert lives(game)["bo"] == 2

    def test_each_dart_takes_exactly_one_life_a_double_does_not_count_twice(self):
        game, _ = new_game(singles=True)
        self.killer_turn(game)
        play(game, hit(5, 2))
        assert lives(game)["bo"] == 2

    def test_a_non_killer_takes_nothing(self):
        game, _ = new_game()
        play(game, hit(5, 2))
        assert lives(game)["bo"] == 3

    def test_a_number_nobody_has_does_nothing(self):
        game, _ = new_game()
        self.killer_turn(game)
        play(game, hit(7, 2))
        assert lives(game) == {"ana": 3, "bo": 3}

    def test_three_darts_can_take_three_lives_and_the_last_one_ends_it(self):
        game, client = new_game()
        play(game, hit(20, 2))
        play(game, MISS)
        play(game, hit(5, 2), hit(5, 2), hit(5, 2))
        snap = game.snapshot()
        assert snap["state"] == "finished" and snap["winner"] == "ana"
        assert [e["victim"] for e in client.events("out")] == ["bo"]


class TestElimination:
    def setup_three(self, **kw):
        game, client = new_game(("ana", "bo", "cy"), **kw)
        play(game, hit(20, 2))        # ana is a killer
        play(game, MISS)              # bo
        play(game, MISS)              # cy
        return game, client

    def test_a_player_without_lives_is_out_and_skipped(self):
        game, _ = self.setup_three()
        play(game, hit(5, 2), hit(5, 2), hit(5, 2))        # ana: bo is out
        assert player(game, "bo")["out"] and player(game, "bo")["lives"] == 0
        assert game.snapshot()["current_player"] == "cy"
        play(game, MISS)                                    # cy
        assert game.snapshot()["current_player"] == "ana"   # bo is skipped

    def test_an_out_players_number_is_dead(self):
        game, _ = self.setup_three()
        play(game, hit(5, 2), hit(5, 2), hit(5, 2))
        play(game, MISS)
        play(game, hit(5, 2))
        assert game.snapshot()["state"] == "playing" and lives(game)["cy"] == 3

    def test_the_last_player_wins_and_the_rest_of_the_turn_does_not_count(self):
        game, client = self.setup_three()
        play(game, hit(5, 2), hit(5, 2), hit(5, 2))        # bo out
        play(game, MISS)                                    # cy
        play(game, hit(12, 2), hit(12, 2), hit(12, 2))      # ana takes cy's three lives
        assert game.snapshot()["winner"] == "ana"
        assert [e["type"] for e in client.events("game_won")] == ["game_won"]

    def test_the_game_ends_with_the_dart_that_decides_it(self):
        game, _ = new_game()
        play(game, hit(20, 2))
        play(game, MISS)
        game.on_board_state(1, [hit(5, 2)])
        game.on_board_state(2, [hit(5, 2), hit(5, 2)])
        game.on_board_state(3, [hit(5, 2), hit(5, 2), hit(5, 2)])
        assert game.snapshot()["state"] == "finished"          # before the darts are pulled

    def test_placements_follow_the_order_they_went_out(self):
        game, _ = self.setup_three()
        play(game, hit(5, 2), hit(5, 2), hit(5, 2))        # bo is out first
        play(game, MISS)
        play(game, hit(12, 2), hit(12, 2), hit(12, 2))     # cy second
        got = {p["name"]: p["placement"] for p in game.snapshot()["players"]}
        assert got == {"ana": 1, "cy": 2, "bo": 3}

    def test_darts_after_the_game_is_over_are_ignored(self):
        game, _ = new_game()
        play(game, hit(20, 2))
        play(game, MISS)
        play(game, hit(5, 2), hit(5, 2), hit(5, 2))
        play(game, hit(20, 2))
        assert game.snapshot()["state"] == "finished"


class TestOwnGoal:
    def test_a_hit_on_the_own_number_costs_an_active_killer_a_life(self):
        game, client = new_game(own_goal=True)
        play(game, hit(20, 2), hit(20, 2))
        assert lives(game)["ana"] == 2
        assert client.events("own_goal")

    def test_the_activating_dart_is_no_own_goal(self):
        game, _ = new_game(own_goal=True)
        play(game, hit(20, 2))
        assert lives(game)["ana"] == 3

    def test_off_by_default(self):
        game, _ = new_game()
        play(game, hit(20, 2), hit(20, 2), hit(20, 2))
        assert lives(game)["ana"] == 3

    def test_the_same_hit_conditions_apply(self):
        game, _ = new_game(own_goal=True)
        play(game, hit(20, 2), hit(20, 1), hit(20, 3))
        assert lives(game)["ana"] == 3
        game, _ = new_game(own_goal=True, singles=True)
        play(game, hit(20, 2), hit(20, 1), hit(20, 3))
        assert lives(game)["ana"] == 2

    def test_a_player_who_throws_themself_out_loses_and_the_last_other_player_wins(self):
        game, _ = new_game(own_goal=True)
        play(game, hit(20, 2), hit(20, 2), hit(20, 2))        # killer, then two own goals
        play(game, MISS)
        play(game, hit(20, 2), hit(20, 2))                    # a third own goal ends ana
        snap = game.snapshot()
        assert snap["state"] == "finished" and snap["winner"] == "bo"

    def test_throwing_oneself_out_ignores_the_rest_of_the_turn(self):
        game, _ = new_game(("ana", "bo", "cy"), own_goal=True)
        play(game, hit(20, 2), hit(20, 2), hit(20, 2))
        play(game, MISS)
        play(game, MISS)
        play(game, hit(20, 2), hit(5, 2))        # own goal: out, bo's number never counted
        assert player(game, "ana")["lives"] == 0 and lives(game)["bo"] == 3


class TestCorrections:
    def test_a_tapped_dart_changes_what_the_turn_did(self):
        game, _ = new_game()
        play(game, hit(20, 2))
        play(game, MISS)
        game.on_board_state(1, [hit(5, 1)])
        assert lives(game)["bo"] == 3
        game.correct_current_dart(0, "D5")
        assert lives(game)["bo"] == 2

    def test_a_tapped_dart_that_makes_a_killer_lets_the_next_darts_attack(self):
        game, _ = new_game()
        game.on_board_state(1, [hit(3, 1)])
        game.on_board_state(2, [hit(3, 1), hit(5, 2)])
        assert lives(game)["bo"] == 3
        game.correct_current_dart(0, "D20")
        assert player(game, "ana")["killer"] and lives(game)["bo"] == 2

    def test_a_correction_does_not_announce_the_same_event_twice(self):
        game, client = new_game()
        game.on_board_state(1, [hit(20, 2)])
        game.correct_current_dart(0, "D20")
        assert len(client.events("killer")) == 1

    def test_the_last_turn_can_be_corrected_after_it_ended_the_game(self):
        game, _ = new_game()
        play(game, hit(20, 2))
        play(game, MISS)
        play(game, hit(5, 2), hit(5, 2), hit(5, 2))
        assert game.snapshot()["state"] == "finished"
        assert game.correct_last_dart(2, "S5")          # the third dart was only a single
        snap = game.snapshot()
        assert snap["state"] == "playing" and lives(game)["bo"] == 1

    def test_the_last_turn_can_be_corrected_into_a_win(self):
        game, _ = new_game()
        play(game, hit(20, 2))
        play(game, MISS)
        play(game, hit(5, 2), hit(5, 2), hit(5, 1))
        assert game.correct_last_dart(2, "D5")
        assert game.snapshot()["winner"] == "ana"

    def test_nothing_to_correct_at_the_start(self):
        game, _ = new_game()
        assert game.correct_last_dart(0, "D5") is False


class TestUndo:
    def test_undo_walks_back_a_turn(self):
        game, _ = new_game()
        play(game, hit(20, 2))
        play(game, MISS)
        play(game, hit(5, 2))
        assert game.undo()
        assert lives(game)["bo"] == 3 and game.snapshot()["current_player"] == "ana"

    def test_undo_reopens_a_finished_game(self):
        game, _ = new_game()
        play(game, hit(20, 2))
        play(game, MISS)
        play(game, hit(5, 2), hit(5, 2), hit(5, 2))
        assert game.snapshot()["state"] == "finished"
        assert game.undo()
        assert game.snapshot()["state"] == "playing" and lives(game)["bo"] == 3

    def test_undo_with_nothing_to_undo(self):
        game, _ = new_game()
        assert game.undo() is False

    def test_undo_takes_back_the_killer_status(self):
        game, _ = new_game()
        play(game, hit(20, 2))
        assert game.undo()
        assert not player(game, "ana")["killer"]


class TestStats:
    @pytest.fixture
    def db(self):
        return StatsDB(":memory:")

    def test_a_game_is_stored_with_its_turns_events_and_result(self, db):
        game, _ = new_game(db=db, own_goal=True)
        play(game, hit(20, 2))
        play(game, MISS)
        play(game, hit(5, 2), hit(5, 2), hit(5, 2))
        mid = game.match_id
        assert db.match_row(mid)["game_mode"] == "Killer" and db.match_row(mid)["winner"] == "ana"
        assert db.match_row(mid)["ended_at"] is not None
        assert [r["player"] for r in db._conn.execute("SELECT player FROM killer_turns ORDER BY id")] == ["ana", "bo", "ana"]
        kinds = [r["kind"] for r in db._conn.execute("SELECT kind FROM killer_events ORDER BY id")]
        assert kinds == ["killer", "hit", "hit", "hit", "out"]
        results = db._conn.execute("SELECT player, placement, lives_left, number FROM killer_results ORDER BY placement").fetchall()
        assert [tuple(r) for r in results] == [("ana", 1, 3, 20), ("bo", 2, None, 5)]
        assert db._conn.execute("SELECT own_goal, singles FROM killer_games").fetchone()["own_goal"] == 1

    def test_the_dart_positions_are_stored(self, db):
        game, _ = new_game(db=db)
        play(game, hit(20, 2), MISS, hit(5, 1))
        assert db._conn.execute(
            "SELECT COUNT(*) FROM dart_positions WHERE game_mode = 'Killer'").fetchone()[0] == 3

    def test_undo_removes_the_stored_turn_and_reopens_the_match(self, db):
        game, _ = new_game(db=db)
        play(game, hit(20, 2))
        play(game, MISS)
        play(game, hit(5, 2), hit(5, 2), hit(5, 2))
        game.undo()
        assert db._conn.execute("SELECT COUNT(*) FROM killer_turns").fetchone()[0] == 2
        assert db._conn.execute("SELECT COUNT(*) FROM killer_results").fetchone()[0] == 0
        assert db.match_row(game.match_id)["ended_at"] is None and db.match_row(game.match_id)["winner"] is None

    def test_a_corrected_last_turn_replaces_the_stored_one(self, db):
        game, _ = new_game(db=db)
        play(game, hit(20, 2))
        play(game, MISS)
        play(game, hit(5, 2), hit(5, 2), hit(5, 1))
        game.correct_last_dart(2, "D5")
        assert db.match_row(game.match_id)["winner"] == "ana"
        assert db._conn.execute("SELECT COUNT(*) FROM killer_turns").fetchone()[0] == 3
        assert db._conn.execute("SELECT COUNT(*) FROM killer_events WHERE kind = 'hit'").fetchone()[0] == 3

    def test_a_killer_game_is_not_counted_as_x01(self, db):
        game, _ = new_game(db=db)
        play(game, hit(20, 2))
        play(game, MISS)
        play(game, hit(5, 2), hit(5, 2), hit(5, 2))
        assert db.x01_win_counts() == {}
        assert db.match_participants(game.match_id) == ["ana", "bo"]


class TestMqtt:
    def test_the_state_is_published(self):
        game, client = new_game(("ana", "bo", "cy"))
        state = json.loads(client.last("autodarts/killer/state"))
        assert state["players"]["ana"] == {"number": 20, "lives": 3, "killer": False}
        assert client.last("autodarts/killer/active") == "true"

    def test_the_controller_starts_a_game_from_a_command(self):
        pub = FakeMqttPub()
        ctrl = KillerController(pub, "autodarts")
        pub.subscribed["autodarts/killer/command"](json.dumps(
            {"action": "start", "players": ["ana", "bo"], "own_goal": True, "singles": True}))
        assert ctrl.active and ctrl.game.own_goal and ctrl.game.singles
        pub.subscribed["autodarts/killer/command"](json.dumps({"action": "stop"}))
        assert not ctrl.active and ctrl.game is None

    def test_a_start_with_one_player_is_refused(self):
        pub = FakeMqttPub()
        ctrl = KillerController(pub, "autodarts")
        pub.subscribed["autodarts/killer/command"](json.dumps({"action": "start", "players": ["ana"]}))
        assert not ctrl.active

    def test_the_controller_hands_the_board_to_the_game(self):
        pub = FakeMqttPub()
        ctrl = KillerController(pub, "autodarts")
        ctrl.start(["ana", "bo"])
        number = ctrl.game.numbers["ana"]
        ctrl.on_board_state(1, [hit(number, 2)])
        assert ctrl.game.snapshot()["players"][0]["killer"]


class TestAchievementsDoNotMix:
    def test_a_killer_win_counts_as_a_game_but_not_as_an_x01_or_elimination_win(self):
        from breakfast.achievements import AchievementEngine
        db = StatsDB(":memory:")
        AchievementEngine(db).attach()
        game, _ = new_game(db=db)
        play(game, hit(20, 2))
        play(game, MISS)
        play(game, hit(5, 2), hit(5, 2), hit(5, 2))
        earned = {r["achievement_id"] for r in db.earned_for_player("ana")}
        assert "first_breakfast" in earned
        assert not earned & {"first_bite", "last_at_the_table", "target_acquired"}


class TestColors:
    def test_a_player_gets_the_color_picked_in_the_profile_and_the_others_a_different_one(self):
        db = StatsDB(":memory:")
        db.upsert_player("ana")
        db.set_player_color("ana", "#ff0000")
        ctrl = KillerController(FakeMqttPub(), "autodarts", stats_db=db)
        ctrl.start(["ana", "bo", "cy"])
        players = ctrl.game.snapshot()["players"]
        assert players[0]["color"] == "#ff0000"
        assert len({p["color"] for p in players}) == 3

    def test_a_game_without_colors_has_none(self):
        game, _ = new_game()
        assert [p["color"] for p in game.snapshot()["players"]] == [None, None]
