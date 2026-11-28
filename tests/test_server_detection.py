import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from starlette.testclient import TestClient

from breakfast.elimination import EliminationController
from breakfast.state import GameState
from breakfast.web import server
from tests.test_target_battle import FakeMqttPub

CALLS = []
EMPTY_BOARD_REFUSED = False


class FakeWorker(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        CALLS.append(("GET", self.path))
        if self.path == "/api/model":
            body, ctype = json.dumps({"size": [800, 600], "ref": {"0": [[1, 2]] * 4}, "radii": {"170": 170.0}, "can_revert": True}).encode(), "application/json"
        elif self.path == "/api/labels":
            body, ctype = json.dumps({"looked_at": 4, "wrong": 1}).encode(), "application/json"
        elif self.path == "/api/settings":
            body, ctype = json.dumps([{"key": "settle_s", "value": 0.35}]).encode(), "application/json"
        elif self.path == "/status.json":
            body, ctype = json.dumps({"board": {"status": "ready", "count": 1}, "events": []}).encode(), "application/json"
        else:
            body, ctype = b"\xff\xd8jpeg", "image/jpeg"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        CALLS.append(("POST", self.path))
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
        if self.path in ("/api/model/move", "/api/model/discard"):
            CALLS.append(("BODY", body))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"size": [800, 600], "points": {}}).encode())
            return
        if self.path == "/api/drift/accept":
            self.send_response(409 if EMPTY_BOARD_REFUSED else 200)
            self.end_headers()
            self.wfile.write(b"{}")
            return
        if self.path in ("/api/settings", "/api/settings/reset"):
            CALLS.append(("BODY", body))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"applied": {"settle_s": 0.5}, "refused": {}} if self.path == "/api/settings" else [{"key": "settle_s", "value": 0.35}]).encode())
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")


@pytest.fixture
def worker_port():
    CALLS.clear()
    srv = HTTPServer(("127.0.0.1", 0), FakeWorker)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


def wire(port):
    state = GameState()
    server.wire(state, EliminationController(FakeMqttPub(), "autodarts"), detection_port=port)
    return state


def test_without_detection_everything_says_off():
    wire(None)
    c = TestClient(server.app)
    assert c.get("/api/detection/status").json() == {"enabled": False}
    assert c.post("/api/detection/reset").json()["error"]
    assert c.get("/api/detection/frame/0").status_code == 404
    assert c.get("/api/state").json()["detection"] is None
    server.wire(None, None)


def test_status_frame_and_buttons_go_to_the_worker(worker_port):
    state = wire(worker_port)
    state.detection = {"enabled": True, "ok": True, "status": "ready", "count": 0, "cameras": []}
    c = TestClient(server.app)
    status = c.get("/api/detection/status").json()
    assert status["enabled"] and status["reachable"] and status["board"]["count"] == 1
    frame = c.get("/api/detection/frame/1")
    assert frame.status_code == 200 and frame.headers["content-type"] == "image/jpeg" and frame.content.startswith(b"\xff\xd8")
    assert c.post("/api/detection/reset").json() == {"ok": True}
    assert ("POST", "/api/reset") in CALLS and ("GET", "/frame/1.jpg") in CALLS
    assert c.get("/api/state").json()["detection"]["status"] == "ready"
    server.wire(None, None)


def test_reset_board_resets_the_detection_instead_of_the_cloud(worker_port):
    wire(worker_port)
    c = TestClient(server.app)
    assert c.post("/api/control/reset-board").json() == {"ok": True}
    assert ("POST", "/api/reset") in CALLS
    server.wire(None, None)


def test_a_worker_that_is_not_there_is_reported():
    wire(1)                                       # nothing listens on port 1
    c = TestClient(server.app)
    assert c.get("/api/detection/status").json() == {"enabled": True, "reachable": False}
    assert c.post("/api/detection/reset").json()["error"]
    server.wire(None, None)


def test_a_worker_that_waits_for_its_board_model_says_so():
    state = wire(1)                               # the worker serves no page while it has no model
    state.detection = {"enabled": True, "ok": False, "status": "no_model", "count": 0, "cameras": []}
    c = TestClient(server.app)
    assert c.get("/api/detection/status").json() == {"enabled": True, "reachable": False, "status": "no_model"}
    server.wire(None, None)


def test_a_correction_is_passed_on_to_the_detection_as_a_label(worker_port):
    import time
    wire(worker_port)
    server._move_board_dart(1, "T20")
    time.sleep(0.5)
    assert ("POST", "/api/label?index=1&field=T20") in CALLS
    server.wire(None, None)


