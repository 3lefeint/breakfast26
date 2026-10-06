import json
import os
import sys

import pytest

from breakfast import frozen


@pytest.fixture
def install(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "breakfast.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "_internal"), raising=False)
    monkeypatch.setenv("PATH", "/usr/bin")
    cwd = os.getcwd()
    yield tmp_path
    os.chdir(cwd)


class TestPrepare:
    def test_runs_from_the_data_folder_and_writes_a_first_config(self, install):
        assert frozen.prepare() is True
        assert os.getcwd() == str(install / "data")
        assert (install / "data" / "sounds").is_dir()
        config = (install / "data" / "config.toml").read_text(encoding="utf-8")
        assert 'mode = "direct"' in config and "port = 8080" in config

    def test_an_existing_config_is_left_alone(self, install):
        (install / "data").mkdir()
        (install / "data" / "config.toml").write_text("mode = 'direct'\n# mine\n", encoding="utf-8")
        assert frozen.prepare() is False
        assert "# mine" in (install / "data" / "config.toml").read_text(encoding="utf-8")

    def test_the_bundled_ffmpeg_comes_first_on_the_path(self, install):
        (install / "_internal" / "ffmpeg").mkdir(parents=True)
        frozen.prepare()
        assert os.environ["PATH"].startswith(str(install / "_internal" / "ffmpeg") + os.pathsep)

    def test_the_first_config_has_no_account_so_only_the_web_ui_starts(self, install):
        import tomllib
        frozen.prepare()
        with open(install / "data" / "config.toml", "rb") as f:
            cfg = tomllib.load(f)
        assert cfg["direct"] == {"email": "", "password": "", "board_id": ""}


def test_configured_port(tmp_path):
    (tmp_path / "c.toml").write_text("[web]\nport = 9090\n")
    assert frozen.configured_port(tmp_path / "c.toml") == 9090
    assert frozen.configured_port(tmp_path / "missing.toml") == 8080


class _Child:
    def __init__(self, code):
        self.code = code

    def wait(self, timeout=None):
        if timeout is not None:       # waiting for a terminated child
            return 0
        if isinstance(self.code, BaseException):
            raise self.code
        return self.code

    def terminate(self):
        pass


class TestSupervise:
    @pytest.fixture
    def run(self, install, monkeypatch):
        spawned = []

        def go(codes, handoff_after=None):
            queue = list(codes)

            def popen(cmd, env=None):
                assert env[frozen.CHILD_ENV] == "1"
                spawned.append(cmd)
                code = queue.pop(0)
                if handoff_after is not None and len(spawned) == handoff_after:
                    frozen.write_json_atomic(frozen.handoff_file(), {})
                return _Child(code)

            monkeypatch.setattr(frozen.subprocess, "Popen", popen)
            monkeypatch.setattr(frozen.time, "sleep", lambda s: None)
            return frozen.supervise(), spawned
        return go

    def test_a_clean_exit_is_a_restart(self, run):
        result, spawned = run([0, 0, KeyboardInterrupt()])
        assert result == 0 and len(spawned) == 3

    def test_a_crash_is_started_again(self, run):
        result, spawned = run([1, 3, KeyboardInterrupt()])
        assert result == 0 and len(spawned) == 3

    def test_ctrl_c_stops_without_a_restart(self, run):
        result, spawned = run([KeyboardInterrupt()])
        assert result == 0 and len(spawned) == 1

    def test_a_handed_over_update_ends_the_loop(self, run):
        result, spawned = run([0, 0], handoff_after=1)
        assert result == 0 and len(spawned) == 1

    def test_a_leftover_handoff_of_an_earlier_update_is_ignored(self, run, install):
        frozen.write_json_atomic(frozen.handoff_file(), {})
        result, spawned = run([0, KeyboardInterrupt()])
        assert result == 0 and len(spawned) == 2


class TestWriteJsonAtomic:
    def test_it_retries_while_the_target_is_held_open(self, tmp_path, monkeypatch):
        real_replace, calls = frozen.os.replace, []

        def replace(src, dst):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError("held open")
            real_replace(src, dst)

        monkeypatch.setattr(frozen.os, "replace", replace)
        monkeypatch.setattr(frozen.time, "sleep", lambda s: None)
        frozen.write_json_atomic(tmp_path / "status.json", {"phase": "done"})
        assert len(calls) == 3
        assert json.loads((tmp_path / "status.json").read_text()) == {"phase": "done"}

    def test_it_gives_up_after_a_while(self, tmp_path, monkeypatch):
        def replace(src, dst):
            raise PermissionError("held open")

        monkeypatch.setattr(frozen.os, "replace", replace)
        monkeypatch.setattr(frozen.time, "sleep", lambda s: None)
        with pytest.raises(PermissionError):
            frozen.write_json_atomic(tmp_path / "status.json", {})
