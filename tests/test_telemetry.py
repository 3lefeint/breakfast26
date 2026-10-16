import asyncio
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import json

import pytest

from breakfast import config as cfg_mod
from breakfast import telemetry
from breakfast.web import server


def make(tmp_path, enabled=True, url=""):
    path = tmp_path / "config.toml"
    section = {"enabled": enabled}
    if url:
        section["url"] = url
    cfg_mod.write(str(path), {"telemetry": section})
    return telemetry.Telemetry(path, version="9.9.9")


class Endpoint:
    """A local endpoint that answers every POST with *status* and keeps the bodies."""

    def __init__(self, status=200):
        self.status, self.bodies = status, []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["content-length"])
                outer.bodies.append((self.path, json.loads(self.rfile.read(length))))
                self.send_response(outer.status)
                self.end_headers()

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()


@pytest.fixture
def endpoint():
    e = Endpoint()
    yield e
    e.close()


def test_nothing_is_recorded_while_off(tmp_path):
    t = make(tmp_path, enabled=False)
    t.record("app_start")
    t.match_opened("m1", "x01")
    assert t.preview()["queued"] == []
    assert not (tmp_path / "telemetry-id").exists()


def test_a_finished_game_reports_mode_duration_and_player_count(tmp_path):
    t = make(tmp_path)
    t.match_opened("m1", "elimination")
    t.match_closed("m1", 3)
    types = [e["type"] for e in t.preview()["queued"]]
    assert types == ["game_started", "game_finished"]
    finished = t.preview()["queued"][1]
    assert finished["mode"] == "elimination" and finished["players"] == 3 and finished["duration_s"] >= 0
    t.match_closed("m1", 3)         # a corrected finish is not counted twice
    assert len(t.preview()["queued"]) == 2


def test_a_game_that_is_replaced_before_its_end_counts_as_aborted(tmp_path):
    t = make(tmp_path)
    t.match_opened("m1", "x01")
    t.match_opened("m2", "killer")
    assert [e["type"] for e in t.preview()["queued"]] == ["game_started", "game_aborted", "game_started"]
    assert t.preview()["queued"][1]["mode"] == "x01"


def test_an_odd_game_mode_is_reported_as_other(tmp_path):
    t = make(tmp_path)
    t.match_opened("m1", "anna's game")
    assert t.preview()["queued"][0]["mode"] == "other"


def test_the_same_error_is_reported_once(tmp_path):
    t = make(tmp_path)
    t.error("KeyError", "breakfast.x", ["a.py:1 in f"])
    t.error("KeyError", "breakfast.x", ["a.py:1 in f"])
    t.error("KeyError", "breakfast.x", ["a.py:2 in f"])
    assert len(t.preview()["queued"]) == 2


def test_error_text_that_is_not_a_location_is_dropped(tmp_path):
    t = make(tmp_path)
    t.error("Error", "frontend", ["/home/anna/app.js:1:2", "index-ab12.js:10:200", "anna scored 180"], source="frontend")
    assert t.preview()["queued"][0]["where"] == ["index-ab12.js:10:200"]


def test_a_logged_exception_carries_type_and_places_but_no_message(tmp_path):
    t = make(tmp_path)
    handler = telemetry._ErrorHandler(t)
    try:
        raise KeyError("anna")
    except KeyError:
        import sys
        record = logging.LogRecord("breakfast.demo", logging.ERROR, __file__, 1, "failed for %s", ("anna",), sys.exc_info())
    handler.emit(record)
    event = t.preview()["queued"][0]
    assert event["exc"] == "KeyError" and event["module"] == "breakfast.demo"
    assert event["where"][-1].startswith("test_telemetry.py:") and "anna" not in json.dumps(event)


def test_an_error_log_without_an_exception_reports_its_location(tmp_path):
    t = make(tmp_path)
    telemetry._ErrorHandler(t).emit(logging.LogRecord("breakfast.demo", logging.ERROR, "/home/anna/x/demo.py", 7, "bad %s", ("anna",), None))
    event = t.preview()["queued"][0]
    assert event["exc"] == "log" and event["where"] == ["demo.py:7 in None"] and "anna" not in json.dumps(event)


