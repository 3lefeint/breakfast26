"""A computer opponent for the turn games (Elimination, Killer).

A bot throws like the board reports: its darts reach the game through the same
`on_board_state(count, throws)` as the darts of a real board, so the TV view, the voice calls,
undo and corrections work unchanged. This module holds the throw model (`Thrower`), what a bot
aims at in each game (`aim_elimination`, `aim_killer`), the filter that keeps bots out of the
stats (`StatsWithoutBots`) and the runner that plays a bot's turn with pauses (`BotRunner`).
"""

import logging
import math
import random
import threading
import time

from .dartboard import DOUBLE_OUT_MM, SEGMENT_ORDER, field_at, field_centers
from .turn_game import dart_value, parse_field

log = logging.getLogger(__name__)

# A level is the 3-dart average the bot makes when it throws at the triple 20 all the time.
LEVELS = tuple(range(10, 111, 10))

# The scatter (standard deviation of a dart around its target, in millimetres) that gives each
# level its average. Calibrated with `calibrate()`, checked by tests/test_bot.py.
SCATTER_MM = {
    10: 207.3, 20: 117.0, 30: 63.0, 40: 31.7, 50: 21.3, 60: 16.6,
    70: 13.7, 80: 11.6, 90: 9.9, 100: 8.3, 110: 7.1,
}

# A dart that lands far outside the board is drawn at most this far out (units of the double ring).
_MAX_RADIUS = 1.3

_CENTERS = field_centers()


def _throw_at(x_mm, y_mm):
    """The throw the board would report for a dart that landed at this point."""
    field = field_at(x_mm, y_mm)
    seg = parse_field(field)["segment"]
    seg["name"] = field if seg["multiplier"] else "M0"
    r = math.hypot(x_mm, y_mm) / DOUBLE_OUT_MM
    scale = _MAX_RADIUS / r if r > _MAX_RADIUS else 1.0
    return {"segment": seg, "coords": {"x": x_mm / DOUBLE_OUT_MM * scale, "y": y_mm / DOUBLE_OUT_MM * scale}}


class Thrower:
    """Throws darts at a target with the scatter of one level."""

    def __init__(self, level, rng=None):
        if level not in SCATTER_MM:
            raise ValueError(f"unknown bot level {level}")
        self.level = level
        self.sigma = SCATTER_MM[level]
        self.rng = rng or random.Random()

    def throw(self, field):
        """A dart aimed at *field* (`T20`, `D16`, `S5`, `25`, `50`), shaped like a throw of the board."""
        center = _CENTERS[field]
        return _throw_at(center["x"] * DOUBLE_OUT_MM + self.rng.gauss(0, self.sigma),
                         center["y"] * DOUBLE_OUT_MM + self.rng.gauss(0, self.sigma))


def average_for(sigma_mm, darts=20000, seed=1, aim="T20"):
    """The 3-dart average of a thrower with this scatter that aims at *aim* every dart."""
    thrower = Thrower(10, random.Random(seed))
    thrower.sigma = sigma_mm
    return 3 * sum(dart_value(thrower.throw(aim)) for _ in range(darts)) / darts


def calibrate(level, darts=20000, seed=1):
    """The scatter that gives *level* as its average (bisection, the average falls as it grows)."""
    low, high = 1.0, 400.0
    for _ in range(30):
        mid = (low + high) / 2
        if average_for(mid, darts, seed) > level:
            low = mid
        else:
            high = mid
    return round((low + high) / 2, 1)


# ── what a bot aims at ───────────────────────────────────────────────────────

def aim_elimination(game, player, rng):
    """Triple 20, the single 20 once the total to beat is within reach of one safe dart."""
    to_beat = 0 if game.freipass else game.target
    needed = to_beat + 1 - sum(game._current_darts)
    return "S20" if needed <= 20 else "T20"


def aim_killer(game, player, rng):
    """Before the game: the bull, then the double of a number nobody has. In the game: the
    double of the own number until it is a killer, then the number of the most dangerous opponent."""
    if game.phase == "bull_off":
        return "50"
    if game.phase == "numbers":
        free = [n for n in SEGMENT_ORDER if n not in game.numbers.values()]
        return f"D{rng.choice(free)}"
    kind = "S" if game.singles else "D"
    if player not in game.killers:
        return f"D{game.numbers[player]}"
    rivals = [p for p in game.active if p != player]
    rivals.sort(key=lambda p: (p in game.killers, game.lives[p]), reverse=True)
    return f"{kind}{game.numbers[rivals[0]]}"


def darts_elimination(game):
    return 3


