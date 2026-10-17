"""The detection process. Reads the cameras, follows the board and sends state messages (the shape of the board manager's
`state` messages) through a queue to Breakfast. It also serves a small diagnostics page (live pictures with the board model,
the last events, buttons for the baseline and the automatic calibration) and keeps the pictures of every event for later analysis.
"""
import json
import logging
import queue as queue_mod
import threading
import time
from dataclasses import fields
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2

from breakfast.detection import calibration
from breakfast.detection.cameras import CameraGroup
from breakfast.detection.clips import ClipRecorder
from breakfast.detection.geometry import BoardModel
from breakfast.detection.tracker import BoardTracker, Settings

log = logging.getLogger("breakfast.detection")
DEFAULT_DEVICES = ["/dev/cam0", "/dev/cam1", "/dev/cam2"]     # the names the compose files give the cameras inside the container
MODEL_WAIT_S = 2.0                      # how often a missing board model is looked for again
KEEP_BUNDLES = 600                      # event folders kept per session


def state_message(tracker, event_name):
    return {"type": "state", "data": {
        "connected": True, "running": True, "event": event_name,
        "status": "Takeout" if tracker.count >= 3 else "Throw",
        "numThrows": tracker.count, "throws": list(tracker.throws)}}


class Worker:
    def __init__(self, cfg, out):
        self.cfg = cfg
        self.out = out
        self.base = Path(cfg.get("dir", "detection"))
        self.model_path = model_path(cfg)
        self.model = BoardModel.from_file(self.model_path)
        names = {f.name for f in fields(Settings)}
        self.settings = Settings(**{k: v for k, v in cfg.get("tracker", {}).items() if k in names})
        self.tracker = BoardTracker(self.model, self.settings)
        self.cams = CameraGroup(cfg.get("devices") or DEFAULT_DEVICES, cfg.get("width", 800), cfg.get("height", 600),
                                cfg.get("fps", 30)).start()
        self.session = self.base / "events" / datetime.now().strftime("session-%Y%m%d-%H%M%S")
        clips = cfg.get("clips", {})
        self.clips = ClipRecorder(self.base / "clips", rate=clips.get("rate", 5.0), pre_s=clips.get("pre_s", 1.5),
                                  post_s=clips.get("post_s", 1.5), max_gb=clips.get("max_gb", 5.0)) if clips.get("enabled", True) else None
        self.events = []                # the last events for the page
        self.seq = 0
        self.lock = threading.Lock()
        self.busy = None                # name of a long job (calibration)
        self.progress = None            # {fraction, text} of that job
        self.points = None              # the 17 points per camera of the adjustment page, {camera: {id: [x, y]}}
        self.edited = {}                # camera -> ids of the points that were moved by hand
        self.dirty = False              # the points hold an automatic fit that has not been saved yet
        self.notes = []                 # results of jobs, newest last
        self.stop = threading.Event()
        self.feed_ms = 0.0              # moving average of the time one set of pictures takes in the tracker
        self.rate = 0.0                 # sets of pictures looked at per second

    # ------------------------------------------------------------------ events

    def handle(self, ev):
        names = {"dart": "Throw detected", "removed": "Takeout in progress", "takeout": "Takeout finished", "baseline": None, "unclear": None}
        entry = {"n": self.seq, "kind": ev.kind, "t": datetime.now().strftime("%H:%M:%S"), "count": ev.count,
                 "field": (ev.throw or {}).get("segment", {}).get("name"), "info": _short(ev.info)}
        self.seq += 1
        with self.lock:
            self.events.append(entry)
            del self.events[:-40]
        log.info("%s: %s", ev.kind, json.dumps(entry["info"] if ev.kind != "dart" else {k: entry["info"].get(k) for k in ("field", "sigma", "margin", "cams")}))
        self._save_bundle(ev, entry)
        if ev.throw is not None:
            ev.throw["detection"]["bundle"] = f"{entry['n']:04d}-{ev.kind}"       # which stored pictures belong to this dart
        if self.clips:
            self.clips.note_event(time.monotonic(), {k: entry[k] for k in ("kind", "count", "field")})
        name = names.get(ev.kind)
        if name:
            self.out.put(state_message(self.tracker, name))

    def _save_bundle(self, ev, entry):
        try:
            d = self.session / f"{entry['n']:04d}-{ev.kind}"
            d.mkdir(parents=True, exist_ok=True)
            for tag, frames in (("before", ev.before), ("after", ev.after)):
                for c, f in (frames or {}).items():
                    cv2.imwrite(str(d / f"{tag}_cam{c}.jpg"), f, [cv2.IMWRITE_JPEG_QUALITY, 92])
            (d / "info.json").write_text(json.dumps({"event": entry, "throw": ev.throw, "tracker_count": ev.count}, default=str, indent=1))
            dirs = sorted(self.session.iterdir())
            for old in dirs[:-KEEP_BUNDLES]:
                for f in old.iterdir():
                    f.unlink()
                old.rmdir()
        except OSError as e:
            log.warning("could not save the pictures of an event: %s", e)

    # ------------------------------------------------------------------ jobs of the page

    def reset(self):
        self.tracker.reset()
        self.note("The next still picture is taken as the empty board.")

    def label(self, index, field, confirm=False):
        """What the player said about a dart of the turn (a correction in Breakfast, or a tap on "this one is right"): stored with the
        detected field and the pictures it came from, a free label for measuring the detection. A confirmation clears the
        uncertain mark and sends the state again."""
        throws = self.tracker.throws
        if not 0 <= index < len(throws):
            return False
        th = throws[index]
        row = {"t": datetime.now().isoformat(timespec="seconds"), "index": index, "detected": th["segment"]["name"],
               "corrected": field, "confirmed": bool(confirm), "detection": th.get("detection")}
        try:
            self.base.mkdir(parents=True, exist_ok=True)
            with open(self.base / "labels.jsonl", "a") as f:
                f.write(json.dumps(row) + "\n")
        except OSError as e:
            log.warning("label not written: %s", e)
        self.note(f"Dart {index + 1}: detected {row['detected']}, " + ("confirmed" if confirm else f"corrected to {field}"))
        if confirm:
            th["detection"]["uncertain"] = False
            self.out.put(state_message(self.tracker, "Dart confirmed"))
        return True

    # ------------------------------------------------------------------ manual adjustment (the 17 points per camera)

    def _signature(self):
        """What identifies the model in use: the points of the page belong to it (after a restart they are only taken back if it is the same)."""
        return json.dumps({"H": {str(c): [round(v, 3) for v in self.model.H[c].flatten()] for c in self.model.cams},
                           "radii": {str(k): round(v, 3) for k, v in sorted(self.model.radii.items())}})

    def _save_points(self):
        try:
            self.base.mkdir(parents=True, exist_ok=True)
            (self.base / "calib_points.json").write_text(json.dumps({"sig": self._signature(), "points": {str(c): p for c, p in self.points.items()},
                                                                     "edited": self.edited}))
        except OSError as e:
            log.warning("calibration points not written: %s", e)

    def _reset_points(self):
        """The points of the page are where the model in use puts them (nothing moved by hand)."""
        self.points = calibration.model_points(self.model)
        self.edited = {str(c): [] for c in self.model.cams}
        self.dirty = False
        self._save_points()

    def _ensure_points(self):
        if self.points is not None:
            return
        try:
            d = json.loads((self.base / "calib_points.json").read_text())
            if d["sig"] == self._signature():
                self.points = {int(c): p for c, p in d["points"].items()}
                self.edited = d["edited"]
                return
        except (OSError, ValueError, KeyError):
            pass
        self._reset_points()

    def adjustment(self):
        """What the adjustment page needs: the 17 points of every camera, which of them were moved by hand, the model fitted to them
        (a homography per camera, the ring radii) and how well it fits."""
        self._ensure_points()
        fitted, report = calibration.fit_points(self.points, self.model)
        return {"size": list(self.model.size), "targets": calibration.targets(),
                "points": {str(c): p for c, p in self.points.items()}, "edited": self.edited,
                "H": {str(c): fitted.H[c].tolist() for c in fitted.cams}, "radii": {str(k): v for k, v in fitted.radii.items()},
                "report": report, "dirty": self.dirty, "can_revert": self.model_path.with_suffix(".prev.json").exists()}

    def move_point(self, cam, pid, xy):
        self._ensure_points()
        if cam not in self.points or pid not in self.points[cam]:
            return None
        w, h = self.model.size
        self.points[cam][pid] = [round(min(max(float(xy[0]), 0.0), w), 2), round(min(max(float(xy[1]), 0.0), h), 2)]
        if pid not in self.edited[str(cam)]:
            self.edited[str(cam)].append(pid)
        self._save_points()
        return self.adjustment()

    def discard_points(self):
        self._reset_points()
        return self.adjustment()

    def save_points_as_model(self):
        """Fit the model to the points and use it. The previous model is kept as `.prev.json`; the next still picture is the empty board."""
        self._ensure_points()
        fitted, report = calibration.fit_points(self.points, self.model)
        calibration.save(fitted, self.model_path, {"source": "manual adjustment", **report})
        self._use_model(fitted)
        self.dirty = False
        self._save_points()                                  # the points stay where they are, now as the points of the model in use
        self.note("Model adjusted by hand and saved; the next still picture is taken as the empty board.")

    def apply_model(self, new, text):
        calibration.save(new, self.model_path, {"source": "manual adjustment"})
        self._use_model(new)
        self.note(text)

    def _use_model(self, new):
        self.model = new
        self.tracker.model = new
        self.tracker._small_mask = {c: cv2.resize(m, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_NEAREST) > 0 for c, m in new.masks.items()}
        self.tracker.reset()

    def revert_model(self):
        old = calibration.revert(self.model_path)
        if old is None:
            return False
        self._use_model(old)
        self._reset_points()
        self.note("The previous model is back; the next still picture is taken as the empty board.")
        return True

    def note(self, text):
        with self.lock:
            self.notes.append({"t": datetime.now().strftime("%H:%M:%S"), "text": text})
            del self.notes[:-12]

    def calibrate(self, preview=False):
        """Fit the model on the pictures of the empty board. With `preview` the result only moves the points of the adjustment page (to be
        looked at, corrected and saved there); otherwise the model is saved and used at once."""
        if self.busy:
            return
        self.busy = "calibration"
        self.progress = {"fraction": 0.0, "text": "starting"}

        def job():
            try:
                frames = self.cams.latest_frames()
                if len(frames) < len(self.model.cams):
                    self.note("Calibration: not every camera has a picture.")
                    return
                self.note("Calibration started (takes about a minute; the board must be empty).")
                new, report = calibration.calibrate(self.model, frames, lambda f, text: setattr(self, "progress", {"fraction": round(f, 3), "text": text}))
                if new is None:
                    self.note("Calibration refused: " + report["refused"])
                    return
                if preview:
                    self._ensure_points()
                    self.points = calibration.model_points(new)
                    self.edited = {str(c): [] for c in new.cams}
                    self.dirty = True
                    self._save_points()
                    self.note("The automatic fit moved the points; look at them, correct what is off and save. " + json.dumps(report))
                else:
                    calibration.save(new, self.model_path, report)
                    self._use_model(new)
                    self._reset_points()
                    self.note("Calibration done and saved: " + json.dumps(report))
            except Exception as e:
                log.exception("calibration failed")
                self.note(f"Calibration failed: {e}")
            finally:
                self.busy = None
                self.progress = None

        threading.Thread(target=job, daemon=True).start()

    # ------------------------------------------------------------------ main loop

    def status(self):
        with self.lock:
            events, notes = list(self.events), list(self.notes)
        return {"cameras": self.cams.status(), "board": {"status": board_status(self.tracker.status, self.cams.status()), "count": self.tracker.count, "moving": self.tracker.moving,
                "throws": [t["segment"]["name"] for t in self.tracker.throws]}, "busy": self.busy, "progress": self.progress, "events": events[::-1],
                "notes": notes[::-1], "settings": self.settings.__dict__, "load": {"feed_ms": round(self.feed_ms, 1), "looks_per_s": round(self.rate, 1)},
                "clips": self.clips.count if self.clips else None, "model": {"radii": {str(k): round(v, 2) for k, v in self.model.radii.items()}}}

    def jpeg(self, cam, overlay=True):
        frames = self.cams.latest_frames()
        f = frames.get(cam)
        if f is None:
            return None
        if overlay:
            f = self.model.draw(cam, f)
        ok, buf = cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return buf.tobytes() if ok else None

    def run(self):
        threading.Thread(target=self._heartbeat, daemon=True).start()
        port = self.cfg.get("diag_port", 8770)
        if port:
            serve(self, port)
        log.info("detection worker running: %d cameras, model %s", len(self.cams.cams), self.model_path)
        interval = 1.0 / float(self.cfg.get("max_rate", 10))     # the board is still for most of the time: 10 looks per second are plenty
        last, count, t0 = 0.0, 0, time.monotonic()
        while not self.stop.is_set():
            frames = self.cams.frames()
            now = time.monotonic()
            if frames is None or now - last < interval:
                time.sleep(0.005)
                continue
            last = now
            for ev in self.tracker.feed(now, frames):
                self.handle(ev)
            if self.clips:
                self.clips.offer(now, frames, self.tracker.moving, {"count": self.tracker.count, "status": self.tracker.status})
            took = (time.monotonic() - now) * 1000.0
            self.feed_ms = took if self.feed_ms == 0 else 0.95 * self.feed_ms + 0.05 * took
            count += 1
            if time.monotonic() - t0 >= 2.0:
                self.rate, count, t0 = count / (time.monotonic() - t0), 0, time.monotonic()

    def _heartbeat(self):
        while not self.stop.is_set():
            ok = all(c["error"] is None and c["age_s"] is not None and c["age_s"] < 2.0 for c in self.cams.status())
            self.out.put({"type": "worker", "ok": ok, "status": board_status(self.tracker.status, self.cams.status()), "count": self.tracker.count,
                          "cameras": [{"error": c["error"], "fps": c["fps"]} for c in self.cams.status()]})
            if ok:
                self.out.put(state_message(self.tracker, "Heartbeat"))
            self.stop.wait(2.0)


