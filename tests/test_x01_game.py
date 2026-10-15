import pytest

from breakfast.state import GameState
from breakfast.stats import StatsDB, StatsTracker
from breakfast.x01_game import X01Controller, X01Game
from tests.test_target_battle import BULL, MISS, hit, play


class Match:
    """A match played in Breakfast with what listens to it: the screen state and the statistics."""

    def __init__(self, players=("ana", "bo"), **kw):
        self.events = []
        self.state = GameState()
        self.db = StatsDB(":memory:")
        self.tracker = StatsTracker(self.db)
        kw.setdefault("bull_off", False)
        kw.setdefault("start_delay", 0)
        kw.setdefault("rng", FixedOrder())
        self.game = X01Game(list(players), self.emit, stats_db=self.db, **kw)
        self.game.announce_start()

    def emit(self, data):
        self.events.append(data)
        self.state.update(data)
        self.tracker.process(data)

    def names(self):
        return [e["event"] for e in self.events]

    def turns(self):
        return self.db._conn.execute("SELECT * FROM turns WHERE match_id = ? ORDER BY id", (self.game.match_id,)).fetchall()

    def scores(self):
        return {p["name"]: p["remaining"] for p in self.game.snapshot()["players"]}


class FixedOrder:
    """Keeps the order of the players when it is drawn."""

    def shuffle(self, items):
        pass


def pull(game):
    game.on_board_state(0, [])


class TestSetup:
    @pytest.mark.parametrize("kw", [
        {"players": []}, {"players": ["ana", "Ana"]},
        {"start": 1}, {"start": 2000}, {"in_mode": "triple"}, {"out_mode": "none"}, {"legs": 0}, {"legs": 26},
    ])
    def test_a_setup_that_cannot_be_played_is_refused(self, kw):
        kw.setdefault("players", ["ana", "bo"])
        with pytest.raises(ValueError):
            X01Game(kw.pop("players"), lambda e: None, **kw)

    def test_the_match_starts_with_the_first_player_and_the_start_score(self):
        m = Match(start=301)
        assert m.names() == ["match-started"]
        assert m.state.snapshot()["match_started"] and m.state.points_start == 301
        assert m.state.remaining_scores == {"player1": 301, "player2": 301}
        assert m.state.active_player_name == "ana"
        assert m.game.snapshot()["current_player"] == "ana"
        assert [r["game_mode"] for r in m.db._conn.execute("SELECT game_mode FROM matches")] == ["X01"]

    def test_one_player_can_play_alone(self):
        m = Match(players=("ana",), start=101)
        play(m.game, hit(20, 3), hit(20, 3), hit(1, 1))      # 121 is more than is left: a bust
        assert m.scores() == {"ana": 101} and m.turns()[0]["is_bust"] == 1
        assert m.state.active_player_name == "ana" and m.names()[-1] == "darts-pulled"


class TestTurns:
    def test_three_darts_are_told_one_by_one_and_scored(self):
        m = Match()
        m.game.on_board_state(1, [hit(20, 3)])
        assert m.state.snapshot()["remaining_scores"] == {"player1": 441, "player2": 501}
        m.game.on_board_state(2, [hit(20, 3), hit(5, 1)])
        m.game.on_board_state(3, [hit(20, 3), hit(5, 1), hit(1, 1)])
        assert m.names() == ["match-started", "dart1-thrown", "dart2-thrown", "dart3-thrown", "darts-thrown"]
        assert m.state.players[0]["turn_score"] == 66 and m.state.players[0]["remaining"] == 435
        pull(m.game)
        assert m.names()[-1] == "darts-pulled"
        assert m.state.active_player_name == "bo"
        assert m.scores() == {"ana": 435, "bo": 501}
        [turn] = m.turns()
        assert (turn["player"], turn["score"], turn["remaining_before"], turn["is_bust"]) == ("ana", 66, 501, 0)

    def test_the_players_throw_in_turn(self):
        m = Match(("ana", "bo", "cy"))
        for _ in range(4):
            play(m.game, hit(20, 1), hit(20, 1), hit(20, 1))
        assert [t["player"] for t in m.turns()] == ["ana", "bo", "cy", "ana"]
        assert m.state.remaining_scores == {"player1": 381, "player2": 441, "player3": 441}

    def test_a_turn_without_a_dart_ends_by_hand_as_three_misses(self):
        m = Match()
        assert m.game.next_turn()
        assert m.state.active_player_name == "bo"
        [turn] = m.turns()
        assert (turn["player"], turn["score"], turn["darts_count"]) == ("ana", 0, 3)

    def test_a_turn_with_fewer_than_three_darts_is_stored_with_them(self):
        m = Match()
        play(m.game, hit(20, 3))
        [turn] = m.turns()
        assert (turn["score"], turn["darts_count"]) == (60, 1)


