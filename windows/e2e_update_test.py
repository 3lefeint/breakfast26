"""End-to-end test of the Windows self-update, run by the workflow on a Windows runner.

    python windows/e2e_update_test.py <zip of the build> <zip of a newer build> <its version>

1. A newer release whose program cannot start is offered: the update must roll back and the
   installed version must answer again.
2. A good newer release is offered: the update must install it, `data/` must survive.
"""
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

PORT = 8099
APP = "http://127.0.0.1:8080"
BAD_VERSION = "998.0.0"


def get(url, timeout=3):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def post(url):
    req = urllib.request.Request(url, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def wait_for(what, predicate, timeout):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            last = predicate()
            if last:
                return last
        except Exception as e:      # the app is restarting
            last = e
        time.sleep(2)
    raise SystemExit(f"timeout waiting for {what} (last: {last})")


def health_version():
    return get(f"{APP}/api/health")["version"]


def main(zip_a, zip_b, version_b):
    work = Path(tempfile.mkdtemp(prefix="e2e-"))
    web = work / "web"
    web.mkdir()
    install = work / "install"
    with zipfile.ZipFile(zip_a) as z:
        z.extractall(install)
    app_dir = install / "breakfast"

    # the release "server": zips and checksum files next to a release.json
    def publish(version, zip_path):
        name = f"breakfast-windows-v{version}.zip"
        shutil.copy(zip_path, web / name)
        import hashlib
        digest = hashlib.sha256((web / name).read_bytes()).hexdigest()
        (web / (name + ".sha256")).write_text(f"{digest}  {name}\n")
        return name

    # a "new version" that cannot start: a program that ends at once
    bad_dir = work / "bad" / "breakfast"
    bad_dir.mkdir(parents=True)
    shutil.copy(Path(os.environ["SystemRoot"]) / "System32" / "whoami.exe", bad_dir / "breakfast.exe")
    bad_zip = work / "bad.zip"
    with zipfile.ZipFile(bad_zip, "w") as z:
        z.write(bad_dir / "breakfast.exe", "breakfast/breakfast.exe")

    assets = []

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(web), **k)

        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path == "/release.json":
                body = json.dumps({"html_url": "http://127.0.0.1/page", "assets": [
                    {"name": n, "browser_download_url": f"http://127.0.0.1:{PORT}/{n}"} for n in assets]})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body.encode())
            else:
                super().do_GET()

    server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    env = dict(os.environ, BREAKFAST_RELEASE_API=f"http://127.0.0.1:{PORT}/release.json")
    proc = subprocess.Popen([str(app_dir / "breakfast.exe")], env=env, cwd=str(app_dir))
    try:
        version_a = wait_for("the installed version", health_version, 90)
        print(f"installed version {version_a}")
        marker = app_dir / "data" / "marker.txt"
        marker.write_text("keep me")

        # 1. a release that cannot start is rolled back
        name = publish(BAD_VERSION, bad_zip)
        assets[:] = [name, name + ".sha256"]
        check = get(f"{APP}/api/updates/check")
        assert check["update_available"] and check["latest"] == BAD_VERSION, check
        assert post(f"{APP}/api/updates/apply") == {"ok": True}
        wait_for("the rollback", lambda: get(f"{APP}/api/updates/status")["phase"] == "rolled_back", 420)
        assert wait_for("the old version again", lambda: health_version() == version_a, 60)
        print("rollback ok:", get(f"{APP}/api/updates/status"))

        # 2. a good release is installed
        name = publish(version_b, zip_b)
        assets[:] = [name, name + ".sha256"]
        assert get(f"{APP}/api/updates/check")["latest"] == version_b
        assert post(f"{APP}/api/updates/apply") == {"ok": True}
        wait_for("the new version", lambda: health_version() == version_b, 420)
        wait_for("the done status", lambda: get(f"{APP}/api/updates/status")["phase"] == "done", 120)
        assert marker.read_text() == "keep me", "data/ must survive an update"
        # the script writes "done" first and removes the backup (hundreds of files) right after
        wait_for("the backup to be removed", lambda: not (app_dir / "update" / "backup").exists(), 90)
        print("update ok:", get(f"{APP}/api/updates/status"))
    except BaseException:
        log = app_dir / "update" / "update.log"
        print("--- update folder ---")
        for p in sorted((app_dir / "update").rglob("*")) if (app_dir / "update").exists() else []:
            print(p.relative_to(app_dir))
        if log.exists():
            print("--- update.log ---")
            print(log.read_text(errors="replace"))
        print("--- processes ---")
        print(subprocess.run(["tasklist"], capture_output=True, text=True).stdout)
        raise
    finally:
        subprocess.run(["taskkill", "/F", "/T", "/IM", "breakfast.exe"], capture_output=True)
        server.shutdown()
    print("e2e ok")


if __name__ == "__main__":
    main(*sys.argv[1:4])
