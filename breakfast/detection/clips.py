"""Short recordings of what happens at the board, for analysing and tuning the tracker without anybody throwing.

While something moves (a hand, a flying dart, a takeout) the pictures of all cameras are stored five times a second, with a second
and a half before and after. A clip is a folder: `NNN_camC.jpg` for every picture set and `clip.json` with the time of every set,
the state of the tracker at that moment and the events it reported. `replay.py` plays a clip through the tracker again.
The oldest clips are deleted when the folder gets bigger than the limit.
"""
import collections
import json
import logging
import queue
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2

log = logging.getLogger("breakfast.detection")


class ClipRecorder:
    def __init__(self, folder, rate=5.0, pre_s=1.5, post_s=1.5, max_gb=5.0, quality=75):
        self.root = Path(folder)
        self.interval = 1.0 / rate
        self.pre = collections.deque(maxlen=max(1, int(pre_s * rate)))
        self.post_s = post_s
        self.max_bytes = int(max_gb * 1e9)
        self.quality = quality
        self.clip = None                # the clip being written: {"dir", "sets": [...], "events": [...], "last_move": t}
        self.last_taken = 0.0
        self.count = 0
        self.last_name = None           # the folder name of the clip that was opened last
        self.session = self.root / datetime.now().strftime("session-%Y%m%d-%H%M%S")
        self._queue = queue.Queue(maxsize=200)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._write_loop, daemon=True, name="clip writer")
        self._thread.start()

    # ------------------------------------------------------------------ called by the worker loop

    def offer(self, t, frames, moving, state):
        """One look at the board. `state`: what to store next to the pictures (count, status, ...)."""
        if t - self.last_taken < self.interval:
            if self.clip is not None and moving:
                self.clip["last_move"] = t
            return
        self.last_taken = t
        item = (t, frames, dict(state, moving=bool(moving)))
        if self.clip is None:
            if moving:
                self._open(t, item)
            else:
                self.pre.append(item)
            return
        if moving:
            self.clip["last_move"] = t
        self._add(item)
        if t - self.clip["last_move"] >= self.post_s:
            self._close()

    def note_event(self, t, entry):
        if self.clip is not None:
            self.clip["events"].append({"t": t, **entry})

    def close(self):
        if self.clip is not None:
            self._close()
        self._stop.set()

    # ------------------------------------------------------------------ clip handling

    def _open(self, t, first):
        self.count += 1
        d = self.session / f"clip-{self.count:04d}-{datetime.now().strftime('%H%M%S')}"
        self.last_name = d.name
        self.clip = {"dir": d, "sets": [], "events": [], "last_move": t}
        for item in list(self.pre):
            self._add(item)
        self.pre.clear()
        self._add(first)

    def _add(self, item):
        t, frames, state = item
        i = len(self.clip["sets"])
        self.clip["sets"].append({"t": t, "i": i, **state})
        for c, f in frames.items():
            try:
                self._queue.put_nowait((self.clip["dir"] / f"{i:03d}_cam{c}.jpg", f))
            except queue.Full:
                log.warning("clip writer is behind, a picture is dropped")

    def _close(self):
        clip, self.clip = self.clip, None
        self._queue.put((clip["dir"] / "clip.json", {"sets": clip["sets"], "events": clip["events"]}))
        self._queue.put((None, str(clip["dir"])))           # marker: the size limit is checked after this clip

    # ------------------------------------------------------------------ writer thread

    def _write_loop(self):
        while not self._stop.is_set() or not self._queue.empty():
            try:
                path, payload = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                if path is None:
                    self._trim()
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.suffix == ".json":
                    path.write_text(json.dumps(payload, default=str))
                else:
                    cv2.imwrite(str(path), payload, [cv2.IMWRITE_JPEG_QUALITY, self.quality])
            except OSError as e:
                log.warning("clip not written: %s", e)

    def _trim(self):
        clips = sorted(p for s in self.root.glob("session-*") for p in s.glob("clip-*"))
        sizes = {p: sum(f.stat().st_size for f in p.iterdir()) for p in clips}
        total = sum(sizes.values())
        for p in clips:
            if total <= self.max_bytes:
                break
            total -= sizes[p]
            shutil.rmtree(p, ignore_errors=True)