class TestBust:
    def test_below_zero_is_a_bust_and_the_score_stays(self):
        m = Match(start=40)
        play(m.game, hit(20, 3))
        assert m.names()[-2:] == ["busted", "darts-pulled"]
        assert m.scores() == {"ana": 40, "bo": 40}
        assert m.state.players[0]["is_bust"]
        [turn] = m.turns()
        assert (turn["score"], turn["is_bust"]) == (0, 1)
        assert turn["dart1"] is not None

    def test_darts_after_a_bust_do_not_count(self):
        m = Match(start=40)
        play(m.game, hit(20, 3), hit(20, 1), hit(1, 1))
        assert m.names().count("dart1-thrown") == 0
        [turn] = m.turns()
        assert turn["is_bust"] == 1 and turn["darts_count"] == 1

    def test_one_left_with_a_double_out_is_a_bust(self):
        m = Match(start=21)
        play(m.game, hit(20, 1))
        assert m.scores()["ana"] == 21 and m.turns()[0]["is_bust"] == 1

    def test_one_left_with_a_straight_out_is_not(self):
        m = Match(start=21, out_mode="straight")
        play(m.game, hit(20, 1))
        assert m.scores()["ana"] == 1

    def test_zero_with_a_single_is_a_bust_with_a_double_out(self):
        m = Match(start=20)
        play(m.game, hit(20, 1))
        assert m.scores()["ana"] == 20 and m.turns()[0]["is_bust"] == 1

    def test_the_busted_turn_does_not_open_a_double_in(self):
        m = Match(start=40, in_mode="double")
        play(m.game, hit(5, 2), hit(10, 3))      # ana: D5 opens (30 left), T10 is zero with a triple: bust
        play(m.game, hit(1, 1))                  # bo: no double, nothing counts
        play(m.game, hit(10, 1))                 # ana again: the bust took the opening back
        assert m.scores() == {"ana": 40, "bo": 40}


class TestModes:
    def test_a_double_in_scores_from_the_first_double(self):
        m = Match(in_mode="double")
        play(m.game, hit(20, 1), hit(20, 3), hit(10, 2))
        [turn] = m.turns()
        assert turn["score"] == 20 and turn["dart1_val"] == 0 and turn["dart2_val"] == 0 and turn["dart3_val"] == 20
        assert m.scores()["ana"] == 481

    def test_a_double_in_stays_open_for_the_next_turn(self):
        m = Match(in_mode="double")
        play(m.game, hit(10, 2))
        play(m.game, hit(1, 1))
        play(m.game, hit(20, 3))
        assert m.scores() == {"ana": 481 - 60, "bo": 501}

    def test_a_master_in_takes_a_triple(self):
        m = Match(in_mode="master")
        play(m.game, hit(20, 1), hit(19, 3))
        assert m.scores()["ana"] == 501 - 57

    def test_a_straight_out_finishes_with_a_single(self):
        m = Match(start=20, out_mode="straight")
        play(m.game, hit(20, 1))
        assert m.game.snapshot()["state"] == "finished"

    def test_a_master_out_finishes_with_a_triple_and_not_with_a_single(self):
        m = Match(start=60, out_mode="master")
        play(m.game, hit(20, 3))
        assert m.game.snapshot()["state"] == "finished"
        m = Match(start=20, out_mode="master")
        play(m.game, hit(20, 1))
        assert m.turns()[0]["is_bust"] == 1

    def test_the_bull_finishes_a_double_out_and_the_outer_bull_does_not(self):
        m = Match(start=50)
        play(m.game, BULL)
        assert m.game.snapshot()["state"] == "finished"
        m = Match(start=25)
        play(m.game, {"segment": {"name": "25", "number": 25, "multiplier": 1}})
        assert m.turns()[0]["is_bust"] == 1


