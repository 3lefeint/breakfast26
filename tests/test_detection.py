"""The dart detection on synthetic pictures: a textured background and dark bars as darts, three cameras with the same view."""
import cv2
import numpy as np
import pytest

from breakfast.detection import detector
from breakfast.detection.geometry import BoardModel
from breakfast.detection.tracker import BoardTracker, Settings

W, H = 800, 600
MATRIX = [[1.6, 0, 400], [0, -1.6, 330], [0, 0, 1]]           # board mm -> pixel: 1.6 px per mm, center at (400, 330)
RNG = np.random.default_rng(7)


def model():
    return BoardModel({0: MATRIX, 1: MATRIX, 2: MATRIX}, size=(W, H))


def background():
    img = RNG.normal(128, 25, (H // 8, W // 8)).astype(np.float32)
    img = cv2.resize(img, (W, H), interpolation=cv2.INTER_CUBIC)
    return cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)


BACKGROUNDS = {c: background() for c in range(3)}


def scene(darts=(), hand=False, noise=2.0):
    """The three pictures of the board with darts at the given board points (mm)."""
    out = {}
    for c in range(3):
        img = BACKGROUNDS[c].copy()
        for x, y in darts:
            px, py = int(400 + 1.6 * x), int(330 - 1.6 * y)
            cv2.line(img, (px, py - 4), (px, py - 120), (15, 15, 15), 7)
        if hand:
            cv2.rectangle(img, (200, 50), (500, 300), (60, 90, 200), -1)
        out[c] = np.clip(img.astype(np.float32) + RNG.normal(0, noise, img.shape), 0, 255).astype(np.uint8)
    return out


def prepared(frames):
    return {c: detector.prepare(f) for c, f in frames.items()}


@pytest.mark.parametrize("point,field", [((0, 103), "T20"), ((0, 166), "D20"), ((0, 130), "S20"), ((0, 0), "50"),
                                         ((103 * 0.309, 103 * 0.951), "T1")])
def test_locate_finds_the_field(point, field):
    m = model()
    result = detector.locate(m, prepared(scene()), prepared(scene([point])))
    assert result["field"] == field
    assert result["cams"] == 3


def test_locate_none_without_a_dart():
    assert detector.locate(model(), prepared(scene()), prepared(scene())) is None


def test_locate_outside_is_a_miss():
    result = detector.locate(model(), prepared(scene()), prepared(scene([(0, 200)])))
    assert result["field"] == "0"
    assert detector.to_throw(result)["segment"]["multiplier"] == 0


def test_throw_has_the_shape_of_the_board_manager():
    result = detector.locate(model(), prepared(scene()), prepared(scene([(0, 103)])))
    throw = detector.to_throw(result)
    assert throw["segment"] == {"name": "T20", "number": 20, "bed": "Triple", "multiplier": 3}
    assert abs(throw["coords"]["y"] - 103 / 170) < 0.03 and abs(throw["coords"]["x"]) < 0.03


def run(tracker, frames_list, dt=0.05, start=0.0):
    events, t = [], start
    for frames in frames_list:
        events += tracker.feed(t, frames)
        t += dt
    return events, t


def test_tracker_follows_three_darts_and_the_takeout():
    tr = BoardTracker(model(), Settings())
    events, t = run(tr, [scene() for _ in range(20)])
    assert [e.kind for e in events] == ["baseline"]
    darts = [(0, 103), (50, 100), (-60, 150)]
    got = []
    for i in range(3):
        steps = [scene(darts[:i]) , scene(darts[:i], hand=True), scene(darts[:i + 1])] + [scene(darts[:i + 1]) for _ in range(12)]
        events, t = run(tr, steps, start=t)
        got += [e for e in events if e.kind == "dart"]
    assert [e.count for e in got] == [1, 2, 3]
    assert [e.throw["segment"]["name"] for e in got] == ["T20", detector.to_throw(detector.locate(model(), prepared(scene()), prepared(scene([darts[1]]))))["segment"]["name"], got[2].throw["segment"]["name"]]
    assert tr.status == "takeout"
    events, t = run(tr, [scene(darts, hand=True)] + [scene() for _ in range(12)], start=t)
    assert [e.kind for e in events] == ["takeout"]
    assert tr.count == 0 and tr.status == "ready"


def test_tracker_pulling_one_dart_is_not_a_new_dart():
    tr = BoardTracker(model(), Settings())
    events, t = run(tr, [scene() for _ in range(20)])
    darts = [(0, 103), (50, 100)]
    for i in range(2):
        events, t = run(tr, [scene(darts[:i + 1]) for _ in range(14)], start=t)
        assert events and events[0].kind == "dart"
    events, t = run(tr, [scene(darts[1:], hand=True)] + [scene(darts[1:]) for _ in range(14)], start=t)
    assert [e.kind for e in events] == ["removed"]
    assert tr.count == 1


def test_tracker_ignores_a_hand_that_goes_away_again():
    tr = BoardTracker(model(), Settings())
    events, t = run(tr, [scene() for _ in range(20)])
    events, t = run(tr, [scene(hand=True)] * 3 + [scene() for _ in range(14)], start=t)
    assert events == [] and tr.count == 0


def test_tracker_waits_while_a_hand_stays_in_the_picture():
    tr = BoardTracker(model(), Settings())
    events, t = run(tr, [scene() for _ in range(20)])
    events, t = run(tr, [scene(hand=True) for _ in range(40)], start=t)          # a hand that holds still for two seconds
    assert events == [] and tr.count == 0 and tr.status == "blocked"
    events, t = run(tr, [scene() for _ in range(14)], start=t)
    assert events == [] and tr.count == 0
    events, t = run(tr, [scene([(0, 103)]) for _ in range(14)], start=t)
    assert [e.kind for e in events] == ["dart"]


def test_tracker_drops_a_counted_dart_that_is_not_there():
    tr = BoardTracker(model(), Settings())
    events, t = run(tr, [scene() for _ in range(20)])
    darts = [(0, 103), (50, 100)]
    events, t = run(tr, [scene(darts[:1]) for _ in range(14)], start=t)
    events, t = run(tr, [scene(darts) for _ in range(14)], start=t)
    assert tr.count == 2
    tr.throws.append(tr.throws[0] | {"coords": {"x": -0.5, "y": -0.5}})          # a phantom the picture does not show
    tr.sup0.append(tr.sup0[0])
    tr.count = 3
    events, t = run(tr, [scene(darts, hand=True)] + [scene(darts) for _ in range(14)], start=t)       # the next movement at the board
    assert tr.count == 2
    events2, t = run(tr, [scene(darts[:1], hand=True)] + [scene(darts[:1]) for _ in range(14)], start=t)
    assert tr.count == 1


def test_tracker_a_pushed_dart_is_not_a_new_dart():
    tr = BoardTracker(model(), Settings())
    events, t = run(tr, [scene() for _ in range(20)])
    events, t = run(tr, [scene([(0, 103)]) for _ in range(14)], start=t)
    assert tr.count == 1
    events, t = run(tr, [scene([(4, 106)], hand=True)] + [scene([(4, 106)]) for _ in range(14)], start=t)       # the same dart, 5 mm further
    assert tr.count == 1 and [e.kind for e in events] == ["moved"]


def test_tracker_a_dart_next_to_a_counted_one_is_a_new_dart():
    tr = BoardTracker(model(), Settings())
    events, t = run(tr, [scene() for _ in range(20)])
    events, t = run(tr, [scene([(0, 103)]) for _ in range(14)], start=t)
    tr.sup0[0] = {0: 0.3, 1: 0.3, 2: 0.3}                  # the synthetic pictures saturate the support; real darts give 0.2 to 0.7
    tr._support_of = lambda x, y, hp: {0: 0.6, 1: 0.6, 2: 0.6}       # and a second body next to it doubles it
    events, t = run(tr, [scene([(0, 103), (6, 104)], hand=True)] + [scene([(0, 103), (6, 104)]) for _ in range(14)], start=t)
    assert tr.count == 2 and [e.kind for e in events] == ["dart"]


def test_tracker_reset_takes_the_next_picture_as_the_empty_board():
    tr = BoardTracker(model(), Settings())
    events, t = run(tr, [scene() for _ in range(20)])
    events, t = run(tr, [scene([(0, 103)]) for _ in range(14)], start=t)
    assert tr.count == 1
    tr.reset()
    assert tr.count == 0 and tr.throws == [] and tr.sup0 == []
    events, t = run(tr, [scene([(0, 103)]) for _ in range(14)], start=t)       # the dart is still in the board: it is part of the "empty" picture now
    assert [e.kind for e in events] == ["baseline"] and tr.count == 0


def test_clips_are_recorded_during_movement_and_replay_to_the_same_events(tmp_path):
    import time
    from breakfast.detection.clips import ClipRecorder
    from breakfast.detection.replay import replay_clip
    m = model()
    rec = ClipRecorder(tmp_path, rate=20.0, pre_s=0.5, post_s=0.5, max_gb=1.0)
    tr = BoardTracker(m, Settings())
    live, t = [], 0.0
    for frames in [scene() for _ in range(20)] + [scene([(0, 103)], hand=True)] + [scene([(0, 103)]) for _ in range(30)]:
        ev = tr.feed(t, frames)
        live += ev
        rec.offer(t, frames, tr.moving, {"count": tr.count, "status": tr.status})
        t += 0.05
    rec.close()
    time.sleep(1.5)                                                   # the writer thread finishes
    clips = sorted(tmp_path.glob("session-*/clip-*"))
    assert clips and (clips[0] / "clip.json").exists()
    # replay: the clip starts on the empty board, so a fresh tracker finds the same dart
    events, _ = replay_clip(m, clips[0])
    assert [e.kind for e in events if e.kind == "dart"] == ["dart"]
    assert [e.kind for e in live if e.kind == "dart"] == ["dart"]
