import random

import pytest

from breakfast import bot, x01_game
from breakfast.stats import StatsDB, StatsTracker
from breakfast.x01_game import X01Controller
from tests.test_bot import sync_bots
from tests.test_target_battle import MISS, hit


@pytest.fixture
def db():
    return StatsDB(":memory:")


@pytest.fixture(autouse=True)
def no_start_delay(monkeypatch):
    monkeypatch.setattr(x01_game, "START_CALLS_DELAY_S", 0)


def controller(db, seed=1):
    return sync_bots(X01Controller(StatsTracker(db).process, stats_db=db), seed)


# ── what a bot aims at ───────────────────────────────────────────────────────

@pytest.mark.parametrize("rem, darts, out, aim", [
    (501, 3, "double", "T20"),
    (200, 3, "double", "T20"),
    (170, 3, "double", "T20"),
    (110, 2, "double", "T20"),
    (100, 3, "double", "T20"),
    (40, 1, "double", "D20"),
    (50, 1, "double", "50"),
    (32, 3, "double", "D16"),
    (60, 3, "double", "S20"),
    (60, 1, "straight", "T20"),
    (60, 1, "master", "T20"),
    (20, 3, "straight", "S20"),
])
def test_a_bot_follows_the_checkout_chart_once_it_can_finish(rem, darts, out, aim):
    assert bot.x01_target(rem, darts, True, "straight", out) == aim


def test_a_bot_that_cannot_finish_leaves_a_rest_for_a_double():
    assert bot.x01_target(41, 1, True, "straight", "double") == "S9"        # 32
    assert bot.x01_target(21, 1, True, "straight", "double") == "S5"        # not 1, which no double finishes


@pytest.mark.parametrize("out", ["double", "master"])
@pytest.mark.parametrize("rem", range(2, 200))
@pytest.mark.parametrize("darts", [1, 2, 3])
def test_a_bot_never_aims_at_a_dart_that_busts(rem, darts, out):
    field = bot.x01_target(rem, darts, True, "straight", out)
    value = bot.cr.points(field)
    route = bot.finish_route(rem, darts, out)
    if route:
        assert field == route[0] and sum(bot.cr.points(f) for f in route) == rem and bot._out_ok(out, route[-1])
    else:
        assert rem - value >= 2


def test_a_bot_with_a_straight_out_finishes_on_any_dart():
    route = bot.finish_route(37, 2, "straight")
    assert len(route) == 2 and sum(bot.cr.points(f) for f in route) == 37
    assert bot.finish_route(19, 1, "straight") == ("S19",)


def test_a_bot_with_a_double_in_looks_for_a_double_that_does_not_bust():
    assert bot.x01_target(501, 3, False, "double", "double") == "D20"
    assert bot.x01_target(501, 3, False, "master", "double") == "T20"
    assert bot.x01_target(30, 3, False, "double", "double") == "D15"


def test_a_bot_throws_at_the_bull_in_a_bull_off(db):
    ctrl = controller(db)
    ctrl.start(["ana", "bot"], bull_off=True, bots={"bot": 5})
    assert bot.aim_x01(ctrl.game, "bot", random.Random(1)) == "50"
    assert bot.darts_x01(ctrl.game) == 1


# ── playing ──────────────────────────────────────────────────────────────────

def play_out(ctrl, db, limit=400, throw=hit(1, 1)):
    """The human throws one dart a turn (a single 1 unless told otherwise) until the match is over."""
    for _ in range(limit):
        if ctrl.game.state == "finished":
            return
        if ctrl.game.current_player == "ana":
            ctrl.on_board_state(1, [throw])
            ctrl.on_board_state(0, [])
    raise AssertionError("the match did not end")


def test_a_bot_plays_the_bull_off_and_a_match_against_a_human(db):
    ctrl = controller(db)
    ctrl.start(["ana", "bot"], start=101, bull_off=True, bots={"bot": 5})
    game = ctrl.game
    while game.phase == "bull_off":
        assert game.current_player == "ana"
        ctrl.on_board_state(1, [hit(25, 2, 0.5, 0.5)])
        ctrl.on_board_state(0, [])
    play_out(ctrl, db)
    assert game.winner == "bot"