def test_flush_sends_the_envelope_and_remembers_what_was_sent(tmp_path, endpoint):
    t = make(tmp_path, url=endpoint.url)
    t.record("app_start", language="en")
    assert t.flush() is True
    path, body = endpoint.bodies[0]
    assert path == "/telemetry"
    assert body["protocol_version"] == 1 and body["version"] == "9.9.9" and len(body["install_id"]) == 32
    assert body["events"][0]["type"] == "app_start"
    assert t.preview()["queued"] == [] and len(t.preview()["sent"]) == 1


def test_the_url_defaults_to_the_relay_address(tmp_path):
    path = tmp_path / "config.toml"
    cfg_mod.write(str(path), {"telemetry": {"enabled": True}, "online": {"relay_url": "wss://relay.example/"}})
    assert telemetry.Telemetry(path).settings() == (True, "https://relay.example")


def test_events_stay_queued_while_the_endpoint_is_down(tmp_path):
    t = make(tmp_path, url="http://127.0.0.1:1")
    t.record("app_start")
    assert t.flush() is False
    assert len(t.preview()["queued"]) == 1


def test_events_stay_queued_after_a_server_error_and_are_dropped_after_a_refusal(tmp_path, endpoint):
    t = make(tmp_path, url=endpoint.url)
    t.record("app_start")
    endpoint.status = 503
    assert t.flush() is False and len(t.preview()["queued"]) == 1
    endpoint.status = 400
    assert t.flush() is True
    assert t.preview()["queued"] == [] and t.preview()["sent"] == []


def test_switching_it_off_drops_the_queue(tmp_path):
    t = make(tmp_path)
    t.record("app_start")
    cfg_mod.write(str(tmp_path / "config.toml"), {"telemetry": {"enabled": False}})
    t.settings_changed()
    assert t.preview()["queued"] == []


def test_switching_it_on_announces_the_installation(tmp_path):
    t = make(tmp_path, enabled=False)
    cfg_mod.write(str(tmp_path / "config.toml"), {"telemetry": {"enabled": True}})
    t.settings_changed()
    assert [e["type"] for e in t.preview()["queued"]] == ["app_start"]


def test_the_installation_id_is_random_and_kept(tmp_path):
    a = make(tmp_path)
    first = a.install_id()
    assert len(first) == 32 and (tmp_path / "telemetry-id").read_text().strip() == first
    assert telemetry.Telemetry(tmp_path / "config.toml").install_id() == first


def test_the_preview_does_not_create_an_id(tmp_path):
    assert make(tmp_path).preview()["install_id"] is None
    assert not (tmp_path / "telemetry-id").exists()


def test_the_routes_work_before_telemetry_is_started():
    assert asyncio.run(server.get_telemetry())["queued"] == []
    assert asyncio.run(server.post_telemetry_client_error({"name": "TypeError", "frames": []})) == {"ok": True}


def test_a_frontend_error_is_taken_over_by_name_and_frames(tmp_path, monkeypatch):
    t = make(tmp_path)
    monkeypatch.setattr(telemetry, "_instance", t)
    asyncio.run(server.post_telemetry_client_error({"name": "TypeError", "frames": ["index-ab.js:1:99"]}))
    event = t.preview()["queued"][0]
    assert event["source"] == "frontend" and event["exc"] == "TypeError" and event["where"] == ["index-ab.js:1:99"]


def test_the_config_route_reports_the_setting(tmp_path):
    cfg_mod.write(str(tmp_path / "config.toml"), {"telemetry": {"enabled": True, "url": "https://x.example"}})
    server.wire(None, None, config_path=str(tmp_path / "config.toml"))
    try:
        assert asyncio.run(server.get_config())["telemetry"] == {"enabled": True, "url": "https://x.example"}
    finally:
        server.wire(None, None)
