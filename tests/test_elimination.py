import contextlib

from breakfast import elimination
from breakfast.elimination import EliminationController, EliminationGame
from breakfast.turn_game import dart_value, parse_field
from breakfast.mqtt_output import NullMqttPublisher
from breakfast.stats import StatsDB


def _throw(number, multiplier):
    return {"segment": {"number": number, "multiplier": multiplier}}


class FakeTimer:
    """Captures the target instead of actually waiting, so tests don't sleep
    for real and can fire the callback deterministically."""
    created = []

    def __init__(self, interval, function, args=None, kwargs=None):
        FakeTimer.created.append((interval, function))
        self.function = function

    def start(self):
        pass


class FakeAudio:
    def __init__(self, missing=()):
        """*missing*: names that simulate "no recording" (play() returns
        False) — e.g. to test the unknown_player fallback."""
        self.played = []
        self.missing = set(missing)

    def play(self, name, **kwargs):
        self.played.append(name)
        return name not in self.missing

    def play_sequence(self, *names):
        for name in names:
            self.play(name)

    def batch(self):
        # No-op: this double records every play() call in real time
        # regardless of batching, so callers using `with audio.batch():`
        # need no special handling here.
        return contextlib.nullcontext()


class FakeMqttClient:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload, retain=False):
        self.published.append((topic, payload, retain))


class FakeMqttPub:
    def __init__(self):
        self.client = FakeMqttClient()

    def subscribe(self, topic, callback):
        pass


def make_controller(on_change=None):
    return EliminationController(FakeMqttPub(), "autodarts", on_change=on_change)


def test_game_is_assigned_before_on_change_fires():
    # Regression test: on_change (the WS push) used to fire while
    # controller.game was still None, since the assignment only completes
    # after EliminationGame.__init__() returns.
    seen = []
    ctrl = make_controller(on_change=lambda: seen.append(ctrl.game))

    ctrl.start(["alice", "bob"], 3)

    assert seen, "on_change was never called"
    assert seen[0] is not None
    assert seen[0] is ctrl.game
    assert seen[0].state == "playing"


class TestWithoutMqtt:
    """Elimination must run fully with no MQTT broker configured at
    all — MqttPublisher's no-op stand-in, not a hand-rolled test fake."""

    def test_full_game_runs_against_null_mqtt_publisher(self):
        ctrl = EliminationController(NullMqttPublisher(), "autodarts")

        ctrl.start(["alice", "bob"], 1)
        assert ctrl.active
        assert ctrl.game.current_player == "alice"

        ctrl.on_board_state(3, [_throw(20, 3)] * 3)   # alice scores 60, passes
        ctrl.game._end_turn()
        ctrl.on_board_state(3, [_throw(1, 0)] * 3)    # bob scores 0, eliminated
        ctrl.game._end_turn()

        assert ctrl.game.state == "finished"
        assert ctrl.game.winner == "alice"

    def test_stop_does_not_raise(self):
        ctrl = EliminationController(NullMqttPublisher(), "autodarts")
        ctrl.start(["alice", "bob"], 3)
        ctrl.stop()
        assert ctrl.game is None


def test_start_publishes_state_and_calls_once():
    calls = []
    ctrl = make_controller(on_change=lambda: calls.append(1))

    ctrl.start(["alice", "bob"], 3)

    assert len(calls) == 1
    assert ctrl.active
    assert ctrl.game.current_player == "alice"


def test_announce_start_delays_opening_calls_past_the_redirect_window(monkeypatch):
    # elimStart()/startRematch() redirect the browser to /tv right after this
    # POST completes; the opening calls must not fire until that new page has
    # had time to load and reconnect with role=audio, or they're lost for good.
    FakeTimer.created = []
    monkeypatch.setattr(elimination.threading, "Timer", FakeTimer)
    audio = FakeAudio()

    game = EliminationGame(["alice", "bob"], 3, FakeMqttClient(), "autodarts", audio=audio)
    game.announce_start()

    assert audio.played == [], "opening calls must not fire synchronously"
    assert len(FakeTimer.created) == 1
    interval, callback = FakeTimer.created[0]
    assert interval == elimination._START_ANNOUNCE_AUDIO_DELAY_S

    callback()  # simulate the timer firing once the redirect window has passed
    assert audio.played == ["matchon", "alice", "filler_after_name"]


