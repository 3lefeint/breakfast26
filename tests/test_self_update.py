import hashlib
import http.server
import json
import threading
import time
import zipfile

import pytest

from breakfast import frozen, self_update


def _zip(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return path


class TestVersions:
    @pytest.mark.parametrize("current,latest,newer", [
        ("1.0.0", "1.0.1", True), ("1.0.0", "1.1.0", True), ("1.9.0", "1.10.0", True),
        ("1.0.0", "1.0.0", False), ("1.2.0", "1.1.9", False), ("1.0.0", None, False),
        ("1.0.0", "garbage", False), (None, "1.0.0", True),
    ])
    def test_is_newer(self, current, latest, newer):
        assert self_update.is_newer(current, latest) is newer


class TestVerifyAndUnpack:
    def test_verify_accepts_the_matching_sha256_line(self, tmp_path):
        z = _zip(tmp_path / "a.zip", {"x": "1"})
        digest = hashlib.sha256(z.read_bytes()).hexdigest()
        assert self_update.verify(z, f"{digest}  a.zip\n")
        assert self_update.verify(z, digest.upper())

    def test_verify_refuses_a_different_or_empty_checksum(self, tmp_path):
        z = _zip(tmp_path / "a.zip", {"x": "1"})
        assert not self_update.verify(z, "0" * 64 + "  a.zip")
        assert not self_update.verify(z, "")

    def test_unpack_returns_the_folder_with_the_executable(self, tmp_path):
        z = _zip(tmp_path / "r.zip", {"breakfast/breakfast.exe": "x", "breakfast/_internal/a.dll": "y"})
        folder = self_update.unpack(z, tmp_path / "staging")
        assert folder == tmp_path / "staging" / "breakfast"
        assert (folder / "_internal" / "a.dll").is_file()

    def test_unpack_clears_an_older_staging_folder(self, tmp_path):
        staging = tmp_path / "staging"
        (staging / "old").mkdir(parents=True)
        z = _zip(tmp_path / "r.zip", {"breakfast/breakfast.exe": "x"})
        self_update.unpack(z, staging)
        assert not (staging / "old").exists()

    def test_unpack_refuses_a_path_outside_of_the_staging_folder(self, tmp_path):
        z = _zip(tmp_path / "r.zip", {"breakfast/breakfast.exe": "x", "../evil.txt": "no"})
        with pytest.raises(ValueError, match="unsafe path"):
            self_update.unpack(z, tmp_path / "staging")
        assert not (tmp_path / "evil.txt").exists()

    def test_unpack_refuses_an_archive_without_the_executable(self, tmp_path):
        z = _zip(tmp_path / "r.zip", {"breakfast/readme.txt": "x"})
        with pytest.raises(ValueError, match="breakfast.exe"):
            self_update.unpack(z, tmp_path / "staging")


class TestScript:
    def test_has_no_placeholder_left_and_the_health_limit(self):
        script = self_update.build_script()
        assert "__" not in script
        assert f"GEQ {self_update.HEALTH_TRIES}" in script

    def test_swaps_backs_up_and_rolls_back(self):
        script = self_update.build_script()
        for part in ("Get-Process -Id", ":parent_gone", "robocopy \"%INSTALL%\" \"%BACKUP%\"", "robocopy \"%NEWFILES%\" \"%INSTALL%\"",
                     "/api/health", ":restore", "taskkill", "rolled_back", "data update"):
            assert part in script


# A release as GitHub serves it, from a local server.
@pytest.fixture
def release_server(tmp_path, monkeypatch):
    web = tmp_path / "web"
    web.mkdir()
    state = {"corrupt": False}

    def make(version):
        name = f"breakfast-windows-v{version}.zip"
        z = _zip(web / name, {"breakfast/breakfast.exe": "new", "breakfast/_internal/x": "y"})
        digest = hashlib.sha256(z.read_bytes()).hexdigest()
        (web / (name + ".sha256")).write_text(("0" * 64 if state["corrupt"] else digest) + f"  {name}\n")
        return name

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(web), **k)

        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path == "/release.json":
                base = f"http://127.0.0.1:{self.server.server_port}"
                body = json.dumps({"html_url": base + "/page", "assets": [
                    {"name": n, "browser_download_url": f"{base}/{n}"} for n in sorted(p.name for p in web.iterdir())]})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body.encode())
            else:
                super().do_GET()

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(self_update, "RELEASE_API", f"http://127.0.0.1:{server.server_port}/release.json")
    monkeypatch.setattr(frozen, "install_dir", lambda: tmp_path / "install")
    (tmp_path / "install").mkdir()
    monkeypatch.setattr(frozen, "configured_port", lambda *a: 8080)
    yield {"make": make, "state": state, "install": tmp_path / "install"}
    server.shutdown()


