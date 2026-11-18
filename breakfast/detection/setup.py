"""The first setup of the dart detection at a new board: it has no board model yet, so the worker opens the cameras and waits for one
to be made. The player empties the board, lets the detection look for it in every camera's picture (`boardsearch`), clicks on the 20 in
each picture and lets the model be fitted. Once it is saved the worker goes on as usual.

While this runs, the worker serves a small part of its diagnostics server (status, pictures, the three steps) and tells Breakfast
`no_model`.
"""
import json
import logging
import threading
import time
from dataclasses import fields
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2

from breakfast.detection import boardsearch, calibration, tuning
from breakfast.detection.cameras import CameraGroup
from breakfast.detection.tracker import Settings

log = logging.getLogger("breakfast.detection")
DEFAULT_DEVICES = ["/dev/cam0", "/dev/cam1", "/dev/cam2"]


class SetupSession:
    def __init__(self, cfg, model_path, out):
        self.cfg, self.model_path, self.out = cfg, Path(model_path), out
        names = {f.name for f in fields(Settings)}
        settings = Settings(**{k: v for k, v in cfg.get("tracker", {}).items() if k in names})
        tuning.apply(settings, tuning.load(Path(cfg.get("dir", "detection")) / "tracker_settings.json"))
        self.cams = CameraGroup(cfg.get("devices") or DEFAULT_DEVICES, cfg.get("width", 800), cfg.get("height", 600), cfg.get("fps", 30))
        self.cams.set_controls(settings.exposure, settings.white_balance)
        self.cams.start()
        self.lock = threading.Lock()
        self.found = {}                 # camera -> {H, agree}: the board as the search left it
        self.clicked = set()            # cameras whose picture got its click on the 20
        self.busy = None                # "search" or "fit"
        self.progress = None            # {fraction, text} of that job
        self.problem = None             # what went wrong last: {kind, cams}
        self.done = threading.Event()   # the model is saved
        self.stop = threading.Event()

    # ------------------------------------------------------------------ what the page asks

    def status(self):
        n = len(self.cams.cams)
        with self.lock:
            cameras = [{"found": c in self.found, "clicked": c in self.clicked, "agree": self.found[c]["agree"] if c in self.found else None} for c in range(n)]
            return {"mode": "setup", "cameras": self.cams.status(), "board": {"status": "no_model"},
                    "setup": {"cameras": cameras, "busy": self.busy, "progress": self.progress, "problem": self.problem,
                              "ready": all(c["clicked"] for c in cameras)}}

    def jpeg(self, cam, overlay=True):
        f = self.cams.latest_frames().get(cam)
        if f is None:
            return None
        with self.lock:
            found = self.found.get(cam)
            marked = cam in self.clicked
        if overlay and found:
            f = boardsearch.draw(f, found["H"], marked)
        ok, buf = cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return buf.tobytes() if ok else None

    # ------------------------------------------------------------------ the steps

    def _job(self, name, work):
        with self.lock:
            if self.busy:
                return False
            self.busy, self.progress, self.problem = name, {"fraction": 0.0, "text": ""}, None

        def run():
            try:
                work()
            except Exception:
                log.exception("setup step %s failed", name)
                with self.lock:
                    self.problem = {"kind": "failed", "cams": []}
            finally:
                with self.lock:
                    self.busy, self.progress = None, None

        threading.Thread(target=run, daemon=True, name=f"detection setup {name}").start()
        return True

    def search(self):
        """Look for the board in the picture of every camera. The clicks are lost: the finding may have moved."""
        def work():
            frames = self.cams.latest_frames()
            n = len(self.cams.cams)
            if len(frames) < n:
                with self.lock:
                    self.problem = {"kind": "no_pictures", "cams": [c for c in range(n) if c not in frames]}
                return
            self._keep_pictures(frames)
            found, missing = {}, []
            for c in range(n):
                result = boardsearch.find_board(frames[c], progress=lambda f, c=c: self._progress((c + f) / n, c))
                if result is None:
                    missing.append(c)
                else:
                    found[c] = result
            with self.lock:
                self.found, self.clicked = found, set()
                self.problem = {"kind": "not_found", "cams": missing} if missing else None
            log.info("board search: found in %s, not in %s", sorted(found), missing)
        return self._job("search", work)

    def _keep_pictures(self, frames):
        """The pictures a search was made on, next to the model, to look at when a setup went wrong."""
        folder = self.model_path.parent / "setup"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            for c, f in frames.items():
                cv2.imwrite(str(folder / f"{stamp}-cam{c}.jpg"), f)
            for old in sorted(folder.glob("*.jpg"))[:-12]:
                old.unlink()
        except OSError:
            log.warning("setup pictures not kept in %s", folder)

    def _progress(self, fraction, cam):
        with self.lock:
            self.progress = {"fraction": round(fraction, 3), "camera": cam + 1}

    def click(self, cam, x, y):
        """The player clicked on the 20 in the picture of `cam` (x, y in picture pixels)."""
        with self.lock:
            found = self.found.get(cam)
            if found is None or self.busy:
                return False
            H = boardsearch.turn_for_click(found["H"], (x, y))
            self.found[cam] = {**found, "H": H}
            self.clicked.add(cam)
        return True

    def fit(self):
        """Fit the model on the pictures and save it; the worker goes on with it."""
        def work():
            n = len(self.cams.cams)
            with self.lock:
                ready = all(c in self.clicked for c in range(n))
                homographies = {c: self.found[c]["H"] for c in range(n)} if ready else None
            frames = self.cams.latest_frames()
            if homographies is None or len(frames) < n:
                with self.lock:
                    self.problem = {"kind": "not_ready", "cams": []}
                return
            model, report = boardsearch.fit_model(homographies, frames, lambda f, text: self._progress_fit(f, text))
            self.model_path.parent.mkdir(parents=True, exist_ok=True)
            calibration.save(model, self.model_path, {"source": "first setup", **report})
            log.info("board model made and saved: %s", json.dumps(report))
            self.done.set()
        return self._job("fit", work)

    def _progress_fit(self, fraction, text):
        with self.lock:
            self.progress = {"fraction": round(fraction, 3), "text": text}

    # ------------------------------------------------------------------ the loop

    def heartbeat(self):
        while not self.stop.is_set():
            self.out.put({"type": "worker", "ok": False, "status": "no_model", "count": 0,
                          "cameras": [{"error": c["error"], "fps": c["fps"]} for c in self.cams.status()]})
            self.stop.wait(2.0)