def test_elimination_order_tracked_and_win_recorded():
    db = StatsDB(":memory:")
    game = EliminationGame(
        ["alice", "bob", "carol"], 1, FakeMqttClient(), "autodarts",
        stats_db=db,
    )

    game._apply_turn(game.current_player, 10, silent=True)  # alice passes (freipass)
    game._apply_turn(game.current_player, 5, silent=True)   # bob fails -> eliminated
    game._apply_turn(game.current_player, 8, silent=True)   # carol passes (freipass)
    game._apply_turn(game.current_player, 3, silent=True)   # alice fails -> carol wins

    assert game.state == "finished"
    assert game.winner == "carol"
    assert game.elimination_order == ["bob", "alice"]
    assert db.win_counts() == {"carol": 1}

    row = db._conn.execute(
        "SELECT winner FROM matches WHERE match_id=?", (game.match_id,)
    ).fetchone()
    assert row["winner"] == "carol"


def test_on_board_state_pushes_immediately_per_dart():
    calls = []
    game = EliminationGame(
        ["alice", "bob"], 3, FakeMqttClient(), "autodarts",
        on_change=lambda: calls.append(1),
    )

    throw = {"segment": {"number": 20, "multiplier": 3}}  # T20 = 60
    game.on_board_state(1, [throw])

    assert calls, "on_change must fire as soon as a dart is detected, not only once darts are pulled"
    assert game._current_darts == [60]


def test_current_darts_reset_once_darts_are_pulled():
    game = EliminationGame(["alice", "bob"], 3, FakeMqttClient(), "autodarts")

    t20 = {"segment": {"number": 20, "multiplier": 3}}
    game.on_board_state(1, [t20])
    assert game._current_darts == [60]

    game.on_board_state(0, [])  # darts pulled -> turn ends

    assert game._current_darts == [], \
        "current_darts must clear once darts are pulled, not linger until the next player's first dart"
    # the just-finished turn's darts must still be available for the
    # "last turn" / correction flow
    assert [dart_value(t) for t in game._last_throws] == [60]


def test_snapshot_turn_order_rotates_current_first_and_hides_eliminated():
    game = EliminationGame(["alice", "bob", "carol"], 1, FakeMqttClient(), "autodarts")

    game._apply_turn(game.current_player, 10, silent=True)  # alice passes (freipass)
    game._apply_turn(game.current_player, 5, silent=True)   # bob fails -> eliminated

    snap = game.snapshot()
    assert [p["name"] for p in snap["turn_order"]] == ["carol", "alice"]
    assert snap["turn_order"][0]["current"] is True
    assert snap["turn_order"][1]["current"] is False
    # bob is eliminated and must not appear in turn_order at all
    assert all(p["name"] != "bob" for p in snap["turn_order"])
    # but is still present (dimmed) in the full roster used elsewhere
    assert any(p["name"] == "bob" for p in snap["players"])


def testparse_field():
    assert parse_field("T20") == _throw(20, 3)
    assert parse_field("D16") == _throw(16, 2)
    assert parse_field("S5") == _throw(5, 1)
    assert parse_field("25") == _throw(25, 1)
    assert parse_field("50") == _throw(25, 2)
    assert parse_field("0") == _throw(0, 0)


def test_correct_current_dart_affects_final_score():
    # A correction must change what actually gets scored at
    # turn-end, not just the display list.
    game = EliminationGame(["alice", "bob"], 3, FakeMqttClient(), "autodarts")

    game.on_board_state(1, [_throw(20, 3)])                    # D1 = T20 = 60
    game.on_board_state(2, [_throw(20, 3), _throw(20, 3)])     # D2 = T20 = 60

    game.correct_current_dart(1, "S1")  # correct D2 (0-based index 1) to S1 = 1
    assert game._current_darts == [60, 1]

    game.on_board_state(0, [])  # pull -> end turn
    assert game.target == 61, "corrected value must be what's scored, not the original 120"