def darts_killer(game):
    """Before the game only the first dart of a visit counts."""
    return 3 if game.phase == "playing" else 1


# ── keeping bots out of the stats ────────────────────────────────────────────

class StatsWithoutBots:
    """The stats database of a match with bots: the match is stored and marked, the bots leave
    no turns and no results, and a win of a bot is stored as no winner."""

    def __init__(self, db, bots):
        self._db = db
        self._bots = set(bots)

    def __getattr__(self, name):
        return getattr(self._db, name)

    def open_match(self, match_id, game_mode, points_start):
        self._db.open_match(match_id, game_mode, points_start)
        self._db.mark_bot_match(match_id)

    def set_winner(self, match_id, winner):
        self._db.set_winner(match_id, None if winner in self._bots else winner)

    def insert_elimination_turn(self, match_id, player, *args, **kwargs):
        if player not in self._bots:
            self._db.insert_elimination_turn(match_id, player, *args, **kwargs)

    def correct_last_elimination_turn(self, match_id, player, *args, **kwargs):
        if player not in self._bots:
            self._db.correct_last_elimination_turn(match_id, player, *args, **kwargs)

    def delete_last_elimination_turn(self, match_id, player):
        if player not in self._bots:
            self._db.delete_last_elimination_turn(match_id, player)

    def record_elimination_result(self, match_id, results):
        self._db.record_elimination_result(match_id, [r for r in results if r[0] not in self._bots])

    def insert_killer_turn(self, match_id, player, *args, **kwargs):
        if player not in self._bots:
            self._db.insert_killer_turn(match_id, player, *args, **kwargs)

    def delete_last_killer_turn(self, match_id, player):
        if player not in self._bots:
            self._db.delete_last_killer_turn(match_id, player)

    def record_killer_results(self, match_id, results):
        self._db.record_killer_results(match_id, [r for r in results if r[0] not in self._bots])


# ── playing a turn ───────────────────────────────────────────────────────────

class BotRunner:
    """Plays the turns of the bots of a running game for a `TurnGameController`.

    `poll()` is called whenever the game changes; when a bot is up and the board is clear it
    plays its turn on a thread: the darts one after another with pauses, then the takeout.
    While it plays, the controller ignores the messages of the real board."""

    FIRST_DART_PAUSE = (1.5, 2.5)
    DART_PAUSE = (0.8, 1.8)
    TAKEOUT_PAUSE = (1.2, 2.2)

    def __init__(self, controller, aim, darts, rng=None, sleep=time.sleep, spawn=None):
        self._ctrl = controller
        self._aim = aim
        self._darts = darts
        self._rng = rng or random.Random()
        self._sleep = sleep
        self._spawn = spawn or self._spawn_thread
        self.levels = {}
        self.playing = False        # a bot turn is in progress: the real board is ignored

    def set_bots(self, levels):
        self.levels = dict(levels)

    def clear(self):
        self.levels = {}

    @staticmethod
    def _spawn_thread(fn):
        threading.Thread(target=fn, daemon=True, name="bot-turn").start()

    def _pause(self, span):
        self._sleep(self._rng.uniform(*span))

    def _due(self, game):
        """Is a bot up in this game, with the board clear."""
        if not self.levels or self._ctrl.game is not game or game.state != "playing":
            return False
        if game.current_player not in self.levels:
            return False
        return game._board_count == 0 and not game._await_pull

    def poll(self):
        game = self._ctrl.game
        if self.playing or game is None or not self._due(game):
            return
        self.playing = True
        player = game.current_player
        self._spawn(lambda: self._play_turn(game, player))

    def _play_turn(self, game, player):
        throws = []
        try:
            self._pause(self.FIRST_DART_PAUSE)
            thrower = Thrower(self.levels[player], self._rng)
            with self._ctrl._lock:
                count = self._darts(game) if self._due(game) and game.current_player == player else 0
            for i in range(count):
                if i:
                    self._pause(self.DART_PAUSE)
                with self._ctrl._lock:
                    if self._ctrl.game is not game or game.state != "playing" \
                            or game.current_player != player:
                        break
                    throws.append(thrower.throw(self._aim(game, player, self._rng)))
                    game.on_board_state(i + 1, list(throws))
            if throws:
                self._pause(self.TAKEOUT_PAUSE)
                with self._ctrl._lock:
                    if self._ctrl.game is game:
                        game.on_board_state(0, [])
        except Exception:
            log.exception("Bot turn failed")
        finally:
            with self._ctrl._lock:
                if throws and self._ctrl.game is game and game._prev_count:
                    game._prev_count = 0        # the turn was cut short, do not carry its darts over
                self.playing = False
                self.poll()
