import json
import random

import pytest

from breakfast.stats import StatsDB
from breakfast.target_battle import TargetBattleController, TargetBattleGame


class FakeMqttClient:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload, retain=False):
        self.published.append((topic, payload, retain))

    def last(self, topic):
        return next(p for t, p, _ in reversed(self.published) if t == topic)

    def events(self, name):
        return [json.loads(p) for t, p, _ in self.published if t.endswith(f"/events/{name}")]


class FakeMqttPub:
    def __init__(self):
        self.client = FakeMqttClient()
        self.subscribed = {}

    def subscribe(self, topic, callback):
        self.subscribed[topic] = callback


def hit(number, multiplier, x=0.31, y=0.17):
    """A dart as the board reports it: a field and a position that is not the field's center."""
    name = {1: "S", 2: "D", 3: "T"}.get(multiplier, "S") + str(number)
    return {"segment": {"name": name, "number": number, "multiplier": multiplier}, "coords": {"x": x, "y": y}}


MISS = {"segment": {"name": "M3", "number": 3, "multiplier": 0}, "coords": {"x": 1.4, "y": 0.2}}
BULL = {"segment": {"name": "50", "number": 25, "multiplier": 2}, "coords": {"x": 0.02, "y": 0.01}}


def play(game, *throws):
    """One turn: the darts land one after the other, then they are pulled."""
    for i in range(len(throws)):
        game.on_board_state(i + 1, list(throws[:i + 1]))
    game.on_board_state(0, [])


def new_game(players=("ana", "bo"), db=None, **kw):
    client = FakeMqttClient()
    kw.setdefault("rounds", 2)
    kw.setdefault("targets", [20] * kw["rounds"])
    game = TargetBattleGame(list(players), client, "autodarts", stats_db=db, **kw)
    game.announce_start()
    return game


def scores(game):
    return {p["name"]: p["score"] for p in game.snapshot()["players"]}


class TestSetup:
    @pytest.mark.parametrize("kwargs", [
        {"players": []},
        {"players": ["ana", "ana"]},
        {"players": ["ana"], "rounds": 0},
        {"players": ["ana"], "rounds": 100},
        {"players": ["ana"], "scoring": "bulls"},
        {"players": ["ana"], "rounds": 2, "targets": [20]},
        {"players": ["ana"], "rounds": 2, "targets": [20, 21]},
        {"players": ["ana"], "rounds": 2, "targets": [20, 0]},
    ])
    def test_a_setup_that_cannot_be_played_is_refused(self, kwargs):
        players = kwargs.pop("players")
        with pytest.raises(ValueError):
            TargetBattleGame(players, FakeMqttClient(), "autodarts", **kwargs)

    def test_one_player_is_enough(self):
        assert new_game(players=("ana",)).current_player == "ana"


class TestTargets:
    def test_a_random_target_never_repeats_the_one_before(self):
        game = new_game(players=("ana",), rounds=40, targets=None, rng=random.Random(7))
        seen = [game.target]
        for _ in range(39):
            play(game, MISS)
            seen.append(game.target)
        assert all(a != b for a, b in zip(seen, seen[1:]))
        assert all(1 <= t <= 20 for t in seen)

    def test_a_fixed_order_is_followed(self):
        game = new_game(players=("ana",), rounds=3, targets=[5, 12, 5])
        seen = [game.target]
        for _ in range(2):
            play(game, MISS)
            seen.append(game.target)
        assert seen == [5, 12, 5]

    def test_every_round_announces_its_target(self):
        game = new_game(players=("ana",), rounds=2, targets=[5, 12])
        play(game, MISS)
        assert [(e["round"], e["target"]) for e in game.client.events("round_start")] == [(1, 5), (2, 12)]