def test_correct_current_dart_survives_next_board_event():
    # Core complication: on_board_state() rebuilds _current_darts
    # from scratch on every board event — a correction must be re-asserted
    # on top, or the next dart landing silently reverts it.
    game = EliminationGame(["alice", "bob"], 3, FakeMqttClient(), "autodarts")

    game.on_board_state(1, [_throw(20, 3)])  # D1 = T20 = 60
    game.correct_current_dart(0, "S1")       # correct D1 to S1 = 1
    assert game._current_darts == [1]

    # D2 lands on the real board; the board's own read still thinks D1=T20
    game.on_board_state(2, [_throw(20, 3), _throw(5, 1)])

    assert game._current_darts == [1, 5], "D1's correction must survive D2 landing"


def test_correct_current_dart_noop_when_not_playing():
    game = EliminationGame(["alice", "bob"], 1, FakeMqttClient(), "autodarts")
    game._apply_turn(game.current_player, 10, silent=True)  # alice passes (freipass)
    game._apply_turn(game.current_player, 0, silent=True)   # bob fails -> alice wins

    assert game.state == "finished"
    game.correct_current_dart(0, "T20")
    assert game._current_darts == [], "correction must be ignored once the game isn't playing"


def test_dart_overrides_reset_between_turns():
    game = EliminationGame(["alice", "bob"], 3, FakeMqttClient(), "autodarts")

    game.on_board_state(1, [_throw(20, 3)])
    game.correct_current_dart(0, "S1")  # correct alice's D1
    game.on_board_state(0, [])          # pull -> ends alice's turn, advances to bob

    # bob's fresh D1 must not be silently overridden by alice's stale correction
    game.on_board_state(1, [_throw(20, 3)])
    assert game._current_darts == [60]


