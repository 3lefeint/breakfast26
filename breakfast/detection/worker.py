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

from breakfast.detection import calibration, debug, detector, drift, labels, tuning
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
        self.settings_path = self.base / "tracker_settings.json"
        tuning.apply(self.settings, tuning.load(self.settings_path))        # what was set on the Board page wins over config.toml
        self.tracker = BoardTracker(self.model, self.settings)
        self.cams = CameraGroup(cfg.get("devices") or DEFAULT_DEVICES, cfg.get("width", 800), cfg.get("height", 600), cfg.get("fps", 30))
        self._push_controls()
        self.cams.start()
        self.session = self.base / "events" / datetime.now().strftime("session-%Y%m%d-%H%M%S")
        removed = tuning.clean_sessions(self.base / "events", keep=cfg.get("keep_sessions", 10), max_gb=cfg.get("events_max_gb", 2.0), current=self.session)
        if removed:
            log.info("removed %d old sessions of event pictures", len(removed))
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
        self.drift = None               # the last drift check: {level, cams, t}, see drift.py
        self._reference_due = False     # the next picture of the empty board becomes the reference of the drift check (the model changed)
        self.stop = threading.Event()
        self.feed_ms = 0.0              # moving average of the time one set of pictures takes in the tracker
        self.rate = 0.0                 # sets of pictures looked at per second
        self._sent_status = None        # the tracker status Breakfast was told last
        self.frozen = None              # the last dart, block or unclear change with its pictures, for the debug view: {entry, before, after}
        self._motion = []               # (time, share of moving pixels) of the last two seconds
        self.turn = []                  # the darts counted since the board was last empty, each like `frozen`, for the debug view
        self._debug = {}                # view -> (key, time, info, pictures): what the debug view was given last
        self._debug_lock = threading.Lock()

    # ------------------------------------------------------------------ events

    def handle(self, ev):
        names = {"dart": "Throw detected", "removed": "Takeout in progress", "takeout": "Takeout finished", "baseline": None, "unclear": None, "blocked": None}
        entry = {"n": self.seq, "kind": ev.kind, "t": datetime.now().strftime("%H:%M:%S"), "count": ev.count,
                 "field": (ev.throw or {}).get("segment", {}).get("name"), "info": _short(ev.info)}
        self.seq += 1
        with self.lock:
            self.events.append(entry)
            del self.events[:-40]
        log.info("%s: %s", ev.kind, json.dumps(entry["info"] if ev.kind != "dart" else {k: entry["info"].get(k) for k in ("field", "sigma", "margin", "cams")}))
        self._save_bundle(ev, entry)
        if ev.kind in ("dart", "blocked", "unclear") and ev.before and ev.after:
            self.frozen = {"entry": entry, "before": ev.before, "after": ev.after}
        if ev.kind == "dart":
            self.turn = ([] if ev.count <= 1 else self.turn[-2:]) + [{"entry": entry, "before": ev.before, "after": ev.after}]
        if ev.kind in ("baseline", "takeout") and ev.after:
            self._check_drift(ev.after)
        if ev.throw is not None:
            ev.throw["detection"]["bundle"] = f"{entry['n']:04d}-{ev.kind}"       # which stored pictures belong to this dart
            if ev.kind == "dart":
                self._log_dart(ev)
        if self.clips:
            self.clips.note_event(time.monotonic(), {k: entry[k] for k in ("kind", "count", "field")})
        name = names.get(ev.kind)
        if name:
            self.out.put(state_message(self.tracker, name))

    def _check_drift(self, frames):
        """The board is empty: has a camera moved since the model was made? The first empty picture after a new model (or without any
        reference yet) becomes the reference."""
        try:
            prepared = {c: detector.prepare(f) for c, f in frames.items()}
            folder = self.base / "reference"
            ref = None if self._reference_due else drift.load_reference(folder, self.model.cams)
            now = datetime.now().strftime("%H:%M:%S")
            if ref is None:
                drift.save_reference(folder, prepared)
                self._reference_due = False
                self.drift = {"level": "ok", "cams": {}, "t": now, "reference": now}
                self.note("The empty board is the reference picture of the drift check now.")
                return
            result = drift.measure(self.model, ref, prepared)
            level = drift.worst(result)
            was = (self.drift or {}).get("level")
            self.drift = {"level": level, "cams": {str(c): r for c, r in result.items()}, "t": now,
                          "reference": (self.drift or {}).get("reference")}
            if level in ("warn", "bad") and level != was:
                moved = ", ".join(f"camera {c + 1}: {r['px']} px" for c, r in result.items() if r["level"] in ("warn", "bad"))
                self.note(f"Drift: the empty board looks different from the reference picture ({moved}). A camera or the board may have moved.")
        except Exception:
            log.exception("drift check failed")

    def _push_controls(self):
        self.cams.set_controls(self.settings.exposure, self.settings.white_balance)

    def change_settings(self, changes):
        """Set tracker settings from the Board page and keep them. Returns {applied, refused}."""
        done, refused = tuning.apply(self.settings, changes)
        if done:
            tuning.save(self.settings_path, {**tuning.load(self.settings_path), **done})
            self._push_controls()
            self.note("Settings changed: " + ", ".join(f"{k} = {v}" for k, v in done.items()))
        return {"applied": done, "refused": refused}

    def reset_settings(self):
        """Back to the values of config.toml (or the built-in ones)."""
        names = {f.name for f in fields(Settings)}
        base = {k: v for k, v in self.cfg.get("tracker", {}).items() if k in names}
        for key in tuning.TUNABLE:
            setattr(self.settings, key, base.get(key, tuning._default(key)))
        self.settings_path.unlink(missing_ok=True)
        self._push_controls()
        self.note("Settings are back to the values of config.toml.")

    def take_reference(self):
        """The empty board as it is now is the reference of the drift check. False if the board is not known to be empty."""
        if self.tracker.empty is None or self.tracker.count:
            return False
        drift.save_reference(self.base / "reference", self.tracker.empty)
        self._reference_due = False
        now = datetime.now().strftime("%H:%M:%S")
        self.drift = {"level": "ok", "cams": {}, "t": now, "reference": now}
        self.note("The empty board is the reference picture of the drift check now.")
        return True

    def _log_dart(self, ev):
        """One row per counted dart in `darts.jsonl` (kept for good, unlike the pictures): what was detected and how sure. A dart that is
        never corrected is in here and not in `labels.jsonl`; together they say how many darts nobody looked at."""
        row = {"t": datetime.now().isoformat(timespec="seconds"), "session": self.session.name, "count": ev.count,
               "field": ev.throw["segment"]["name"], "at": ev.throw.get("coords"), "detection": ev.throw["detection"]}
        try:
            self.base.mkdir(parents=True, exist_ok=True)
            with open(self.base / "darts.jsonl", "a") as f:
                f.write(json.dumps(row, default=str) + "\n")
        except OSError as e:
            log.warning("dart not logged: %s", e)

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

    def _context(self):
        """Where a label belongs: the session of the event pictures, the clip that was recorded last, the number of the last event."""
        return {"session": self.session.name, "clip": self.clips.last_name if self.clips else None, "event": self.seq - 1}

    def _write_label(self, row):
        try:
            self.base.mkdir(parents=True, exist_ok=True)
            with open(self.base / "labels.jsonl", "a") as f:
                f.write(json.dumps(row) + "\n")
        except OSError as e:
            log.warning("label not written: %s", e)

    def bouncer(self):
        """A dart bounced off (reported by the player): it takes its place in the turn as a miss (so the next dart is the next one), and a label
        says when, in which session and clip. False when the turn is full."""
        throw = self.tracker.add_bouncer()
        if throw is None:
            return False
        self._write_label({"t": datetime.now().isoformat(timespec="seconds"), "kind": "bouncer", "index": self.tracker.count - 1,
                           **self._context()})
        if self.clips:
            self.clips.note_event(time.monotonic(), {"kind": "bouncer", "count": self.tracker.count, "field": None})
        self.note(f"Dart {self.tracker.count}: bounced off, counted as a miss")
        self.out.put(state_message(self.tracker, "Dart confirmed"))
        return True

    def mark(self):
        """Something was off at this moment (reported by the player, no more than that): a label with the time, the session and the clip."""
        self._write_label({"t": datetime.now().isoformat(timespec="seconds"), "kind": "mark", "count": self.tracker.count, **self._context()})
        if self.clips:
            self.clips.note_event(time.monotonic(), {"kind": "mark", "count": self.tracker.count, "field": None})
        self.note("Marked: something was off here")
        return True

    def label(self, index, field, confirm=False, point=None):
        """What the player said about a dart of the turn (a correction in Breakfast, or a tap on "this one is right"): stored with the
        detected field and the pictures it came from, a free label for measuring the detection. A confirmation clears the
        uncertain mark and sends the state again."""
        throws = self.tracker.throws
        if index == len(throws) and field and not confirm:      # a dart the detection never counted, entered by hand: a label of its own
            th = None
        elif not 0 <= index < len(throws):
            return False
        else:
            th = throws[index]
        row = {"t": datetime.now().isoformat(timespec="seconds"), "index": index, "detected": th["segment"]["name"] if th else "",
               "corrected": field, "confirmed": bool(confirm), "detection": th.get("detection") if th else None,
               "detected_at": th.get("coords") if th else None, **self._context()}
        if th is None:
            row["unseen"] = True
        if point:
            row["corrected_at"] = point          # where the player tapped on the board, board units: the detection error in mm
        self._write_label(row)
        self.note(f"Dart {index + 1}: " + (f"not counted, entered as {field}" if th is None else
                  f"detected {row['detected']}, " + ("confirmed" if confirm else f"corrected to {field}")))
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
        self._reference_due = True                  # the model fits the picture of the empty board that comes next
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
                "clips": self.clips.count if self.clips else None, "drift": self.drift, "model": {"radii": {str(k): round(v, 2) for k, v in self.model.radii.items()}}}

    def debug_view(self, view):
        """(info, camera -> JPEG) of the debug view: what the detection sees between two picture sets. `live`: the picture after the
        last settled state against the picture of now, with the movement and the latest look. `frozen`: the pictures before and after
        the last dart, block or unclear change. Worked out when the page asks and kept for a moment, so three pictures and
        their numbers come from the same look."""
        with self._debug_lock:
            frozen, now = self.frozen, time.monotonic()
            key = frozen["entry"]["n"] if view == "frozen" and frozen else None
            kept = self._debug.get(view)
            if kept and kept[0] == key and (view == "frozen" or now - kept[1] < 0.3):
                return kept[2], kept[3]
            info, pictures = {"cams": {}, "fused": None}, {}
            if view == "frozen":
                if frozen:
                    before = {c: detector.prepare(f) for c, f in frozen["before"].items()}
                    after = {c: detector.prepare(f) for c, f in frozen["after"].items()}
                    info, pictures = debug.explain(self.model, before, after, frozen["after"])
                    info["event"] = frozen["entry"]
            else:
                frames, ref = self.cams.latest_frames(), self.tracker.ref
                if ref is not None and all(c in frames and c in ref for c in self.model.cams):
                    info, pictures = debug.explain(self.model, ref, {c: detector.prepare(frames[c]) for c in self.model.cams}, frames)
                look = self.tracker.look
                info.update(motion=self.tracker.motion, motion_peak=max((m for _, m in self._motion), default=0.0),
                            motion_threshold=self.settings.motion_fraction, moving=self.tracker.moving, status=self.tracker.status,
                            count=self.tracker.count, min_area=self.settings.min_area, max_area=self.settings.max_area,
                            look=look and {"ago_s": round(now - look["t"], 1), "events": look["events"], "status": look["status"], "why": look["why"]})
            self._debug[view] = (key, now, info, pictures)
            return info, pictures

    def debug_turn(self):
        """The darts counted since the board was last empty, for the debug view: per dart its event and where every camera put it
        (as `debug_view` gives it, without pictures). They stay after the takeout, until the first dart of the next turn."""
        with self._debug_lock:
            turn = list(self.turn)
            key = tuple(d["entry"]["n"] for d in turn)
            kept = self._debug.get("turn")
            if kept and kept[0] == key:
                return kept[2]
            darts = []
            for d in turn:
                info = {"cams": {}, "fused": None}
                if d["before"] and d["after"]:
                    info, _ = debug.explain(self.model, {c: detector.prepare(f) for c, f in d["before"].items()},
                                            {c: detector.prepare(f) for c, f in d["after"].items()})
                info["event"] = d["entry"]
                darts.append(info)
            out = {"darts": darts}
            self._debug["turn"] = (key, time.monotonic(), out, {})
            return out

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
            self._motion = [(ts, m) for ts, m in self._motion if now - ts < 2.0] + [(now, self.tracker.motion)]
            if self.tracker.status != self._sent_status:
                self._send_status()
            if self.clips:
                self.clips.offer(now, frames, self.tracker.moving or self.tracker.status == "blocked", {"count": self.tracker.count, "status": self.tracker.status})
            took = (time.monotonic() - now) * 1000.0
            self.feed_ms = took if self.feed_ms == 0 else 0.95 * self.feed_ms + 0.05 * took
            count += 1
            if time.monotonic() - t0 >= 2.0:
                self.rate, count, t0 = count / (time.monotonic() - t0), 0, time.monotonic()

    def _send_status(self):
        """The state of the cameras and the tracker for Breakfast; every 2 seconds, and at once when the tracker's status changes
        (so a blocked board shows on the TV view without delay). Returns whether the cameras are fine."""
        ok = all(c["error"] is None and c["age_s"] is not None and c["age_s"] < 2.0 for c in self.cams.status())
        self._sent_status = self.tracker.status
        self.out.put({"type": "worker", "ok": ok, "status": board_status(self.tracker.status, self.cams.status()), "count": self.tracker.count,
                      "drift": (self.drift or {}).get("level"),
                      "cameras": [{"error": c["error"], "fps": c["fps"]} for c in self.cams.status()]})
        return ok

    def _heartbeat(self):
        while not self.stop.is_set():
            ok = self._send_status()
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
.dbg img{width:100%}.dbg figure{display:inline-block;width:32%;margin:0 .5% 0 0;vertical-align:top}.dbg figcaption{font-size:.8rem;color:#bbb}
.dbg canvas{background:#111;border:1px solid #444;vertical-align:top}.bar{position:relative;display:inline-block;width:22rem;height:.9rem;background:#111;border:1px solid #444;vertical-align:middle}
.bar i{position:absolute;left:0;top:0;bottom:0;background:#6cb6ff}.bar b{position:absolute;top:-3px;bottom:-3px;width:2px;background:#f5c542}.bar u{position:absolute;top:0;bottom:0;width:2px;background:#fff}
.k-dart{color:#7ddc7d}.k-unclear,.k-blocked{color:#f5c542}.k-takeout,.k-removed{color:#6cb6ff}pre{white-space:pre-wrap;font-size:.8rem}</style>
<h2>Dart detection</h2>
<div><button onclick="post('reset')">Empty board = now</button>
<span id=st></span></div>
<div id=cams></div>
<h3><label><input type=checkbox id=dbgon onchange="dbgToggle()"> What the detection sees</label></h3>
<div id=dbg class=dbg style="display:none">
<p style="font-size:.8rem;color:#bbb">red: changed pixels | cyan: the biggest blob | magenta: line of the shaft | white cross: tip. Board: one dot per camera, white cross where they are put together.</p>
<p>Movement <span class=bar><i id=mv></i><u id=mvp></u><b id=mvt></b></span> <span id=mvx></span></p>
<p id=look></p>
<h4>Now, against the picture after the last settled state</h4><div id=dl></div>
<h4>Darts since the board was last empty</h4><div id=dt></div>
<h4 id=fzt>Last dart, block or unclear change</h4><div id=df></div>
</div>
<h3>Events</h3><table id=ev></table><h3>Notes</h3><pre id=nt></pre><h3>Cameras and settings</h3><pre id=cm></pre>
<script>
const cams=document.getElementById('cams');for(let i=0;i<3;i++){const im=document.createElement('img');im.id='c'+i;cams.appendChild(im)}
async function post(p){await fetch('/api/'+p,{method:'POST'});tick()}
async function tick(){
 const s=await (await fetch('/status.json')).json();
 document.getElementById('st').textContent=' board: '+s.board.status+' | darts: '+s.board.count+' ['+s.board.throws.join(', ')+'] '+(s.board.moving?'| moving':'')+(s.busy?' | '+s.busy+' '+Math.round(((s.progress||{}).fraction||0)*100)+' % '+((s.progress||{}).text||''):'');
 document.getElementById('ev').innerHTML='<tr><th>#<th>time<th>kind<th>darts<th>field<th>info</tr>'+s.events.map(e=>`<tr class=k-${e.kind}><td>${e.n}<td>${e.t}<td>${e.kind}<td>${e.count}<td>${e.field??''}<td>${JSON.stringify(e.info).slice(0,160)}</tr>`).join('');
 document.getElementById('nt').textContent=s.notes.map(n=>n.t+' '+n.text).join('\\n');
 radii=s.model.radii;
 document.getElementById('cm').textContent=JSON.stringify({cameras:s.cameras,settings:s.settings,model:s.model},null,1);
 for(let i=0;i<3;i++)document.getElementById('c'+i).src='/frame/'+i+'.jpg?'+Date.now();
}
const COL=['#ff6b6b','#6bff8f','#6bb5ff'];let radii=null,dbgTimer=null,frozenN=null;
function build(id,view){const d=document.getElementById(id);for(let i=0;i<3;i++){const f=document.createElement('figure');f.innerHTML=`<img id=${view}i${i}><figcaption id=${view}c${i}></figcaption>`;d.appendChild(f)}
 const p=document.createElement('p');p.innerHTML=`<canvas id=${view}b width=260 height=260></canvas> <span id=${view}f style="display:inline-block;vertical-align:top;font-size:.85rem;margin-left:.6rem"></span>`;d.appendChild(p)}
build('dl','live');build('df','frozen');
{const d=document.getElementById('dt');for(let i=0;i<3;i++){const f=document.createElement('figure');f.innerHTML=`<canvas id=turn${i}b width=260 height=260></canvas><figcaption id=turn${i}f></figcaption>`;d.appendChild(f)}}
function turn(t){for(let i=0;i<3;i++){const d=t.darts[i],cap=document.getElementById('turn'+i+'f');board('turn'+i,d||{});
 if(!d){cap.textContent='dart '+(i+1)+': none yet';continue}
 const e=d.event,f=d.fused,why=(e.info||{}).why;
 cap.innerHTML=`dart ${e.count}: <b>${e.field??''}</b> #${e.n} ${e.t}${why?' ('+why+')':''}<br>`+Object.entries(d.cams||{}).map(([c,row])=>`<span style="color:${COL[c%3]}">&#9679;</span> ${row.mm?row.mm[0]+', '+row.mm[1]+' mm'+(row.off?' (off)':''):(row.how||'nothing')}`).join('<br>')+
  (f?`<br>cameras ${f.cams}, agreeing ${f.agree} | apart ${f.spread} mm | to the next wire ${f.margin} mm`:'<br>no pictures of this dart')}}
function board(view,info){const cv=document.getElementById(view+'b'),g=cv.getContext('2d'),R=260,S=130/215,X=(x)=>130+x*S,Y=(y)=>130-y*S;
 g.clearRect(0,0,R,R);g.strokeStyle='#666';g.lineWidth=1;
 const rr=radii?Object.values(radii).concat([15.9,6.35]):[170,162,107,99,15.9,6.35];
 for(const r of rr){g.beginPath();g.arc(130,130,r*S,0,7);g.stroke()}
 const ro=radii?radii['170.0']||170:170;
 for(let k=0;k<20;k++){const a=(9+18*k)*Math.PI/180;g.beginPath();g.moveTo(X(15.9*Math.sin(a)),Y(15.9*Math.cos(a)));g.lineTo(X(ro*Math.sin(a)),Y(ro*Math.cos(a)));g.stroke()}
 const cl=(v)=>Math.max(-212,Math.min(212,v));
 for(const [c,row] of Object.entries(info.cams||{})){if(!row.mm)continue;g.fillStyle=COL[c%3];g.beginPath();g.arc(X(cl(row.mm[0])),Y(cl(row.mm[1])),4,0,7);g.fill()}
 const f=info.fused;if(f){const x=X(cl(f.x)),y=Y(cl(f.y));g.strokeStyle='#fff';g.lineWidth=2;g.beginPath();g.moveTo(x-7,y);g.lineTo(x+7,y);g.moveTo(x,y-7);g.lineTo(x,y+7);g.stroke()}}
function show(view,info){
 for(let i=0;i<3;i++){const row=(info.cams||{})[i];const im=document.getElementById(view+'i'+i);
  im.src=row?'/debug/'+view+'/'+i+'.jpg?'+(view=='frozen'?'n='+frozenN:Date.now()):'';
  document.getElementById(view+'c'+i).innerHTML=row?`<span style="color:${COL[i]}">&#9679;</span> camera ${i}: blob ${row.area} px`+(row.tip?` | tip ${row.tip[0]}, ${row.tip[1]} px (${row.how}) | board ${row.mm[0]}, ${row.mm[1]} mm`+(row.off?' | off the board':''):` | ${row.how||''}`):''}
 const f=info.fused;
 document.getElementById(view+'f').innerHTML=f?`together: <b>${f.field=='0'?'miss':f.field}</b> at ${f.x}, ${f.y} mm<br>cameras ${f.cams}, agreeing ${f.agree}, off the board ${f.off}<br>farthest apart ${f.spread} mm<br>uncertainty ${f.sigma} mm, to the next wire ${f.margin} mm`:'no camera sees a change';
 board(view,info)}
async function dbgTick(){
 try{
  const l=await (await fetch('/debug/live.json')).json();
  const top=Math.max(4*l.motion_threshold,l.motion_peak,1e-6),pc=(v)=>Math.min(100,100*v/top)+'%';
  document.getElementById('mv').style.width=pc(l.motion);document.getElementById('mvp').style.left=pc(l.motion_peak);document.getElementById('mvt').style.left=pc(l.motion_threshold);
  document.getElementById('mvx').textContent=`${(100*l.motion).toFixed(2)} % of the pixels (most in 2 s: ${(100*l.motion_peak).toFixed(2)} %, moving from ${(100*l.motion_threshold).toFixed(2)} %) | ${l.moving?'moving':'still'} | blob: dart from ${l.min_area} px, hand from ${l.max_area} px`;
  const k=l.look;document.getElementById('look').textContent='Board: '+l.status+', darts: '+l.count+' | last look '+(k?`${k.ago_s} s ago: ${k.events.length?k.events.join(', '):(k.status=='blocked'?'blocked':'nothing new')}${k.why?' ('+k.why+')':''}`:'none yet');
  show('live',l);
  turn(await (await fetch('/debug/turn.json')).json());
  const f=await (await fetch('/debug/frozen.json')).json();
  const n=f.event?f.event.n:null;
  if(n!==frozenN){frozenN=n;document.getElementById('fzt').textContent=f.event?`Last dart, block or unclear change: #${f.event.n} ${f.event.t} ${f.event.kind} ${f.event.field??''} ${(f.event.info||{}).why??''}`:'Last dart, block or unclear change: none yet';show('frozen',f)}
 }catch(e){}
}
function dbgToggle(){const on=document.getElementById('dbgon').checked;document.getElementById('dbg').style.display=on?'':'none';
 clearInterval(dbgTimer);dbgTimer=null;if(on){frozenN=undefined;dbgTick();dbgTimer=setInterval(dbgTick,500)}}
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
            elif path == "/api/settings":
                self._send(200, json.dumps(tuning.describe(worker.settings)).encode(), "application/json")
            elif path == "/api/labels":
                self._send(200, json.dumps(labels.summary_of(worker.base / "labels.jsonl", worker.base / "darts.jsonl")).encode(), "application/json")
            elif path == "/api/model":
                self._send(200, json.dumps(worker.adjustment()).encode(), "application/json")
            elif path == "/debug/turn.json":
                self._send(200, json.dumps(worker.debug_turn(), default=str).encode(), "application/json")
            elif path in ("/debug/live.json", "/debug/frozen.json"):
                self._send(200, json.dumps(worker.debug_view(path[7:-5])[0], default=str).encode(), "application/json")
            elif path.startswith(("/debug/live/", "/debug/frozen/")) and path.endswith(".jpg"):
                view, cam = path[7:-4].split("/")
                data = worker.debug_view(view)[1].get(int(cam)) if cam.isdigit() else None
                self._send(200 if data else 404, data or b"", "image/jpeg")
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
            if self.path == "/api/settings":
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
                return self._send(200, json.dumps(worker.change_settings(body if isinstance(body, dict) else {})).encode(), "application/json")
            if self.path == "/api/settings/reset":
                worker.reset_settings()
                return self._send(200, json.dumps(tuning.describe(worker.settings)).encode(), "application/json")
            if self.path == "/api/drift/accept":
                ok = worker.take_reference()
                return self._send(200 if ok else 409, b'{"ok":true}' if ok else b'{"ok":false}', "application/json")
            if self.path == "/api/reset":
                worker.reset()
            elif self.path == "/api/bouncer":
                ok = worker.bouncer()
                return self._send(200 if ok else 409, b'{"ok":true}' if ok else b'{"ok":false}', "application/json")
            elif self.path == "/api/mark":
                worker.mark()
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
                    point = {"x": float(q["x"][0]), "y": float(q["y"][0])} if "x" in q and "y" in q else None
                    ok = worker.label(index, q.get("field", [""])[0], point=point)
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
