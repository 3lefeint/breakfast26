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
        if hand is True or (hand and c in hand):
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
    assert all(set(e.info["timing"]) == {"moving_s", "still_s", "work_ms"} and e.info["timing"]["still_s"] >= tr.s.settle_s for e in got)
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
    events, t = run(tr, [scene(hand=True) for _ in range(80)], start=t)          # a hand that holds still for four seconds
    assert events == [] and tr.count == 0 and tr.status == "blocked"
    events, t = run(tr, [scene() for _ in range(14)], start=t)
    assert [e.kind for e in events] == ["blocked"] and tr.count == 0 and tr.status == "ready"
    assert events[0].info["seconds"] >= 3 and events[0].after
    events, t = run(tr, [scene([(0, 103)]) for _ in range(14)], start=t)
    assert [e.kind for e in events] == ["dart"]


def test_a_dart_is_counted_while_an_arm_covers_one_camera():
    tr = BoardTracker(model(), Settings())
    events, t = run(tr, [scene() for _ in range(20)])
    events, t = run(tr, [scene([(0, 103)], hand=(1,)) for _ in range(14)], start=t)
    assert [e.kind for e in events] == ["dart"] and tr.count == 1
    assert events[0].throw["detection"]["cams"] == 2 and events[0].throw["detection"]["uncertain"]
    assert tr.status != "blocked"


def test_a_block_that_is_taken_as_it_is_is_logged_with_its_trace():
    tr = BoardTracker(model(), Settings())
    events, t = run(tr, [scene() for _ in range(20)])
    events, t = run(tr, [scene(hand=True) for _ in range(400)], start=t)
    kinds = [e.kind for e in events]
    assert "blocked" in kinds and "unclear" in kinds and tr.status == "ready"
    b = next(e for e in events if e.kind == "blocked")
    assert b.info["accepted"] and b.info["looks"] == tr.s.patience and b.info["peak"] and b.info["trace"] and b.before and b.after


def test_a_short_block_is_not_logged_but_the_state_goes_back():
    tr = BoardTracker(model(), Settings(block_log_s=60.0))
    events, t = run(tr, [scene() for _ in range(20)])
    events, t = run(tr, [scene(hand=True) for _ in range(80)], start=t)
    assert tr.status == "blocked"
    events, t = run(tr, [scene() for _ in range(14)], start=t)
    assert events == [] and tr.status == "ready"


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


def test_a_dart_next_to_a_wire_is_marked_uncertain_and_one_in_the_middle_is_not():
    for point, uncertain in (((0, 130), False), ((0, 99.4), True)):         # the middle of the single, 0.4 mm over the inner edge of the triple
        tr = BoardTracker(model(), Settings())
        events, t = run(tr, [scene() for _ in range(20)])
        events, t = run(tr, [scene([point]) for _ in range(14)], start=t)
        dart = [e for e in events if e.kind == "dart"][0]
        assert dart.throw["detection"]["uncertain"] is uncertain, dart.throw["detection"]


def test_a_dart_just_off_the_board_is_marked_uncertain_and_one_further_off_is_not():
    for point, uncertain in (((0, 171.0), True), ((-170, 60), False)):       # 1 mm outside the double, 10 mm outside it and next to a wire (the wires do not count out there)
        tr = BoardTracker(model(), Settings())
        events, t = run(tr, [scene() for _ in range(20)])
        events, t = run(tr, [scene([point]) for _ in range(14)], start=t)
        dart = [e for e in events if e.kind == "dart"][0]
        assert dart.throw["segment"]["multiplier"] == 0 and dart.throw["detection"]["uncertain"] is uncertain, dart.throw["detection"]


def test_the_calibration_reports_its_progress():
    from breakfast.detection import calibration
    m = model()
    frames = {c: scene()[c] for c in range(3)}
    steps = []
    calibration.fit(frames, calibration.reference_points(m), m.radii, lambda f, text: steps.append((f, text)))
    fractions = [f for f, _ in steps]
    assert fractions == sorted(fractions) and fractions[0] == 0.0 and 0.6 <= fractions[-1] < 1.0
    assert "camera 1" in steps[0][1] and "fine adjustment" in steps[-1][1]