class TestAudioOrderCR007:
    """Elimination audio call order redesign — see
    ELIMINATION_AUDIO_ORDER.md for the full case-by-case decisions this
    codifies."""

    def test_preview_plays_life_lost_without_the_name_when_not_fatal(self):
        audio = FakeAudio()
        game = EliminationGame(["alice", "bob"], 3, FakeMqttClient(), "autodarts", audio=audio)
        game.freipass = False
        game.target = 100
        game._current_darts = [10, 10, 10]  # score 30, fails, still has lives left

        game._publish_turn_preview()

        assert audio.played == ["30", "life_lost"]

    def test_preview_announces_name_then_eliminated_when_match_continues(self):
        audio = FakeAudio()
        game = EliminationGame(["alice", "bob", "carol"], 1, FakeMqttClient(), "autodarts", audio=audio)
        game.freipass = False
        game.target = 100
        game._current_darts = [0, 0, 0]  # score 0, only life -> eliminated, 3 active -> not match over

        game._publish_turn_preview()

        # "too_low" also fires per Case 5 (unchanged, score < 5) — the name
        # insertion (Case 4) only changes what precedes "eliminated" itself.
        assert audio.played == ["0", "alice", "eliminated", "too_low"]

    def test_preview_finishes_match_immediately_skipping_eliminated_cue(self):
        audio = FakeAudio()
        game = EliminationGame(["alice", "bob"], 1, FakeMqttClient(), "autodarts", audio=audio)
        game.freipass = False
        game.target = 100
        game._current_darts = [0, 0, 0]  # score 0, only life -> eliminated, 2 active -> match over

        game._publish_turn_preview()

        # Timing fix: the match finishes right here, in the preview —
        # before darts are even pulled — skipping the name+eliminated
        # cue (Case 8) and going straight to the winner announcement.
        assert audio.played == ["0", "bob", "matchshot"]
        assert game.state == "finished"
        assert game.winner == "bob"

    def test_nice_threshold_is_double_the_target(self):
        audio = FakeAudio()
        game = EliminationGame(["alice", "bob"], 3, FakeMqttClient(), "autodarts", audio=audio)
        game.freipass = False
        game.target = 40
        game._current_darts = [30, 30, 20]  # score 80 == 2x target

        game._publish_turn_preview()

        assert "nice" in audio.played

    def test_nice_does_not_fire_for_high_absolute_score_below_double_target(self):
        # Regresses the old >=100 rule: 110 would have triggered "nice" before,
        # but is below 2x this turn's target (120) under the new rule.
        audio = FakeAudio()
        game = EliminationGame(["alice", "bob"], 3, FakeMqttClient(), "autodarts", audio=audio)
        game.freipass = False
        game.target = 60
        game._current_darts = [40, 40, 30]  # score 110, passes but < 2x target

        game._publish_turn_preview()

        assert "nice" not in audio.played

    def test_apply_turn_fallback_plays_life_lost_without_the_name(self):
        audio = FakeAudio()
        game = EliminationGame(["alice", "bob", "carol"], 3, FakeMqttClient(), "autodarts", audio=audio)

        game._apply_turn(game.current_player, 0)  # alice fails, still has lives left

        assert audio.played[0] == "life_lost"

    def test_apply_turn_fallback_announces_name_before_eliminated_when_not_match_over(self):
        audio = FakeAudio()
        game = EliminationGame(["alice", "bob", "carol"], 1, FakeMqttClient(), "autodarts", audio=audio)

        game._apply_turn(game.current_player, 0)  # alice fails, only life, 3 active -> not match over

        assert audio.played[:2] == ["alice", "eliminated"]

    def test_apply_turn_fallback_skips_eliminated_and_announces_winner_when_match_ends(self):
        audio = FakeAudio()
        game = EliminationGame(["alice", "bob"], 1, FakeMqttClient(), "autodarts", audio=audio)

        game._apply_turn(game.current_player, 0)  # alice fails, only life, 2 active -> bob wins

        assert game.state == "finished"
        assert game.winner == "bob"
        assert audio.played == ["bob", "matchshot"], \
            "match-ending turn must skip the loser's eliminated cue and announce winner name before matchshot"

    def test_match_ending_turn_skips_fail_cue_and_announces_winner_first(self):
        # Full end-to-end path through on_board_state()/_publish_turn_preview(),
        # not just direct _apply_turn() calls.
        audio = FakeAudio()
        game = EliminationGame(["alice", "bob"], 1, FakeMqttClient(), "autodarts", audio=audio)

        game.on_board_state(3, [_throw(20, 3)] * 3)  # alice: 180, passes via freipass
        game.on_board_state(0, [])                    # darts pulled -> advances to bob
        audio.played = []

        game.on_board_state(3, [_throw(1, 1)] * 3)   # bob: 3, fails, only life -> match over

        # Timing fix: the match is already finished right after the 3rd
        # dart lands — before anyone pulls the darts from the board.
        assert game.state == "finished"
        assert game.winner == "alice"
        assert audio.played == ["3", "alice", "matchshot"]

        # Pulling the darts afterward must be a no-op — on_board_state()'s
        # `state != "playing"` guard means this turn is never re-processed.
        audio.played = []
        game.on_board_state(0, [])
        assert audio.played == []

    def test_next_player_announces_filler_target_and_target_plus_one_when_no_freipass(self):
        audio = FakeAudio()
        game = EliminationGame(["alice", "bob", "carol"], 3, FakeMqttClient(), "autodarts", audio=audio)
        game.freipass = False

        game._apply_turn("alice", 50)  # passes, sets target=50, advances to bob (no freipass)

        # passes = score > target, so target itself (50) wouldn't be
        # enough — the announced minimum passing score is target + 1.
        assert audio.played == ["bob", "filler_target", "51"]

    def test_next_player_gets_freipass_instead_of_filler_target(self):
        audio = FakeAudio()
        game = EliminationGame(["alice", "bob", "carol"], 1, FakeMqttClient(), "autodarts", audio=audio)

        game._apply_turn(game.current_player, 0)  # alice fails, only life -> eliminated, bob inherits freipass

        assert audio.played[-2:] == ["bob", "freipass"]

    def test_score_is_announced_only_once_on_a_passing_turn(self):
        # Regression: _end_turn()'s "preview didn't fire" fallback used to
        # check _outcome_published, which is only ever set on a *failed*
        # turn — so a passing turn's score (already announced by the
        # preview) got announced a second time once darts were pulled.
        audio = FakeAudio()
        game = EliminationGame(["alice", "bob"], 3, FakeMqttClient(), "autodarts", audio=audio)
        game.freipass = False
        game.target = 40

        game.on_board_state(3, [_throw(20, 1)] * 3)  # alice: 60, passes (60 > 40)
        game.on_board_state(0, [])                    # darts pulled -> ends turn

        assert audio.played.count("60") == 1
        assert audio.played == ["60", "bob", "filler_target", "61"]


