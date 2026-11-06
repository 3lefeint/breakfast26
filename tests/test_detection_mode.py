"""The script that switches the Breakfast of the board host between its own dart detection and Autodarts."""
import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "detection_host" / "breakfast-mode.sh"
OVERRIDE = Path(__file__).resolve().parents[1] / "tools" / "detection_host" / "docker-compose.override.yml"
CONFIG = '[web]\nport = 8080\n\n[stats]\ndb = "stats.db"\n'


@pytest.fixture
def host(tmp_path):
    app, bin_dir, log = tmp_path / "app", tmp_path / "bin", tmp_path / "calls.log"
    (app / "data" / "detection").mkdir(parents=True), bin_dir.mkdir()
    (app / "data" / "detection" / "calib_model.json").write_text("{}")
    (app / "data" / "config.toml").write_text(CONFIG)
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"game": {"match_started": False}, "elimination": {"active": False}}))
    for name, body in (("systemctl", 'echo "systemctl $@" >> "$LOG"\n[ "$1" = is-active ] && echo active\nexit 0\n'),
                       ("docker", 'echo "docker $@" >> "$LOG"\n'),
                       ("curl", '[ -f "$STATE" ] && cat "$STATE" || exit 7\n')):
        (bin_dir / name).write_text("#!/bin/sh\n" + body)
        (bin_dir / name).chmod(0o755)
    env = {**os.environ, "APP_DIR": str(app), "PATH": f"{bin_dir}:{os.environ['PATH']}", "LOG": str(log), "STATE": str(state)}
    return env, app / "data" / "config.toml", log, state


def run(env, *args):
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True)


def calls(log):
    return log.read_text().splitlines() if log.exists() else []


def test_own_stops_autodarts_sets_the_flag_and_restarts_breakfast(host):
    env, config, log, _ = host
    out = run(env, "own")
    assert out.returncode == 0, out.stderr
    assert calls(log) == ["systemctl stop autodarts.service", "docker restart breakfast"]       # the cameras are free before Breakfast opens them
    assert "[cameras]\nenabled = true\n" in config.read_text() and 'diag_port = 8770' in config.read_text() and "max_rate = 15" in config.read_text()
    assert config.read_text().startswith(CONFIG.rstrip("\n"))                                    # the rest of the file stays as it was
    assert (config.parent / "config.toml.before-mode").read_text() == CONFIG


def test_autodarts_sets_the_flag_back_restarts_breakfast_and_then_starts_autodarts(host):
    env, config, log, _ = host
    run(env, "own")
    log.unlink()
    assert run(env, "autodarts").returncode == 0
    assert calls(log) == ["docker restart breakfast", "systemctl start autodarts.service"]
    assert "enabled = false" in config.read_text() and "enabled = true" not in config.read_text()


def test_only_the_enabled_line_of_an_existing_cameras_section_changes(host):
    env, config, *_ = host
    config.write_text('[cameras]\nenabled = false\nmax_rate = 15\ndevices = ["/dev/cam0"]\n\n[cameras.tracker]\nenabled = 1\n\n[stats]\nenabled = false\n')
    assert run(env, "own").returncode == 0
    assert config.read_text() == '[cameras]\nenabled = true\nmax_rate = 15\ndevices = ["/dev/cam0"]\n\n[cameras.tracker]\nenabled = 1\n\n[stats]\nenabled = false\n'


def test_an_existing_section_without_the_line_gets_it(host):
    env, config, *_ = host
    config.write_text('[cameras]\nmax_rate = 15\n\n[stats]\ndb = "x"\n')
    run(env, "own")
    assert config.read_text() == '[cameras]\nenabled = true\nmax_rate = 15\n\n[stats]\ndb = "x"\n'


def test_a_running_match_stops_the_switch_before_anything_changes(host):
    env, config, log, state = host
    state.write_text(json.dumps({"game": {"match_started": True}}))
    out = run(env, "own")
    assert out.returncode == 1 and "a match is running" in out.stderr
    assert calls(log) == [] and config.read_text() == CONFIG
    assert run(env, "own", "--force").returncode == 0 and calls(log)[0] == "systemctl stop autodarts.service"


def test_a_running_elimination_also_counts_and_an_unreachable_api_does_not(host):
    env, config, log, state = host
    state.write_text(json.dumps({"game": {}, "elimination": {"active": True}}))
    assert run(env, "own").returncode == 1
    state.unlink()                                                      # container down: nothing to protect
    assert run(env, "own").returncode == 0


def test_status_reports_the_flag(host):
    env, config, *_ = host
    assert "enabled = none" in run(env, "status").stdout
    run(env, "own")
    assert "enabled = true" in run(env, "status").stdout


def test_a_missing_config_changes_nothing_and_a_bad_word_prints_the_usage(host):
    env, config, log, _ = host
    config.unlink()
    assert run(env, "own").returncode == 1 and calls(log) == []
    assert run(env, "sideways").returncode == 2


def test_the_override_names_the_stable_camera_links_and_needs_no_own_build():
    text = OVERRIDE.read_text()
    for i in range(3):
        assert f"/dev/autodarts-cam{i}:/dev/cam{i}" in text
    assert "build:" not in text and '- "44"' in text         # the container does not run as root: it needs the group of the camera nodes
    assert "- /dev/bus/usb:/dev/bus/usb" in text and "c 189:* rmw" in text


def test_own_refuses_without_a_board_model_and_changes_nothing(host):
    env, config, log, _ = host
    (config.parent / "detection" / "calib_model.json").unlink()
    out = run(env, "own")
    assert out.returncode == 1 and "no board model" in out.stderr
    assert calls(log) == [] and config.read_text() == CONFIG
