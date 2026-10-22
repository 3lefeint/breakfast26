from breakfast.source_direct import _dart_value, _handle_board_message
from breakfast.state import GameState


def _throw(number, multiplier):
    return {"segment": {"number": number, "multiplier": multiplier}}


class FakeMqttPub:
    def __init__(self):
        self.freeplay_calls = []
        self.board_status_events = []

    def publish_board_status(self, event):
        self.board_status_events.append(event)

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

    def test_active_target_battle_routes_to_its_controller_not_freeplay(self):
        state = GameState()
        mqtt_pub, audio = FakeMqttPub(), FakeAudio()
        tb_ctrl = FakeElimCtrl(active=True)
        _handle_board_message(
            {"numThrows": 1, "throws": [_throw(20, 3)]}, state, mqtt_pub, FakeElimCtrl(), audio,
            prev_count=0, tb_ctrl=tb_ctrl)
        assert tb_ctrl.board_state_calls == [(1, [_throw(20, 3)])]
        assert mqtt_pub.freeplay_calls == [] and audio.calls == []

    def test_an_active_warm_up_routes_to_its_controller_not_freeplay(self):
        state = GameState()
        mqtt_pub, audio = FakeMqttPub(), FakeAudio()
        wu_ctrl = FakeElimCtrl(active=True)
        _handle_board_message(
            {"numThrows": 1, "throws": [_throw(20, 3)]}, state, mqtt_pub, FakeElimCtrl(), audio,
            prev_count=0, wu_ctrl=wu_ctrl)
        assert wu_ctrl.board_state_calls == [(1, [_throw(20, 3)])]
        assert mqtt_pub.freeplay_calls == [] and audio.calls == []

    def test_a_running_elimination_wins_over_target_battle(self):
        state = GameState()
        elim_ctrl, tb_ctrl = FakeElimCtrl(active=True), FakeElimCtrl(active=True)
        _handle_board_message(
            {"numThrows": 1, "throws": [_throw(20, 3)]}, state, None, elim_ctrl, None,
            prev_count=0, tb_ctrl=tb_ctrl)
        assert elim_ctrl.board_state_calls and tb_ctrl.board_state_calls == []

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
        throws = [{"segment": {"name": "T1", "number": 1, "multiplier": 3}, "coords": {"x": 0.16, "y": 0.58}}]
        _handle_board_message({"numThrows": 1, "throws": throws}, state, None, None, None, prev_count=0)
        assert state.board_darts.snapshot() == [{"n": 1, "field": "T1", "points": 3, "x": 0.16, "y": 0.58}]

    def test_darts_are_tracked_while_a_match_is_running(self):
        state = self._connected_state()
        state.match_started = True
        throws = [{"segment": {"name": "T1", "number": 1, "multiplier": 3}, "coords": {"x": 0.16, "y": 0.58}}]
        _handle_board_message({"numThrows": 1, "throws": throws}, state, None, None, None, prev_count=0)
        assert state.board_darts.snapshot() == [{"n": 1, "field": "T1", "points": 3, "x": 0.16, "y": 0.58}]

    def test_takeout_clears_the_darts(self):
        state = self._connected_state()
        throws = [{"segment": {"name": "T1", "number": 1, "multiplier": 3}, "coords": {"x": 0.16, "y": 0.58}}]
        _handle_board_message({"numThrows": 1, "throws": throws}, state, None, None, None, prev_count=0)
        _handle_board_message({"numThrows": 0, "throws": []}, state, None, None, None, prev_count=1)
        assert state.board_darts.snapshot() == []


class TestX01Routing:
    """A match played in Breakfast sets `match_started` like an Autodarts match, so it is asked before that."""

    def test_an_active_x01_match_gets_the_board_even_with_a_match_started(self):
        state = GameState()
        state.match_started = True
        mqtt_pub, audio = FakeMqttPub(), FakeAudio()
        x01 = FakeElimCtrl(active=True)
        elim = FakeElimCtrl(active=True)
        new_count = _handle_board_message(
            {"numThrows": 1, "throws": [_throw(20, 3)]}, state, mqtt_pub, elim, audio, prev_count=0, x01_ctrl=x01)
        assert new_count == 1
        assert x01.board_state_calls == [(1, [_throw(20, 3)])]
        assert elim.board_state_calls == []

    def test_an_inactive_x01_controller_leaves_the_board_to_the_others(self):
        state = GameState()
        mqtt_pub, audio = FakeMqttPub(), FakeAudio()
        x01, elim = FakeElimCtrl(active=False), FakeElimCtrl(active=True)
        _handle_board_message(
            {"numThrows": 1, "throws": [_throw(20, 3)]}, state, mqtt_pub, elim, audio, prev_count=0, x01_ctrl=x01)
        assert x01.board_state_calls == [] and elim.board_state_calls == [(1, [_throw(20, 3)])]


