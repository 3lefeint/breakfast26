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