class TestLegsAndMatch:
    def test_a_finish_wins_the_leg_and_the_next_one_starts_with_the_next_player(self):
        m = Match(("ana", "bo", "cy"), start=40, legs=2)
        play(m.game, hit(20, 2))
        assert m.names()[-3:] == ["dart1-thrown", "game-won", "darts-pulled"] or "game-won" in m.names()
        assert m.names()[-2:] == ["darts-pulled", "game-started"]
        assert m.db.legs_won_by_player(m.game.match_id) == {"ana": 1}
        snap = m.game.snapshot()
        assert snap["leg"] == 2 and snap["current_player"] == "bo" and snap["state"] == "playing"
        assert m.scores() == {"ana": 40, "bo": 40, "cy": 40}
        assert m.state.current_leg == 2 and m.state.players[0]["legs_won"] == 1
        assert m.state.active_player_name == "bo"

    def test_the_first_thrower_moves_on_each_leg(self):
        m = Match(("ana", "bo"), start=40, legs=3)
        play(m.game, hit(20, 2))                    # ana wins leg 1, bo starts leg 2
        play(m.game, hit(20, 2))                    # bo wins leg 2, ana starts leg 3
        assert m.game.snapshot()["current_player"] == "ana" and m.game.snapshot()["leg"] == 3

    def test_the_player_who_reaches_the_legs_to_win_wins_the_match(self):
        m = Match(("ana", "bo"), start=40, legs=2)
        play(m.game, hit(20, 2))
        play(m.game, hit(1, 1))
        play(m.game, hit(20, 2))
        snap = m.game.snapshot()
        assert snap["state"] == "finished" and snap["winner"] == "ana"
        assert m.names()[-1] == "match-won"
        row = m.db._conn.execute("SELECT winner, ended_at FROM matches").fetchone()
        assert row["winner"] == "ana" and row["ended_at"] is not None
        assert m.db.legs_won_by_player(m.game.match_id) == {"ana": 2}

    def test_darts_after_the_match_are_ignored(self):
        m = Match(start=40)
        play(m.game, hit(20, 2))
        n = len(m.events)
        play(m.game, hit(20, 1))
        assert len(m.events) == n

    def test_the_checkout_is_counted_in_the_statistics(self):
        m = Match(start=40)
        play(m.game, hit(20, 2))
        assert m.turns()[0]["is_checkout"] == 1
        assert m.tracker.computed_session_stats()["ana"]["co_hits"] == 1


