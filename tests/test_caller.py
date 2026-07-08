from breakfast.caller import Caller, ModeHandler, from_config
from breakfast.caller_x01 import X01Caller

from conftest import FakeAudio


def snap(player="anna", idx=0, leg=1, mode="X01"):
    return {
        "active_player_name": player,
        "active_player_index": idx,
        "current_leg": leg,
        "game_mode": mode,
    }


class TestMatchStart:
    def test_player_then_matchon(self):
        audio = FakeAudio({"anna", "matchon"})
        Caller(audio).on_event({"type": "match_started", "mode": "X01"}, snap())
        assert audio.played() == ["anna", "matchon"]

    def test_matchon_falls_back_to_gameon(self):
        audio = FakeAudio({"anna", "gameon"})
        Caller(audio).on_event({"type": "match_started", "mode": "X01"}, snap())
        assert audio.played() == ["anna", "gameon"]

    def test_unknown_player_falls_back_to_unknown_player_key(self):
        # Replaces the old player{N} numbering entirely.
        audio = FakeAudio({"unknown_player", "matchon"})
        Caller(audio).on_event({"type": "match_started", "mode": "X01"},
                               snap(player="unbekannt", idx=2))
        assert audio.played() == ["unknown_player", "matchon"]

    def test_player_announce_can_be_disabled(self):
        audio = FakeAudio({"anna", "matchon"})
        Caller(audio, call_player=False).on_event(
            {"type": "match_started", "mode": "X01"}, snap())
        assert audio.played() == ["matchon"]


class TestLegStart:
    def test_game_started_plays_gameon(self):
        audio = FakeAudio({"anna", "gameon"})
        Caller(audio).on_event({"type": "game_started", "mode": "X01"}, snap(leg=2))
        assert audio.played() == ["anna", "gameon"]


class TestWon:
    def test_match_won(self):
        audio = FakeAudio({"matchshot", "anna"})
        Caller(audio).on_event({"type": "won", "scope": "match", "mode": "X01"}, snap())
        assert audio.played() == ["matchshot", "anna"]

    def test_match_won_falls_back_to_gameshot(self):
        audio = FakeAudio({"gameshot", "anna"})
        Caller(audio).on_event({"type": "won", "scope": "match", "mode": "X01"}, snap())
        assert audio.played() == ["gameshot", "anna"]

    def test_leg_won_real_life_style(self):
        # snapshot leg already incremented by state.py: leg 2 => leg 1 finished
        audio = FakeAudio({"gameshot_l1_n", "anna"})
        Caller(audio).on_event({"type": "won", "scope": "game", "mode": "X01"},
                               snap(leg=2))
        assert audio.played() == ["gameshot_l1_n", "anna"]

    def test_leg_won_fallback_plain_gameshot_plus_leg(self):
        audio = FakeAudio({"gameshot", "leg_3", "anna"})
        Caller(audio).on_event({"type": "won", "scope": "game", "mode": "X01"},
                               snap(leg=4))
        assert audio.played() == ["gameshot", "leg_3", "anna"]


class TestMatchEnded:
    def test_cancelled_match_plays_matchcancel(self):
        audio = FakeAudio({"matchcancel"})
        c = Caller(audio)
        c.on_event({"type": "match_started", "mode": "X01"}, snap())
        c.on_event({"type": "match_ended"}, snap())
        assert "matchcancel" in audio.played()

    def test_won_match_end_is_silent(self):
        audio = FakeAudio({"matchshot", "matchcancel", "anna"})
        c = Caller(audio)
        c.on_event({"type": "match_started", "mode": "X01"}, snap())
        c.on_event({"type": "won", "scope": "match", "mode": "X01"}, snap())
        c.on_event({"type": "match_ended"}, snap())
        assert "matchcancel" not in audio.calls


class TestBust:
    def test_bust_plays_busted(self):
        audio = FakeAudio({"busted"})
        Caller(audio).on_event({"type": "bust", "mode": "X01"}, snap())
        assert audio.played() == ["busted"]