class TestScoring:
    @pytest.mark.parametrize("scoring, expected", [
        ("standard", [1, 2, 3]),
        ("singles", [1, 0, 0]),
        ("doubles", [0, 1, 0]),
        ("triples", [0, 0, 1]),
    ])
    def test_a_hit_is_worth_what_the_profile_says(self, scoring, expected):
        for multiplier, points in zip((1, 2, 3), expected):
            game = new_game(players=("ana",), scoring=scoring)
            game.on_board_state(1, [hit(20, multiplier)])
            assert game.snapshot()["current_darts"] == [points]

    def test_only_the_target_scores(self):
        game = new_game(players=("ana",), targets=[20, 20])
        game.on_board_state(3, [hit(19, 3), BULL, MISS])
        assert game.snapshot()["current_darts"] == [0, 0, 0]

    def test_the_points_of_a_turn_add_up_over_the_rounds(self):
        game = new_game(players=("ana",), rounds=2, targets=[20, 20])
        play(game, hit(20, 3), hit(20, 1), MISS)
        play(game, hit(20, 2))
        assert scores(game) == {"ana": 6}


class TestRounds:
    def test_the_players_throw_in_order_and_the_round_ends_after_the_last_one(self):
        game = new_game(players=("ana", "bo", "cy"), targets=[20, 20])
        assert game.current_player == "ana"
        play(game, hit(20, 1))
        assert (game.current_player, game.round) == ("bo", 1)
        play(game, hit(20, 1))
        play(game, hit(20, 1))
        assert (game.current_player, game.round) == ("ana", 2)

    def test_a_turn_with_fewer_than_three_darts_counts(self):
        game = new_game(players=("ana", "bo"))
        play(game, hit(20, 3))
        assert scores(game)["ana"] == 3 and game.current_player == "bo"

    def test_the_game_ends_after_the_last_round_and_the_highest_total_wins(self):
        game = new_game(players=("ana", "bo"))
        for darts in ([hit(20, 1)], [hit(20, 3)], [hit(20, 2)], [hit(20, 1)]):
            play(game, *darts)
        snap = game.snapshot()
        assert (snap["state"], snap["active"], snap["current_player"]) == ("finished", False, None)
        assert snap["winners"] == ["bo"]
        assert {p["name"]: p["placement"] for p in snap["players"]} == {"ana": 2, "bo": 1}

    def test_players_on_the_same_total_all_win_and_share_the_placement(self):
        game = new_game(players=("ana", "bo", "cy"), rounds=1, targets=[20])
        play(game, hit(20, 2))
        play(game, hit(20, 2))
        play(game, hit(20, 1))
        snap = game.snapshot()
        assert snap["winners"] == ["ana", "bo"]
        assert {p["name"]: p["placement"] for p in snap["players"]} == {"ana": 1, "bo": 1, "cy": 3}

    def test_playing_alone_has_a_score_but_no_winner(self):
        game = new_game(players=("ana",), rounds=1, targets=[20])
        play(game, hit(20, 3))
        snap = game.snapshot()
        assert snap["state"] == "finished" and snap["winners"] == []
        assert snap["players"][0]["score"] == 3

    def test_darts_that_arrive_after_the_end_are_ignored(self):
        game = new_game(players=("ana",), rounds=1, targets=[20])
        play(game, hit(20, 3))
        play(game, hit(20, 3))
        assert scores(game) == {"ana": 3}


class TestTiebreak:
    def _tied(self, tiebreak=True):
        game = new_game(players=("ana", "bo", "cy"), rounds=1, targets=[20], tiebreak=tiebreak,
                        rng=random.Random(3))
        play(game, hit(20, 2))
        play(game, hit(20, 2))
        play(game, MISS)
        return game

    def test_only_the_players_tied_for_the_top_play_on(self):
        game = self._tied()
        snap = game.snapshot()
        assert snap["state"] == "playing" and snap["tiebreak"] is True
        assert snap["contenders"] == ["ana", "bo"] and game.current_player == "ana"
        assert snap["target"] != 20

    def test_the_highest_score_of_the_round_decides(self):
        game = self._tied()
        play(game, hit(game.target, 1))
        play(game, hit(game.target, 3))
        snap = game.snapshot()
        assert snap["state"] == "finished" and snap["winners"] == ["bo"]
        assert {p["name"]: p["placement"] for p in snap["players"]} == {"bo": 1, "ana": 2, "cy": 3}

    def test_a_new_tie_goes_on_with_a_new_round_on_a_new_target(self):
        game = self._tied()
        first = game.target
        play(game, hit(first, 1))
        play(game, hit(first, 1))
        snap = game.snapshot()
        assert snap["state"] == "playing" and snap["contenders"] == ["ana", "bo"]
        assert game.target != first

    def test_tiebreak_points_do_not_change_the_totals(self):
        game = self._tied()
        play(game, hit(game.target, 3))
        play(game, hit(game.target, 1))
        assert scores(game) == {"ana": 2, "bo": 2, "cy": 0}

    def test_without_a_tiebreak_a_tie_is_shared(self):
        game = self._tied(tiebreak=False)
        assert game.snapshot()["winners"] == ["ana", "bo"]

    def test_a_tiebreak_only_comes_up_when_the_top_is_tied(self):
        game = new_game(players=("ana", "bo"), rounds=1, targets=[20], tiebreak=True)
        play(game, hit(20, 3))
        play(game, hit(20, 1))
        assert game.snapshot()["state"] == "finished"


