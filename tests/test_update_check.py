from breakfast.update_check import UpdateChecker

NEWER = {"current": "1.5.0", "latest": "1.6.0", "update_available": True}
SAME = {"current": "1.5.0", "latest": "1.5.0", "update_available": False}


def config(tmp_path, text=""):
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


def test_nothing_is_known_before_the_first_check(tmp_path):
    assert UpdateChecker(lambda: NEWER, config(tmp_path)).status() is None


def test_a_newer_release_is_reported_and_the_change_is_announced(tmp_path):
    changes = []
    checker = UpdateChecker(lambda: NEWER, config(tmp_path), on_change=lambda: changes.append(1))
    assert checker.run_once() is True
    assert checker.status() == {"available": True, "latest": "1.6.0"}
    checker.run_once()
    assert changes == [1]            # the same answer again is no change


def test_the_installed_version_is_not_an_update(tmp_path):
    checker = UpdateChecker(lambda: SAME, config(tmp_path))
    checker.run_once()
    assert checker.status() == {"available": False, "latest": "1.5.0"}


def test_a_failed_check_keeps_what_was_known(tmp_path):
    answers = [NEWER, {"error": "could not reach GitHub"}]
    checker = UpdateChecker(lambda: answers.pop(0), config(tmp_path))
    assert checker.run_once() is True
    assert checker.run_once() is False
    assert checker.status()["latest"] == "1.6.0"


def test_a_check_that_raises_is_a_failed_check(tmp_path):
    def boom():
        raise RuntimeError("down")
    assert UpdateChecker(boom, config(tmp_path)).run_once() is False


def test_it_can_be_switched_off_in_the_config(tmp_path):
    path = config(tmp_path)
    checker = UpdateChecker(lambda: NEWER, path)
    checker.run_once()
    assert checker.enabled() is True
    path.write_text("[updates]\ncheck = false\n")
    assert checker.enabled() is False and checker.status() is None


# ── installing by itself ─────────────────────────────────────────────────────

import threading
import time
from datetime import datetime, timezone

from breakfast import update_check

PATCH = {"current": "1.5.0", "latest": "1.5.1", "update_available": True}
MAJOR = {"current": "1.5.0", "latest": "2.0.0", "update_available": True}


def auto(tmp_path, answer, **kw):
    path = config(tmp_path, "[updates]\nauto_install = true\n")
    calls = []
    result = kw.pop("result", NEWER)

    def install():
        calls.append(1)
        return {"ok": True} if answer is None else answer

    checker = UpdateChecker(lambda: result, path, install=install, **kw)
    checker.run_once()
    return checker, calls


def test_it_does_not_install_unless_switched_on(tmp_path):
    calls = []
    checker = UpdateChecker(lambda: NEWER, config(tmp_path), install=lambda: calls.append(1))
    checker.run_once()
    assert checker.maybe_install() is False and calls == []


def test_a_minor_or_patch_release_is_installed(tmp_path):
    checker, calls = auto(tmp_path, None)
    assert checker.maybe_install() is True and calls == [1]


def test_a_new_major_version_is_only_announced(tmp_path):
    checker, calls = auto(tmp_path, None, result=MAJOR)
    assert checker.maybe_install() is False and calls == []
    assert checker.status() == {"available": True, "latest": "2.0.0"}


def test_nothing_is_installed_while_a_game_is_running_and_it_goes_on_later(tmp_path):
    state = {"busy": True}
    checker, calls = auto(tmp_path, None, busy=lambda: state["busy"])
    assert checker.maybe_install() is False and calls == []
    state["busy"] = False
    assert checker.maybe_install() is True and calls == [1]


def test_a_version_is_tried_only_once_also_after_a_restart(tmp_path):
    checker, calls = auto(tmp_path, None)
    checker.maybe_install()
    assert checker.maybe_install() is False
    again = UpdateChecker(lambda: NEWER, tmp_path / "config.toml", install=lambda: calls.append(2))
    again.run_once()
    assert again.maybe_install() is False and calls == [1]


def test_a_newer_version_than_the_one_tried_is_installed(tmp_path):
    checker, calls = auto(tmp_path, None)
    checker.maybe_install()
    checker._result = {"current": "1.5.0", "latest": "1.6.1", "update_available": True}
    assert checker.maybe_install() is True and calls == [1, 1]


def test_an_update_that_does_not_start_is_not_a_crash(tmp_path):
    checker, calls = auto(tmp_path, {"error": "updater unreachable"})
    assert checker.maybe_install() is False and calls == [1]

    def boom():
        raise RuntimeError("down")
    path = config(tmp_path, "[updates]\nauto_install = true\n")
    other = UpdateChecker(lambda: {"current": "1.5.0", "latest": "1.5.2", "update_available": True}, path, install=boom)
    other.run_once()
    assert other.maybe_install() is False


class TestMoments:
    """The loop installs after the first check and at 04:00, not at the other checks."""

    def run_loop(self, tmp_path, monkeypatch, answers, hours, busy=None):
        monkeypatch.setattr(update_check, "TICK_S", 0.01)
        monkeypatch.setattr(update_check, "FIRST_DELAY_S", 0)
        monkeypatch.setattr(update_check, "INTERVAL_S", 0.05)
        clock = {"now": hours[0]}
        installs = []
        path = config(tmp_path, "[updates]\nauto_install = true\n")
        checker = UpdateChecker(lambda: answers["now"], path, install=lambda: installs.append(clock["now"]) or {"ok": True},
                                busy=busy, now=lambda: clock["now"])
        checker.start()
        for moment in hours:
            clock["now"] = moment
            time.sleep(0.3)
        checker.stop()
        return installs

    def test_the_first_check_after_the_start_installs(self, tmp_path, monkeypatch):
        day = datetime(2026, 10, 19, 10, 0, tzinfo=timezone.utc)
        assert self.run_loop(tmp_path, monkeypatch, {"now": PATCH}, [day]) == [day]

    def test_a_version_that_comes_later_waits_for_04_00(self, tmp_path, monkeypatch):
        evening = datetime(2026, 10, 19, 22, 0, tzinfo=timezone.utc)
        night = datetime(2026, 10, 20, 4, 0, tzinfo=timezone.utc)
        answers = {"now": SAME}       # nothing new at the start; the release appears while the app runs

        def appears():
            time.sleep(0.15)
            answers["now"] = PATCH
        threading.Thread(target=appears, daemon=True).start()
        assert self.run_loop(tmp_path, monkeypatch, answers, [evening, night]) == [night]

    def test_04_00_is_tried_once_a_day_and_skipped_while_a_game_runs(self, tmp_path, monkeypatch):
        day = datetime(2026, 10, 19, 10, 0, tzinfo=timezone.utc)
        night = datetime(2026, 10, 20, 4, 0, tzinfo=timezone.utc)
        asked = []

        def busy():
            asked.append(1)
            return True
        installs = self.run_loop(tmp_path, monkeypatch, {"now": PATCH}, [day, night], busy=busy)
        assert installs == [] and len(asked) == 2        # after the start and at 04:00, not at every tick
