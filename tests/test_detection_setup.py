"""The first setup of the dart detection: the search for the board in a picture, the turn by the click on the 20, and the steps of the
setup session. The pictures are a board drawn from above and warped to a camera view."""
import math
import threading
import time

import cv2
import numpy as np
import pytest

from breakfast.detection import boardsearch, calibration, setup, worker
from breakfast.detection.geometry import BoardModel, board_pt

PX_PER_MM = 3.0
CENTER = 350


def top_view():
    """The board from above, 700 x 700 px: light and dark single fields (20 dark), duller rings in the same order, a dark surround."""
    img = np.full((700, 700), 12, np.uint8)
    for k in range(20):
        a0, a1 = 18 * k - 9, 18 * k + 9
        for r0, r1, ring in ((16, 99, False), (99, 107, True), (107, 162, False), (162, 170, True)):
            shade = (30 if k % 2 == 0 else 225) if not ring else (70 if k % 2 == 0 else 160)       # the rings are red and green: duller, same order
            pts = [board_pt(r0, a) for a in np.linspace(a0, a1, 6)] + [board_pt(r1, a) for a in np.linspace(a1, a0, 6)]
            poly = np.array([[CENTER + x * PX_PER_MM, CENTER - y * PX_PER_MM] for x, y in pts], np.int32)
            cv2.fillPoly(img, [poly], int(shade))
    cv2.circle(img, (CENTER, CENTER), int(15.9 * PX_PER_MM), 120, -1)
    return img


def camera_view(quad, size=(800, 600)):
    """The board picture seen from a camera: returns (BGR picture, board millimetres to pixels)."""
    src = np.float32([[0, 0], [700, 0], [700, 700], [0, 700]])
    Hview = cv2.getPerspectiveTransform(src, np.float32(quad))
    picture = cv2.warpPerspective(top_view(), Hview, size, borderValue=10)
    picture = cv2.GaussianBlur(picture, (0, 0), 1.2)
    Htop = np.array([[PX_PER_MM, 0, CENTER], [0, -PX_PER_MM, CENTER], [0, 0, 1.0]])
    return cv2.cvtColor(picture, cv2.COLOR_GRAY2BGR), Hview @ Htop


QUAD = [[190, 150], [610, 140], [680, 480], [120, 470]]          # a view from the side and a little to one side


@pytest.fixture(scope="module")
def view():
    return camera_view(QUAD)


def wires_error(H, truth):
    """Mean distance of the four reference points, for the best turn by a multiple of 18 degrees."""
    r = boardsearch.reference_points(truth)
    return min(float(np.linalg.norm(boardsearch.reference_points(boardsearch._turn(H, 18 * k)) - r, axis=1).mean()) for k in range(20))


def test_the_search_finds_a_board_without_a_model(view):
    """A board drawn from above is much simpler than a real one (nothing pins down its size), so only the place is checked here; on
    pictures of a real board the reference points came out within 2 to 5 pixels of a model made by hand."""
    picture, truth = view
    found = boardsearch.find_board(picture)
    assert found is not None
    assert found["agree"] >= boardsearch.MIN_AGREE
    cx, cy = calibration.project(found["H"], np.array([[0.0, 0.0]]))[0]
    tx, ty = calibration.project(truth, np.array([[0.0, 0.0]]))[0]
    assert math.hypot(cx - tx, cy - ty) < 30


def test_the_click_on_the_20_turns_the_board_to_its_place(view):
    _, truth = view
    for turn in (0, 36, -90, 162, 18 * 7):                           # whichever of the 20 positions the search left
        H = boardsearch._turn(truth, turn)
        x, y = calibration.project(truth, np.array([board_pt(110, 0)]))[0]       # the middle of the 20, a little off
        fixed = boardsearch.turn_for_click(H, (x + 6, y + 4))
        assert float(np.linalg.norm(boardsearch.reference_points(fixed) - boardsearch.reference_points(truth), axis=1).mean()) < 1e-6


@pytest.mark.parametrize("make", [lambda: np.random.default_rng(0).integers(0, 255, (600, 800, 3), dtype=np.uint8),
                                  lambda: np.full((600, 800, 3), 5, np.uint8)])
def test_a_picture_without_a_board_finds_nothing(make):
    assert boardsearch.find_board(make()) is None


def test_the_drawing_marks_the_20(view):
    picture, truth = view
    plain, marked = boardsearch.draw(picture, truth), boardsearch.draw(picture, truth, marked=True)
    assert plain.shape == picture.shape
    assert not np.array_equal(plain, marked)


# ---------------------------------------------------------------------- the session


class Out:
    def __init__(self):
        self.messages = []

    def put(self, msg):
        self.messages.append(msg)


@pytest.fixture
def session(tmp_path, view):
    """A setup session on a folder of pictures as its three cameras."""
    picture, truth = view
    devices = []
    for i in range(3):
        folder = tmp_path / f"cam{i}"
        folder.mkdir()
        cv2.imwrite(str(folder / "0.jpg"), picture)
        devices.append(str(folder))
    s = setup.SetupSession({"devices": devices, "dir": str(tmp_path / "det")}, tmp_path / "det" / "calib_model.json", Out())
    deadline = time.time() + 5
    while len(s.cams.latest_frames()) < 3 and time.time() < deadline:
        time.sleep(0.05)
    yield s, truth
    s.cams.stop()


def wait(s):
    deadline = time.time() + 120
    while s.busy and time.time() < deadline:
        time.sleep(0.1)
    assert not s.busy


