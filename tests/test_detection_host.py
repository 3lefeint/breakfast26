"""The script that starts the dart detection stack on the board host: cameras found by USB port, the stack created with them."""
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "detection_host" / "breakfast-detect-host.sh"
NAMES = ["usb-a-index0", "usb-b-index0", "usb-c-index0"]


@pytest.fixture
def host(tmp_path):
    dev, by_path = tmp_path / "dev", tmp_path / "dev" / "by-path"
    by_path.mkdir(parents=True)
    for n, name in zip((14, 16, 18), NAMES):
        (dev / f"video{n}").write_text("")
        (by_path / name).symlink_to(f"../video{n}")
    bin_dir, project = tmp_path / "bin", tmp_path / "project"
    bin_dir.mkdir(), project.mkdir()
    (project / "docker-compose.detection.yml").write_text("")
    (bin_dir / "docker").write_text('#!/bin/sh\necho "$@" > "$DOCKER_LOG"\nenv | grep ^CAM >> "$DOCKER_LOG"\n')
    (bin_dir / "docker").chmod(0o755)
    env = {**os.environ, "V4L_DIR": str(by_path), "CAM_PATHS": " ".join(NAMES), "DETECT_DIR": str(project), "WAIT_S": "0",
           "PATH": f"{bin_dir}:{os.environ['PATH']}", "DOCKER_LOG": str(tmp_path / "docker.log")}
    return env, dev, by_path, tmp_path


def run(env, *args):
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True)


def test_resolve_prints_the_device_node_behind_every_usb_port(host):
    env, dev, *_ = host
    out = run(env, "resolve")
    assert out.returncode == 0
    assert out.stdout.split() == [f"CAM0={dev}/video14", f"CAM1={dev}/video16", f"CAM2={dev}/video18"]


def test_the_numbers_may_change_between_two_boots(host):
    env, dev, by_path, _ = host
    (dev / "video20").write_text("")
    (by_path / NAMES[0]).unlink()
    (by_path / NAMES[0]).symlink_to("../video20")
    assert run(env, "resolve").stdout.split()[0] == f"CAM0={dev}/video20"


def test_a_missing_camera_is_named_and_fails(host):
    env, dev, by_path, _ = host
    (by_path / NAMES[1]).unlink()
    out = run(env, "resolve")
    assert out.returncode != 0 and "camera 1 not found" in out.stderr


def test_start_creates_the_stack_again_with_the_current_devices(host):
    env, dev, _, tmp = host
    out = run(env, "start")
    assert out.returncode == 0, out.stderr
    log = (tmp / "docker.log").read_text().split("\n")
    assert log[0] == "compose -f docker-compose.detection.yml up -d --force-recreate"
    assert f"CAM2={dev}/video18" in log


def test_start_does_not_touch_docker_when_a_camera_is_missing(host):
    env, dev, by_path, tmp = host
    (by_path / NAMES[2]).unlink()
    assert run(env, "start").returncode != 0 and not (tmp / "docker.log").exists()


def test_stop_takes_the_stack_down(host):
    env, _, _, tmp = host
    assert run(env, "stop").returncode == 0
    assert (tmp / "docker.log").read_text().startswith("compose -f docker-compose.detection.yml down")


def test_without_camera_names_nothing_starts_and_the_reason_is_said(host):
    env, _, _, tmp = host
    out = run({**env, "CAM_PATHS": ""}, "start")
    assert out.returncode != 0 and "CAM_PATHS is not set" in out.stderr and not (tmp / "docker.log").exists()


def test_the_host_files_fit_no_single_machine():
    for path in SCRIPT.parent.iterdir():
        text = path.read_text()
        assert "pci-0000" not in text, path.name
    assert 'subject.user == "BOARD_USER"' in (SCRIPT.parent / "50-breakfast-detect.rules").read_text()