class TestDartsOnTheBoard:
    def test_the_darts_of_a_round_stay_until_the_round_is_over(self):
        game = new_game(players=("ana", "bo"), targets=[20, 20])
        play(game, hit(20, 3), MISS)
        game.on_board_state(1, [hit(20, 1)])
        darts = game.snapshot()["round_darts"]
        assert [d["points"] for d in darts["ana"]] == [3, 0]
        assert [d["points"] for d in darts["bo"]] == [1]
        assert all({"field", "x", "y"} <= set(d) for d in darts["ana"])
        game.on_board_state(0, [])
        assert game.snapshot()["round_darts"] == {}

    def test_a_dart_corrected_by_tapping_shows_at_its_field(self):
        game = new_game(players=("ana",))
        game.on_board_state(1, [MISS])
        game.correct_current_dart(0, "T20")
        dart = game.snapshot()["round_darts"]["ana"][0]
        assert (dart["field"], dart["points"]) == ("T20", 3)
        assert dart["x"] is not None and dart["y"] is not None

    def test_a_dart_corrected_by_tapping_is_scored_when_the_turn_ends(self):
        game = new_game(players=("ana", "bo"))
        game.on_board_state(1, [MISS])
        game.correct_current_dart(0, "D20")
        game.on_board_state(2, [MISS, hit(20, 1)])      # the board reports everything afresh
        game.on_board_state(0, [])
        assert scores(game)["ana"] == 3

    def test_the_live_turn_is_published_over_mqtt(self):
        game = new_game()
        game.on_board_state(2, [hit(20, 3), MISS])
        assert game.client.last("autodarts/target_battle/current/dart1") == "3"
        assert game.client.last("autodarts/target_battle/current/dart2") == "0"
        assert game.client.last("autodarts/target_battle/current/total") == "3"


class TestUndoAndCorrection:
    def test_undo_walks_back_one_turn_at_a_time(self):
        game = new_game(players=("ana", "bo"))
        play(game, hit(20, 3))
        play(game, hit(20, 1))
        assert game.undo() is True
        assert (game.current_player, scores(game)) == ("bo", {"ana": 3, "bo": 0})
        assert game.undo() is True
        assert (game.current_player, scores(game)) == ("ana", {"ana": 0, "bo": 0})
        assert game.undo() is False

    def test_undo_across_a_round_gets_the_old_target_back(self):
        game = new_game(players=("ana",), rounds=2, targets=[5, 12])
        play(game, MISS)
        assert game.target == 12
        game.undo()
        assert (game.round, game.target) == (1, 5)

    def test_undo_reopens_a_finished_game(self):
        game = new_game(players=("ana", "bo"), rounds=1, targets=[20])
        play(game, hit(20, 1))
        play(game, hit(20, 3))
        assert game.state == "finished"
        game.undo()
        assert (game.state, game.winners, game.current_player) == ("playing", [], "bo")

    def test_correcting_a_total_scores_the_turn_again(self):
        game = new_game(players=("ana", "bo"))
        play(game, hit(20, 3))
        game.correct_turn(1)
        assert scores(game)["ana"] == 1 and game.current_player == "bo"
        assert game.snapshot()["round_darts"]["ana"] == []        # the darts were misread

    def test_correcting_the_turn_that_ended_the_game_changes_the_result(self):
        game = new_game(players=("ana", "bo"), rounds=1, targets=[20])
        play(game, hit(20, 2))
        play(game, hit(20, 1))
        assert game.winners == ["ana"]
        game.correct_turn(3)
        assert game.state == "finished" and game.winners == ["bo"]

    def test_a_correction_after_the_round_keeps_the_target_of_the_next_one(self):
        game = new_game(players=("ana",), rounds=3, targets=None, rng=random.Random(11))
        play(game, hit(1, 1))
        second = game.target
        game.correct_turn(2)
        assert game.target == second

    def test_nothing_to_correct_before_a_turn_is_over(self):
        game = new_game()
        game.correct_turn(2)
        assert scores(game) == {"ana": 0, "bo": 0}


