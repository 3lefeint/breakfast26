import base64
import json
from unittest.mock import MagicMock

import pytest
import requests

from breakfast.autodarts_client import AutodartsCloudClient


def _fake_jwt(sub="user-1"):
    payload = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).rstrip(b"=")
    return b"header." + payload + b".sig"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    # AutodartsCloudClient logs in synchronously in its constructor (via
    # _AuthClient.__init__ → _login()) — stub both requests.post (login) and
    # requests.get (match-details fetch) so tests never hit the real API.
    login_resp = MagicMock()
    login_resp.raise_for_status = lambda: None
    login_resp.json = lambda: {
        "access_token": _fake_jwt().decode(), "refresh_token": "rt", "expires_in": 900,
    }
    monkeypatch.setattr("breakfast.autodarts_client.requests.post", lambda *a, **kw: login_resp)
    monkeypatch.setattr(
        "breakfast.autodarts_client.requests.get",
        lambda *a, **kw: MagicMock(json=lambda: {}),
    )


def _make_client(events=None):
    return AutodartsCloudClient(
        email="e", password="p", board_id="b",
        on_event=events.append if events is not None else (lambda evt: None),
    )


def _start_match(client, match_id="m1"):
    client._subscribe_match({"event": "start", "id": match_id}, MagicMock())


class FakeThread:
    """Captures the target instead of actually running it, so tests are
    deterministic and don't race a real background thread (mirrors
    tests/test_mqtt_output.py's TestMqttPublisherStartup)."""
    started = []

    def __init__(self, target=None, daemon=None, name=None):
        self.target = target
        FakeThread.started.append(target)

    def start(self):
        pass


class TestLoginFailure:
    def test_login_failure_does_not_raise_and_starts_retry_loop(self, monkeypatch):
        FakeThread.started = []
        bad_resp = MagicMock()
        bad_resp.raise_for_status.side_effect = requests.HTTPError("401 Unauthorized")
        monkeypatch.setattr("breakfast.autodarts_client.requests.post", lambda *a, **kw: bad_resp)
        monkeypatch.setattr("breakfast.autodarts_client.threading.Thread", FakeThread)

        client = _make_client()

        assert client.logged_in is False
        assert FakeThread.started == [client._login_retry_loop]

    def test_successful_login_does_not_start_retry_loop(self, monkeypatch):
        FakeThread.started = []
        monkeypatch.setattr("breakfast.autodarts_client.threading.Thread", FakeThread)

        client = _make_client()   # _no_network fixture already makes login succeed

        assert client.logged_in is True
        assert FakeThread.started == []

    def test_start_is_a_no_op_while_not_logged_in(self, monkeypatch):
        bad_resp = MagicMock()
        bad_resp.raise_for_status.side_effect = requests.HTTPError("401 Unauthorized")
        monkeypatch.setattr("breakfast.autodarts_client.requests.post", lambda *a, **kw: bad_resp)
        monkeypatch.setattr("breakfast.autodarts_client.threading.Thread", FakeThread)

        client = _make_client()
        client.start()   # run_direct() calls this unconditionally right after construction

        assert client.connected is False


class TestMatchStatus:
    def test_inactive_by_default(self):
        client = _make_client()
        status = client.match_status()
        assert status == {
            "match_id": None,
            "match_started_at": None,
            "seconds_since_activity": None,
        }

    def test_active_after_start(self):
        client = _make_client()
        _start_match(client, match_id="m1")

        status = client.match_status()
        assert status["match_id"] == "m1"
        assert status["match_started_at"] is not None
        assert 0 <= status["seconds_since_activity"] < 1

    def test_inactive_after_finish_event(self):
        client = _make_client()
        _start_match(client, match_id="m1")
        client._subscribe_match({"event": "finish", "id": "m1"}, MagicMock())

        assert client.match_status() == {
            "match_id": None,
            "match_started_at": None,
            "seconds_since_activity": None,
        }


class TestForceClearMatch:
    def test_no_active_match_returns_false(self):
        client = _make_client()
        assert client.force_clear_match() is False

    def test_clears_state_and_emits_match_ended(self):
        events = []
        client = _make_client(events)
        _start_match(client, match_id="m1")

        ok = client.force_clear_match()

        assert ok is True
        assert client.match_status() == {
            "match_id": None,
            "match_started_at": None,
            "seconds_since_activity": None,
        }
        assert events[-1] == {"event": "match-ended"}

    def test_stale_finish_event_for_cleared_match_is_ignored(self):
        events = []
        client = _make_client(events)
        _start_match(client, match_id="m1")
        client.force_clear_match()
        events.clear()

        # A belated finish/delete event for the already-cleared match must
        # not re-trigger match-ended handling (id/active checks in
        # _subscribe_match guard against this).
        client._subscribe_match({"event": "finish", "id": "m1"}, MagicMock())

        assert events == []