def _short(info):
    out = {}
    for k, v in (info or {}).items():
        out[k] = round(v, 2) if isinstance(v, float) else v
    return out


# ---------------------------------------------------------------------- diagnostics page

PAGE = """<!doctype html><meta charset=utf-8><title>Detection</title>
<style>body{font-family:system-ui;background:#17171f;color:#eee;margin:1rem}img{width:32%;border:1px solid #444}
button{padding:.4rem .9rem;margin:.2rem;border-radius:8px;border:1px solid #666;background:#2a2a35;color:#eee;cursor:pointer}
table{border-collapse:collapse;font-size:.85rem}td,th{border-bottom:1px solid #333;padding:.2rem .6rem;text-align:left}
.k-dart{color:#7ddc7d}.k-unclear{color:#f5c542}.k-takeout,.k-removed{color:#6cb6ff}pre{white-space:pre-wrap;font-size:.8rem}</style>
<h2>Dart detection</h2>
<div><button onclick="post('reset')">Empty board = now</button>
<span id=st></span></div>
<div id=cams></div><h3>Events</h3><table id=ev></table><h3>Notes</h3><pre id=nt></pre><h3>Cameras and settings</h3><pre id=cm></pre>
<script>
const cams=document.getElementById('cams');for(let i=0;i<3;i++){const im=document.createElement('img');im.id='c'+i;cams.appendChild(im)}
async function post(p){await fetch('/api/'+p,{method:'POST'});tick()}
async function tick(){
 const s=await (await fetch('/status.json')).json();
 document.getElementById('st').textContent=' board: '+s.board.status+' | darts: '+s.board.count+' ['+s.board.throws.join(', ')+'] '+(s.board.moving?'| moving':'')+(s.busy?' | '+s.busy+' '+Math.round(((s.progress||{}).fraction||0)*100)+' % '+((s.progress||{}).text||''):'');
 document.getElementById('ev').innerHTML='<tr><th>#<th>time<th>kind<th>darts<th>field<th>info</tr>'+s.events.map(e=>`<tr class=k-${e.kind}><td>${e.n}<td>${e.t}<td>${e.kind}<td>${e.count}<td>${e.field??''}<td>${JSON.stringify(e.info).slice(0,160)}</tr>`).join('');
 document.getElementById('nt').textContent=s.notes.map(n=>n.t+' '+n.text).join('\\n');
 document.getElementById('cm').textContent=JSON.stringify({cameras:s.cameras,settings:s.settings,model:s.model},null,1);
 for(let i=0;i<3;i++)document.getElementById('c'+i).src='/frame/'+i+'.jpg?'+Date.now();
}
tick();setInterval(tick,1500);
</script>"""


