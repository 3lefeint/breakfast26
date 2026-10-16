"""Opt-in anonymous usage and error reporting.

Off unless `[telemetry] enabled = true`. Events are queued in memory and sent in batches by a background
thread to `POST <url>/telemetry` (the relay Worker, see relay/README.md). A failing endpoint never reaches
the games: every error here is logged at debug level and dropped.

What is sent is fixed by the event builders below: a random installation id, the version and the platform,
and per event only counters, durations, game modes and code locations. No player names, no scores, no IP
address, no exception messages (they can carry names), no absolute paths.
"""

import collections
import logging
import os
import platform as platform_mod
import re
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

from breakfast import __version__
from breakfast import config as cfg_mod

log = logging.getLogger(__name__)

PROTOCOL_VERSION = 1
FLUSH_INTERVAL_S = 60
SEND_TIMEOUT_S = 10
BATCH_MAX = 50
QUEUE_MAX = 200
SENT_KEEP = 50
ERROR_REPEAT_S = 600        # the same error from the same place is reported once per this time
FRAMES_MAX = 8

_SAFE_MODE = re.compile(r"[A-Za-z0-9 _-]{1,24}\Z")
_SAFE_NAME = re.compile(r"[A-Za-z0-9_$.]{1,40}\Z")
_SAFE_FRAME = re.compile(r"[\w.$-]{1,60}:\d{1,6}(:\d{1,6})?( in [\w.<>$-]{1,80})?\Z")


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _http_base(url):
    url = url.strip().rstrip("/")
    for ws, http in (("wss://", "https://"), ("ws://", "http://")):
        if url.startswith(ws):
            return http + url[len(ws):]
    return url


def detect_platform():
    """A coarse platform label: how Breakfast runs, not on which machine."""
    from breakfast import frozen
    if frozen.is_frozen():
        return "windows-build"
    if Path("/.dockerenv").exists():
        return "docker"
    return {"Linux": "linux", "Darwin": "macos", "Windows": "windows"}.get(platform_mod.system(), "other")


def safe_frames(frames):
    """Keep only the entries that look like `file.py:12 in function`; nothing else leaves the machine."""
    out = []
    for f in frames if isinstance(frames, list) else []:
        if isinstance(f, str) and _SAFE_FRAME.match(f):
            out.append(f)
        if len(out) >= FRAMES_MAX:
            break
    return out


def exception_frames(tb):
    """The last frames of a traceback as `file.py:12 in function`, file names without their folders."""
    entries = traceback.extract_tb(tb)[-FRAMES_MAX:]
    return safe_frames([f"{os.path.basename(e.filename)}:{e.lineno} in {e.name}" for e in entries])


