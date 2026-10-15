import random

import pytest

from breakfast import tournament as tm
from breakfast.state import GameState
from breakfast.stats import StatsDB, StatsTracker
from breakfast.tournament import Bracket, TournamentController
from breakfast.x01_game import X01Controller
from tests.test_target_battle import MISS, hit, play


@pytest.fixture(autouse=True)
def no_start_delay(monkeypatch):
    monkeypatch.setattr("breakfast.x01_game.START_CALLS_DELAY_S", 0)


class TestDraw:
    @pytest.mark.parametrize("n, size", [(2, 2), (3, 4), (4, 4), (5, 8), (8, 8), (9, 16), (32, 32), (33, 64)])
    def test_the_bracket_is_the_next_power_of_two(self, n, size):
        assert tm.bracket_size(n) == size

    @pytest.mark.parametrize("n", [2, 3, 5, 6, 7, 9, 13, 17, 31])
    def test_every_player_has_a_seat_and_no_bye_faces_a_bye(self, n):
        players = [f"p{i}" for i in range(n)]
        for seed in range(20):
            seats = tm.draw(players, random.Random(seed))
            assert sorted(s for s in seats if s) == sorted(players)
            assert len(seats) == tm.bracket_size(n)
            assert all(seats[k] or seats[k + 1] for k in range(0, len(seats), 2))

    def test_the_draw_is_random(self):
        players = [f"p{i}" for i in range(8)]
        assert len({tuple(tm.draw(players, random.Random(s))) for s in range(10)}) > 5

    @pytest.mark.parametrize("n", [0, 1])
    def test_a_draw_needs_two_players(self, n):
        with pytest.raises(ValueError):
            tm.draw([f"p{i}" for i in range(n)])

    @pytest.mark.parametrize("seats, message", [
        (["a"], "power of two"),
        (["a", "b", "c"], "power of two"),
        (["a", "a"], "only play once"),
        (["a", "A"], "only play once"),
        (["a", None], "at least 2"),
        (["a", None, None, None], "at least 2"),
        (["a", "b", None, None], "bye cannot face a bye"),
        (["a", None, "b", None, "c", None, None, "d"], "match the number"),
    ])
    def test_seats_that_cannot_be_played_are_refused(self, seats, message):
        with pytest.raises(ValueError, match=message):
            tm.validate_seats(seats)


class TestBracket:
    def test_four_players_play_two_semi_finals_and_a_final(self):
        b = Bracket(["a", "b", "c", "d"], [1, 3])
        assert b.next_match() == (0, 0)
        b.record(0, 0, "b")
        assert b.next_match() == (0, 1)
        b.record(0, 1, "c")
        assert b.next_match() == (1, 0) and (b.rounds[1][0]["a"], b.rounds[1][0]["b"]) == ("b", "c")
        assert b.winner is None
        b.record(1, 0, "c")
        assert b.winner == "c" and b.next_match() is None

    def test_a_bye_moves_on_without_a_match(self):
        b = Bracket(["a", None, "c", "d"], [1, 1])
        assert b.rounds[0][0]["bye"] and b.rounds[0][0]["winner"] == "a"
        assert b.next_match() == (0, 1)
        b.record(0, 1, "d")
        assert b.next_match() == (1, 0) and b.rounds[1][0]["a"] == "a" and b.rounds[1][0]["b"] == "d"

    def test_five_players_have_three_byes(self):
        seats = tm.draw(["a", "b", "c", "d", "e"], random.Random(3))
        b = Bracket(seats, [1, 1, 1])
        assert sum(1 for m in b.rounds[0] if m["bye"]) == 3
        assert len(b.rounds) == 3 and [len(r) for r in b.rounds] == [4, 2, 1]

    def test_two_players_play_a_final(self):
        b = Bracket(["a", "b"], [5])
        assert len(b.rounds) == 1 and b.next_match() == (0, 0)
        b.record(0, 0, "a")
        assert b.winner == "a"

    def test_a_winner_has_to_be_in_the_match_and_is_recorded_once(self):
        b = Bracket(["a", "b", "c", "d"], [1, 1])
        with pytest.raises(ValueError):
            b.record(0, 0, "c")
        b.record(0, 0, "a")
        with pytest.raises(ValueError):
            b.record(0, 0, "b")

    def test_it_survives_being_stored(self):
        b = Bracket(["a", None, "c", "d"], [1, 2])
        b.record(0, 1, "c", match_id="m1", legs={"c": 1, "d": 0})
        again = Bracket.from_dict(b.to_dict())
        assert again.to_dict() == b.to_dict() and again.next_match() == (1, 0)


class FakeTimer:
    created = []

    def __init__(self, interval, function):
        self.interval, self.function, self.daemon, self.cancelled = interval, function, False, False
        FakeTimer.created.append(self)

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True

    @classmethod
    def fire(cls):
        timer = next(t for t in reversed(cls.created) if not t.cancelled)
        timer.cancelled = True
        timer.function()