class TestUndoAndCorrections:
    def test_undo_takes_the_last_turn_back_also_from_the_statistics(self):
        m = Match()
        play(m.game, hit(20, 3), hit(20, 3), hit(20, 3))
        assert m.game.undo()
        assert m.scores() == {"ana": 501, "bo": 501} and m.game.snapshot()["current_player"] == "ana"
        assert m.turns() == []
        assert m.state.remaining_scores == {"player1": 501, "player2": 501}
        assert m.state.active_player_name == "ana"
        assert m.tracker.computed_session_stats() == {}
        play(m.game, hit(1, 1))
        assert [t["turn"] for t in m.turns()] == [1] and m.turns()[0]["score"] == 1

    def test_undo_walks_back_several_turns(self):
        m = Match()
        play(m.game, hit(20, 1))
        play(m.game, hit(19, 1))
        assert m.game.undo() and m.game.undo()
        assert not m.game.undo()
        assert m.scores() == {"ana": 501, "bo": 501} and m.turns() == []

    def test_undo_of_the_turn_that_ended_the_match_opens_it_again(self):
        m = Match(start=40)
        play(m.game, hit(20, 2))
        assert m.game.snapshot()["state"] == "finished"
        assert m.game.undo()
        assert m.game.snapshot()["state"] == "playing" and m.scores()["ana"] == 40
        row = m.db._conn.execute("SELECT winner, ended_at FROM matches").fetchone()
        assert row["winner"] is None and row["ended_at"] is None
        assert m.db.legs_won_by_player(m.game.match_id) == {} and m.turns() == []

    def test_undo_of_a_leg_win_takes_the_leg_back(self):
        m = Match(start=40, legs=2)
        play(m.game, hit(20, 2))
        assert m.game.undo()
        snap = m.game.snapshot()
        assert snap["leg"] == 1 and snap["current_player"] == "ana" and m.scores()["ana"] == 40
        assert m.db.legs_won_by_player(m.game.match_id) == {} and m.state.current_leg == 1
        play(m.game, hit(20, 2))
        assert m.db.legs_won_by_player(m.game.match_id) == {"ana": 1}
        assert [t["turn"] for t in m.turns()] == [1]

    def test_a_dart_corrected_in_the_turn_in_progress_changes_what_it_scores(self):
        m = Match()
        m.game.on_board_state(1, [hit(20, 1)])
        m.game.correct_current_dart(0, "T20")
        pull(m.game)
        assert m.turns()[0]["score"] == 60 and m.scores()["ana"] == 441

    def test_a_correction_that_removes_a_bust_is_told_afresh_and_makes_no_calls(self):
        m = Match(start=60)
        m.game.on_board_state(1, [hit(20, 3)])           # 60 left 0 with a triple: bust (double out)
        assert "busted" in m.names()
        m.game.correct_current_dart(0, "D20")            # 40 left 20, no bust, no finish
        assert m.names()[-2:] == ["x01-resync", "dart1-thrown"] and m.events[-1].get("silent")
        assert not m.state.players[0]["is_bust"]
        pull(m.game)
        assert m.scores()["ana"] == 20 and m.turns()[0]["is_bust"] == 0

    def test_a_correction_of_a_finish_that_was_stored_takes_it_out_again(self):
        m = Match(start=20, legs=2)
        m.game.on_board_state(1, [hit(10, 2)])           # leg won, stored
        assert m.db.legs_won_by_player(m.game.match_id) == {"ana": 1}
        m.game.correct_current_dart(0, "S20")            # a single to finish: a bust with a double out
        assert m.db.legs_won_by_player(m.game.match_id) == {} and m.turns() == []
        pull(m.game)
        assert m.turns()[0]["is_bust"] == 1 and m.game.snapshot()["leg"] == 1

    def test_the_last_turn_can_be_corrected_after_it_ended(self):
        m = Match()
        play(m.game, hit(20, 1), hit(20, 1), hit(20, 1))
        assert m.game.correct_last_dart(2, "T20")
        assert m.scores() == {"ana": 501 - 100, "bo": 501} and m.game.snapshot()["current_player"] == "bo"
        [turn] = m.turns()
        assert turn["score"] == 100
        assert all(e.get("silent") for e in m.events[m.names().index("x01-resync") + 1:])

    def test_the_last_turn_can_be_corrected_after_it_ended_the_match(self):
        m = Match(start=40)
        play(m.game, hit(20, 2))
        assert m.game.correct_last_dart(0, "D10")
        snap = m.game.snapshot()
        assert snap["state"] == "playing" and m.scores()["ana"] == 20 and snap["current_player"] == "bo"
        assert m.db._conn.execute("SELECT winner FROM matches").fetchone()["winner"] is None