def test_the_steps_of_the_setup(session, monkeypatch):
    s, truth = session
    monkeypatch.setattr(boardsearch, "find_board", lambda frame, progress=None: {"H": boardsearch._turn(truth, 54), "score": 0.3, "agree": 9})
    st = s.status()
    assert st["mode"] == "setup" and st["board"]["status"] == "no_model" and st["setup"]["ready"] is False
    assert s.click(0, 100, 100) is False                           # nothing found yet
    assert s.search() is True
    wait(s)
    st = s.status()["setup"]
    assert [c["found"] for c in st["cameras"]] == [True, True, True] and st["problem"] is None
    assert s.fit() is True                                         # not every picture has its click: refused after the start
    wait(s)
    assert s.status()["setup"]["problem"]["kind"] == "not_ready"
    x, y = calibration.project(truth, np.array([board_pt(110, 0)]))[0]
    for c in range(3):
        assert s.click(c, float(x), float(y))
    st = s.status()["setup"]
    assert st["ready"] is True and all(c["clicked"] for c in st["cameras"])
    assert s.jpeg(0) is not None and s.jpeg(7) is None

    seen = {}

    def fake_fit(homographies, frames, progress=None):
        seen["H"] = homographies
        return BoardModel(homographies, None, (800, 600)), {"kept_search_result": []}

    monkeypatch.setattr(boardsearch, "fit_model", fake_fit)
    assert s.fit() is True
    wait(s)
    assert s.done.is_set() and s.model_path.exists()
    assert wires_error(seen["H"][0], truth) < 1e-6
    assert np.allclose(boardsearch.reference_points(seen["H"][0]), boardsearch.reference_points(truth), atol=1e-6)      # turned back by the click
    assert BoardModel.from_file(s.model_path).cams == [0, 1, 2]


def test_the_fit_starts_from_other_sizes_of_the_model_too(monkeypatch):
    """A model a tenth too small sits on the ring next to the right one: the search must start from larger and smaller ones too."""
    ref = np.array([[300.0, 200.0], [500.0, 220.0], [480.0, 400.0], [280.0, 380.0]])
    center = calibration.project(calibration.homography_from(ref), np.array([[0.0, 0.0]]))[0]
    target = center + (ref - center) * 1.1                           # where the board really is
    started = []
    corners = np.array([board_pt(170, a) for a in (9, 99, 189, 279)])
    monkeypatch.setattr(calibration, "score", lambda emap, H, radii: -float(np.abs(calibration.project(H, corners) - target).mean()))
    monkeypatch.setattr(calibration, "edge_map", lambda gray, sigma: gray)
    monkeypatch.setattr(calibration, "_search_h", lambda gray, start, radii, scales, anchor=None, limit=None: (started.append(start) or (start, 0.0)))
    frames = {0: np.zeros((600, 800, 3), np.uint8)}
    try:
        calibration.fit(frames, {0: ref}, {170.0: 170.0, 162.0: 162.0, 107.0: 107.0, 99.0: 99.0})
    except Exception:
        pass                                                         # the fine scales run on the fake maps: only the starts matter
    assert len(started) == calibration.STARTS_KEPT
    assert min(float(np.abs(st - target).mean()) for st in started) < 3.0        # a start at the 1.1 times larger model is among them


def test_a_camera_the_fit_moved_far_keeps_its_search_result(view, monkeypatch):
    _, truth = view
    frames = {0: view[0], 1: view[0]}
    homographies = {0: truth, 1: truth}
    moved = boardsearch._turn(truth, 5)
    fitted = BoardModel({0: moved, 1: moved}, None, (800, 600))
    monkeypatch.setattr(calibration, "calibrate", lambda model, f, progress=None, limit=None: (fitted, {"moved_px": {"0": 3.0, "1": 15.9}}))
    monkeypatch.setattr(boardsearch, "pattern_score", lambda img, H: 1.0)        # the pattern does not object: only the length of the move
    model, report = boardsearch.fit_model(homographies, frames)
    assert report["kept_search_result"] == [1]
    assert np.allclose(model.H[0], moved) and np.allclose(model.H[1], truth)


def test_the_pictures_of_a_search_are_kept(session, monkeypatch):
    s, truth = session
    monkeypatch.setattr(boardsearch, "find_board", lambda frame, progress=None: {"H": truth, "score": 0.3, "agree": 9})
    s.search()
    wait(s)
    assert len(list((s.model_path.parent / "setup").glob("*-cam*.jpg"))) == 3


def test_a_second_job_is_refused_while_one_runs(session, monkeypatch):
    s, _ = session
    release = threading.Event()
    monkeypatch.setattr(boardsearch, "find_board", lambda frame, progress=None: release.wait(5) and None)
    assert s.search() is True
    assert s.search() is False
    release.set()
    wait(s)


def test_a_board_that_is_not_found_is_reported_per_camera(session, monkeypatch):
    s, _ = session
    monkeypatch.setattr(boardsearch, "find_board", lambda frame, progress=None: None)
    s.search()
    wait(s)
    assert s.status()["setup"]["problem"] == {"kind": "not_found", "cams": [0, 1, 2]}


def test_the_worker_sets_up_first_when_there_is_no_model(tmp_path, monkeypatch):
    calls = []
    model_file = tmp_path / "calib_model.json"

    def fake_setup(cfg, path, out):
        calls.append(path)
        model_file.write_text('{"H": {}}')

    monkeypatch.setattr(setup, "run_setup", fake_setup)
    monkeypatch.setattr(worker, "wait_for_model", lambda cfg, out, stop=None: True)

    class Stop(Exception):
        pass

    def no_worker(cfg, out):
        raise Stop

    monkeypatch.setattr(worker, "Worker", no_worker)
    with pytest.raises(Stop):
        worker.run({"model": str(model_file)}, Out())
    assert calls == [model_file]
    calls.clear()
    with pytest.raises(Stop):                                      # a model exists: no setup
        worker.run({"model": str(model_file)}, Out())
    assert calls == []