class TestStoredGame:
    def _db(self):
        return StatsDB(":memory:")

    def test_the_match_turns_darts_and_result_are_stored(self):
        db = self._db()
        game = new_game(players=("ana", "bo"), db=db, rounds=1, targets=[20])
        play(game, hit(20, 3), hit(20, 1), MISS)
        play(game, hit(20, 1))
        match = db.match_row(game.match_id)
        assert (match["game_mode"], match["points_start"], match["winner"]) == ("Target Battle", 1, "ana")
        assert match["ended_at"] is not None
        turns = [tuple(r) for r in db._conn.execute(
            "SELECT player, round_no, target, tiebreak, darts_count, score FROM target_battle_turns ORDER BY id")]
        assert turns == [("ana", 1, 20, 0, 3, 4), ("bo", 1, 20, 0, 1, 1)]
        results = [tuple(r) for r in db._conn.execute(
            "SELECT player, placement, score FROM target_battle_results ORDER BY placement")]
        assert results == [("ana", 1, 4), ("bo", 2, 1)]
        darts = db._conn.execute(
            "SELECT player, dart_number, field, corrected FROM dart_positions WHERE game_mode = 'Target Battle'"
            " ORDER BY id").fetchall()
        assert [tuple(r) for r in darts] == [("ana", 1, "T20", 0), ("ana", 2, "S20", 0), ("ana", 3, "M3", 0),
                                              ("bo", 1, "S20", 0)]

    def test_a_tie_has_no_single_winner_in_the_match(self):
        db = self._db()
        game = new_game(players=("ana", "bo"), db=db, rounds=1, targets=[20])
        play(game, hit(20, 1))
        play(game, hit(20, 1))
        assert db.match_row(game.match_id)["winner"] is None
        assert db._conn.execute("SELECT COUNT(*) FROM target_battle_results WHERE placement = 1").fetchone()[0] == 2

    def test_playing_alone_stores_the_score_without_a_winner(self):
        db = self._db()
        game = new_game(players=("ana",), db=db, rounds=1, targets=[20])
        play(game, hit(20, 3))
        assert db.match_row(game.match_id)["winner"] is None
        assert tuple(db._conn.execute("SELECT placement, score FROM target_battle_results").fetchone()) == (1, 3)

    def test_tiebreak_turns_are_marked(self):
        db = self._db()
        game = new_game(players=("ana", "bo"), db=db, rounds=1, targets=[20], tiebreak=True,
                        rng=random.Random(3))
        play(game, hit(20, 1))
        play(game, hit(20, 1))
        play(game, hit(game.target, 1))
        rows = db._conn.execute("SELECT tiebreak, round_no FROM target_battle_turns ORDER BY id").fetchall()
        assert [tuple(r) for r in rows] == [(0, 1), (0, 1), (1, 1)]

    def test_undo_takes_the_turn_the_result_and_the_closing_back(self):
        db = self._db()
        game = new_game(players=("ana", "bo"), db=db, rounds=1, targets=[20])
        play(game, hit(20, 3))
        play(game, hit(20, 1))
        game.undo()
        match = db.match_row(game.match_id)
        assert match["ended_at"] is None and match["winner"] is None
        assert db._conn.execute("SELECT COUNT(*) FROM target_battle_results").fetchone()[0] == 0
        assert db._conn.execute("SELECT COUNT(*) FROM target_battle_turns").fetchone()[0] == 1
        assert db._conn.execute("SELECT COUNT(*) FROM dart_positions WHERE player = 'bo'").fetchone()[0] == 0

    def test_a_corrected_total_is_stored_and_its_darts_are_not_trusted(self):
        db = self._db()
        game = new_game(players=("ana", "bo"), db=db)
        play(game, hit(20, 3))
        game.correct_turn(1)
        assert db._conn.execute("SELECT score FROM target_battle_turns").fetchone()[0] == 1
        assert tuple(db._conn.execute("SELECT corrected, misread FROM dart_positions").fetchone()) == (1, 1)

    def test_a_dart_set_by_tapping_is_stored_with_its_field(self):
        db = self._db()
        game = new_game(players=("ana", "bo"), db=db)
        game.on_board_state(1, [MISS])
        game.correct_current_dart(0, "T20")
        game.on_board_state(0, [])
        row = db._conn.execute("SELECT field, entry, corrected, misread FROM dart_positions").fetchone()
        assert tuple(row) == ("T20", "manual", 1, 0)

    def test_deleting_a_player_removes_their_games(self):
        db = self._db()
        game = new_game(players=("ana", "bo"), db=db, rounds=1, targets=[20])
        play(game, hit(20, 1))
        play(game, hit(20, 1))
        db.delete_player("ana")
        for table in ("target_battle_turns", "target_battle_results"):
            assert db._conn.execute(f"SELECT COUNT(*) FROM {table} WHERE player = 'ana'").fetchone()[0] == 0
        assert db._conn.execute("SELECT COUNT(*) FROM dart_positions WHERE player = 'ana'").fetchone()[0] == 0

    def test_target_battle_does_not_show_up_in_the_x01_statistics(self):
        db = self._db()
        game = new_game(players=("ana", "bo"), db=db, rounds=1, targets=[20])
        play(game, hit(20, 3))
        play(game, hit(20, 1))
        assert db.x01_win_counts() == {}
        assert db.player_dart_positions("ana", mode="x01")["total"] == 0
        assert db.x01_points_start_values() == []