class TestAmbient:
    def test_player_specific_ambient_wins(self):
        audio = FakeAudio({"anna", "matchon", "ambient_matchon_anna", "ambient_matchon"})
        Caller(audio).on_event({"type": "match_started", "mode": "X01"}, snap())
        assert "ambient_matchon_anna" in audio.played()
        assert "ambient_matchon" not in audio.played()

    def test_ambient_chain_falls_through_bases(self):
        audio = FakeAudio({"anna", "matchon", "ambient_gameon"})
        Caller(audio).on_event({"type": "match_started", "mode": "X01"}, snap())
        assert "ambient_gameon" in audio.played()

    def test_ambient_disabled_by_zero_volume(self):
        audio = FakeAudio({"anna", "matchon", "ambient_matchon"})
        Caller(audio, ambient_volume=0).on_event(
            {"type": "match_started", "mode": "X01"}, snap())
        assert "ambient_matchon" not in audio.calls


class SpyHandler(ModeHandler):
    def __init__(self):
        self.events = []

    def on_dart(self, evt, snapshot, audio):
        self.events.append(("dart", evt))

    def on_turn_end(self, evt, snapshot, audio):
        self.events.append(("turn_end", evt))

    def on_match_start(self, snapshot):
        self.events.append(("match_start", None))


class TestModeDispatch:
    def test_dart_and_turn_end_delegated_by_mode_prefix(self):
        audio = FakeAudio(set())
        c = Caller(audio)
        x01 = SpyHandler()
        c.register("X01", x01)
        c.on_event({"type": "dart", "mode": "X01", "points": 60}, snap())
        c.on_event({"type": "turn_end", "mode": "X01"}, snap())
        assert [e[0] for e in x01.events] == ["dart", "turn_end"]

    def test_unknown_mode_is_ignored(self):
        audio = FakeAudio(set())
        c = Caller(audio)
        c.register("X01", SpyHandler())
        c.on_event({"type": "dart", "mode": "Shanghai"}, snap(mode="Shanghai"))
        assert audio.calls == []

    def test_match_start_resets_handler(self):
        audio = FakeAudio(set())
        c = Caller(audio)
        x01 = SpyHandler()
        c.register("X01", x01)
        c.on_event({"type": "match_started", "mode": "X01"}, snap())
        assert ("match_start", None) in x01.events

    def test_handler_exception_does_not_propagate(self):
        class Boom(ModeHandler):
            def on_dart(self, evt, snapshot, audio):
                raise RuntimeError("boom")
        audio = FakeAudio(set())
        c = Caller(audio)
        c.register("X01", Boom())
        c.on_event({"type": "dart", "mode": "X01"}, snap())   # must not raise


class TestFromConfig:
    def test_defaults(self):
        c = from_config(FakeAudio(set()))
        assert c is not None
        assert c.call_player is True
        x01 = c._handler_for("X01")
        assert isinstance(x01, X01Caller)
        assert x01.per_dart is True
        assert x01.checkout_limit == 1
        assert x01.announce_change is False
        assert x01.call_misses is True

    def test_disabled_returns_none(self):
        assert from_config(FakeAudio(set()), {"enabled": False}) is None

    def test_values_propagate(self):
        cfg = {"per_dart": False, "turn_total": False, "checkout_limit": 3,
               "announce_change": True, "call_player": False,
               "ambient_volume": 0, "call_misses": False}
        c = from_config(FakeAudio(set()), cfg)
        assert c.call_player is False
        assert c.ambient_volume == 0
        x01 = c._handler_for("X01")
        assert x01.per_dart is False
        assert x01.turn_total is False
        assert x01.checkout_limit == 3
        assert x01.announce_change is True
        assert x01.call_misses is False


class TestNoOps:
    def test_none_event_ignored(self):
        audio = FakeAudio({"matchon"})
        Caller(audio).on_event(None, snap())
        assert audio.calls == []

    def test_no_audio_engine_ignored(self):
        Caller(None).on_event({"type": "match_started"}, snap())   # must not raise