def serve(worker, port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/":
                self._send(200, PAGE.encode(), "text/html; charset=utf-8")
            elif path == "/status.json":
                self._send(200, json.dumps(worker.status(), default=str).encode(), "application/json")
            elif path == "/api/model":
                self._send(200, json.dumps(worker.adjustment()).encode(), "application/json")
            elif path.startswith("/frame/") and path.endswith(".jpg"):
                data = worker.jpeg(int(path[7:-4]), overlay="raw" not in self.path)
                self._send(200 if data else 404, data or b"", "image/jpeg")
            else:
                self._send(404, b"", "text/plain")

        def do_POST(self):
            if self.path == "/api/model/move":
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
                state = worker.move_point(int(body["cam"]), str(body["id"]), body["xy"])
                return self._send(200 if state else 404, json.dumps(state or {"ok": False}).encode(), "application/json")
            if self.path == "/api/model/discard":
                return self._send(200, json.dumps(worker.discard_points()).encode(), "application/json")
            if self.path == "/api/model/save":
                worker.save_points_as_model()
                return self._send(200, b'{"ok":true}', "application/json")
            if self.path == "/api/model/revert":
                ok = worker.revert_model()
                return self._send(200 if ok else 404, json.dumps({"ok": ok}).encode(), "application/json")
            if self.path == "/api/reset":
                worker.reset()
            elif self.path == "/api/calibrate":
                worker.calibrate()
            elif self.path == "/api/model/auto":
                worker.calibrate(preview=True)
            elif self.path.startswith("/api/label") or self.path.startswith("/api/confirm"):
                from urllib.parse import parse_qs, urlparse
                q = parse_qs(urlparse(self.path).query)
                index = int(q.get("index", ["-1"])[0])
                if self.path.startswith("/api/confirm"):
                    ok = worker.label(index, worker.tracker.throws[index]["segment"]["name"] if 0 <= index < len(worker.tracker.throws) else "", confirm=True)
                else:
                    ok = worker.label(index, q.get("field", [""])[0])
                return self._send(200 if ok else 404, b'{"ok":true}' if ok else b'{"ok":false}', "application/json")
            else:
                return self._send(404, b"", "text/plain")
            self._send(200, b'{"ok":true}', "application/json")

    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True, name="detection diagnostics").start()
    log.info("detection diagnostics page on port %d", port)