class TestMqtt:
    def test_the_state_is_published_and_follows_the_game(self):
        game = new_game(players=("ana", "bo"), rounds=2, targets=[5, 12])
        topic = "autodarts/target_battle"
        assert game.client.last(f"{topic}/active") == "true"
        assert (game.client.last(f"{topic}/round"), game.client.last(f"{topic}/rounds")) == ("1", "2")
        assert game.client.last(f"{topic}/target") == "5"
        play(game, hit(5, 3))
        play(game, hit(5, 1))
        assert game.client.last(f"{topic}/round") == "2" and game.client.last(f"{topic}/target") == "12"
        state = json.loads(game.client.last(f"{topic}/state"))
        assert state["players"]["ana"]["score"] == 3 and state["current_player"] == "ana"

    def test_the_events_of_the_game_are_published(self):
        game = new_game(players=("ana",), rounds=1, targets=[20])
        play(game, hit(20, 3))
        assert game.client.events("turn_end")[0]["score"] == 3
        assert game.client.events("game_won")[0]["scores"] == {"ana": 3}

    def test_the_game_is_over_when_the_state_says_so(self):
        game = new_game(players=("ana",), rounds=1, targets=[20])
        play(game, MISS)
        assert game.client.last("autodarts/target_battle/active") == "false"

    def test_every_state_change_reaches_the_screens(self):
        changes = []
        game = TargetBattleGame(["ana"], FakeMqttClient(), "autodarts", rounds=1, targets=[20],
                                on_change=lambda: changes.append(1))
        game.announce_start()
        before = len(changes)
        game.on_board_state(1, [hit(20, 1)])
        assert len(changes) > before