class TestBullOff:
    def thrower(self, m):
        return m.game.snapshot()["current_player"]

    def test_the_closest_dart_throws_first_and_the_others_follow_by_distance(self):
        m = Match(("ana", "bo", "cy"), bull_off=True)
        snap = m.game.snapshot()
        assert snap["phase"] == "bull_off" and snap["current_player"] == "ana"
        assert m.events == []                                 # the match is not started yet
        play(m.game, hit(5, 1, x=0.5, y=0.0))                 # ana: 0.5
        assert self.thrower(m) == "bo"
        play(m.game, hit(25, 1, x=0.05, y=0.0))               # bo: 0.05
        play(m.game, hit(3, 1, x=0.2, y=0.0))                 # cy: 0.2
        snap = m.game.snapshot()
        assert snap["phase"] == "playing" and snap["order"] == ["bo", "cy", "ana"]
        assert snap["current_player"] == "bo"
        assert m.names() == ["match-started"] and m.state.active_player_name == "bo"
        assert m.state.remaining_scores == {"player1": 501, "player2": 501, "player3": 501}

    def test_only_the_first_dart_of_a_visit_counts(self):
        m = Match(bull_off=True)
        play(m.game, hit(5, 1, x=0.5, y=0.0), hit(25, 2, x=0.0, y=0.0))
        assert m.game.snapshot()["current_player"] == "bo"
        assert [p["bull_off_mm"] for p in m.game.snapshot()["players"]] == [85, None]

    def test_players_tied_throw_again(self):
        m = Match(("ana", "bo", "cy"), bull_off=True)
        play(m.game, MISS)
        play(m.game, hit(25, 1, x=0.05, y=0.0))
        play(m.game, MISS)                                    # ana and cy are both far away: tied
        snap = m.game.snapshot()
        assert snap["phase"] == "bull_off" and snap["current_player"] == "ana"
        assert [p["name"] for p in snap["players"] if p["placed"]] == ["bo"]
        play(m.game, hit(1, 1, x=0.3, y=0.0))
        play(m.game, hit(1, 1, x=0.2, y=0.0))
        assert m.game.snapshot()["order"] == ["bo", "cy", "ana"]

    def test_the_throw_of_a_bull_off_can_be_undone(self):
        m = Match(bull_off=True)
        play(m.game, hit(5, 1, x=0.5, y=0.0))
        assert m.game.undo()
        assert m.game.snapshot()["current_player"] == "ana" and m.events == []

    def test_by_lot_the_match_starts_at_once(self):
        m = Match(("ana", "bo"), bull_off=False)
        assert m.names() == ["match-started"] and m.game.snapshot()["phase"] == "playing"

    def test_the_first_leg_starter_is_the_first_of_the_order_and_then_it_moves_on(self):
        m = Match(("ana", "bo", "cy"), bull_off=True, start=40, legs=3)
        play(m.game, hit(5, 1, x=0.5, y=0.0))
        play(m.game, hit(5, 1, x=0.3, y=0.0))
        play(m.game, hit(5, 1, x=0.1, y=0.0))
        assert m.game.snapshot()["order"] == ["cy", "bo", "ana"]
        play(m.game, hit(20, 2))                               # cy wins leg 1
        assert m.game.snapshot()["current_player"] == "bo"


@pytest.fixture(autouse=True)
def no_start_delay(monkeypatch):
    monkeypatch.setattr("breakfast.x01_game.START_CALLS_DELAY_S", 0)