def test_a_match_with_a_bot_keeps_the_bot_out_of_the_stats(db):
    ctrl = controller(db)
    ctrl.start(["ana", "bot"], start=301, bull_off=False, bots={"bot": 5})
    play_out(ctrl, db)
    match = db._conn.execute("SELECT has_bot, winner, players FROM matches").fetchone()
    assert match["has_bot"] == 1 and match["winner"] is None
    assert not db._conn.execute("SELECT 1 FROM turns WHERE player = 'bot'").fetchall()
    assert db._conn.execute("SELECT COUNT(*) FROM turns WHERE player = 'ana'").fetchone()[0] > 0
    assert [r["name"] for r in db._conn.execute("SELECT name FROM players")] == ["ana"]
    assert [r["winner"] for r in db._conn.execute("SELECT winner FROM legs")] == [None]


def test_the_events_of_a_bot_say_so(db):
    events = []
    ctrl = sync_bots(X01Controller(events.append, stats_db=db))
    ctrl.start(["ana", "bot"], start=101, bull_off=False, bots={"bot": 5})
    assert all(e["playerIsBot"] == str(e["player"] == "bot") for e in events if e.get("player"))
    assert [e["game"]["bots"] for e in events if e["event"] == "match-started"] == [["bot"]]
    assert {p["name"]: p["bot"] for p in ctrl.game.snapshot()["players"]} == {"ana": None, "bot": 5}


def test_a_bot_stops_after_a_bust_and_after_a_finish(db):
    ctrl = controller(db)
    ctrl.start(["ana", "bot"], start=40, in_mode="straight", out_mode="double", bull_off=False, bots={"bot": 3})
    thrown = []
    original = ctrl.game.on_board_state

    def watch(count, throws):
        thrown.append(count)
        original(count, throws)
    ctrl.game.on_board_state = watch
    play_out(ctrl, db, throw=MISS)
    assert ctrl.game.winner == "bot" and thrown
    # a turn never goes on after a bust or a checkout: the counts of a turn rise by one up to the end of it
    for a, b in zip(thrown, thrown[1:]):
        assert b in (a + 1, 0) or a == 0
    assert any(b == 0 and a < 3 for a, b in zip(thrown, thrown[1:]))        # a turn that ended early


def test_undoing_a_bot_turn_takes_nothing_of_the_human_out(db):
    ctrl = controller(db)
    ctrl.start(["ana", "bot"], start=501, bull_off=False, bots={"bot": 3})
    game = ctrl.game
    ctrl.on_board_state(1, [hit(20, 3)])
    ctrl.on_board_state(0, [])          # ana's turn, then the bot's
    assert db._conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 1
    ctrl.bots._spawn = lambda fn: None  # the bot would throw again at once
    with ctrl._lock:
        assert game.undo()              # the bot's turn goes
    assert db._conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 1
    with ctrl._lock:
        assert game.undo()              # now ana's
    assert db._conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 0


def test_undoing_the_checkout_of_a_bot_takes_its_leg_back(db):
    ctrl = controller(db)
    ctrl.start(["ana", "bot"], start=40, legs=2, bull_off=False, bots={"bot": 5})
    game = ctrl.game
    for _ in range(200):
        if game.legs_won["bot"] >= 1:
            break
        if game.current_player == "ana":
            ctrl.on_board_state(1, [MISS])
            ctrl.on_board_state(0, [])
    assert game.legs_won["bot"] == 1
    assert db._conn.execute("SELECT COUNT(*) FROM legs").fetchone()[0] == 1
    first_leg = db._conn.execute("SELECT COUNT(*) FROM turns WHERE leg = 1").fetchone()[0]
    ctrl.bots._spawn = lambda fn: None  # the bot would throw again at once
    while game.legs_won["bot"]:
        with ctrl._lock:
            assert game.undo()
    assert db._conn.execute("SELECT COUNT(*) FROM legs").fetchone()[0] == 0
    assert db._conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == first_leg


