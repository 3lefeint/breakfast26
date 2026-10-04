"""Runtime-triggered game simulations, gated behind the `[dev] enabled`
config flag — lets someone developing away from a physical board watch a
full X01 leg or Elimination match play out on /tv, triggered from the
Settings "Dev" tab instead of needing a separate CLI mode/restart.

X01: replays the bundled `data/sessions/test.jsonl` fixture (a real
recorded bot-vs-bot leg) through the exact same on_event() callback
run_direct() already wires up for live board events — same technique as
source_replay.py, just triggerable at runtime instead of as its own
process mode.

Elimination: has no equivalent recorded fixture (its board-throw pipeline
is per-dart counts, not the X01/cloud event shape) and no config-driven
"start automatically" hook of its own, so this runs a short, hand-written
turn sequence through the same on_board_state(count, throws) calls a real
board would make, via elimination.py's own field-string parser.
"""

import json
import logging
import threading
import time
from datetime import datetime

from breakfast.turn_game import parse_field

log = logging.getLogger(__name__)

_X01_DEMO_FILE = "/app/data/sessions/301.jsonl"
# Paced from the fixture's own recorded `ts` deltas (Recorder always writes
# one) rather than a flat per-line interval, so dart-to-dart gaps feel like
# real throwing cadence instead of every line costing the same pause.
# Multiplier: 1.0 = real recorded pace, 2.0 = twice as fast, 0.5 = half.
_X01_DEMO_SPEED_MULTIPLIER = 1.0
_X01_DEMO_MIN_DELAY_S = 0.15  # floor — keeps back-to-back events from feeling instantaneous
_X01_DEMO_MAX_DELAY_S = 3.5   # ceiling — caps real-world pauses/recorder idle gaps

_ELIM_DEMO_PLAYERS = ["anna", "sam"]
_ELIM_DEMO_LIVES = 3
_ELIM_DEMO_DART_DELAY_S = 2.4
_ELIM_DEMO_TURN_DELAY_S = 1.5
# Hand-scripted turns (field strings, parsed like a real board's throws via
# turn_game.parse_field) — engineered to run both players through a
# couple of life losses before a decisive finish, without depending on any
# specific outcome (the engine just plays out whatever these totals mean).
_ELIM_DEMO_TURNS = [
    ["T20", "T20", "T20"],
    ["S5", "S1", "S1"],
    ["S1", "S1", "S1"],
    ["T20", "T19", "T18"],
    ["S5", "S5", "S5"],
    ["S1", "0", "0"],
    ["T20", "S20", "D20"],
    ["S1", "0", "0"],
    # Extra turns in case the match runs longer than the trace above
    # expects — harmless, the loop stops as soon as the match finishes.
    ["T20", "T20", "T20"],
    ["0", "0", "0"],
]


class DemoRunner:
    """Wired into the running `direct` mode process via web.wire(dev_demo=...);
    triggered by POST /api/dev/demo/{x01,elimination}."""

    def __init__(self, on_x01_event=None, elim_ctrl=None, game_state=None):
        self._on_x01_event = on_x01_event
        self._elim_ctrl = elim_ctrl
        self._game_state = game_state
        self._lock = threading.Lock()
        self._running = False
        self._mode = None

    def status(self) -> dict:
        return {"running": self._running, "mode": self._mode}

    def start_x01(self):
        if not self._on_x01_event:
            return False, "X01 demo unavailable (no event pipeline wired)"
        if self._game_state and self._game_state.match_started:
            return False, "A real match is already in progress"
        if not self._claim("x01"):
            return False, "A demo is already running"
        threading.Thread(target=self._run_x01, daemon=True).start()
        return True, None

    def start_elimination(self):
        if not self._elim_ctrl:
            return False, "Elimination demo unavailable"
        if self._elim_ctrl.active:
            return False, "A real Elimination match is already in progress"
        if not self._claim("elimination"):
            return False, "A demo is already running"
        threading.Thread(target=self._run_elimination, daemon=True).start()
        return True, None

    def _claim(self, mode):
        with self._lock:
            if self._running:
                return False
            self._running = True
            self._mode = mode
            return True

    def _release(self):
        self._running = False
        self._mode = None

    def _run_x01(self):
        try:
            with open(_X01_DEMO_FILE) as f:
                entries = [json.loads(line) for line in f if line.strip()]

            if entries and entries[0]["payload"].get("event") != "match-started":
                # The bundled fixture's recording starts a moment after the
                # real match-started fired (its first line is already
                # game-started) — state.py only sets game_mode/points_start/
                # match_started from an actual match-started event, so
                # without one /tv would never leave "waiting for match" even
                # though dart-by-dart processing runs fine underneath.
                # game-started already carries the same game/remainingScores
                # shape match-started needs, so synthesize one from it.
                synthetic = dict(entries[0]["payload"])
                synthetic["event"] = "match-started"
                self._on_x01_event(synthetic)
                time.sleep(_X01_DEMO_MIN_DELAY_S)

            prev_ts = None
            for entry in entries:
                ts = datetime.fromisoformat(entry["ts"])
                if prev_ts is not None:
                    delay = (ts - prev_ts).total_seconds() / _X01_DEMO_SPEED_MULTIPLIER
                    time.sleep(max(_X01_DEMO_MIN_DELAY_S, min(_X01_DEMO_MAX_DELAY_S, delay)))
                prev_ts = ts

                payload = entry["payload"]
                self._on_x01_event(payload)
                if payload.get("event") == "match-won":
                    # The bundled fixture is a real recording of two full
                    # matches back to back (a second match-started fires
                    # right after this one) — a demo is meant to show one
                    # leg "from start to end", not silently roll into a
                    # second match, so stop here rather than replaying
                    # the whole file.
                    break
        except Exception:
            log.exception("X01 demo failed")
        finally:
            self._release()

    def _run_elimination(self):
        try:
            self._elim_ctrl.start(list(_ELIM_DEMO_PLAYERS), _ELIM_DEMO_LIVES)
            time.sleep(_ELIM_DEMO_TURN_DELAY_S)
            for turn in _ELIM_DEMO_TURNS:
                if not self._elim_ctrl.active:
                    break
                throws = []
                for field in turn:
                    throws.append(parse_field(field))
                    self._elim_ctrl.on_board_state(len(throws), list(throws))
                    time.sleep(_ELIM_DEMO_DART_DELAY_S)
                self._elim_ctrl.on_board_state(0, [])  # darts pulled, ends the turn
                time.sleep(_ELIM_DEMO_TURN_DELAY_S)
        except Exception:
            log.exception("Elimination demo failed")
        finally:
            self._release()