def serve(session, port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/status.json":
                self._send(200, json.dumps(session.status(), default=str).encode())
            elif path.startswith("/frame/") and path.endswith(".jpg") and path[7:-4].isdigit():
                data = session.jpeg(int(path[7:-4]), overlay="raw" not in self.path)
                self._send(200 if data else 404, data or b"", "image/jpeg")
            elif path == "/":
                self._send(200, b"The dart detection waits for its first setup (Board page of Breakfast).", "text/plain")
            else:
                self._send(404, b"", "text/plain")

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
            if self.path == "/api/setup/search":
                ok = session.search()
            elif self.path == "/api/setup/click":
                ok = session.click(int(body["cam"]), float(body["x"]), float(body["y"]))
            elif self.path == "/api/setup/fit":
                ok = session.fit()
            else:
                return self._send(404, b"", "text/plain")
            self._send(200 if ok else 409, b'{"ok":true}' if ok else b'{"ok":false}')

    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True, name="detection setup server").start()
    return srv


def run_setup(cfg, model_path, out):
    """Returns once a board model is saved at `model_path`."""
    session = SetupSession(cfg, model_path, out)
    port = cfg.get("diag_port", 8770)
    srv = serve(session, port) if port else None
    threading.Thread(target=session.heartbeat, daemon=True).start()
    log.info("no board model at %s: waiting for the first setup (Board page of Breakfast)", model_path)
    session.done.wait()
    session.stop.set()
    if srv:
        srv.shutdown()
        srv.server_close()
    session.cams.stop(wait=True)
