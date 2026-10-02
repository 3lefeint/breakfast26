from breakfast.caller_x01 import X01Caller

from conftest import FakeAudio

# Mirrors the real sound inventory: d/t/m field files exist, plain singles
# don't (announced via number), require_* mostly missing.
FIELD_SET = {f"{p}{n}" for p in "dtm" for n in range(1, 21)} | \
            {"bull", "bullseye", "outside", "double", "triple"} | \
            {str(n) for n in range(0, 181)} | \
            {"you_require", "anna", "carla", "unknown_player"}


WITH_REQUIRE = FIELD_SET | {"require_40", "require_32"}


def dart(number, multiplier, dartno=1, miss=False, field=None):
    points = 0 if multiplier == 0 else number * multiplier
    if field is None:
        prefix = {0: "m", 1: "s", 2: "d", 3: "t"}[multiplier]
        field = f"{prefix}{number}"
    return {"type": "dart", "dart": dartno, "miss": miss, "points": points,
            "field": field, "number": number, "multiplier": multiplier,
            "mode": "X01"}


def snap(remaining=301, turn_score=0, player="anna", idx=0, players=2,
         throws=(None, None, None)):
    return {
        "active_player_name": player,
        "active_player_index": idx,
        "game_mode": "X01",
        "players": {i: {} for i in range(players)},
        "current": {
            "remaining": remaining,
            "turn_score": turn_score,
            "throw1_raw": throws[0],
            "throw2_raw": throws[1],
            "throw3_raw": throws[2],
        },
    }


def make(audio=None, **kw):
    audio = audio if audio is not None else FakeAudio(FIELD_SET)
    c = X01Caller(ambient_volume=0, **kw)
    return c, audio


class TestPerDart:
    def test_triple_plays_field_file(self):
        c, audio = make()
        c.on_dart(dart(20, 3), snap(), audio)
        assert audio.played() == ["t20"]

    def test_single_falls_back_to_number(self):
        c, audio = make()
        c.on_dart(dart(20, 1), snap(), audio)   # no s20 file in the set
        assert audio.played() == ["20"]

    def test_miss_field_file(self):
        c, audio = make()
        c.on_dart(dart(3, 0, miss=True), snap(), audio)
        assert audio.played() == ["m3"]

    def test_miss_without_field_file_plays_outside(self):
        audio = FakeAudio(FIELD_SET - {"m3"})
        c, _ = make(audio)
        c.on_dart(dart(3, 0, miss=True), snap(), audio)
        assert audio.played() == ["outside"]

    def test_call_misses_disabled_silences_miss_field_file(self):
        c, audio = make(call_misses=False)
        c.on_dart(dart(3, 0, miss=True), snap(), audio)
        assert audio.calls == []

    def test_call_misses_disabled_silences_outside_fallback(self):
        audio = FakeAudio(FIELD_SET - {"m3"})
        c, _ = make(audio, call_misses=False)
        c.on_dart(dart(3, 0, miss=True), snap(), audio)
        assert audio.calls == []

    def test_call_misses_disabled_does_not_affect_hits(self):
        c, audio = make(call_misses=False)
        c.on_dart(dart(20, 3), snap(), audio)
        assert audio.played() == ["t20"]

    def test_bull_and_bullseye(self):
        c, audio = make()
        c.on_dart(dart(25, 1, field="25"), snap(), audio)
        c.on_dart(dart(25, 2, dartno=2, field="bull"), snap(), audio)
        assert audio.played() == ["bull", "bullseye"]

    def test_double_without_field_file_plays_type_then_number(self):
        audio = FakeAudio(FIELD_SET - {"d16"})
        c, _ = make(audio)
        c.on_dart(dart(16, 2), snap(), audio)
        assert audio.played() == ["double", "16"]

    def test_winning_dart_is_silent(self):
        c, audio = make()
        c.on_dart(dart(16, 2, dartno=3), snap(remaining=0), audio)
        assert audio.calls == []

    def test_per_dart_disabled(self):
        c, audio = make(per_dart=False)
        c.on_dart(dart(20, 3), snap(), audio)
        assert "t20" not in audio.calls


class TestTurnTotal:
    def test_total_after_third_dart(self):
        c, audio = make()
        c.on_dart(dart(20, 3, dartno=3), snap(turn_score=180), audio)
        assert audio.played() == ["t20", "180"]

    def test_no_total_on_first_or_second_dart(self):
        c, audio = make()
        c.on_dart(dart(20, 3, dartno=1), snap(turn_score=60), audio)
        c.on_dart(dart(20, 3, dartno=2), snap(turn_score=120), audio)
        assert audio.played() == ["t20", "t20"]

    def test_total_disabled(self):
        c, audio = make(turn_total=False)
        c.on_dart(dart(20, 3, dartno=3), snap(turn_score=180), audio)
        assert audio.played() == ["t20"]


