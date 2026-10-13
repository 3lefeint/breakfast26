import random

import pytest

from breakfast import bot
from breakfast.dartboard import DOUBLE_OUT_MM, field_at, field_centers
from breakfast.elimination import EliminationController
from breakfast.killer import KillerController
from breakfast.stats import StatsDB
from tests.test_target_battle import FakeMqttPub, hit, play


def sync_bots(ctrl, seed=1):
    """Let the bots of a controller play at once, on the calling thread, without pauses."""
    ctrl.bots._spawn = lambda fn: fn()
    ctrl.bots._sleep = lambda seconds: None
    ctrl.bots._rng = random.Random(seed)
    return ctrl


def test_field_at_finds_the_field_of_every_field_center():
    for name, c in field_centers().items():
        if name != "0":
            assert field_at(c["x"] * DOUBLE_OUT_MM, c["y"] * DOUBLE_OUT_MM) == name
    assert field_at(0, 175) == "0"
    assert field_at(-60, 80) == "T12"


def test_the_scatter_of_every_level_gives_its_average():
    for level in bot.LEVELS:
        assert bot.average_for(bot.SCATTER_MM[level]) == pytest.approx(level, rel=0.04, abs=0.8)


def test_a_thrown_dart_is_shaped_like_a_dart_of_the_board():
    dart = bot.Thrower(110, random.Random(3)).throw("T20")
    assert set(dart) == {"segment", "coords"}
    assert set(dart["segment"]) == {"name", "number", "multiplier"}
    assert -1.4 <= dart["coords"]["x"] <= 1.4 and -1.4 <= dart["coords"]["y"] <= 1.4


def test_a_dart_far_off_the_board_is_a_miss_and_drawn_near_it():
    thrower = bot.Thrower(10, random.Random(1))
    darts = [thrower.throw("T20") for _ in range(200)]
    misses = [d for d in darts if d["segment"]["multiplier"] == 0]
    assert misses
    assert all((d["coords"]["x"] ** 2 + d["coords"]["y"] ** 2) ** 0.5 <= 1.31 for d in misses)


def test_the_same_seed_throws_the_same_darts():
    a = [bot.Thrower(60, random.Random(5)).throw("T19") for _ in range(3)]
    b = [bot.Thrower(60, random.Random(5)).throw("T19") for _ in range(3)]
    assert a == b


def test_an_unknown_level_is_refused():
    with pytest.raises(ValueError):
        bot.Thrower(15)


# ── what a bot aims at ───────────────────────────────────────────────────────

class FakeElimGame:
    def __init__(self, target, freipass, darts):
        self.target, self.freipass, self._current_darts = target, freipass, darts


def test_elimination_aims_at_the_triple_20_unless_one_safe_dart_will_do():
    rng = random.Random(1)
    assert bot.aim_elimination(FakeElimGame(90, False, []), "x", rng) == "T20"
    assert bot.aim_elimination(FakeElimGame(90, False, [60, 15]), "x", rng) == "S20"
    assert bot.aim_elimination(FakeElimGame(90, False, [60, 40]), "x", rng) == "S20"
    assert bot.aim_elimination(FakeElimGame(0, True, []), "x", rng) == "S20"


class FakeKillerGame:
    def __init__(self, phase="playing", numbers=None, killers=(), lives=None, singles=False):
        self.phase, self.singles = phase, singles
        self.numbers = numbers or {"bot": 7, "ana": 12, "bo": 3}
        self.killers = set(killers)
        self.lives = lives or {p: 3 for p in self.numbers}

    @property
    def active(self):
        return [p for p in self.numbers if self.lives[p] > 0]


def test_killer_aims_at_the_bull_then_at_a_free_number():
    rng = random.Random(1)
    assert bot.aim_killer(FakeKillerGame("bull_off"), "bot", rng) == "50"
    taken = {"ana": 20, "bo": 19}
    aims = {bot.aim_killer(FakeKillerGame("numbers", taken), "bot", random.Random(s)) for s in range(40)}
    assert aims and all(a[0] == "D" and int(a[1:]) not in (20, 19) for a in aims)


def test_killer_aims_at_the_own_double_until_it_is_a_killer():
    assert bot.aim_killer(FakeKillerGame(), "bot", random.Random(1)) == "D7"


def test_a_killer_bot_aims_at_the_most_dangerous_opponent():
    game = FakeKillerGame(killers={"bot", "bo"}, lives={"bot": 3, "ana": 3, "bo": 2})
    assert bot.aim_killer(game, "bot", random.Random(1)) == "D3"        # a killer beats more lives
    game = FakeKillerGame(killers={"bot"}, lives={"bot": 3, "ana": 1, "bo": 3})
    assert bot.aim_killer(game, "bot", random.Random(1)) == "D3"        # nobody is a killer: most lives
    game = FakeKillerGame(killers={"bot", "ana", "bo"}, lives={"bot": 3, "ana": 2, "bo": 2}, singles=True)
    assert bot.aim_killer(game, "bot", random.Random(1)) in ("S12", "S3")


# ── playing a turn ───────────────────────────────────────────────────────────

def test_a_bot_that_is_up_plays_its_turn_and_hands_over(db):
    ctrl = sync_bots(EliminationController(FakeMqttPub(), "autodarts", stats_db=db))
    ctrl.start(["bot", "ana"], 3, bots={"bot": 110})
    game = ctrl.game
    assert game.current_player == "ana"          # the bot threw its three darts and the turn moved on
    assert game.target > 0 and not game.freipass
    assert len(game._history) == 1


