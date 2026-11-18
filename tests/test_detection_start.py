"""The dart detection is switched on but cannot start: no board model, no cameras, packages missing. Breakfast keeps running."""
import json
import logging
import sys
import threading
import time
from pathlib import Path

from breakfast import source_direct
from breakfast.detection import cameras, source, worker
from tests.test_detection import model

ROOT = Path(__file__).resolve().parent.parent


class Out:
    """The queue to Breakfast; `on_put` runs with every message."""

    def __init__(self, on_put=None):
        self.messages, self.on_put = [], on_put

    def put(self, msg):
        self.messages.append(msg)
        if self.on_put:
            self.on_put(len(self.messages))


def test_a_missing_board_model_is_waited_for_and_reported(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(worker, "MODEL_WAIT_S", 0.01)
    path = tmp_path / "detection" / "calib_model.json"

    def write_on_third(n):
        if n == 3:
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(model().to_json()))

    out = Out(write_on_third)
    with caplog.at_level(logging.WARNING, logger="breakfast.detection"):
        assert worker.wait_for_model({"dir": str(tmp_path / "detection")}, out) is True
    assert out.messages == [{"type": "worker", "ok": False, "status": "no_model", "count": 0, "cameras": []}] * 3
    assert len([r for r in caplog.records if "board model" in r.getMessage()]) == 1           # said once, not with every look


def test_a_broken_board_model_does_not_end_the_worker(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "MODEL_WAIT_S", 0.01)
    path = tmp_path / "calib_model.json"
    path.write_text("{not json")
    stop = threading.Event()
    out = Out(lambda n: stop.set() if n == 2 else None)
    assert worker.wait_for_model({"model": str(path)}, out, stop) is False
    assert [m["status"] for m in out.messages] == ["no_model", "no_model"]


def test_a_model_that_is_there_starts_at_once(tmp_path):
    path = tmp_path / "calib_model.json"
    path.write_text(json.dumps(model().to_json()))
    out = Out()
    assert worker.wait_for_model({"model": str(path)}, out) is True
    assert out.messages == []


def test_a_worker_that_keeps_ending_is_restarted_more_and_more_slowly():
    pause, pauses = source.RESTART_S / 2, []
    for _ in range(7):
        pause = source.next_pause(pause, ran_s=0.5)
        pauses.append(pause)
    assert pauses == [3.0, 6.0, 12.0, 24.0, 48.0, 60.0, 60.0]
    assert source.next_pause(60.0, ran_s=source.STABLE_S + 1) == source.RESTART_S      # it ran fine for a while: quick again


def test_a_detection_that_cannot_be_loaded_leaves_breakfast_running(monkeypatch, caplog):
    monkeypatch.setitem(sys.modules, "breakfast.detection.source", None)               # the import fails, as without OpenCV
    with caplog.at_level(logging.ERROR):
        assert source_direct._camera_source({"enabled": True}, lambda data: None, lambda ok: None) is None
    assert "cannot be loaded" in caplog.text


def test_a_camera_that_cannot_be_opened_is_logged_once(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(cameras, "RETRY_S", 0.01)

    class Closed:
        def isOpened(self):
            return False

        def release(self):
            pass

    tries = []
    cam = cameras.V4L2Camera(str(tmp_path / "no-camera"))
    monkeypatch.setattr(cam, "_open", lambda: tries.append(1) or Closed())
    with caplog.at_level(logging.WARNING):
        cam.start()
        deadline = time.monotonic() + 2.0
        while len(tries) < 4 and time.monotonic() < deadline:
            time.sleep(0.01)
        cam.stop()
    assert len(tries) >= 4 and cam.error == "not found"
    assert len([r for r in caplog.records if "cannot open" in r.getMessage()]) == 1


def test_a_camera_that_is_there_but_cannot_be_opened_is_in_use(tmp_path, monkeypatch):
    class Closed:
        def isOpened(self):
            return False

        def release(self):
            pass

    device = tmp_path / "video0"
    device.write_text("")
    cam = cameras.V4L2Camera(str(device))
    monkeypatch.setattr(cam, "_open", lambda: Closed())
    cam.start()
    deadline = time.monotonic() + 2.0
    while cam.error == "starting" and time.monotonic() < deadline:
        time.sleep(0.01)
    cam.stop()
    assert cam.error == "in use"


def test_a_camera_that_cannot_be_read_shows_as_no_cameras():
    fine, broken = {"error": None, "fps": 30.0}, {"error": "cannot open", "fps": 0.0}
    assert worker.board_status("ready", [fine, fine, fine]) == "ready"
    assert worker.board_status("starting", [fine, broken, fine]) == "no_cameras"


def test_no_default_fits_one_machine_only():
    assert worker.DEFAULT_DEVICES == ["/dev/cam0", "/dev/cam1", "/dev/cam2"]
    for name in ("config.toml.example", "docker-compose.detection.yml", "tools/detection_deploy.sh"):
        text = (ROOT / name).read_text()
        assert "pci-0000" not in text and "/dev/video1" not in text, name