class TestUndo:
    """Undo the most recently completed turn, repeatable to
    walk back further, including reopening an already-finished match."""

    def test_returns_false_when_nothing_to_undo(self):
        game = EliminationGame(["alice", "bob"], 3, FakeMqttClient(), "autodarts")
        assert game.undo() is False

    def test_reverts_a_normal_turn(self):
        game = EliminationGame(["alice", "bob"], 3, FakeMqttClient(), "autodarts")
        game.on_board_state(3, [_throw(20, 3)] * 3)  # alice: 180, passes via freipass
        game.on_board_state(0, [])                    # pull -> target=180, advances to bob

        assert game.target == 180
        assert game.current_player == "bob"

        assert game.undo() is True
        assert game.target == 0
        assert game.freipass is True
        assert game.current_player == "alice"

    def test_is_repeatable_across_multiple_turns(self):
        game = EliminationGame(["alice", "bob"], 3, FakeMqttClient(), "autodarts")
        game.on_board_state(3, [_throw(20, 1)] * 3)  # alice: 60, passes via freipass -> target=60
        game.on_board_state(0, [])
        game.on_board_state(3, [_throw(1, 1)] * 3)   # bob: 3, fails (3 <= 60) -> life_lost
        game.on_board_state(0, [])

        assert game.lives["bob"] == 2
        assert game.current_player == "alice"

        assert game.undo() is True  # undo bob's failed turn
        assert game.lives["bob"] == 3
        assert game.current_player == "bob"
        assert game.target == 60

        assert game.undo() is True  # undo alice's passing turn
        assert game.target == 0
        assert game.freipass is True
        assert game.current_player == "alice"

        assert game.undo() is False  # nothing left

    def test_is_silent(self):
        audio = FakeAudio()
        game = EliminationGame(["alice", "bob"], 3, FakeMqttClient(), "autodarts", audio=audio)
        game.on_board_state(3, [_throw(20, 1)] * 3)
        game.on_board_state(0, [])
        audio.played = []

        game.undo()

        assert audio.played == []

    def test_removes_the_recorded_elimination_turn(self):
        db = StatsDB(":memory:")
        game = EliminationGame(["alice", "bob"], 3, FakeMqttClient(), "autodarts", stats_db=db)
        game.on_board_state(3, [_throw(20, 1)] * 3)
        game.on_board_state(0, [])

        n = db._conn.execute(
            "SELECT COUNT(*) as n FROM elimination_turns WHERE match_id=? AND player='alice'",
            (game.match_id,),
        ).fetchone()["n"]
        assert n == 1

        game.undo()

        n = db._conn.execute(
            "SELECT COUNT(*) as n FROM elimination_turns WHERE match_id=? AND player='alice'",
            (game.match_id,),
        ).fetchone()["n"]
        assert n == 0

    def test_reopens_a_match_finished_via_the_instant_preview_path(self):
        db = StatsDB(":memory:")
        game = EliminationGame(["alice", "bob"], 1, FakeMqttClient(), "autodarts", stats_db=db)
        game.on_board_state(3, [_throw(20, 3)] * 3)  # alice: 180, passes via freipass
        game.on_board_state(0, [])                    # advances to bob
        game.on_board_state(3, [_throw(1, 1)] * 3)    # bob: 3, fails, only life -> instant match-over

        assert game.state == "finished"
        assert game.winner == "alice"
        assert db.win_counts() == {"alice": 1}
        row = db._conn.execute(
            "SELECT ended_at FROM matches WHERE match_id=?", (game.match_id,)
        ).fetchone()
        assert row["ended_at"] is not None
        # the instant-finish path skips _end_turn(), but bob's match-ending turn is recorded
        n = db._conn.execute(
            "SELECT COUNT(*) as n FROM elimination_turns WHERE match_id=? AND player='bob'",
            (game.match_id,),
        ).fetchone()["n"]
        assert n == 1

        assert game.undo() is True
        n = db._conn.execute(
            "SELECT COUNT(*) as n FROM elimination_turns WHERE match_id=? AND player='bob'",
            (game.match_id,),
        ).fetchone()["n"]
        assert n == 0

        assert game.state == "playing"
        assert game.winner is None
        assert game.current_player == "bob"
        assert game.lives["bob"] == 1
        assert db.win_counts() == {}
        row = db._conn.execute(
            "SELECT winner, ended_at FROM matches WHERE match_id=?", (game.match_id,)
        ).fetchone()
        assert row["winner"] is None
        assert row["ended_at"] is None

    def test_reopens_a_match_finished_via_the_apply_turn_fallback_path(self):
        db = StatsDB(":memory:")
        game = EliminationGame(["alice", "bob"], 1, FakeMqttClient(), "autodarts", stats_db=db)
        game.on_board_state(3, [_throw(20, 3)] * 3)  # alice: 180, passes via freipass
        game.on_board_state(0, [])                    # advances to bob

        # bob throws only 1 dart then pulls -> preview (3-dart) never fires,
        # so _end_turn()/_apply_turn()'s <3-dart fallback finishes the match.
        game.on_board_state(1, [_throw(1, 1)])
        game.on_board_state(0, [])

        assert game.state == "finished"
        assert game.winner == "alice"
        # unlike the instant-preview path, this one DOES go through
        # _end_turn(), so bob's finishing turn is recorded.
        n = db._conn.execute(
            "SELECT COUNT(*) as n FROM elimination_turns WHERE match_id=? AND player='bob'",
            (game.match_id,),
        ).fetchone()["n"]
        assert n == 1

        assert game.undo() is True

        assert game.state == "playing"
        assert game.winner is None
        assert game.current_player == "bob"
        n = db._conn.execute(
            "SELECT COUNT(*) as n FROM elimination_turns WHERE match_id=? AND player='bob'",
            (game.match_id,),
        ).fetchone()["n"]
        assert n == 0
        row = db._conn.execute(
            "SELECT winner, ended_at FROM matches WHERE match_id=?", (game.match_id,)
        ).fetchone()
        assert row["winner"] is None
        assert row["ended_at"] is None