def test_the_17_points_fit_back_to_the_same_model_and_follow_a_moved_point():
    from breakfast.detection import calibration
    m = model()
    pts = calibration.model_points(m)
    assert len(pts[0]) == 17 and "center" in pts[0] and "99@189" in pts[2]
    same, report = calibration.fit_points(pts, m)
    assert max(report["rms_px"].values()) < 0.05 and abs(same.to_pixel(1, 30, 40)[0] - m.to_pixel(1, 30, 40)[0]) < 0.2
    pts[0]["162@99"] = [pts[0]["162@99"][0] + 5, pts[0]["162@99"][1]]           # one point pulled 5 px away: the fit stays close to all the others
    moved, report = calibration.fit_points(pts, m)
    assert 0.1 < report["rms_px"]["0"] < 3.0 and max(report["rms_px"][c] for c in ("1", "2")) < 0.3


def test_the_previous_model_can_be_taken_back(tmp_path):
    from breakfast.detection import calibration
    m = model()
    path = tmp_path / "calib_model.json"
    calibration.save(m, path)
    assert calibration.revert(path) is None
    other = calibration.BoardModel({c: m.H[c] @ __import__('numpy').array([[1, 0, 10], [0, 1, 0], [0, 0, 1]]) for c in m.cams}, m.radii, m.size)
    calibration.save(other, path)
    back = calibration.revert(path)
    assert abs(back.to_pixel(0, 0, 0)[0] - m.to_pixel(0, 0, 0)[0]) < 0.5


def _board_with(darts, **settings):
    """A tracker that has seen the empty board and counted the darts (each thrown on its own)."""
    tr = BoardTracker(model(), Settings(**settings))
    events, t = run(tr, [scene() for _ in range(20)])
    for i in range(len(darts)):
        events, t = run(tr, [scene(darts[:i]), scene(darts[:i], hand=True), scene(darts[:i + 1])] + [scene(darts[:i + 1]) for _ in range(12)], start=t)
    assert tr.count == len(darts)
    return tr, t


def _forget_last_dart(tr):
    tr.throws.pop(), tr.sup0.pop()
    tr.count -= 1


class TestRecount:
    DARTS = [(0, 103), (50, 100)]

    def test_a_dart_the_count_missed_is_counted_when_the_picture_keeps_showing_it(self):
        tr, t = _board_with(self.DARTS)
        _forget_last_dart(tr)                                       # the count lost the second dart, the board still has it
        events, t = run(tr, [scene(self.DARTS, hand=True)] + [scene(self.DARTS) for _ in range(60)], start=t)
        darts = [e for e in events if e.kind == "dart"]
        assert len(darts) == 1 and darts[0].info["recounted"] and darts[0].count == 2
        assert darts[0].throw["detection"]["recounted"] is True and darts[0].throw["detection"]["uncertain"] is True
        assert abs(darts[0].throw["coords"]["x"] - 50 / 170) < 0.03 and abs(darts[0].throw["coords"]["y"] - 100 / 170) < 0.03
        assert tr.count == 2

    def test_one_look_is_not_enough(self):
        tr, t = _board_with(self.DARTS)
        _forget_last_dart(tr)
        events, t = run(tr, [scene(self.DARTS, hand=True)] + [scene(self.DARTS) for _ in range(12)], start=t)    # about 0.6 s of stillness: one look
        assert [e for e in events if e.kind == "dart"] == [] and tr.count == 1

    def test_counted_darts_are_not_counted_again(self):
        tr, t = _board_with(self.DARTS)
        events, t = run(tr, [scene(self.DARTS, hand=True)] + [scene(self.DARTS) for _ in range(80)], start=t)
        assert [e for e in events if e.kind == "dart"] == [] and tr.count == 2

    def test_nothing_is_counted_with_the_switch_off(self):
        tr, t = _board_with(self.DARTS, recount=False)
        _forget_last_dart(tr)
        events, t = run(tr, [scene(self.DARTS, hand=True)] + [scene(self.DARTS) for _ in range(60)], start=t)
        assert [e for e in events if e.kind == "dart"] == [] and tr.count == 1

    def test_nothing_is_counted_beyond_the_most_darts_on_the_board(self):
        tr, t = _board_with(self.DARTS, max_darts=1)
        _forget_last_dart(tr)
        events, t = run(tr, [scene(self.DARTS, hand=True)] + [scene(self.DARTS) for _ in range(60)], start=t)
        assert [e for e in events if e.kind == "dart"] == [] and tr.count == 1


def test_the_field_comes_from_the_median_of_the_cameras_not_from_the_weighted_fusion():
    # camera 2 sees the dart 2.5 mm further out; the weighted fusion would follow it a little, the median stays with the other two
    after = scene([(0, 130)])
    shifted = scene([(0, 132.5)])
    after[2] = shifted[2]
    result = detector.locate(model(), prepared(scene()), prepared(after))
    assert (result["x"], result["y"]) == tuple(result["median"])
    assert abs(result["y"] - result["tips"][0]["mm"][1]) < 0.1 and result["used"] == 3


