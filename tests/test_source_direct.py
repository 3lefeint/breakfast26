from breakfast.source_direct import _dart_value, _handle_board_message
from breakfast.state import GameState


def _throw(number, multiplier):
    return {"segment": {"number": number, "multiplier": multiplier}}


class FakeMqttPub:
    def __init__(self):
        self.freeplay_calls = []

    def publish_freeplay(self, count, throws):
        self.freeplay_calls.append((count, list(throws)))


class FakeAudio:
    def __init__(self):
        self.calls = []

    def play(self, name, prob=1.0, volume=1.0, channel=None, break_last=False):
        self.calls.append(name)
        return True


class FakeElimCtrl:
    def __init__(self, active=False):
        self.active = active
        self.board_state_calls = []

    def on_board_state(self, count, throws):
        self.board_state_calls.append((count, list(throws)))


class TestDartValue:
    def test_scoring_dart(self):
        assert _dart_value(_throw(20, 3)) == 60

    def test_miss_has_zero_multiplier(self):
        assert _dart_value(_throw(0, 0)) == 0

    def test_missing_multiplier_is_a_miss(self):
        assert _dart_value({"segment": {"number": 5}}) == 0


class TestHandleBoardMessage:
    def test_match_started_skips_freeplay_and_audio_entirely(self):
        state = GameState()
        state.match_started = True
        mqtt_pub, audio = FakeMqttPub(), FakeAudio()
        new_count = _handle_board_message(
            {"numThrows": 1, "throws": [_throw(20, 3)]}, state, mqtt_pub, None, audio, prev_count=0)
        assert new_count == 1
        assert mqtt_pub.freeplay_calls == []
        assert audio.calls == []

    def test_active_elimination_routes_to_controller_not_freeplay(self):
        state = GameState()
        mqtt_pub, audio = FakeMqttPub(), FakeAudio()
        elim_ctrl = FakeElimCtrl(active=True)
        _handle_board_message(
            {"numThrows": 1, "throws": [_throw(20, 3)]}, state, mqtt_pub, elim_ctrl, audio, prev_count=0)
        assert elim_ctrl.board_state_calls == [(1, [_throw(20, 3)])]
        assert mqtt_pub.freeplay_calls == []
        assert audio.calls == []

    def test_freeplay_publishes_mqtt_on_count_change(self):
        state = GameState()
        mqtt_pub = FakeMqttPub()
        _handle_board_message(
            {"numThrows": 1, "throws": [_throw(20, 3)]}, state, mqtt_pub, None, None, prev_count=0)
        assert mqtt_pub.freeplay_calls == [(1, [_throw(20, 3)])]

    def test_no_audio_configured_is_a_noop(self):
        state = GameState()
        new_count = _handle_board_message(
            {"numThrows": 1, "throws": [_throw(20, 3)]}, state, None, None, None, prev_count=0)
        assert new_count == 1

    def test_scoring_dart_plays_no_miss_call(self):
        state = GameState()
        audio = FakeAudio()
        _handle_board_message(
            {"numThrows": 1, "throws": [_throw(20, 3)]}, state, None, None, audio, prev_count=0)
        assert audio.calls == []

    def test_miss_dart_plays_miss_call(self):
        state = GameState()
        audio = FakeAudio()
        _handle_board_message(
            {"numThrows": 1, "throws": [_throw(0, 0)]}, state, None, None, audio, prev_count=0)
        assert audio.calls == ["miss"]

    def test_third_dart_announces_turn_total(self):
        state = GameState()
        audio = FakeAudio()
        throws = [_throw(20, 3), _throw(20, 3), _throw(20, 3)]  # 60+60+60
        _handle_board_message(
            {"numThrows": 3, "throws": throws}, state, None, None, audio, prev_count=2)
        assert audio.calls == ["180"]

    def test_third_dart_miss_plays_both_miss_and_total(self):
        state = GameState()
        audio = FakeAudio()
        throws = [_throw(20, 3), _throw(20, 3), _throw(0, 0)]  # 60+60+0
        _handle_board_message(
            {"numThrows": 3, "throws": throws}, state, None, None, audio, prev_count=2)
        assert audio.calls == ["miss", "120"]

    def test_repeated_same_count_does_not_replay_audio(self):
        """A resent WS message with the same numThrows (no new dart) must
        not re-trigger the miss/total calls — only an actual increase in
        numThrows counts as a new dart landing."""
        state = GameState()
        audio = FakeAudio()
        throws = [_throw(20, 3)]
        _handle_board_message({"numThrows": 1, "throws": throws}, state, None, None, audio, prev_count=1)
        assert audio.calls == []

    def test_darts_pulled_reset_plays_no_audio(self):
        state = GameState()
        audio = FakeAudio()
        new_count = _handle_board_message(
            {"numThrows": 0, "throws": []}, state, None, None, audio, prev_count=3)
        assert new_count == 0
        assert audio.calls == []


class TestBoardDartsFromBoardStream:
    def _connected_state(self):
        state = GameState()
        state.board_darts.set_connected(True)
        return state

    def test_darts_are_tracked_in_freeplay(self):
        state = self._connected_state()
        throws = [{"segment": {"name": "T1"}, "coords": {"x": 0.16, "y": 0.58}}]
        _handle_board_message({"numThrows": 1, "throws": throws}, state, None, None, None, prev_count=0)
        assert state.board_darts.snapshot() == [{"n": 1, "x": 0.16, "y": 0.58}]

    def test_darts_are_tracked_while_a_match_is_running(self):
        state = self._connected_state()
        state.match_started = True
        throws = [{"segment": {"name": "T1"}, "coords": {"x": 0.16, "y": 0.58}}]
        _handle_board_message({"numThrows": 1, "throws": throws}, state, None, None, None, prev_count=0)
        assert state.board_darts.snapshot() == [{"n": 1, "x": 0.16, "y": 0.58}]

    def test_takeout_clears_the_darts(self):
        state = self._connected_state()
        throws = [{"segment": {"name": "T1"}, "coords": {"x": 0.16, "y": 0.58}}]
        _handle_board_message({"numThrows": 1, "throws": throws}, state, None, None, None, prev_count=0)
        _handle_board_message({"numThrows": 0, "throws": []}, state, None, None, None, prev_count=1)
        assert state.board_darts.snapshot() == []
