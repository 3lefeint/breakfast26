"""The camera board source: starts the worker process, passes its state messages on and restarts it if it dies.

`handler(data)` gets the `data` of every state message, exactly as the board WebSocket would deliver it;
`set_connected(bool)` tells whether the cameras are up."""
import logging
import multiprocessing
import queue as queue_mod
import threading
import time

from breakfast.detection import worker

log = logging.getLogger("breakfast.detection")
RESTART_S = 3.0
RESTART_MAX_S = 60.0         # a worker that keeps ending is started again more and more slowly, up to this pause
STABLE_S = 60.0              # a worker that ran this long was fine: the next restart is a quick one again
SILENT_S = 8.0               # no message from the worker for this long: it is stuck


def next_pause(pause, ran_s):
    """The pause before the next start of the worker: short after one that ran for a while, doubled after one that ended at once."""
    return RESTART_S if ran_s >= STABLE_S else min(pause * 2, RESTART_MAX_S)


class CameraSource:
    def __init__(self, cfg, handler, set_connected, on_status=None):
        self.cfg, self.handler, self.set_connected = cfg, handler, set_connected
        self.on_status = on_status or (lambda status: None)
        self._ctx = multiprocessing.get_context("spawn")
        self._proc = None

    def start(self):
        threading.Thread(target=self._supervise, daemon=True, name="detection supervisor").start()

    def _supervise(self):
        pause = RESTART_S / 2
        while True:
            started = time.monotonic()
            out = self._ctx.Queue()
            self._proc = self._ctx.Process(target=worker.run, args=(self.cfg, out), daemon=True, name="detection worker")
            self._proc.start()
            last = time.monotonic()
            while self._proc.is_alive() and time.monotonic() - last < SILENT_S:
                try:
                    msg = out.get(timeout=1.0)
                except queue_mod.Empty:
                    continue
                last = time.monotonic()
                if msg.get("type") == "worker":
                    self.set_connected(bool(msg.get("ok")))
                    self.on_status({k: v for k, v in msg.items() if k != "type"})
                elif msg.get("type") == "state":
                    try:
                        self.handler(msg["data"])
                    except Exception:
                        log.exception("board message handler failed")
            self.set_connected(False)
            self.on_status({"ok": False, "status": "stopped", "count": 0, "cameras": []})
            pause = next_pause(pause, time.monotonic() - started)
            log.log(logging.WARNING if pause <= RESTART_S else logging.INFO, "detection worker stopped, restarting in %.0f s", pause)
            if self._proc.is_alive():
                self._proc.terminate()
            time.sleep(pause)