def test_a_dart_that_only_two_cameras_saw_is_marked_uncertain_even_in_the_middle_of_a_field():
    for cameras, uncertain in ((3, False), (2, True)):
        tr = BoardTracker(model(), Settings())
        events, t = run(tr, [scene() for _ in range(20)])
        frames = []
        for _ in range(14):
            f = scene([(0, 130)])
            if cameras == 2:
                f[2] = scene()[2]
            frames.append(f)
        events, t = run(tr, frames, start=t)
        dart = [e for e in events if e.kind == "dart"][0]
        assert dart.throw["detection"]["cams"] == cameras
        assert dart.throw["detection"]["uncertain"] is uncertain, dart.throw["detection"]


def test_a_bounce_takes_a_place_in_the_turn_and_an_empty_board_is_no_takeout_of_it():
    tr = BoardTracker(model(), Settings())
    events, t = run(tr, [scene() for _ in range(20)])
    events, t = run(tr, [scene([(0, 103)]) for _ in range(14)], start=t)
    assert [e.count for e in events if e.kind == "dart"] == [1]
    throw = tr.add_bouncer()                                         # the second dart bounced off
    assert tr.count == 2 and throw["segment"]["multiplier"] == 0 and throw["detection"]["bounce"] is True
    events, t = run(tr, [scene([(0, 103)]) for _ in range(20)], start=t)
    assert tr.count == 2 and not [e for e in events if e.kind in ("removed", "takeout")]      # the miss is not checked against the pictures
    events, t = run(tr, [scene([(0, 103), (50, 100)]) for _ in range(14)], start=t)
    assert [e.count for e in events if e.kind == "dart"] == [3] and tr.status == "takeout"      # the next dart that sticks is the third
    assert tr.add_bouncer() is None                                  # the turn is full
    events, t = run(tr, [scene([(0, 103), (50, 100)], hand=True)] + [scene() for _ in range(12)], start=t)
    assert [e.kind for e in events] == ["takeout"] and tr.count == 0 and tr.throws == []


def test_a_bounce_alone_on_an_empty_board_stays_counted():
    tr = BoardTracker(model(), Settings())
    events, t = run(tr, [scene() for _ in range(20)])
    tr.add_bouncer()
    events, t = run(tr, [scene() for _ in range(30)], start=t)
    assert tr.count == 1 and events == []


def test_cameras_that_disagree_on_a_still_board_do_not_block_it(monkeypatch):
    tr = BoardTracker(model(), Settings())
    events, t = run(tr, [scene() for _ in range(20)])
    real = detector.locate
    monkeypatch.setattr(detector, "locate", lambda *a, **k: (lambda r: r and {**r, "agree": 1, "spread": 300.0})(real(*a, **k)))
    events, t = run(tr, [scene([(0, 103)]) for _ in range(14)], start=t)
    assert [e.kind for e in events] == ["unclear"] and events[0].info["why"] == "the cameras disagree" and events[0].before and events[0].after
    assert tr.count == 0 and tr.status == "ready"                                # nothing is counted and nothing waits
    events, t = run(tr, [scene([(0, 103)]) for _ in range(14)], start=t)
    assert tr.status == "ready" and not [e for e in events if e.kind == "blocked"]


def test_cameras_that_disagree_while_a_big_change_is_in_the_picture_still_block(monkeypatch):
    tr = BoardTracker(model(), Settings())
    events, t = run(tr, [scene() for _ in range(20)])
    real = detector.locate
    monkeypatch.setattr(detector, "locate", lambda *a, **k: (lambda r: r and {**r, "agree": 1, "spread": 300.0})(real(*a, **k)))
    monkeypatch.setattr(detector, "changed_area", lambda *a, **k: 8000)          # not yet an arm (13000), but far more than a dart
    events, t = run(tr, [scene([(0, 103)]) for _ in range(14)], start=t)
    assert tr.status == "blocked" and tr.count == 0 and not [e for e in events if e.kind == "unclear"]
    events, t = run(tr, [scene([(0, 103)]) for _ in range(400)], start=t)          # the patience runs out, as it does for an arm
    assert tr.status != "blocked" and [e for e in events if e.kind == "blocked" or (e.kind == "unclear" and e.info.get("accepted"))]