class TestBullOffPulling:
    """In the bull-off the next player is up when the darts are pulled, not when the dart lands."""

    def thrown(self, game, *throws):
        for i in range(len(throws)):
            game.on_board_state(i + 1, list(throws[:i + 1]))

    def test_the_thrower_stays_until_the_darts_are_pulled(self):
        m = Match(bull_off=True)
        self.thrown(m.game, hit(5, 1, x=0.5, y=0.0))
        snap = m.game.snapshot()
        assert snap["current_player"] == "ana" and snap["pull_darts"]
        assert [p["bull_off_mm"] for p in snap["players"]] == [85, None]
        assert snap["last_turn"]["darts"][0]["field"] == "S5"
        pull(m.game)
        snap = m.game.snapshot()
        assert snap["current_player"] == "bo" and not snap["pull_darts"]
        assert [p["bull_off_mm"] for p in snap["players"]] == [85, None]

    def test_the_last_thrower_starts_the_match_when_the_darts_are_pulled(self):
        m = Match(bull_off=True)
        play(m.game, hit(5, 1, x=0.5, y=0.0))
        self.thrown(m.game, hit(25, 1, x=0.05, y=0.0))
        assert m.events == [] and m.game.snapshot()["phase"] == "bull_off"
        pull(m.game)
        assert m.names() == ["match-started"] and m.game.snapshot()["order"] == ["bo", "ana"]
        assert [p["bull_off_mm"] for p in m.game.snapshot()["players"]] == [8, 85]     # the distances stay

    def test_a_further_dart_of_the_visit_changes_nothing(self):
        m = Match(bull_off=True)
        self.thrown(m.game, hit(5, 1, x=0.5, y=0.0), hit(25, 2, x=0.0, y=0.0))
        assert m.game.snapshot()["current_player"] == "ana"
        pull(m.game)
        assert [p["bull_off_mm"] for p in m.game.snapshot()["players"]] == [85, None]

    def test_the_dart_can_be_corrected_before_it_is_pulled(self):
        m = Match(bull_off=True)
        self.thrown(m.game, hit(5, 1, x=0.5, y=0.0))
        m.game.correct_current_dart(0, "50")
        snap = m.game.snapshot()
        assert snap["players"][0]["bull_off_mm"] == 0 and snap["last_turn"]["darts"][0]["field"] == "50"

    def test_a_dart_the_board_did_not_see_can_be_entered_and_next_goes_on(self):
        m = Match(bull_off=True)
        m.game.correct_current_dart(0, "25")
        assert m.game.snapshot()["current_player"] == "ana" and m.game.snapshot()["pull_darts"]
        assert m.game.next_turn()
        assert m.game.snapshot()["current_player"] == "bo"
        assert not m.game.next_turn()                    # nothing counted for bo yet

    def test_undo_before_the_darts_are_pulled_takes_the_throw_back(self):
        m = Match(bull_off=True)
        self.thrown(m.game, hit(5, 1, x=0.5, y=0.0))
        assert m.game.undo()
        snap = m.game.snapshot()
        assert snap["current_player"] == "ana" and snap["players"][0]["bull_off_mm"] is None


class TestScreens:
    """What the screen state shows of a match played in Breakfast."""

    def test_every_player_is_known_from_the_start(self):
        m = Match(("ana", "bo", "cy"), start=301)
        assert {i: (p["name"], p["remaining"]) for i, p in m.state.players.items()} == {
            0: ("ana", 301), 1: ("bo", 301), 2: ("cy", 301)}
        assert m.state.snapshot()["current"]["remaining"] == 301

    def test_the_player_who_is_up_has_no_turn_on_the_card(self):
        m = Match()
        play(m.game, hit(20, 3))
        bo = m.state.players[1]
        assert bo["turn_score"] == 0 and bo["throw1_raw"] is None and not bo["is_bust"]
        assert m.state.players[0]["turn_score"] == 60          # the card of the one who threw keeps it

    def test_a_bust_does_not_show_on_the_next_player(self):
        m = Match(start=40)
        play(m.game, hit(20, 3))
        assert m.state.players[0]["is_bust"] and not m.state.players[1]["is_bust"]
        assert m.state.snapshot()["current"]["is_bust"] is False

    def test_a_new_leg_sets_everybodys_score_again(self):
        m = Match(start=40, legs=2)
        play(m.game, hit(10, 1), hit(10, 1))              # ana: 20 left
        play(m.game, hit(5, 1))                           # bo: 35 left
        play(m.game, hit(10, 2))                          # ana finishes
        assert {i: p["remaining"] for i, p in m.state.players.items()} == {0: 40, 1: 40}
        assert all(p["throw1_raw"] is None for p in m.state.players.values())

    def test_the_player_is_called_after_the_darts_of_the_first_turn_are_pulled(self):
        from breakfast.caller import from_config
        from tests.conftest import FakeAudio
        audio = FakeAudio({"ana", "bo", "matchon", "20"})
        caller = from_config(audio, {})
        m = Match()
        m.game._emit_to = lambda data: (m.events.append(data), caller.on_event(m.state.update(data), m.state.snapshot()),
                                        m.tracker.process(data))
        audio.calls.clear()
        play(m.game, hit(20, 1))
        assert audio.played()[-1] == "bo"