class TestUnknownPlayerFallback:
    """Elimination calls audio.play() directly rather than through
    Caller/X01Caller, so it needs its own copy of that name-lookup
    fallback — a name with no recording must fall back to
    unknown_player, not go silent."""

    def test_match_start_falls_back_for_unrecorded_name(self):
        audio = FakeAudio(missing={"ghost"})
        game = EliminationGame(["ghost", "bob"], 3, FakeMqttClient(), "autodarts", audio=audio)

        game._play_start_calls()

        assert audio.played == ["matchon", "ghost", "unknown_player", "filler_after_name"]

    def test_next_player_falls_back_for_unrecorded_name(self):
        audio = FakeAudio(missing={"ghost"})
        game = EliminationGame(["alice", "ghost"], 3, FakeMqttClient(), "autodarts", audio=audio)
        game.freipass = False

        game._apply_turn("alice", 50)  # passes, advances to ghost (no freipass)

        assert audio.played == ["ghost", "unknown_player", "filler_target", "51"]

    def test_winner_announcement_falls_back_for_unrecorded_name(self):
        audio = FakeAudio(missing={"ghost"})
        game = EliminationGame(["alice", "ghost"], 1, FakeMqttClient(), "autodarts", audio=audio)

        game._apply_turn(game.current_player, 0)  # alice fails, only life -> ghost wins

        assert audio.played == ["ghost", "unknown_player", "matchshot"]


