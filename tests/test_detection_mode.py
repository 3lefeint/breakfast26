"""The script that switches the Breakfast of the board host between its own dart detection and Autodarts."""
import json
import os
import shutil
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
    """What the fakes were called with, without the `systemctl cat` that looks for the unit."""
    return [c for c in log.read_text().splitlines() if " cat " not in c] if log.exists() else []


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
        assert f"/dev/breakfast-cam{i}:/dev/cam{i}" in text
    assert "build:" not in text and '- "44"' in text         # the container does not run as root: it needs the group of the camera nodes
    assert "- /dev/bus/usb:/dev/bus/usb" in text and "c 189:* rmw" in text


def test_own_refuses_without_a_board_model_and_changes_nothing(host):
    env, config, log, _ = host
    (config.parent / "detection" / "calib_model.json").unlink()
    out = run(env, "own")
    assert out.returncode == 1 and "no board model" in out.stderr
    assert calls(log) == [] and config.read_text() == CONFIG


def test_a_user_unit_of_autodarts_is_stopped_and_started_with_the_user_flag(host):
    env, config, log, _ = host
    bin_dir = Path(env["PATH"].split(":")[0])
    (bin_dir / "systemctl").write_text('#!/bin/sh\necho "systemctl $@" >> "$LOG"\n[ "$1" = cat ] && exit 1\n[ "$1 $2" = "--user cat" ] && exit 0\nexit 0\n')
    assert run(env, "own").returncode == 0
    run(env, "autodarts")
    assert [c for c in calls(log) if "autodarts.service" in c] == \
        ["systemctl --user stop autodarts.service", "systemctl --user start autodarts.service"]


def test_without_a_unit_the_script_says_the_app_must_be_quit_by_hand_and_goes_on(host):
    env, config, log, _ = host
    env["AUTODARTS_SCOPE"] = "none"
    out = run(env, "own")
    assert out.returncode == 0 and "note: Autodarts has no service here" in out.stdout
    assert calls(log) == ["docker restart breakfast"] and "enabled = true" in config.read_text()


SHORTCUT = SCRIPT.with_name("breakfast-mode-shortcut.sh")
INSTALL = SCRIPT.with_name("install.sh")


def shortcut(tmp_path, mode_script_body, *programs):
    bin_dir, shown = tmp_path / "wbin", tmp_path / "shown.log"
    bin_dir.mkdir(exist_ok=True)
    for name in programs:
        (bin_dir / name).write_text(f'#!/bin/sh\necho "{name} $@" >> "{shown}"\n')
        (bin_dir / name).chmod(0o755)
    mode = tmp_path / "mode.sh"
    mode.write_text("#!/bin/sh\n" + mode_script_body)
    mode.chmod(0o755)
    for tool in ("dirname", "readlink", "grep", "bash"):                # the system tools the script needs, but none of the window programs
        (bin_dir / tool).symlink_to(shutil.which(tool))
    env = {"PATH": str(bin_dir), "MODE_SCRIPT": str(mode)}
    out = subprocess.run(["bash", str(SHORTCUT), "own"], env=env, capture_output=True, text=True)
    return out, (shown.read_text().splitlines() if shown.exists() else [])


def test_a_shortcut_that_worked_shows_nothing(tmp_path):
    out, shown = shortcut(tmp_path, "echo done\n", "kdialog")
    assert out.returncode == 0 and shown == []


def test_a_shortcut_that_failed_shows_the_text_in_a_window(tmp_path):
    out, shown = shortcut(tmp_path, 'echo "a match is running" >&2\nexit 1\n', "kdialog", "zenity")
    assert out.returncode == 1
    assert shown == ["kdialog --title Breakfast --error a match is running"]               # kdialog before zenity


def test_the_window_falls_back_to_zenity_then_xmessage(tmp_path):
    _, shown = shortcut(tmp_path, "echo broken >&2\nexit 1\n", "zenity", "xmessage")
    assert shown == ["zenity --error --title=Breakfast --text=broken"]
    (tmp_path / "x").mkdir()
    _, shown = shortcut(tmp_path / "x", "echo broken >&2\nexit 1\n", "xmessage")
    assert shown == ["xmessage -center broken"]


def test_a_note_of_a_successful_run_is_shown(tmp_path):
    out, shown = shortcut(tmp_path, 'echo "note: quit the app"\n', "kdialog")
    assert out.returncode == 0 and shown == ["kdialog --title Breakfast --msgbox note: quit the app"]


def test_the_installer_writes_the_names_the_rule_the_scripts_and_both_shortcuts(tmp_path):
    app, home = tmp_path / "app", tmp_path / "home"
    app.mkdir(), home.mkdir()
    (app / "docker-compose.yml").write_text("services: {}\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("udevadm", 'echo "udevadm $@" >> "$LOG"\n'), ("systemctl", "exit 0\n")):
        (bin_dir / name).write_text("#!/bin/sh\n" + body)
        (bin_dir / name).chmod(0o755)
    log = tmp_path / "calls.log"
    env = {**os.environ, "HOME": str(home), "PATH": f"{bin_dir}:{os.environ['PATH']}", "LOG": str(log), "SUDO": "env",
           "UDEV_RULE": str(tmp_path / "udev.rules"), "POLKIT_RULE": str(tmp_path / "polkit.rules"),
           "INSTALL_PORTS": "1-1.1.1 1-1.1.2 1-1.1.3"}
    out = subprocess.run(["bash", str(INSTALL), str(app)], env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    rules = (tmp_path / "udev.rules").read_text()
    for i, port in enumerate(("1-1.1.1", "1-1.1.2", "1-1.1.3")):
        assert f'KERNELS=="{port}", SYMLINK+="breakfast-cam{i}"' in rules
    assert "udevadm control --reload-rules" in log.read_text()
    assert "subject.user ==" in (tmp_path / "polkit.rules").read_text() and "BOARD_USER" not in (tmp_path / "polkit.rules").read_text()
    assert (app / "docker-compose.override.yml").read_text() == OVERRIDE.read_text()
    for name in ("breakfast-mode.sh", "breakfast-mode-shortcut.sh"):
        assert os.access(home / ".local" / "bin" / name, os.X_OK)
    own = (home / "Desktop" / "breakfast-own-detection.desktop").read_text()
    assert f"Exec=env APP_DIR={app} {home}/.local/bin/breakfast-mode-shortcut.sh own" in own
    assert "breakfast-mode-shortcut.sh autodarts" in (home / "Desktop" / "breakfast-board-manager.desktop").read_text()
    assert (home / ".local" / "share" / "applications" / "breakfast-own-detection.desktop").exists()


@pytest.mark.parametrize("ports", ["1-1.1.1 1-1.1.2", "1-1.1.1 1-1.1.1 1-1.1.2", "1-1.1.1 1-1.1.2 camera"])
def test_the_installer_refuses_a_wrong_set_of_ports_and_writes_nothing(tmp_path, ports):
    app = tmp_path / "app"
    app.mkdir()
    (app / "docker-compose.yml").write_text("")
    env = {**os.environ, "HOME": str(tmp_path), "SUDO": "false", "UDEV_RULE": str(tmp_path / "udev.rules"), "INSTALL_PORTS": ports}
    out = subprocess.run(["bash", str(INSTALL), str(app)], env=env, capture_output=True, text=True)
    assert out.returncode == 1 and not (tmp_path / "udev.rules").exists()