class Telemetry:
    def __init__(self, config_path, version=__version__):
        self.config_path = Path(config_path)
        self.version = version
        self.platform = detect_platform()
        self._lock = threading.Lock()
        self._queue = collections.deque(maxlen=QUEUE_MAX)
        self._sent = collections.deque(maxlen=SENT_KEEP)
        self._matches = {}          # match_id -> (mode, monotonic start) of the matches not finished yet
        self._seen_errors = {}      # (exc, place) -> monotonic time of the last report
        self._install_id = None
        self._settings_cache = (None, (False, ""))      # (mtime, (enabled, url))
        self._wake = threading.Event()
        self._thread = None
        self._stop = False
        self._seen_start = False

    # ── settings ──────────────────────────────────────────────────────────────

    def settings(self):
        """(enabled, endpoint base url) from config.toml, re-read when the file changes."""
        try:
            mtime = self.config_path.stat().st_mtime_ns
        except OSError:
            return False, ""
        if self._settings_cache[0] != mtime:
            raw = cfg_mod.load(self.config_path)
            section = raw.get("telemetry", {})
            url = section.get("url") or raw.get("online", {}).get("relay_url") or ""
            self._settings_cache = (mtime, (section.get("enabled") is True, _http_base(str(url))))
        return self._settings_cache[1]

    @property
    def enabled(self):
        return self.settings()[0]

    def install_id(self, create=True):
        """The random id of this installation, kept in `telemetry-id` next to config.toml."""
        if self._install_id:
            return self._install_id
        path = self.config_path.parent / "telemetry-id"
        try:
            value = path.read_text().strip()
            if re.fullmatch(r"[0-9a-f]{32}", value):
                self._install_id = value
                return value
        except OSError:
            pass
        if not create:
            return None
        self._install_id = uuid.uuid4().hex
        try:
            path.write_text(self._install_id + "\n")
        except OSError:
            log.debug("Telemetry: could not store the installation id")
        return self._install_id

    # ── recording ─────────────────────────────────────────────────────────────

    def record(self, type_, **fields):
        if not self.enabled:
            return
        with self._lock:
            self._queue.append({"type": type_, "ts": _now_iso(), **fields})
        if len(self._queue) >= BATCH_MAX:
            self._wake.set()

    def app_start(self):
        raw = cfg_mod.load(self.config_path)
        self.record(
            "app_start",
            language=str(raw.get("web", {}).get("language", "en"))[:8],
            mqtt=raw.get("mqtt", {}).get("enabled", True) is not False and bool(raw.get("mqtt", {}).get("host")),
            caller=raw.get("caller", {}).get("enabled", True) is not False,
            voice_pack=bool(raw.get("audio", {}).get("dir")),
            online=bool(raw.get("online", {}).get("relay_url")),
        )

    def error(self, exc, module, frames, source="backend"):
        """One error, by its type and where it happened. The same one is reported once per ERROR_REPEAT_S."""
        frames = safe_frames(frames)
        key = (exc, frames[-1] if frames else module)
        now = time.monotonic()
        with self._lock:
            if now - self._seen_errors.get(key, -ERROR_REPEAT_S) < ERROR_REPEAT_S:
                return
            self._seen_errors[key] = now
        self.record("error", source=source, exc=exc if _SAFE_NAME.match(exc) else "Error",
                    module=module if _SAFE_NAME.match(module) else "unknown", where=frames)

    def match_opened(self, match_id, mode):
        if not self.enabled:
            return
        mode = mode if _SAFE_MODE.match(mode or "") else "other"
        now = time.monotonic()
        with self._lock:
            old, self._matches = self._matches, {match_id: (mode, now)}
        for other_id, (other_mode, started) in old.items():
            if other_id != match_id:
                self.record("game_aborted", mode=other_mode, duration_s=int(now - started))
        self.record("game_started", mode=mode)

    def match_closed(self, match_id, players):
        with self._lock:
            entry = self._matches.pop(match_id, None)
        if entry:
            mode, started = entry
            self.record("game_finished", mode=mode, duration_s=int(time.monotonic() - started), players=int(players))

    # ── sending ───────────────────────────────────────────────────────────────

    def envelope(self, events):
        return {"protocol_version": PROTOCOL_VERSION, "install_id": self.install_id(), "version": self.version,
                "platform": self.platform, "events": events}

    def flush(self):
        """Send up to BATCH_MAX queued events. Returns True if nothing is left to retry later."""
        enabled, base = self.settings()
        with self._lock:
            if not enabled:
                self._queue.clear()
                return True
            batch = list(self._queue)[:BATCH_MAX]
        if not batch or not base:
            return True
        try:
            res = requests.post(base + "/telemetry", json=self.envelope(batch), timeout=SEND_TIMEOUT_S)
        except requests.RequestException as e:
            log.debug("Telemetry: send failed: %s", type(e).__name__)
            return False
        if res.status_code >= 500 or res.status_code == 429:
            log.debug("Telemetry: endpoint answered %s, keeping %d events", res.status_code, len(batch))
            return False
        if res.status_code >= 400:
            log.debug("Telemetry: endpoint refused the batch (%s), dropping %d events", res.status_code, len(batch))
        with self._lock:
            for _ in batch:
                self._queue.popleft()
            if res.status_code < 400:
                self._sent.extend(batch)
        return True

    def preview(self):
        """What would be sent, and what was sent lately."""
        enabled, base = self.settings()
        with self._lock:
            queued, sent = list(self._queue), list(self._sent)
        return {
            "enabled": enabled,
            "endpoint": base + "/telemetry" if base else None,
            "install_id": self.install_id(create=False),
            "version": self.version,
            "platform": self.platform,
            "queued": queued,
            "sent": sent,
        }

    def settings_changed(self):
        """Called after the settings were saved: a newly switched-on installation announces itself."""
        self._settings_cache = (None, (False, ""))
        if self.enabled:
            if not self._seen_start:
                self._seen_start = True
                self.app_start()
        else:
            self._seen_start = False
            with self._lock:
                self._queue.clear()

    # ── background thread and hooks ───────────────────────────────────────────

    def start(self):
        if self._thread:
            return
        self._thread = threading.Thread(target=self._run, name="telemetry", daemon=True)
        self._thread.start()
        logging.getLogger().addHandler(_ErrorHandler(self))
        _hook_uncaught(self)
        if self.enabled:
            self._seen_start = True
            self.app_start()

    def stop(self):
        self._stop = True
        self._wake.set()

    def _run(self):
        while not self._stop:
            self._wake.wait(FLUSH_INTERVAL_S)
            self._wake.clear()
            try:
                self.flush()
            except Exception:
                log.debug("Telemetry: flush failed", exc_info=True)


class _ErrorHandler(logging.Handler):
    """Reports every ERROR log record that carries an exception, and those without by their code location."""

    def __init__(self, telemetry):
        super().__init__(level=logging.ERROR)
        self.telemetry = telemetry

    def emit(self, record):
        if record.name.startswith("breakfast.telemetry") or not self.telemetry.enabled:
            return
        try:
            if record.exc_info and record.exc_info[0]:
                exc, frames = record.exc_info[0].__name__, exception_frames(record.exc_info[2])
            else:
                exc, frames = "log", safe_frames([f"{os.path.basename(record.pathname)}:{record.lineno} in {record.funcName}"])
            self.telemetry.error(exc, record.name, frames)
        except Exception:
            pass


def _hook_uncaught(telemetry):
    """Uncaught exceptions of the main thread and of other threads are reported, then handled as before."""
    previous_main, previous_thread = sys.excepthook, threading.excepthook

    def main_hook(exc_type, exc, tb):
        telemetry.error(exc_type.__name__, "uncaught", exception_frames(tb))
        previous_main(exc_type, exc, tb)

    def thread_hook(args):
        if args.exc_type is not SystemExit:
            telemetry.error(args.exc_type.__name__, "thread", exception_frames(args.exc_traceback))
        previous_thread(args)

    sys.excepthook, threading.excepthook = main_hook, thread_hook


# ── module-level access: the rest of the program does not carry a telemetry object around ──

_instance = None


def start(config_path):
    global _instance
    if _instance is None:
        _instance = Telemetry(config_path)
        _instance.start()
    return _instance


def get():
    return _instance


def record_match_opened(match_id, mode):
    if _instance:
        _instance.match_opened(match_id, mode)


def record_match_closed(match_id, players):
    if _instance:
        _instance.match_closed(match_id, players)