def _wait_phase(*phases, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if self_update.status().get("phase") in phases:
            return self_update.status()
        time.sleep(0.05)
    raise AssertionError(f"still {self_update.status()}")


class TestCheck:
    def test_reports_a_newer_release(self, release_server):
        release_server["make"]("1.0.1")
        assert self_update.check("1.0.0") == {"current": "1.0.0", "latest": "1.0.1", "update_available": True}

    def test_reports_no_update_for_the_same_version(self, release_server):
        release_server["make"]("1.0.0")
        assert self_update.check("1.0.0")["update_available"] is False

    def test_release_without_a_windows_build_is_an_error(self, release_server):
        assert "no Windows build" in self_update.check("1.0.0")["error"]

    def test_a_repository_without_any_release_says_so(self, release_server, monkeypatch):
        monkeypatch.setattr(self_update, "RELEASE_API", self_update.RELEASE_API.replace("/release.json", "/nothing"))
        assert self_update.check("1.0.0") == {"error": self_update.NO_BUILD}

    def test_an_unreachable_github_is_an_error(self, monkeypatch):
        monkeypatch.setattr(self_update, "RELEASE_API", "http://127.0.0.1:9/none")
        assert "could not reach GitHub" in self_update.check("1.0.0")["error"]


class TestApply:
    def test_downloads_verifies_unpacks_and_hands_over(self, release_server):
        release_server["make"]("1.0.1")
        calls = []
        res = self_update.apply("1.0.0", spawn=lambda script, args: calls.append((script, args)),
                                leave=lambda: calls.append("left"))
        assert res == {"ok": True}
        deadline = time.time() + 10
        while "left" not in calls and time.time() < deadline:
            time.sleep(0.05)
        script, args = calls[0]
        install = release_server["install"]
        assert script == install / "update" / "apply-update.cmd" and script.read_text().startswith("@echo off")
        assert args[0] == install and args[1] == install / "update" / "staging" / "breakfast"
        assert (args[1] / "breakfast.exe").read_text() == "new"
        assert args[2] == install / "update" / "backup" and args[4] == 8080 and args[5] == "1.0.1"
        assert json.loads(frozen.handoff_file().read_text()) == {"version": "1.0.1"}
        assert calls[1] == "left"

    def test_a_wrong_checksum_stops_the_update(self, release_server):
        release_server["state"]["corrupt"] = True
        release_server["make"]("1.0.1")
        calls = []
        self_update.apply("1.0.0", spawn=lambda *a: calls.append(a), leave=lambda: calls.append("left"))
        st = _wait_phase("failed")
        assert "checksum" in st["detail"] and not calls and not frozen.handoff_file().exists()

    def test_the_current_version_is_not_installed_again(self, release_server):
        release_server["make"]("1.0.0")
        self_update.apply("1.0.0", spawn=lambda *a: None, leave=lambda: None)
        assert "already on the latest" in _wait_phase("failed")["detail"]

    def test_a_second_update_is_refused_while_one_runs(self, release_server):
        frozen.write_json_atomic(frozen.update_dir() / "status.json", {"phase": "fetching", "at": time.time()})
        res = self_update.apply("1.0.0")
        assert res["ok"] is False and "in progress" in res["error"]

    def test_a_leftover_phase_of_a_crash_does_not_block(self, release_server):
        release_server["make"]("1.0.1")
        frozen.write_json_atomic(frozen.update_dir() / "status.json", {"phase": "fetching", "at": time.time() - 3600})
        assert self_update.apply("1.0.0", spawn=lambda *a: None, leave=lambda: None) == {"ok": True}
        _wait_phase("installing")


def test_status_is_idle_without_a_status_file(release_server):
    assert self_update.status()["phase"] == "idle"
