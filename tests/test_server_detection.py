import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from starlette.testclient import TestClient

from breakfast.elimination import EliminationController
from breakfast.state import GameState
from breakfast.web import server
from tests.test_target_battle import FakeMqttPub

CALLS = []


class FakeWorker(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        CALLS.append(("GET", self.path))
        if self.path == "/api/model":
            body, ctype = json.dumps({"size": [800, 600], "ref": {"0": [[1, 2]] * 4}, "radii": {"170": 170.0}, "can_revert": True}).encode(), "application/json"
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
