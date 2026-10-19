"""Looks for a newer release by itself.

Once shortly after the start, then every 24 hours, `check` (the same function as Settings → Updates → Check for update)
is asked for the newest release. The result is kept, so that opening the page never queries GitHub. It is off with
`[updates] check = false` in config.toml, which is re-read on every round.
"""

import logging
import threading

from . import config as cfg_mod

log = logging.getLogger(__name__)

FIRST_DELAY_S = 30         # the updater service may still be starting
INTERVAL_S = 24 * 3600
RETRY_S = 10 * 60          # after a check that failed
IDLE_S = 60                # while the check is switched off


class UpdateChecker:
    def __init__(self, check, config_path, on_change=None):
        """*check*: returns what `/api/updates/check` answers. *on_change*: called when the result is new."""
        self._check = check
        self._config_path = config_path
        self._on_change = on_change
        self._result = None
        self._stop = threading.Event()

    def enabled(self):
        if not self._config_path:
            return True
        try:
            return cfg_mod.load(self._config_path).get("updates", {}).get("check") is not False
        except Exception:
            return True

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

    def start(self):
        threading.Thread(target=self._run, name="update-check", daemon=True).start()

    def stop(self):
        self._stop.set()

    def _run(self):
        wait = FIRST_DELAY_S
        while not self._stop.wait(wait):
            if not self.enabled():
                wait = IDLE_S
                continue
            wait = INTERVAL_S if self.run_once() else RETRY_S