class TestController:
    def _controller(self, db=None):
        pub = FakeMqttPub()
        return TargetBattleController(pub, "autodarts", stats_db=db), pub

    def test_a_started_game_is_active_and_gets_the_board_state(self):
        ctrl, _ = self._controller()
        assert ctrl.active is False
        ctrl.start(["ana"], rounds=1, targets=[20])
        assert ctrl.active is True
        ctrl.on_board_state(1, [hit(20, 3)])
        assert ctrl.game.snapshot()["current_darts"] == [3]

    def test_the_game_is_assigned_before_the_screens_are_told(self):
        pub = FakeMqttPub()
        seen = []
        ctrl = TargetBattleController(pub, "autodarts", on_change=lambda: seen.append(ctrl.game is not None))
        ctrl.start(["ana"], rounds=1, targets=[20])
        assert seen and all(seen)

    def test_stop_clears_the_game_and_the_topics(self):
        ctrl, pub = self._controller()
        ctrl.start(["ana"], rounds=1, targets=[20])
        ctrl.stop()
        assert ctrl.game is None and ctrl.active is False
        assert pub.client.last("autodarts/target_battle/state") == ""
        assert pub.client.last("autodarts/target_battle/active") == "false"

    def test_a_setup_that_cannot_be_played_is_refused(self):
        ctrl, _ = self._controller()
        with pytest.raises(ValueError):
            ctrl.start([], rounds=1)
        assert ctrl.game is None

    def test_mqtt_commands_start_correct_undo_and_stop(self):
        ctrl, pub = self._controller()
        handler = pub.subscribed["autodarts/target_battle/command"]
        handler(json.dumps({"action": "start", "players": ["ana", "bo"], "rounds": 2,
                            "targets": [20, 20], "scoring": "triples", "tiebreak": True}))
        assert ctrl.active and ctrl.game.scoring == "triples" and ctrl.game.tiebreak_enabled
        play(ctrl.game, hit(20, 3))
        handler(json.dumps({"action": "correct_turn", "total": 0}))
        assert ctrl.game.snapshot()["players"][0]["score"] == 0
        handler(json.dumps({"action": "undo"}))
        assert ctrl.game.current_player == "ana"
        handler(json.dumps({"action": "stop"}))
        assert ctrl.game is None

    def test_a_start_command_that_cannot_be_played_is_ignored(self):
        ctrl, pub = self._controller()
        handler = pub.subscribed["autodarts/target_battle/command"]
        handler(json.dumps({"action": "start", "players": [], "rounds": 1}))
        handler(json.dumps({"action": "start", "players": ["ana"], "rounds": "many"}))
        handler("not json")
        assert ctrl.game is None

    def test_players_can_be_added_and_hidden_over_mqtt(self):
        db = StatsDB(":memory:")
        ctrl, pub = self._controller(db)
        handler = pub.subscribed["autodarts/target_battle/command"]
        handler(json.dumps({"action": "add_player", "name": "ana"}))
        assert json.loads(pub.client.last("autodarts/target_battle/known_players")) == ["ana"]
        handler(json.dumps({"action": "remove_player", "name": "ana"}))
        assert json.loads(pub.client.last("autodarts/target_battle/known_players")) == []


class TestAchievements:
    def _engine(self, db):
        from breakfast.achievements import AchievementEngine, ACHIEVEMENTS
        return AchievementEngine(db, definitions=ACHIEVEMENTS).attach()

    def _earned(self, db, player):
        return {(r["achievement_id"], r["tier"]) for r in db.earned_for_player(player)}

    def test_a_finished_game_counts_for_the_general_achievements_only(self):
        db = StatsDB(":memory:")
        self._engine(db)
        game = new_game(players=("ana", "bo"), db=db, rounds=1, targets=[20])
        play(game, hit(20, 3), hit(20, 1), MISS)
        play(game, hit(20, 1))
        earned = self._earned(db, "ana")
        assert ("first_breakfast", 0) in earned
        # The X01 and Elimination achievements are not decided by a Target Battle.
        assert ("first_bite", 0) not in earned and ("last_at_the_table", 0) not in earned
        assert ("job_done", 0) not in earned

    def test_the_darts_count_for_the_achievements_of_every_game(self):
        db = StatsDB(":memory:")
        self._engine(db)
        game = new_game(players=("ana", "bo"), db=db, rounds=1, targets=[20])
        play(game, BULL, MISS, MISS)
        play(game, hit(20, 1))
        assert ("bullseye", 0) in self._earned(db, "ana")
        assert ("bullseye", 0) not in self._earned(db, "bo")

    def test_a_game_that_is_not_finished_earns_nothing_yet(self):
        db = StatsDB(":memory:")
        self._engine(db)
        game = new_game(players=("ana", "bo"), db=db, rounds=2, targets=[20, 20])
        play(game, BULL, MISS, MISS)
        assert self._earned(db, "ana") == set()

    def test_undoing_the_last_turn_takes_the_achievements_back(self):
        db = StatsDB(":memory:")
        self._engine(db)
        game = new_game(players=("ana", "bo"), db=db, rounds=1, targets=[20])
        play(game, BULL, MISS, MISS)
        play(game, hit(20, 1))
        assert ("bullseye", 0) in self._earned(db, "ana")
        game.undo()
        assert self._earned(db, "ana") == set()


