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
        self.controls = (0, 0)                   # (exposure, white balance): 0 = the camera's automatic, see `set_controls`
        self._applied = None                     # what the open camera was last given
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"camera {path}")

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    def set_controls(self, exposure=0, white_balance=0):
        """Fix the exposure (`exposure_time_absolute`, units of 100 microseconds) and the white balance (Kelvin), or 0 for the camera's automatic.
        The automatic follows an arm in the picture and needs a moment to settle again, which looks like a change of the board. Takes
        effect within a picture or two; it is also given again whenever the camera is reopened."""
        self.controls = (int(exposure or 0), int(white_balance or 0))

    def _apply_controls(self, cap):
        if self.controls == self._applied or (self._applied is None and self.controls == (0, 0)):
            return
        exposure, white_balance = self.controls
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1 if exposure else 3)          # V4L2: 1 = manual, 3 = aperture priority (automatic)
        if exposure:
            cap.set(cv2.CAP_PROP_EXPOSURE, exposure)
        cap.set(cv2.CAP_PROP_AUTO_WB, 0 if white_balance else 1)
        if white_balance:
            cap.set(cv2.CAP_PROP_WB_TEMPERATURE, white_balance)
        self._applied = self.controls
        log.info("camera %s: exposure %s, white balance %s", self.path, exposure or "automatic", white_balance or "automatic")

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
                reason = "in use" if os.path.exists(self.path) else "not found"     # a camera held by the board manager is there
                if self.error != reason:                    # one line when it starts, not one per try
                    log.warning("camera %s: cannot open (%s), trying again every %.0f s", self.path, reason, RETRY_S)
                self.error = reason
                cap.release()
                self._stop.wait(RETRY_S)
                continue
            self.error = None
            self._applied = None
            count, t0 = 0, time.monotonic()
            while not self._stop.is_set():
                self._apply_controls(cap)
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

    def set_controls(self, exposure=0, white_balance=0):
        pass                                    # pictures of a folder have their own light

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

    def stop(self, wait=False):
        """Stop the cameras; with `wait` return only once they are released, so that another group can open them."""
        for c in self.cams:
            c.stop()
        if wait:
            for c in self.cams:
                thread = getattr(c, "_thread", None)
                if thread is not None and thread.is_alive():
                    thread.join(timeout=5.0)

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

    def set_controls(self, exposure=0, white_balance=0):
        for c in self.cams:
            c.set_controls(exposure, white_balance)

    def status(self):
        now = time.monotonic()
        return [{"path": c.path, "error": c.error, "fps": round(c.rate, 1),
                 "age_s": round(now - c.stamp, 2) if c.stamp else None, "brightness": _brightness(c.latest()[0])} for c in self.cams]

    def latest_frames(self):
        return {i: c.latest()[0] for i, c in enumerate(self.cams) if c.latest()[0] is not None}


def _brightness(frame):
    """Mean gray level (0 to 255) of a picture: what to look at when fixing the exposure."""
    return None if frame is None else round(float(cv2.mean(cv2.cvtColor(frame[::4, ::4], cv2.COLOR_BGR2GRAY))[0]), 1)
