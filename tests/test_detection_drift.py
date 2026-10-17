from types import SimpleNamespace

import cv2
import numpy as np

from breakfast.detection import detector, drift
from breakfast.detection.worker import Worker
from tests.test_detection import model, scene


def prep(frames):
    return {c: detector.prepare(f) for c, f in frames.items()}


def shifted(frames, dx, dy):
    """The same pictures with the camera moved by (dx, dy) pixels."""
    m = np.float32([[1, 0, dx], [0, 1, dy]])
    return {c: cv2.warpAffine(f, m, (f.shape[1], f.shape[0]), borderMode=cv2.BORDER_REFLECT) for c, f in frames.items()}


class TestMeasure:
    def test_the_same_board_is_ok(self):
        base = scene(noise=0.0)
        result = drift.measure(model(), prep(base), prep(scene(noise=2.0)))
        assert drift.worst(result) == "ok" and all(r["px"] < 1.0 for r in result.values())

    def test_a_moved_camera_is_found_with_its_size(self):
        base = scene(noise=0.0)
        small = drift.measure(model(), prep(base), prep(shifted(base, 3, 0)))
        assert drift.worst(small) == "warn" and all(abs(r["px"] - 3.0) < 0.5 for r in small.values())
        big = drift.measure(model(), prep(base), prep(shifted(base, 4, 5)))
        assert drift.worst(big) == "bad"

    def test_one_moved_camera_makes_the_set_warn(self):
        base = scene(noise=0.0)
        moved = {**base, 1: shifted(base, 3, 2)[1]}
        result = drift.measure(model(), prep(base), prep(moved))
        assert [result[c]["level"] for c in (0, 1, 2)] == ["ok", "warn", "ok"] and drift.worst(result) == "warn"

    def test_a_different_picture_says_nothing(self):
        base = scene(noise=0.0)
        other = {c: np.roll(f, 0, axis=0) for c, f in scene([(0, 103), (50, 100)], hand=True).items()}
        result = drift.measure(model(), prep(base), prep(other))
        assert all(r["level"] in ("unknown", "ok", "warn", "bad") for r in result.values())
        assert drift.worst({0: {"level": "unknown"}}) == "unknown"

    def test_the_reference_is_stored_and_read_back(self, tmp_path):
        base = prep(scene(noise=0.0))
        assert drift.load_reference(tmp_path / "reference", [0, 1, 2]) is None
        drift.save_reference(tmp_path / "reference", base)
        back = drift.load_reference(tmp_path / "reference", [0, 1, 2])
        assert all((back[c] == base[c]).all() for c in base)


class TestWorkerCheck:
    def stub(self, tmp_path):
        stub = SimpleNamespace(base=tmp_path, model=model(), drift=None, _reference_due=False, notes=[])
        stub.note = stub.notes.append
        return stub

    def test_the_first_empty_board_is_the_reference_then_a_move_is_reported_once(self, tmp_path):
        w = self.stub(tmp_path)
        base = scene(noise=0.0)
        Worker._check_drift(w, base)
        assert w.drift["level"] == "ok" and len(w.notes) == 1 and (tmp_path / "reference" / "cam0.png").exists()
        Worker._check_drift(w, scene(noise=2.0))
        assert w.drift["level"] == "ok" and len(w.notes) == 1
        Worker._check_drift(w, shifted(base, 4, 3))
        assert w.drift["level"] == "bad" and len(w.notes) == 2 and "Drift" in w.notes[-1]
        Worker._check_drift(w, shifted(base, 4, 3))
        assert len(w.notes) == 2                                     # the same finding is not reported again

    def test_a_new_model_makes_the_next_empty_board_the_reference(self, tmp_path):
        w = self.stub(tmp_path)
        base = scene(noise=0.0)
        Worker._check_drift(w, base)
        w._reference_due = True
        Worker._check_drift(w, shifted(base, 4, 3))
        assert w.drift["level"] == "ok" and not w._reference_due
        Worker._check_drift(w, shifted(base, 4, 3))
        assert w.drift["level"] == "ok"                              # measured against the new reference