def test_confirming_a_dart_goes_to_the_worker(worker_port):
    wire(worker_port)
    c = TestClient(server.app)
    assert c.post("/api/detection/confirm?index=0").json() == {"ok": True}
    assert ("POST", "/api/confirm?index=0") in CALLS
    server.wire(None, None)


def test_uncertain_darts_are_flagged_on_the_board_darts():
    from breakfast.board_darts import BoardDarts
    bd = BoardDarts()
    bd.set_connected(True)
    seg = {"name": "T20", "number": 20, "multiplier": 3}
    bd.update([{"segment": seg, "coords": {"x": 0.0, "y": 0.6}, "detection": {"uncertain": True}}, {"segment": seg, "coords": {"x": 0.1, "y": 0.6}}])
    shown = bd.snapshot()
    assert shown[0].get("uncertain") is True and "uncertain" not in shown[1]


def test_the_manual_adjustment_goes_through_to_the_worker(worker_port):
    wire(worker_port)
    c = TestClient(server.app)
    model = c.get("/api/detection/model").json()
    assert model["size"] == [800, 600] and model["can_revert"]
    assert c.post("/api/detection/model/move", json={"cam": 0, "id": "162@99", "xy": [1, 2]}).json()["size"] == [800, 600]
    assert any(k == "BODY" and b'"162@99"' in v for k, v in CALLS)
    assert c.post("/api/detection/model/discard").json()["size"] == [800, 600]
    assert c.post("/api/detection/model/auto").json() == {"ok": True}
    assert c.post("/api/detection/model/save").json() == {"ok": True}
    assert c.post("/api/detection/model/revert").json() == {"ok": True}
    assert {("POST", "/api/model/move"), ("POST", "/api/model/discard"), ("POST", "/api/model/save"), ("POST", "/api/model/revert"), ("POST", "/api/model/auto")} <= set(CALLS)
    server.wire(None, None)


def test_the_numbers_of_the_corrections_come_from_the_worker(worker_port):
    wire(worker_port)
    c = TestClient(server.app)
    assert c.get("/api/detection/labels").json() == {"looked_at": 4, "wrong": 1}
    server.wire(None, None)
    wire(None)
    assert c.get("/api/detection/labels").json()["error"]
    server.wire(None, None)


def test_a_correction_with_a_spot_passes_the_spot_to_the_label(worker_port):
    import time
    wire(worker_port)
    server._move_board_dart(0, "T20", {"x": 0.04, "y": 0.6})
    time.sleep(0.5)
    assert ("POST", "/api/label?index=0&field=T20&x=0.04&y=0.6") in CALLS
    server.wire(None, None)


def test_the_settings_are_read_changed_and_reset_through_the_worker(worker_port):
    wire(worker_port)
    c = TestClient(server.app)
    assert c.get("/api/detection/settings").json() == {"settings": [{"key": "settle_s", "value": 0.35}]}
    assert c.post("/api/detection/settings", json={"settle_s": 0.5}).json() == {"applied": {"settle_s": 0.5}, "refused": {}}
    assert ("BODY", b'{"settle_s": 0.5}') in CALLS or any(k == "BODY" and b"settle_s" in v for k, v in CALLS)
    assert c.post("/api/detection/settings/reset").json() == {"settings": [{"key": "settle_s", "value": 0.35}]}
    server.wire(None, None)
    wire(None)
    assert c.get("/api/detection/settings").json()["error"] and c.post("/api/detection/settings", json={}).json()["error"]
    server.wire(None, None)


def test_the_reference_of_the_drift_check_is_taken_only_on_an_empty_board(worker_port, monkeypatch):
    wire(worker_port)
    c = TestClient(server.app)
    assert c.post("/api/detection/drift/accept").json() == {"ok": True}
    monkeypatch.setattr(sys.modules[__name__], "EMPTY_BOARD_REFUSED", True)
    assert c.post("/api/detection/drift/accept").json() == {"error": "The board is not empty."}
    server.wire(None, None)


def test_a_bounce_and_a_mark_go_to_the_worker(worker_port):
    wire(worker_port)
    c = TestClient(server.app)
    assert c.post("/api/detection/bouncer").json() == {"ok": True}
    assert c.post("/api/detection/mark").json() == {"ok": True}
    assert ("POST", "/api/bouncer") in CALLS and ("POST", "/api/mark") in CALLS
    assert server.run_control("detect_bouncer") == {"ok": True}
    server.wire(None, None)
    assert server.run_control("detect_mark")["error"] == "dart detection is off"


