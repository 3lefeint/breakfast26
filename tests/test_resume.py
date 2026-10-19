import pytest

from breakfast.elimination import EliminationController
from breakfast.killer import KillerController
from breakfast.mqtt_output import NullMqttPublisher
from breakfast.resume import ResumeOffers
from breakfast.state import GameState
from breakfast.stats import StatsDB, StatsTracker
from breakfast.tournament import TournamentController
from breakfast.x01_game import X01Controller
from tests.test_target_battle import MISS, hit, play


@pytest.fixture(autouse=True)
def no_start_delay(monkeypatch):
    monkeypatch.setattr("breakfast.x01_game.START_CALLS_DELAY_S", 0)
    monkeypatch.setattr("breakfast.killer.START_CALLS_DELAY_S", 0)


class Site:
    """The program with the games that can be resumed. `Site(path)` again is a restart on the same database."""

    def __init__(self, path):
        self.db = StatsDB(str(path))
        self.state = GameState()
        self.tracker = StatsTracker(self.db)
        self.x01 = X01Controller(self.emit, stats_db=self.db)
        self.elim = EliminationController(NullMqttPublisher(), "autodarts", stats_db=self.db)
        self.killer = KillerController(NullMqttPublisher(), "autodarts", stats_db=self.db)
        self.tournament = TournamentController(self.x01, stats_db=self.db)
        self.offers = ResumeOffers(self.db, {"X01": self.x01, "Elimination": self.elim, "Killer": self.killer},
                                   tournament=self.tournament, board_darts=self.state.board_darts)

    def emit(self, data):
        self.state.update(data)
        self.tracker.process(data)


@pytest.fixture
def path(tmp_path):
    return tmp_path / "stats.db"


def saved(site):
    return site.db.running_matches()


class TestX01:
    def start(self, site, **kw):
        site.x01.start(["ana", "bo"], start=101, bull_off=False, **kw)
        return site.x01.game

    def test_a_running_match_is_saved_and_offered_after_a_restart(self, path):
        site = Site(path)
        game = self.start(site)
        play(game, hit(20, 3), hit(20, 1), hit(1, 1))
        again = Site(path)
        assert again.offers.offers()[0]["mode"] == "X01"
        assert again.offers.offers()[0]["players"] == ["ana", "bo"]
        assert again.x01.game is None            # nothing resumes by itself

    def test_it_goes_on_where_the_turn_began_and_the_statistics_go_on_with_it(self, path):
        site = Site(path)
        game = self.start(site)
        first, second = game.order
        play(game, hit(20, 3), hit(20, 1), hit(1, 1))                  # first: 101 -> 20
        play(game, hit(20, 1), hit(20, 1), hit(20, 1))                  # second: 101 -> 41
        game.on_board_state(1, [hit(5, 1)])                             # first's turn in progress, lost
        again = Site(path)
        assert again.offers.resume("x01") is None
        resumed = again.x01.game
        assert resumed.match_id == game.match_id
        assert {p["name"]: p["remaining"] for p in resumed.snapshot()["players"]} == {first: 20, second: 41}
        assert resumed.current_player == first and resumed.snapshot()["current_darts"] == []
        play(resumed, hit(5, 1))                                        # a later turn is numbered on
        turns = again.db._conn.execute("SELECT player, turn FROM turns WHERE match_id = ? ORDER BY id",
                                       (game.match_id,)).fetchall()
        assert [(t["player"], t["turn"]) for t in turns] == [(first, 1), (second, 1), (first, 2)]
        assert again.db._conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 1
        assert again.state.match_started

    def test_a_match_that_is_over_or_cancelled_is_not_kept(self, path):
        site = Site(path)
        game = self.start(site)
        assert "X01" in saved(site)
        site.x01.stop()
        assert saved(site) == {}
        site.x01.start(["ana", "bo"], start=2, bull_off=False, in_mode="straight", out_mode="double")
        game = site.x01.game
        assert "X01" in saved(site)
        while game.state == "playing":
            play(game, hit(1, 2))
        assert saved(site) == {}

    def test_the_turn_in_progress_does_not_write_again(self, path):
        site = Site(path)
        game = self.start(site)
        before = saved(site)["X01"]["saved_at"]
        game.on_board_state(1, [hit(20, 3)])
        assert saved(site)["X01"]["saved_at"] == before

    def test_discard_removes_it(self, path):
        site = Site(path)
        self.start(site)
        again = Site(path)
        assert again.offers.discard("x01") is True
        assert again.offers.offers() == [] and saved(again) == {}
        assert Site(path).offers.offers() == []

    def test_a_new_game_replaces_the_offer(self, path):
        site = Site(path)
        self.start(site)
        again = Site(path)
        again.x01.start(["cy", "di"], start=101, bull_off=False)
        assert again.offers.offers() == []
        assert Site(path).offers.offers()[0]["players"] == ["cy", "di"]

    def test_it_is_refused_while_another_game_is_open(self, path):
        site = Site(path)
        self.start(site)
        again = Site(path)
        again.elim.start(["x", "y"], 3)
        assert "open" in again.offers.resume("x01")

    def test_darts_on_the_board_are_not_taken_for_new_ones(self, path):
        site = Site(path)
        self.start(site)
        again = Site(path)
        again.state.board_darts.update([hit(20, 3)])
        again.offers.resume("x01")
        game = again.x01.game
        game.on_board_state(1, [hit(20, 3)])
        assert game._current_darts == []
        game.on_board_state(0, [])
        game.on_board_state(1, [hit(5, 1)])
        assert game._current_darts == [5]