class TestBoardStatusAtConnect:
    def test_the_state_url_sits_next_to_the_event_stream(self):
        from breakfast.source_direct import _board_state_url
        assert _board_state_url("ws://10.0.0.5:3180/api/events") == "http://10.0.0.5:3180/api/state"
        assert _board_state_url("wss://board.example/api/events") == "https://board.example/api/state"

    def test_a_board_that_stopped_before_the_start_is_known(self, monkeypatch):
        from breakfast import source_direct
        from breakfast.web import server

        asked = []

        class Reply:
            def json(self):
                return {"connected": True, "running": False, "status": "Stopped", "numThrows": 0}

        monkeypatch.setattr(source_direct.requests, "get", lambda url, timeout: asked.append(url) or Reply())
        monkeypatch.setattr(server, "push", lambda: None)
        state = GameState()
        source_direct._fetch_board_status(state, "ws://10.0.0.5:3180/api/events")
        assert asked == ["http://10.0.0.5:3180/api/state"]
        assert state.board_status == "Stopped"

    def test_an_unreachable_board_manager_changes_nothing(self, monkeypatch):
        from breakfast import source_direct

        def boom(url, timeout):
            raise ConnectionError("refused")

        monkeypatch.setattr(source_direct.requests, "get", boom)
        state = GameState()
        source_direct._fetch_board_status(state, "ws://10.0.0.5:3180/api/events")
        assert state.board_status is None


class TestBoardStatusToMqtt:
    def test_a_status_of_the_local_board_is_published(self):
        mqtt_pub = FakeMqttPub()
        state = GameState()
        _handle_board_message({"status": "Stopped", "numThrows": 0}, state, mqtt_pub, None, None, 0)
        assert mqtt_pub.board_status_events == [{"type": "board_status", "status": "Stopped"}]

    def test_the_same_status_is_published_once(self):
        mqtt_pub = FakeMqttPub()
        state = GameState()
        for _ in range(2):
            _handle_board_message({"status": "Throw", "numThrows": 0}, state, mqtt_pub, None, None, 0)
        assert len(mqtt_pub.board_status_events) == 1

    def test_the_status_found_at_connect_is_published_too(self, monkeypatch):
        from breakfast import source_direct
        from breakfast.web import server

        class Reply:
            def json(self):
                return {"status": "Stopped"}

        monkeypatch.setattr(source_direct.requests, "get", lambda url, timeout: Reply())
        monkeypatch.setattr(server, "push", lambda: None)
        mqtt_pub = FakeMqttPub()
        source_direct._fetch_board_status(GameState(), "ws://10.0.0.5:3180/api/events", mqtt_pub)
        assert mqtt_pub.board_status_events == [{"type": "board_status", "status": "Stopped"}]


class TestRemoteDartsStayOnTheBoard:
    """While a player at another site of an online match is up, the empty local board must not wipe his darts."""

    def _run(self, remote_turn):
        state = GameState()
        state.board_darts.set_connected(True)
        state.board_darts.update([{"segment": {"name": "S5", "number": 5, "multiplier": 1}, "coords": {"x": 0.1, "y": 0.2}}], remote=True)
        elim = FakeElimCtrl(active=True)
        elim.remote_turn_active = lambda: remote_turn
        _handle_board_message({"numThrows": 0, "throws": []}, state, FakeMqttPub(), elim, FakeAudio(), 0)
        return state.board_darts.snapshot()

    def test_the_remote_darts_stay_while_the_remote_player_is_up(self):
        assert [d["field"] for d in self._run(remote_turn=True)] == ["S5"]

    def test_the_empty_board_clears_them_otherwise(self):
        assert self._run(remote_turn=False) == []
