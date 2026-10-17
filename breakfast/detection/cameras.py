"""Reading the board cameras: one thread per V4L2 device, the latest picture of each is kept. `ReplayGroup` plays pictures
back for tests."""
import logging
import os
import threading
import time
from pathlib import Path

import cv2

log = logging.getLogger(__name__)
RETRY_S = 2.0


class V4L2Camera:
    def __init__(self, path, width=800, height=600, fps=30):
        self.path, self.width, self.height, self.fps = path, width, height, fps
        self.frame, self.stamp, self.seq = None, 0.0, 0
        self.error = "starting"
        self.rate = 0.0                          # measured pictures per second
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"camera {path}")

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    def _open(self):
        cap = cv2.VideoCapture(self.path, cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, self.fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _run(self):
        while not self._stop.is_set():
            cap = self._open()
            if not cap.isOpened():
                if self.error != "cannot open":             # one line when it starts, not one per try
                    log.warning("camera %s: cannot open, trying again every %.0f s", self.path, RETRY_S)
                self.error = "cannot open"
                cap.release()
                self._stop.wait(RETRY_S)
                continue
            self.error = None
            count, t0 = 0, time.monotonic()
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    self.error = "read failed"
                    log.warning("camera %s: read failed, reopening", self.path)
                    break
                now = time.monotonic()
                with self._lock:
                    self.frame, self.stamp, self.seq = frame, now, self.seq + 1
                count += 1
                if now - t0 >= 2.0:
                    self.rate, count, t0 = count / (now - t0), 0, now
            cap.release()
            self._stop.wait(RETRY_S)

    def latest(self):
        with self._lock:
            return self.frame, self.stamp, self.seq


class FolderCamera:
    """A "camera" that plays the pictures of a folder (sorted by name, in a loop) at `fps`: for trying the whole chain without a board."""

    def __init__(self, path, width=800, height=600, fps=15, loop=True):
        self.path, self.fps, self.loop = path, fps, loop
        self.files = sorted(Path(path).glob("*.jpg"))
        self.frame, self.stamp, self.seq = None, 0.0, 0
        self.error = None if self.files else "no pictures"
        self.rate = float(fps)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"folder camera {path}")

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    def _run(self):
        i = 0
        while not self._stop.is_set() and self.files:
            frame = cv2.imread(str(self.files[i % len(self.files)]))
            with self._lock:
                self.frame, self.stamp, self.seq = frame, time.monotonic(), self.seq + 1
            i += 1
            if not self.loop and i >= len(self.files):
                break
            self._stop.wait(1.0 / self.fps)
        while not self._stop.is_set():          # at the end of a run that does not loop the last picture stays
            with self._lock:
                self.stamp, self.seq = time.monotonic(), self.seq + 1
            self._stop.wait(1.0 / self.fps)

    def latest(self):
        with self._lock:
            return self.frame, self.stamp, self.seq


class CameraGroup:
    """The cameras of the board; `frames()` returns the latest picture of every camera, or None while one is missing."""

    def __init__(self, paths, width=800, height=600, fps=30, max_age_s=0.5):
        self.cams = [FolderCamera(p, width, height, min(fps, 15)) if os.path.isdir(p) else V4L2Camera(p, width, height, fps) for p in paths]
        self.max_age_s = max_age_s
        self._last = {}

    def start(self):
        for c in self.cams:
            c.start()
        return self

    def stop(self):
        for c in self.cams:
            c.stop()

    def frames(self):
        """{camera index: picture} when every camera delivered a new picture since the last call and none is older than
        `max_age_s`; None otherwise."""
        out, now = {}, time.monotonic()
        for i, cam in enumerate(self.cams):
            frame, stamp, seq = cam.latest()
            if frame is None or now - stamp > self.max_age_s or self._last.get(i) == seq:
                return None
            out[i] = frame
        for i, cam in enumerate(self.cams):
            self._last[i] = cam.latest()[2]
        return out

    def status(self):
        now = time.monotonic()
        return [{"path": c.path, "error": c.error, "fps": round(c.rate, 1),
                 "age_s": round(now - c.stamp, 2) if c.stamp else None} for c in self.cams]

    def latest_frames(self):
        return {i: c.latest()[0] for i, c in enumerate(self.cams) if c.latest()[0] is not None}