class TestRecordedTurnDetails:
    """Each turn is stored with the score it had to beat, so the Stats tab can
    show how a game was lost, not just that it was."""

    def _turns(self, db, game):
        rows = db._conn.execute(
            "SELECT player, darts_count, score, target, freipass, passed, lives_before"
            " FROM elimination_turns WHERE match_id=? ORDER BY id", (game.match_id,)).fetchall()
        return [dict(r) for r in rows]

    def _game(self, lives=3):
        db = StatsDB(":memory:")
        return db, EliminationGame(["alice", "bob"], lives, FakeMqttClient(), "autodarts", stats_db=db)

    def test_a_passing_freipass_turn_and_a_failing_turn(self):
        db, game = self._game()
        game.on_board_state(3, [_throw(20, 3)] * 3)   # alice: 180, freipass
        game.on_board_state(0, [])
        game.on_board_state(3, [_throw(1, 1)] * 3)    # bob: 3 against 180, loses a life
        game.on_board_state(0, [])
        assert self._turns(db, game) == [
            {"player": "alice", "darts_count": 3, "score": 180, "target": 0, "freipass": 1, "passed": 1, "lives_before": 3},
            {"player": "bob", "darts_count": 3, "score": 3, "target": 180, "freipass": 0, "passed": 0, "lives_before": 3},
        ]

    def test_the_match_ending_turn_is_recorded_before_the_life_is_taken(self):
        db, game = self._game(lives=1)
        game.on_board_state(3, [_throw(20, 3)] * 3)
        game.on_board_state(0, [])
        game.on_board_state(3, [_throw(1, 1)] * 3)    # bob's last life, instant finish
        assert game.state == "finished"
        assert self._turns(db, game)[-1] == {
            "player": "bob", "darts_count": 3, "score": 3, "target": 180, "freipass": 0, "passed": 0, "lives_before": 1}

    def test_a_turn_after_an_elimination_is_a_freipass(self):
        db = StatsDB(":memory:")
        game = EliminationGame(["a", "b", "c"], 1, FakeMqttClient(), "autodarts", stats_db=db)
        game.on_board_state(3, [_throw(20, 3)] * 3)    # a: 180, freipass
        game.on_board_state(0, [])
        game.on_board_state(3, [_throw(1, 1)] * 3)     # b: 3 against 180, only life gone
        game.on_board_state(0, [])
        game.on_board_state(1, [_throw(5, 1)])         # c: freipass, any score above 0 passes
        game.on_board_state(0, [])
        last = self._turns(db, game)[-1]
        assert (last["player"], last["freipass"], last["target"], last["passed"]) == ("c", 1, 0, 1)

    def test_a_corrected_turn_total_updates_the_recorded_turn(self):
        db, game = self._game()
        game.on_board_state(3, [_throw(20, 3)] * 3)
        game.on_board_state(0, [])
        game.correct_turn(0)                            # misread, scored nothing: no pass on a freipass
        row = self._turns(db, game)[0]
        assert (row["score"], row["passed"], row["target"], row["freipass"]) == (0, 0, 0, 1)
        game.correct_turn(12)
        row = self._turns(db, game)[0]
        assert (row["score"], row["passed"]) == (12, 1)

    def test_without_a_stats_db_nothing_is_recorded_and_nothing_breaks(self):
        game = EliminationGame(["alice", "bob"], 1, FakeMqttClient(), "autodarts")
        game.on_board_state(3, [_throw(20, 3)] * 3)
        game.on_board_state(0, [])
        game.on_board_state(3, [_throw(1, 1)] * 3)
        assert game.state == "finished"
        assert game.undo() is True