def test_a_confirm_key_asks_the_worker_only_for_a_dart_in_doubt(worker_port):
    state = wire(worker_port)
    state.board_darts.set_connected(True)
    seg = {"name": "T20", "number": 20, "multiplier": 3}
    state.board_darts.update([{"segment": seg, "coords": {"x": 0.0, "y": 0.6}},
                              {"segment": seg, "coords": {"x": 0.1, "y": 0.6}, "detection": {"uncertain": True}}])
    assert server._uncertain_flags() == [False, True]
    assert server.run_control("confirm_dart:1") == {"ok": True} and ("POST", "/api/confirm?index=0") not in CALLS
    assert server.run_control("confirm_dart:3") == {"ok": True} and ("POST", "/api/confirm?index=2") not in CALLS      # no third dart yet
    assert server.run_control("confirm_dart:2") == {"ok": True} and ("POST", "/api/confirm?index=1") in CALLS
    assert server.run_control("confirm_dart:4")["error"] == "bad dart confirmation"
    server.wire(None, None)


@pytest.fixture
def camera_folder(tmp_path, monkeypatch):
    """A folder of cameras like the one the udev rule fills (two are plugged in) and a config file to save the choice in."""
    from breakfast.detection import devices
    folder = tmp_path / "video"
    folder.mkdir()
    for port in ("1.1.1", "1.1.3"):
        (folder / port).write_text("")
    monkeypatch.setattr(devices, "VIDEO_DIR", str(folder))
    monkeypatch.setattr(devices, "snapshot", lambda path: b"\xff\xd8" + path.encode() if path.endswith("1.1.1") else None)
    config = tmp_path / "config.toml"
    config.write_text("")
    server.wire(GameState(), EliminationController(FakeMqttPub(), "autodarts"), config_path=str(config))
    yield TestClient(server.app), config
    server.wire(None, None)


def test_the_cameras_are_listed_with_the_ones_plugged_in_and_empty_slots_without_a_choice(camera_folder):
    c, _ = camera_folder
    assert c.get("/api/detection/cameras").json() == {"slots": [{"index": i, "port": None, "found": False} for i in range(3)], "found": ["1.1.1", "1.1.3"]}
    assert c.get("/api/config").json()["cameras"]["ports"] is None


def test_a_saved_choice_shows_which_camera_is_missing(camera_folder):
    c, config = camera_folder
    assert c.patch("/api/config", json={"cameras": {"ports": ["1.1.1", "1.1.2", "1.1.3"]}}).json() == {"saved": True, "restart_required": ["cameras.ports"]}
    assert "1.1.2" in config.read_text()
    assert c.get("/api/config").json()["cameras"]["ports"] == ["1.1.1", "1.1.2", "1.1.3"]
    slots = c.get("/api/detection/cameras").json()["slots"]
    assert [(s["port"], s["found"]) for s in slots] == [("1.1.1", True), ("1.1.2", False), ("1.1.3", True)]


@pytest.mark.parametrize("ports", [["1.1.1", "1.1.1", "1.1.3"], ["1.1.1", "1.1.3"], ["1.1.1", "x", "1.1.3"], "1.1.1"])
def test_a_choice_that_is_not_three_different_ports_is_refused(camera_folder, ports):
    c, config = camera_folder
    assert c.patch("/api/config", json={"cameras": {"ports": ports}}).json() == {"saved": False, "error": "Choose three different cameras"}
    assert config.read_text() == ""


def test_a_camera_picture_comes_from_the_device_and_only_for_cameras_that_are_there(camera_folder):
    c, _ = camera_folder
    ok = c.get("/api/detection/cameras/frame/1.1.1")
    assert ok.status_code == 200 and ok.content.startswith(b"\xff\xd8") and ok.headers["cache-control"] == "no-store"
    assert c.get("/api/detection/cameras/frame/1.1.3").status_code == 503        # present but cannot be opened
    assert c.get("/api/detection/cameras/frame/1.1.2").status_code == 404        # not plugged in
    assert c.get("/api/detection/cameras/frame/..%2Fetc").status_code == 404


def test_a_camera_the_running_detection_has_is_shown_from_its_picture(camera_folder, worker_port):
    c, _ = camera_folder
    c.patch("/api/config", json={"cameras": {"ports": ["1.1.3", "1.1.1", "1.1.5"]}})
    server.wire(GameState(), EliminationController(FakeMqttPub(), "autodarts"), detection_port=worker_port, config_path=str(camera_folder[1]))
    r = c.get("/api/detection/cameras/frame/1.1.1")
    assert r.status_code == 200 and ("GET", "/frame/1.jpg?raw=1") in CALLS