def board_status(tracker_status, cameras):
    """What Breakfast is told about the board: `no_cameras` while a camera cannot be opened or read, else the tracker's status."""
    return "no_cameras" if any(c["error"] for c in cameras) else tracker_status


def model_path(cfg):
    return Path(cfg.get("model", Path(cfg.get("dir", "detection")) / "calib_model.json"))


def wait_for_model(cfg, out, stop=None):
    """Returns once the board model can be read. Without one the detection cannot follow the board: the worker stays alive, tells
    Breakfast `no_model` and looks again every few seconds, instead of ending and being started over and over."""
    path, told = model_path(cfg), False
    while stop is None or not stop.is_set():
        try:
            BoardModel.from_file(path)
            return True
        except (OSError, ValueError, KeyError, TypeError) as e:
            if not told:
                log.warning("no usable board model at %s (%s: %s): the dart detection waits for it", path, type(e).__name__, e)
                told = True
        out.put({"type": "worker", "ok": False, "status": "no_model", "count": 0, "cameras": []})
        time.sleep(MODEL_WAIT_S) if stop is None else stop.wait(MODEL_WAIT_S)
    return False


def run(cfg, out):
    """Entry point of the worker process."""
    cv2.setNumThreads(int(cfg.get("cv_threads", 2)))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    wait_for_model(cfg, out)
    Worker(cfg, out).run()