def test_a_bot_waits_for_the_board_to_be_clear(db):
    ctrl = sync_bots(EliminationController(FakeMqttPub(), "autodarts", stats_db=db))
    ctrl.start(["ana", "bot"], 3, bots={"bot": 110})
    ctrl.on_board_state(1, [hit(20, 3)])          # ana throws, the darts stay on the board
    ctrl.on_board_state(2, [hit(20, 3), hit(5, 1)])
    assert ctrl.game.current_player == "ana"
    ctrl.on_board_state(0, [])                    # ana pulls: the board is clear, the bot is up
    assert ctrl.game.current_player == "ana" or ctrl.game._history[-1]["player"] == "bot"
    assert len(ctrl.game._history) == 2


def test_the_real_board_is_ignored_while_a_bot_throws(db):
    ctrl = EliminationController(FakeMqttPub(), "autodarts", stats_db=db)
    ctrl.start(["ana", "bo"], 3)
    ctrl.bots.playing = True
    ctrl.on_board_state(1, [hit(20, 3)])
    assert ctrl.game._current_darts == []
    ctrl.bots.playing = False
    ctrl.on_board_state(1, [hit(20, 3)])
    assert ctrl.game._current_darts == [60]


def test_a_bot_does_not_play_in_another_game_after_a_stop(db):
    ctrl = sync_bots(EliminationController(FakeMqttPub(), "autodarts", stats_db=db))
    ctrl.start(["ana", "bot"], 3, bots={"bot": 60})
    ctrl.stop()
    assert ctrl.bots.levels == {} and ctrl.game is None


def test_a_bot_plays_a_whole_elimination_match_against_a_human(db):
    ctrl = sync_bots(EliminationController(FakeMqttPub(), "autodarts", stats_db=db))
    ctrl.start(["ana", "bot"], 1, bots={"bot": 60})
    for _ in range(60):
        if ctrl.game.state == "finished":
            break
        ctrl.on_board_state(1, [hit(1, 1)])       # ana scores 1 and pulls
        ctrl.on_board_state(0, [])
    assert ctrl.game.state == "finished"
    match = db._conn.execute("SELECT has_bot, winner, players FROM matches").fetchone()
    assert match["has_bot"] == 1
    assert "bot" not in (match["players"] or "")
    assert match["winner"] in (None, "ana")
    assert not db._conn.execute("SELECT 1 FROM elimination_turns WHERE player = 'bot'").fetchall()
    assert not db._conn.execute("SELECT 1 FROM elimination_results WHERE player = 'bot'").fetchall()
    assert [r["name"] for r in db._conn.execute("SELECT name FROM players")] == ["ana"]


def test_a_bot_plays_the_bull_off_and_the_numbers_in_killer(db):
    ctrl = sync_bots(KillerController(FakeMqttPub(), "autodarts", stats_db=db))
    ctrl.start(["bot", "ana"], bots={"bot": 110})
    game = ctrl.game
    assert game.phase == "bull_off" and game.current_player == "ana"      # the bot's bull-off dart counted
    ctrl.on_board_state(1, [hit(25, 2, 0.5, 0.5)])
    ctrl.on_board_state(0, [])
    assert game.phase == "numbers"
    for _ in range(40):
        if game.phase == "playing":
            break
        if game.current_player == "ana":
            free = next(n for n in range(1, 21) if n not in game.numbers.values())
            ctrl.on_board_state(1, [hit(free, 1)])
            ctrl.on_board_state(0, [])
    assert game.phase == "playing"
    assert set(game.numbers) == {"bot", "ana"}


def test_a_killer_match_with_a_bot_keeps_the_bot_out_of_the_stats(db):
    ctrl = sync_bots(KillerController(FakeMqttPub(), "autodarts", stats_db=db))
    ctrl.start(["ana", "bot"], bull_off=False, throw_numbers=False, bots={"bot": 100})
    game = ctrl.game
    for _ in range(300):
        if game.state == "finished":
            break
        if game.current_player == "ana":
            target = game.numbers["bot"] if "ana" in game.killers else game.numbers["ana"]
            ctrl.on_board_state(1, [hit(target, 2)])
            ctrl.on_board_state(0, [])
    assert game.state == "finished"
    assert db._conn.execute("SELECT has_bot FROM matches").fetchone()["has_bot"] == 1
    assert not db._conn.execute("SELECT 1 FROM killer_turns WHERE player = 'bot'").fetchall()
    assert not db._conn.execute("SELECT 1 FROM killer_results WHERE player = 'bot'").fetchall()
    assert [r["name"] for r in db._conn.execute("SELECT name FROM players")] == ["ana"]


def test_a_match_without_bots_is_not_marked(db):
    ctrl = EliminationController(FakeMqttPub(), "autodarts", stats_db=db)
    ctrl.start(["ana", "bo"], 3)
    assert db._conn.execute("SELECT has_bot FROM matches").fetchone()["has_bot"] == 0


def test_a_database_without_the_column_is_migrated(tmp_path):
    import sqlite3
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE matches (match_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, ended_at TEXT,"
                 " game_mode TEXT, points_start INTEGER, players TEXT, winner TEXT)")
    conn.execute("INSERT INTO matches (match_id, started_at) VALUES ('m', 'now')")
    conn.commit()
    conn.close()
    migrated = StatsDB(path)
    assert migrated._conn.execute("SELECT has_bot FROM matches").fetchone()["has_bot"] == 0
