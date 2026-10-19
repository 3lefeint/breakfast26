"""Looks for a newer release by itself, and installs it when that is switched on.

Once shortly after the start, then every 24 hours, `check` (the same function as Settings → Updates → Check for update)
is asked for the newest release. The result is kept, so that opening the page never queries GitHub. It is off with
`[updates] check = false` in config.toml, which is re-read on every round.

With `[updates] auto_install = true` a newer patch or minor release is installed by itself at two moments: after the first
check following the start, and at 04:00 every day (in `[stats] timezone`, else the time of the server). Not while a game is
running (that moment is skipped), never a new major version, and never a version that was tried before: a failed update is
rolled back and the app starts again, which would otherwise try the same update over and over.
"""

import logging
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config as cfg_mod

log = logging.getLogger(__name__)

FIRST_DELAY_S = 30         # the updater service may still be starting
INTERVAL_S = 24 * 3600
RETRY_S = 10 * 60          # after a check that failed
TICK_S = 30                # how often the 04:00 window is looked at
WINDOW_HOUR = 4
ATTEMPT_FILE = "auto-update-attempt"      # next to config.toml: the version an automatic update was started for


def _same_major(current, latest):
    """A patch or minor release: the major number stays."""
    try:
        return int(str(current).split(".")[0]) == int(str(latest).split(".")[0])
    except ValueError:
        return False


class UpdateChecker:
    def __init__(self, check, config_path, on_change=None, install=None, busy=None, now=None):
        """*check*: returns what `/api/updates/check` answers. *on_change*: called when the result is new. *install*:
        starts the update (what `/api/updates/apply` does) and returns its answer. *busy*: True while a game is running.
        *now*: the time as a datetime with its time zone, for the tests."""
        self._check = check
        self._config_path = config_path
        self._on_change = on_change
        self._install = install
        self._busy = busy or (lambda: False)
        self._now = now or self._local_now
        self._result = None
        self._tried = None            # the version an automatic update was started for
        self._stop = threading.Event()

    def _section(self):
        if not self._config_path:
            return {}
        try:
            return cfg_mod.load(self._config_path).get("updates", {})
        except Exception:
            return {}

    def enabled(self):
        return self._section().get("check") is not False

    def auto_install(self):
        return self._section().get("auto_install") is True

    def _local_now(self):
        name = None
        if self._config_path:
            try:
                name = cfg_mod.load(self._config_path).get("stats", {}).get("timezone")
            except Exception:
                name = None
        try:
            return datetime.now(ZoneInfo(name)) if name else datetime.now().astimezone()
        except Exception:
            return datetime.now().astimezone()

    def status(self):
        """{"available", "latest"} of the last successful check, None while the check is off or nothing was found out."""
        result = self._result
        if not result or not self.enabled():
            return None
        return {"available": bool(result["update_available"]), "latest": result["latest"]}

    def run_once(self):
        """Ask for the newest release. Returns False when that failed."""
        try:
            result = self._check()
        except Exception as e:
            log.warning("Update check failed: %s", e)
            return False
        if not isinstance(result, dict) or result.get("error") or "latest" not in result:
            log.info("Update check found nothing: %s", (result or {}).get("error") if isinstance(result, dict) else result)
            return False
        changed = result != self._result
        self._result = result
        if changed and self._on_change:
            self._on_change()
        return True

    # ── installing by itself ─────────────────────────────────────────────────

    def _attempt_path(self):
        return self._config_path.parent / ATTEMPT_FILE if self._config_path else None

    def _was_tried(self, version):
        if self._tried == version:
            return True
        path = self._attempt_path()
        try:
            return bool(path) and path.read_text().strip() == version
        except OSError:
            return False

    def _remember_attempt(self, version):
        self._tried = version
        path = self._attempt_path()
        try:
            if path:
                path.write_text(version)
        except OSError:
            log.warning("Could not write %s", path)

    def maybe_install(self):
        """Install the release the last check found, when that is switched on and allowed. Returns True when an update
        was started."""
        result = self._result
        if not (self._install and result and result.get("update_available") and self.auto_install()):
            return False
        current, latest = result.get("current"), result["latest"]
        if not _same_major(current, latest):
            log.info("Version %s is a new major version, it is not installed automatically", latest)
            return False
        if self._busy():
            log.info("Update to %s skipped, a game is running", latest)
            return False
        if self._was_tried(latest):
            log.info("Update to %s was tried before, it is not tried again automatically", latest)
            return False
        self._remember_attempt(latest)
        log.info("Installing update %s -> %s automatically", current, latest)
        try:
            answer = self._install()
        except Exception as e:
            log.warning("Automatic update failed to start: %s", e)
            return False
        if isinstance(answer, dict) and (answer.get("error") or answer.get("ok") is False):
            log.warning("Automatic update did not start: %s", answer.get("error"))
            return False
        return True

    # ── the loop ─────────────────────────────────────────────────────────────

    def start(self):
        threading.Thread(target=self._run, name="update-check", daemon=True).start()

    def stop(self):
        self._stop.set()

    def _run(self):
        due = time.monotonic() + FIRST_DELAY_S
        first = True
        window_day = self._now().date()     # an app that starts after 04:00 has its window tomorrow
        while not self._stop.wait(TICK_S):
            if not self.enabled():
                continue
            now = self._now()
            at_window = now.hour == WINDOW_HOUR and window_day != now.date()
            if not (at_window or time.monotonic() >= due):
                continue
            if at_window:
                window_day = now.date()
            ok = self.run_once()
            due = time.monotonic() + (INTERVAL_S if ok else RETRY_S)
            if ok:
                if first or at_window:
                    self.maybe_install()
                first = False