class TestController:
    def test_a_match_is_started_and_stopped_through_the_controller(self):
        events = []
        ctrl = X01Controller(events.append)
        game = ctrl.start(["ana", "bo"], bull_off=False)
        assert ctrl.active and ctrl.match_active and ctrl.game is game
        ctrl.stop()
        assert not ctrl.match_active and events[-1] == {"event": "match-ended"}

    def test_a_started_match_ends_the_one_before(self):
        events = []
        ctrl = X01Controller(events.append)
        ctrl.start(["ana", "bo"], bull_off=False)
        ctrl.start(["cy", "di"], bull_off=False)
        assert [e["event"] for e in events].count("match-ended") == 1

    def test_the_board_is_followed_while_the_match_is_active(self):
        events = []
        ctrl = X01Controller(events.append)
        ctrl.start(["ana", "bo"], bull_off=False)
        ctrl.on_board_state(1, [hit(20, 3)])
        assert events[-1]["event"] == "dart1-thrown"
        assert ctrl.next_turn() and events[-1]["event"] == "darts-pulled"

    def test_a_setup_that_cannot_be_played_is_refused(self):
        with pytest.raises(ValueError):
            X01Controller(lambda e: None).start(["ana"], start=1)


def test_a_missed_dart_is_a_miss_for_the_screens():
    m = Match()
    m.game.on_board_state(1, [MISS])
    assert m.state.players[0]["last_is_miss"] and m.state.players[0]["remaining"] == 501


class TestCalls:
    """What the caller says to the events of a match played in Breakfast."""

    def run(self, *plays, **kw):
        from breakfast.caller import from_config
        from tests.conftest import FakeAudio
        audio = FakeAudio({"matchon", "gameon", "ana", "bo", "busted", "matchshot", "gameshot", "t20", "d20", "20",
                           "180", "bull_off", "bull_off_tie"})
        caller = from_config(audio, {})
        m = Match(**kw)

        def emit(data):
            m.events.append(data)
            evt = m.state.update(data)
            if not data.get("silent"):
                caller.on_event(evt, m.state.snapshot())
            m.tracker.process(data)

        m.game._emit_to = emit
        m.events.clear()
        m.game._match_started = False
        m.game._start_match()
        for turn in plays:
            play(m.game, *turn)
        return audio.played()

    def test_the_match_start_calls_the_first_player_and_the_darts_their_fields(self):
        calls = self.run([hit(20, 3), hit(20, 3), hit(20, 3)])
        assert calls[:2] == ["ana", "matchon"]
        assert calls.count("t20") == 3 and "180" in calls

    def test_a_bust_is_called(self):
        assert "busted" in self.run([hit(20, 3)], start=40)

    def test_the_winning_dart_is_called_as_the_match_shot(self):
        calls = self.run([hit(20, 2)], start=40)
        assert calls[-2:] == ["ana", "matchshot"] or calls[-1] == "matchshot"
        assert "d20" not in calls

    def test_a_leg_win_is_called_as_a_gameshot_and_the_next_leg_as_game_on(self):
        calls = self.run([hit(20, 2)], start=40, legs=2)
        assert "gameshot" in calls and calls[-1] == "gameon"