class Setup:
    def __init__(self, db=None, delay=3):
        FakeTimer.created = []
        self.events = []
        self.state = GameState()
        self.db = db or StatsDB(":memory:")
        self.tracker = StatsTracker(self.db)
        self.x01 = X01Controller(self.emit, stats_db=self.db)
        self.t = TournamentController(self.x01, stats_db=self.db, next_delay=delay, timer_factory=FakeTimer)

    def emit(self, data):
        self.events.append(data)
        self.state.update(data)
        self.tracker.process(data)

    @property
    def game(self):
        return self.x01.game

    def bull_off(self):
        for k in range(len(self.game.order)):
            play(self.game, hit(25, 1, x=0.2 + 0.1 * k, y=0.0))

    def win(self, who):
        """Play the running match until `who` has won it (start score 2: a D1 finishes)."""
        assert who in self.game.order, f"{who} is not in the match {self.game.order}"
        if self.game.phase == "bull_off":
            self.bull_off()
        while self.game.snapshot()["state"] == "playing":
            play(self.game, hit(1, 2) if self.game.snapshot()["current_player"] == who else MISS)

    def start(self, seats, **kw):
        kw.setdefault("start", 2)
        return self.t.start(seats, **kw)


class TestPlaying:
    def test_the_first_pairing_starts_and_carries_the_tournament(self):
        s = Setup()
        tid = s.start(["a", "b", "c", "d"], legs_by_round=[1, 2])
        assert sorted(s.game.order) == ["a", "b"] and s.t.phase == "match"
        s.bull_off()
        assert s.db._conn.execute("SELECT tournament_id FROM matches").fetchone()[0] == tid
        assert s.t.snapshot()["current"] == {"round": 0, "index": 0}

    def test_a_won_match_waits_and_the_next_one_starts_by_itself(self):
        s = Setup()
        s.start(["a", "b", "c", "d"])
        s.win("b")
        snap = s.t.snapshot()
        assert snap["phase"] == "pending" and snap["pending"]["winner"] == "b" and snap["pending"]["next_in"] == 3
        assert snap["rounds"][0][0]["winner"] is None                  # not recorded yet
        FakeTimer.fire()
        FakeTimer.fire()
        assert s.t.snapshot()["pending"]["next_in"] == 1
        FakeTimer.fire()
        snap = s.t.snapshot()
        assert snap["phase"] == "match" and snap["rounds"][0][0]["winner"] == "b"
        assert snap["current"] == {"round": 0, "index": 1} and sorted(s.game.order) == ["c", "d"]

    def test_start_now_does_not_wait(self):
        s = Setup()
        s.start(["a", "b", "c", "d"])
        s.win("a")
        assert s.t.next()
        assert s.t.snapshot()["current"] == {"round": 0, "index": 1}

    def test_the_final_waits_for_the_owner_and_ends_the_tournament(self):
        s = Setup()
        s.start(["a", "b"])
        s.win("a")
        snap = s.t.snapshot()
        assert snap["phase"] == "pending" and snap["pending"]["next_in"] is None and not FakeTimer.created
        assert s.t.next()
        snap = s.t.snapshot()
        assert snap["phase"] == "finished" and snap["status"] == "finished" and snap["winner"] == "a"
        assert s.db.list_tournaments()[0]["status"] == "finished"
        assert s.db.list_tournaments()[0]["data"]["winner"] == "a"
        assert s.t.running is False and s.t.close()
        assert s.t.snapshot() == {"active": False}

    def test_a_whole_tournament_with_byes(self):
        s = Setup()
        s.start(["a", "b", "c", None])
        s.win("b")
        s.t.next()
        assert s.t.snapshot()["current"] == {"round": 1, "index": 0}
        assert sorted(s.game.order) == ["b", "c"]
        s.win("c")
        s.t.next()
        assert s.t.snapshot()["winner"] == "c"

    def test_the_legs_to_win_follow_the_round(self):
        s = Setup()
        s.start(["a", "b", "c", "d"], legs_by_round=[1, 2])
        assert s.game.legs == 1
        s.win("a")
        s.t.next()
        s.win("c")
        s.t.next()
        assert s.game.legs == 2 and s.game.snapshot()["rules"]["legs"] == 2
        s.win("a")
        assert s.t.snapshot()["pending"]["legs"] == {"a": 2, "c": 0}

    def test_the_result_can_be_undone_while_it_waits(self):
        s = Setup()
        s.start(["a", "b", "c", "d"])
        s.win("a")
        assert s.t.snapshot()["phase"] == "pending"
        assert s.game.undo()
        snap = s.t.snapshot()
        assert snap["phase"] == "match" and snap["pending"] is None and snap["current"] == {"round": 0, "index": 0}
        assert all(t.cancelled for t in FakeTimer.created)
        s.win("b")
        assert s.t.snapshot()["pending"]["winner"] == "b"

    def test_a_corrected_dart_that_changes_the_winner_is_taken_into_account(self):
        s = Setup()
        s.start(["a", "b"], start=40)
        s.bull_off()
        who = s.game.snapshot()["current_player"]
        play(s.game, hit(20, 2))
        assert s.t.snapshot()["pending"]["winner"] == who
        assert s.game.correct_last_dart(0, "S20")             # a single: a bust, the match is open again
        assert s.t.snapshot()["phase"] == "match"
        assert s.t.snapshot()["pending"] is None

    def test_no_second_tournament_while_one_runs(self):
        s = Setup()
        s.start(["a", "b"])
        with pytest.raises(ValueError, match="already running"):
            s.start(["c", "d"])

    @pytest.mark.parametrize("kw", [{"start": 1}, {"in_mode": "x"}, {"legs_by_round": [1, 1]}, {"legs_by_round": [0]}])
    def test_rules_that_cannot_be_played_are_refused(self, kw):
        s = Setup()
        with pytest.raises(ValueError):
            s.start(["a", "b"], **kw)
        assert not s.t.running


