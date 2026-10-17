import json
from types import SimpleNamespace

import pytest

from breakfast.detection import tuning
from breakfast.detection.tracker import Settings
from breakfast.detection.worker import Worker


class TestSettings:
    def test_describe_lists_every_tunable_setting_with_value_and_range(self):
        items = {i["key"]: i for i in tuning.describe(Settings(settle_s=0.5))}
        assert set(items) == set(tuning.TUNABLE)
        assert items["settle_s"]["value"] == 0.5 and items["settle_s"]["default"] == 0.35
        assert (items["recount_looks"]["kind"], items["recount_looks"]["min"], items["recount_looks"]["max"]) == ("int", 1, 5)

    def test_valid_values_are_applied(self):
        s = Settings()
        done, refused = tuning.apply(s, {"settle_s": 0.6, "recount": False, "recount_looks": 3, "uncertain_margin_mm": 1})
        assert refused == {} and (s.settle_s, s.recount, s.recount_looks, s.uncertain_margin_mm) == (0.6, False, 3, 1.0)

    @pytest.mark.parametrize("key,value", [("settle_s", 0.0), ("settle_s", "fast"), ("recount", 1), ("recount_looks", 2.5),
                                           ("recount_looks", 9), ("motion_fraction", True), ("max_area", 100), ("nothing", 1)])
    def test_invalid_values_are_refused_and_change_nothing(self, key, value):
        s = Settings()
        before = dict(s.__dict__)
        done, refused = tuning.apply(s, {key: value})
        assert done == {} and key in refused and s.__dict__ == before

    def test_exposure_and_white_balance_take_zero_for_the_automatic_or_a_value_in_range(self):
        s = Settings(exposure=200, white_balance=4600)
        assert tuning.apply(s, {"exposure": 0, "white_balance": 0}) == ({"exposure": 0, "white_balance": 0}, {})
        done, refused = tuning.apply(s, {"exposure": 2500, "white_balance": 1000})
        assert done == {} and set(refused) == {"exposure", "white_balance"}

    def test_one_refusal_does_not_stop_the_others(self):
        s = Settings()
        done, refused = tuning.apply(s, {"settle_s": 0.5, "recount_looks": 99})
        assert done == {"settle_s": 0.5} and "recount_looks" in refused and s.settle_s == 0.5

    def test_the_file_survives_a_missing_or_damaged_state(self, tmp_path):
        assert tuning.load(tmp_path / "none.json") == {}
        (tmp_path / "bad.json").write_text("{nope")
        assert tuning.load(tmp_path / "bad.json") == {}
        tuning.save(tmp_path / "sub" / "ok.json", {"settle_s": 0.5})
        assert tuning.load(tmp_path / "sub" / "ok.json") == {"settle_s": 0.5}


class TestWorkerSettings:
    def stub(self, tmp_path, cfg=None):
        stub = SimpleNamespace(settings=Settings(), settings_path=tmp_path / "tracker_settings.json", cfg=cfg or {}, notes=[])
        stub.note = stub.notes.append
        stub.pushed = []
        stub._push_controls = lambda: stub.pushed.append((stub.settings.exposure, stub.settings.white_balance))
        return stub

    def test_a_change_is_kept_and_survives_a_restart(self, tmp_path):
        w = self.stub(tmp_path)
        out = Worker.change_settings(w, {"settle_s": 0.7, "recount_looks": 50})
        assert out["applied"] == {"settle_s": 0.7} and "recount_looks" in out["refused"] and w.settings.settle_s == 0.7
        assert json.loads(w.settings_path.read_text()) == {"settle_s": 0.7}
        restarted = Settings()
        tuning.apply(restarted, tuning.load(w.settings_path))
        assert restarted.settle_s == 0.7

    def test_the_camera_controls_are_given_to_the_cameras_when_changed_and_reset(self, tmp_path):
        w = self.stub(tmp_path)
        Worker.change_settings(w, {"exposure": 200, "white_balance": 4600})
        Worker.reset_settings(w)
        assert w.pushed == [(200, 4600), (0, 0)]

    def test_reset_goes_back_to_config_toml_or_the_built_in_value(self, tmp_path):
        w = self.stub(tmp_path, cfg={"tracker": {"settle_s": 0.4}})
        Worker.change_settings(w, {"settle_s": 0.9, "uncertain_sigma": 3.0})
        Worker.reset_settings(w)
        assert (w.settings.settle_s, w.settings.uncertain_sigma) == (0.4, 1.6) and not w.settings_path.exists()


class TestCleanSessions:
    def make(self, folder, names, size=1000):
        for n in names:
            (folder / n).mkdir(parents=True)
            (folder / n / "a.jpg").write_bytes(b"x" * size)

    def test_the_newest_sessions_stay_and_the_current_one_is_never_removed(self, tmp_path):
        names = [f"session-2026101{d}-000000" for d in range(1, 8)]
        self.make(tmp_path, names)
        removed = tuning.clean_sessions(tmp_path, keep=3, max_gb=1, current=names[0])
        assert removed == names[1:5] and sorted(p.name for p in tmp_path.iterdir()) == [names[0], *names[5:]]

    def test_a_size_limit_removes_the_oldest_until_it_fits(self, tmp_path):
        names = [f"session-2026101{d}-000000" for d in range(1, 5)]
        self.make(tmp_path, names, size=1024 ** 2)
        removed = tuning.clean_sessions(tmp_path, keep=10, max_gb=2.5 / 1024)       # 2.5 MB: two sessions fit
        assert removed == names[:2]

    def test_a_missing_folder_is_fine(self, tmp_path):
        assert tuning.clean_sessions(tmp_path / "none") == []


class TestCameraControls:
    class Cap:
        def __init__(self):
            self.calls = []

        def set(self, prop, value):
            self.calls.append((prop, value))

    def test_nothing_is_set_while_both_are_automatic_and_never_were_fixed(self):
        from breakfast.detection.cameras import V4L2Camera
        cam, cap = V4L2Camera("/dev/none"), self.Cap()
        cam._apply_controls(cap)
        assert cap.calls == []

    def test_a_fixed_value_is_given_once_and_again_after_the_camera_is_reopened(self):
        import cv2
        from breakfast.detection.cameras import V4L2Camera
        cam, cap = V4L2Camera("/dev/none"), self.Cap()
        cam.set_controls(200, 4600)
        cam._apply_controls(cap)
        cam._apply_controls(cap)
        assert cap.calls == [(cv2.CAP_PROP_AUTO_EXPOSURE, 1), (cv2.CAP_PROP_EXPOSURE, 200), (cv2.CAP_PROP_AUTO_WB, 0), (cv2.CAP_PROP_WB_TEMPERATURE, 4600)]
        cam._applied = None                                         # what the loop does when it opens the camera again
        cam._apply_controls(cap)
        assert len(cap.calls) == 8

    def test_going_back_to_automatic_switches_it_on_again(self):
        import cv2
        from breakfast.detection.cameras import V4L2Camera
        cam, cap = V4L2Camera("/dev/none"), self.Cap()
        cam.set_controls(200, 0)
        cam._apply_controls(cap)
        cap.calls.clear()
        cam.set_controls(0, 0)
        cam._apply_controls(cap)
        assert cap.calls == [(cv2.CAP_PROP_AUTO_EXPOSURE, 3), (cv2.CAP_PROP_AUTO_WB, 1)]