class TestForwardBoardStatus:
    @pytest.mark.parametrize("raw,mapped", [
        ("Takeout started", "Takeout Started"),
        ("Takeout finished", "Takeout Finished"),
        ("Manual reset", "Manual reset"),
        ("Stopped", "Board Stopped"),
        ("Started", "Board Started"),
        ("Starting", "Board Starting"),
        ("Stopping", "Board Stopping"),
        ("Disconnected", "Board Disconnected"),
        ("Calibration started", "Calibration Started"),
        ("Calibration finished", "Calibration Finished"),
    ])
    def test_known_events_are_forwarded(self, raw, mapped):
        events = []
        client = _make_client(events)
        client._forward_board_status(raw)
        assert events == [{"event": "Board Status", "data": {"status": mapped}}]

    def test_throw_detected_is_silently_ignored_not_logged(self, caplog):
        events = []
        client = _make_client(events)
        client._forward_board_status("Throw detected")
        assert events == []
        assert "Throw detected" not in caplog.text

    def test_takeout_status_on_throw_detected_fires_immediately(self):
        # The turn-ending dart carries status="Takeout" on a "Throw
        # detected" event, well before the separate "Takeout started"
        # event exists at all — the raw status is forwarded as-is (no
        # renaming), right away, not held back for that later event.
        events = []
        client = _make_client(events)
        client._forward_board_status("Throw detected", raw_status="Takeout")
        assert events == [{"event": "Board Status", "data": {"status": "Takeout"}}]

    def test_raw_status_takes_priority_over_event_map(self):
        # Even if some other event name happened to arrive alongside a
        # status field, the status field wins.
        events = []
        client = _make_client(events)
        client._forward_board_status("Something else", raw_status="Takeout")
        assert events == [{"event": "Board Status", "data": {"status": "Takeout"}}]

    def test_throw_status_is_forwarded_too(self):
        # "Throw" is what actually resets the board back to ready — it
        # must be forwarded like any other status, not treated as a
        # no-op.
        events = []
        client = _make_client(events)
        client._forward_board_status("Throw detected", raw_status="Throw")
        assert events == [{"event": "Board Status", "data": {"status": "Throw"}}]

    def test_unrecognized_event_is_not_forwarded_but_is_logged(self, caplog):
        events = []
        client = _make_client(events)
        with caplog.at_level("INFO"):
            client._forward_board_status("Something new")
        assert events == []
        assert "Something new" in caplog.text


def test_on_message_processes_in_arrival_order_even_when_handlers_are_slow(monkeypatch):
    import threading
    import time

    client = _make_client()
    seen = []
    concurrent = []
    active = 0
    guard = threading.Lock()

    def slow_handler(data):
        nonlocal active
        with guard:
            active += 1
            concurrent.append(active)
        # Earlier messages take longer, so a thread-per-message model would
        # finish them out of order.
        time.sleep(0.02 if data["n"] % 2 == 0 else 0.0)
        seen.append(data["n"])
        with guard:
            active -= 1

    monkeypatch.setattr(client, "_handle_match_state", slow_handler)

    for n in range(20):
        client._on_message(None, json.dumps(
            {"channel": "autodarts.matches", "data": {"n": n}}))
    client._msg_queue.join()

    assert seen == list(range(20))
    assert max(concurrent) == 1


def test_on_message_survives_a_failing_message(monkeypatch):
    client = _make_client()
    seen = []
    monkeypatch.setattr(client, "_handle_match_state", lambda data: seen.append(data["n"]))

    client._on_message(None, "not json")
    client._on_message(None, json.dumps({"channel": "autodarts.matches", "data": {"n": 1}}))
    client._msg_queue.join()

    assert seen == [1]


class TestCorrectThrow:
    def _patch_with(self, monkeypatch, status, text=""):
        calls = []
        resp = MagicMock(status_code=status, ok=status < 400, text=text)
        monkeypatch.setattr(
            "breakfast.autodarts_client.requests.patch",
            lambda url, **kw: calls.append((url, kw)) or resp)
        return calls

    def test_patches_the_throw_with_the_field_center(self, monkeypatch):
        calls = self._patch_with(monkeypatch, 200)
        client = _make_client()
        _start_match(client, "m1")
        client.correct_throw(2, "t20")
        url, kw = calls[0]
        assert url.endswith("/m1/throws")
        assert kw["json"] == {"changes": {"1": {"coords": {"x": 0.0, "y": 103 / 170}, "type": "normal"}}}

    def test_rejected_correction_logs_the_response_body(self, monkeypatch, caplog):
        self._patch_with(monkeypatch, 502, "upstream failed")
        client = _make_client()
        _start_match(client)
        with caplog.at_level("WARNING"):
            client.correct_throw(1, "50")
        assert "upstream failed" in caplog.text

    def test_unknown_field_sends_nothing(self, monkeypatch):
        calls = self._patch_with(monkeypatch, 200)
        client = _make_client()
        _start_match(client)
        client.correct_throw(1, "20")
        assert calls == []