def test_the_darts_of_a_bot_are_shown_while_it_throws_and_cleared_after(db):
    shown = []
    ctrl = controller(db)
    ctrl.bots.on_darts = shown.append
    ctrl.start(["ana", "bot"], start=501, bull_off=False, bots={"bot": 3})
    ctrl.on_board_state(1, [hit(20, 3)])
    ctrl.on_board_state(0, [])
    counts = [len(s) for s in shown]
    assert counts[:3] == [1, 2, 3] or counts[-4:] == [1, 2, 3, 0]
    assert counts[-1] == 0 and all("coords" in d for s in shown for d in s)


def test_a_bot_has_live_stats_but_none_in_the_database(db):
    tracker = StatsTracker(db)
    ctrl = sync_bots(X01Controller(tracker.process, stats_db=db))
    ctrl.start(["ana", "bot"], start=501, bull_off=False, bots={"bot": 3})
    ctrl.on_board_state(1, [hit(20, 3)])
    ctrl.on_board_state(0, [])
    stats = tracker.computed_session_stats()
    bot_turns = stats["bot"]["turns"]          # one or two, depending on who started
    assert bot_turns >= 1 and stats["bot"]["avg3"] > 0 and stats["ana"]["turns"] == 1
    ctrl.bots._spawn = lambda fn: None
    with ctrl._lock:
        assert ctrl.game.undo()
    after = tracker.computed_session_stats()
    assert after.get("bot", {"turns": 0})["turns"] == bot_turns - 1 and after["ana"]["turns"] == 1
    assert not db._conn.execute("SELECT 1 FROM turns WHERE player = 'bot'").fetchall()


def test_the_darts_of_a_bot_show_without_a_board_stream():
    from breakfast.board_darts import BoardDarts
    darts = BoardDarts()
    assert darts.snapshot() is None
    assert darts.update([hit(20, 3)], bot=True) and len(darts.snapshot()) == 1
    darts.update([], bot=True)
    assert darts.snapshot() is None


# ── the five stages ──────────────────────────────────────────────────────────

STAGE_TARGETS = {       # darts on the board, T20, the number 20, 3-dart average when aiming at T20 all the time
    1: ((88, 93), (1, 4), (20, 30), (31, 39)),
    2: ((97, 100), (3, 7), (36, 48), (38, 47)),
    3: ((99, 100), (7, 12), (50, 64), (47, 57)),
    4: ((99.5, 100), (15, 23), (72, 84), (66, 80)),
    5: ((99.5, 100), (27, 37), (88, 97), (88, 101)),
}


@pytest.mark.parametrize("stage", bot.X01_LEVELS)
def test_a_stage_throws_like_its_precision_test(stage):
    thrower = bot.Thrower(stage, random.Random(7), bot.X01_SCATTER_MM)
    darts = [thrower.throw("T20") for _ in range(20000)]
    share = lambda test: 100 * sum(1 for d in darts if test(d)) / len(darts)
    board, t20, number, average = STAGE_TARGETS[stage]
    assert board[0] <= share(lambda d: d["segment"]["multiplier"] > 0) <= board[1]
    assert t20[0] <= share(lambda d: d["segment"]["name"] == "T20") <= t20[1]
    assert number[0] <= share(lambda d: d["segment"]["number"] == 20) <= number[1]
    assert average[0] <= 3 * sum(bot.dart_value(d) for d in darts) / len(darts) <= average[1]


def test_the_stages_get_stronger_and_use_their_own_table(db):
    assert bot.X01_LEVELS == (1, 2, 3, 4, 5)
    assert list(bot.X01_SCATTER_MM.values()) == sorted(bot.X01_SCATTER_MM.values(), reverse=True)
    ctrl = controller(db)
    ctrl.start(["ana", "bot"], bull_off=False, bots={"bot": 5})
    assert ctrl.bots._scatter is bot.X01_SCATTER_MM
    with pytest.raises(ValueError):
        bot.Thrower(60, random.Random(1), bot.X01_SCATTER_MM)