class TestElimination:
    def test_lives_target_and_player_are_kept(self, path):
        site = Site(path)
        site.elim.start(["ana", "bo", "cy"], 3)
        game = site.elim.game
        play(game, hit(20, 1), hit(20, 1), hit(20, 1))                  # ana: 60
        play(game, hit(1, 1), MISS, MISS)                               # bo cannot beat it: -1 life
        again = Site(path)
        assert again.offers.resume("elimination") is None
        resumed = again.elim.game
        assert resumed.match_id == game.match_id
        assert resumed.lives == game.lives and resumed.target == game.target == 1 and resumed.current_player == "cy"

    def test_an_online_match_is_not_saved(self, path):
        site = Site(path)
        site.elim.start_online(["ana", "bo"], 3, "m1", ["ana"], online=object())
        site.elim.game._changed()
        assert saved(site) == {}


class TestKiller:
    def test_numbers_and_lives_are_kept(self, path):
        site = Site(path)
        site.killer.start(["ana", "bo"], bull_off=False, throw_numbers=False)
        game = site.killer.game
        numbers, lives = dict(game.numbers), dict(game.lives)
        play(game, hit(numbers["ana"], 2), MISS, MISS)
        again = Site(path)
        assert again.offers.resume("killer") is None
        resumed = again.killer.game
        assert resumed.match_id == game.match_id
        assert resumed.numbers == numbers and resumed.lives == lives
        assert "ana" in resumed.killers and resumed.current_player == "bo"


class TestTournament:
    def start(self, site):
        site.tournament.start(["ana", "bo", "cy", "di"], start=2, bull_off=False)
        return site.x01.game

    def test_the_match_in_play_is_taken_over_again(self, path):
        site = Site(path)
        game = self.start(site)
        again = Site(path)
        offer = again.offers.offers()[0]
        assert offer["tournament"] is True
        assert again.offers.resume("x01") is None
        assert again.tournament.phase == "match" and again.tournament.current == (0, 0)
        assert again.x01.game.match_id == game.match_id

    def test_a_match_that_was_won_waits_for_its_result(self, path):
        site = Site(path)
        game = self.start(site)
        winner = game.current_player
        while game.state == "playing":
            play(game, hit(1, 2) if game.current_player == winner else MISS)
        assert "X01" in saved(site)            # the result is not taken over yet
        again = Site(path)
        assert again.offers.resume("x01") is None
        assert again.tournament.phase == "pending" and again.tournament.pending["winner"] == winner

    def test_next_clears_the_saved_match(self, path):
        site = Site(path)
        game = self.start(site)
        while game.state == "playing":
            play(game, hit(1, 2) if game.current_player == "ana" else MISS)
        site.tournament.next()
        assert saved(site)["X01"]["data"]["match_id"] != game.match_id     # the next match, not the won one

    def test_it_is_refused_when_the_tournament_is_gone(self, path):
        site = Site(path)
        self.start(site)
        site.tournament.abort()
        again = Site(path)
        assert again.offers.offers() == []