class TestBullOff:
    def test_with_a_bull_off_the_first_leg_starts_with_one(self):
        s = Setup()
        s.start(["a", "b"])
        assert s.game.phase == "bull_off" and s.game.bull_off

    def test_without_one_the_match_starts_at_once_with_a_drawn_order(self):
        s = Setup()
        s.start(["a", "b"], bull_off=False)
        assert s.game.phase == "playing" and not s.game.bull_off and sorted(s.game.order) == ["a", "b"]
        assert s.events[-1]["event"] == "match-started"
        assert s.t.snapshot()["config"]["bull_off"] is False

    def test_the_first_thrower_alternates_in_the_following_legs(self):
        s = Setup()
        s.start(["a", "b"], bull_off=False, legs_by_round=[2])
        first = s.game.snapshot()["current_player"]
        other = "b" if first == "a" else "a"
        play(s.game, hit(1, 2))                                          # the first thrower wins leg one
        assert s.game.snapshot()["leg"] == 2 and s.game.snapshot()["current_player"] == other

    def test_the_option_is_kept_for_every_match(self):
        s = Setup()
        s.start(["a", "b", "c", "d"], bull_off=False)
        s.win("a")
        s.t.next()
        assert s.game.phase == "playing" and not s.game.bull_off


class TestAbortAndRestart:
    def test_abort_ends_it_keeps_the_played_matches_and_discards_the_running_one(self):
        s = Setup()
        s.start(["a", "b", "c", "d"])
        s.win("a")
        s.t.next()
        assert s.t.abort()
        assert s.t.snapshot() == {"active": False} and s.x01.game is None
        row = s.db.list_tournaments()[0]
        assert row["status"] == "aborted" and row["ended_at"]
        assert row["data"]["bracket"]["rounds"][0][0]["winner"] == "a"
        assert s.db._conn.execute("SELECT COUNT(*) FROM matches WHERE tournament_id IS NOT NULL").fetchone()[0] == 1       # the one that was played
        assert s.db._conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0] > 0
        assert not s.t.abort()
        s.start(["x", "y"])                                    # a new one can start
        assert s.t.running

    def test_the_tournament_survives_a_restart_but_not_the_running_match(self, tmp_path):
        db = StatsDB(str(tmp_path / "t.db"))
        s = Setup(db=db)
        s.start(["a", "b", "c", "d"])
        s.win("b")
        s.t.next()                                             # a vs b is recorded, c vs d starts
        again = Setup(db=StatsDB(str(tmp_path / "t.db")))
        snap = again.t.snapshot()
        assert snap["active"] and snap["phase"] == "idle" and snap["current"] is None
        assert snap["rounds"][0][0]["winner"] == "b"
        assert snap["next"] == {"round": 0, "index": 1, "a": "c", "b": "d"}
        assert again.x01.game is None
        assert again.t.next() and sorted(again.game.order) == ["c", "d"]

    def test_a_finished_tournament_is_not_resumed(self, tmp_path):
        s = Setup(db=StatsDB(str(tmp_path / "t.db")))
        s.start(["a", "b"])
        s.win("a")
        s.t.next()
        assert Setup(db=StatsDB(str(tmp_path / "t.db"))).t.snapshot() == {"active": False}


def test_the_stats_see_the_matches_as_normal_x01_matches():
    s = Setup()
    s.start(["a", "b"])
    s.win("a")
    row = s.db._conn.execute("SELECT game_mode, winner, ended_at, tournament_id FROM matches").fetchone()
    assert (row["game_mode"], row["winner"]) == ("X01", "a") and row["ended_at"] and row["tournament_id"]