class TestCheckoutCall:
    def test_checkout_without_require_file_is_skipped(self):
        c, audio = make(announce_change=False)
        c.on_turn_end({"type": "turn_end", "mode": "X01"}, snap(remaining=40), audio)
        assert "you_require" not in audio.calls     # no half sentence
        assert audio.calls.count("40") == 0         # never the euphoric number

    def test_missing_require_file_still_names_the_player(self):
        c, audio = make()
        c.on_turn_end({"type": "turn_end", "mode": "X01"}, snap(remaining=40), audio)
        assert audio.played() == ["anna"]

    def test_require_file_used_when_available(self):
        audio = FakeAudio(WITH_REQUIRE)
        c, _ = make(audio)
        c.on_turn_end({"type": "turn_end", "mode": "X01"}, snap(remaining=40), audio)
        assert audio.played() == ["anna", "you_require", "require_40"]

    def test_bogey_number_is_ambient_only(self):
        c, audio = make()
        c.on_turn_end({"type": "turn_end", "mode": "X01"}, snap(remaining=169), audio)
        assert "you_require" not in audio.calls

    def test_above_170_silent(self):
        c, audio = make()
        c.on_turn_end({"type": "turn_end", "mode": "X01"}, snap(remaining=171), audio)
        assert "you_require" not in audio.calls

    def test_same_remaining_respects_limit(self):
        c, audio = make(FakeAudio(WITH_REQUIRE))
        s = snap(remaining=40)
        c.on_turn_end({"type": "turn_end"}, s, audio)
        c.on_turn_end({"type": "turn_end"}, s, audio)   # same score again
        assert audio.calls.count("you_require") == 1

    def test_new_remaining_resets_counter(self):
        c, audio = make(FakeAudio(WITH_REQUIRE))
        c.on_turn_end({"type": "turn_end"}, snap(remaining=40), audio)
        c.on_turn_end({"type": "turn_end"}, snap(remaining=32), audio)
        assert audio.calls.count("you_require") == 2

    def test_counter_is_per_player(self):
        c, audio = make(FakeAudio(WITH_REQUIRE))
        c.on_turn_end({"type": "turn_end"}, snap(remaining=40, player="anna", idx=0), audio)
        c.on_turn_end({"type": "turn_end"}, snap(remaining=40, player="carla", idx=1), audio)
        assert audio.calls.count("you_require") == 2

    def test_match_start_resets_counters(self):
        c, audio = make(FakeAudio(WITH_REQUIRE))
        c.on_turn_end({"type": "turn_end"}, snap(remaining=40), audio)
        c.on_match_start(snap())
        c.on_turn_end({"type": "turn_end"}, snap(remaining=40), audio)
        assert audio.calls.count("you_require") == 2

    def test_disabled_via_limit_zero(self):
        c, audio = make(checkout_limit=0)
        c.on_turn_end({"type": "turn_end"}, snap(remaining=40), audio)
        assert "you_require" not in audio.calls


class TestPlayerChange:
    def test_announce_change_calls_incoming_player(self):
        c, audio = make(announce_change=True)
        c.on_turn_end({"type": "turn_end"}, snap(remaining=301), audio)
        assert audio.played() == ["anna"]

    def test_announce_player_falls_back_to_unknown_player_when_name_missing(self):
        # A registered name with no recording gets the generic
        # unknown_player fallback instead of the old player{N} numbering.
        c, audio = make(announce_change=True)
        c.on_turn_end({"type": "turn_end"}, snap(remaining=301, player="ghost"), audio)
        assert audio.played() == ["unknown_player"]

    def test_announce_change_skipped_when_checkout_called(self):
        c, audio = make(FakeAudio(WITH_REQUIRE), announce_change=True)
        c.on_turn_end({"type": "turn_end"}, snap(remaining=40), audio)
        assert audio.calls.count("anna") == 1   # once for the checkout call only

    def test_announce_change_still_fires_when_limit_exceeded_across_turns(self):
        c, audio = make(FakeAudio(WITH_REQUIRE), announce_change=True, checkout_limit=1)
        s = snap(remaining=40)
        c.on_turn_end({"type": "turn_end"}, s, audio)   # first time — limit not yet exceeded
        audio.calls.clear()
        c.on_turn_end({"type": "turn_end"}, s, audio)   # same remaining again — limit exceeded
        assert audio.played() == ["anna"]
        assert "you_require" not in audio.calls

    def test_announce_change_is_on_by_default(self):
        assert X01Caller().announce_change is True

    def test_announce_change_respects_call_player(self):
        c, audio = make(announce_change=True, call_player=False)
        c.on_turn_end({"type": "turn_end"}, snap(remaining=301), audio)
        assert audio.calls == []

    def test_single_player_no_change_announce(self):
        c, audio = make(announce_change=True)
        c.on_turn_end({"type": "turn_end"}, snap(remaining=301, players=1), audio)
        assert audio.calls == []