class TestColorsAndWheel:
    def test_the_players_carry_their_colors_into_the_snapshot(self):
        colors = {"ana": {"color": "#ff0000", "ring": None},
                  "bo": {"color": "#ff0000", "ring": {"color": "#ffffff", "dash": False}}}
        game = new_game(colors=colors)
        players = {p["name"]: p for p in game.snapshot()["players"]}
        assert players["ana"]["color"] == "#ff0000" and players["ana"]["ring"] is None
        assert players["bo"]["ring"] == {"color": "#ffffff", "dash": False}

    def test_a_player_without_a_color_has_none_in_the_snapshot(self):
        assert new_game().snapshot()["players"][0]["color"] is None

    def test_the_controller_uses_the_profile_colors_and_fills_in_the_rest(self):
        db = StatsDB(":memory:")
        db.upsert_player("ana")
        db.set_player_color("ana", "#123456")
        ctrl = TargetBattleController(FakeMqttPub(), "autodarts", stats_db=db)
        ctrl.start(["ana", "bo"], rounds=1, targets=[20])
        players = {p["name"]: p for p in ctrl.game.snapshot()["players"]}
        assert players["ana"]["color"] == "#123456"
        assert players["bo"]["color"] is not None and players["bo"]["color"] != "#123456"

    def test_the_wheel_turns_for_random_targets_and_in_a_tiebreak_only(self):
        assert new_game(targets=None).snapshot()["wheel"] is True
        game = new_game(players=("ana", "bo"), rounds=1, targets=[20], tiebreak=True, rng=random.Random(3))
        assert game.snapshot()["wheel"] is False
        play(game, hit(20, 1))
        play(game, hit(20, 1))
        assert game.snapshot()["tiebreak"] is True and game.snapshot()["wheel"] is True

    def test_a_new_round_is_fresh_and_an_old_one_restored_by_undo_is_not(self):
        game = new_game(players=("ana",), rounds=2, targets=[5, 12])
        assert game.snapshot()["round_age"] < 3
        play(game, MISS)
        assert game.snapshot()["round_age"] < 3
        game.undo()
        assert game.snapshot()["round_age"] > 60


class TestHistory:
    def test_every_round_is_listed_with_its_target_and_the_scores_so_far(self):
        game = new_game(players=("ana", "bo"), rounds=3, targets=[5, 12, 7])
        play(game, hit(5, 3))
        history = game.snapshot()["history"]
        assert history == [{"round": 1, "tiebreak": False, "target": 5, "scores": {"ana": 3}, "current": True}]
        play(game, hit(5, 1))
        play(game, hit(12, 2))
        history = game.snapshot()["history"]
        assert history[0] == {"round": 1, "tiebreak": False, "target": 5, "scores": {"ana": 3, "bo": 1}}
        assert history[1] == {"round": 2, "tiebreak": False, "target": 12, "scores": {"ana": 2}, "current": True}

    def test_the_finished_game_lists_all_rounds_and_none_as_current(self):
        game = new_game(players=("ana",), rounds=2, targets=[5, 12])
        play(game, hit(5, 1))
        play(game, hit(12, 1))
        history = game.snapshot()["history"]
        assert [r["round"] for r in history] == [1, 2] and not any(r.get("current") for r in history)

    def test_a_tiebreak_round_is_marked(self):
        game = new_game(players=("ana", "bo"), rounds=1, targets=[20], tiebreak=True, rng=random.Random(3))
        play(game, hit(20, 1))
        play(game, hit(20, 1))
        assert [(r["tiebreak"], r["round"]) for r in game.snapshot()["history"]] == [(False, 1), (True, 1)]

    def test_a_corrected_total_and_undo_keep_the_history_right(self):
        game = new_game(players=("ana",), rounds=3, targets=[5, 12, 7])
        play(game, hit(5, 3))
        game.correct_turn(2)
        history = game.snapshot()["history"]
        assert [r["round"] for r in history] == [1, 2]
        assert history[0]["scores"] == {"ana": 2} and history[1].get("current")
        game.undo()
        history = game.snapshot()["history"]
        assert [r["round"] for r in history] == [1] and history[0]["scores"] == {} and history[0]["current"]
