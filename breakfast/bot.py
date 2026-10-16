"""A computer opponent for the turn games (Elimination, Killer, X01).

A bot throws like the board reports: its darts reach the game through the same
`on_board_state(count, throws)` as the darts of a real board, so the TV view, the voice calls,
undo and corrections work unchanged. This module holds the throw model (`Thrower`), what a bot
aims at in each game (`aim_elimination`, `aim_killer`, `aim_x01`), the filter that keeps bots out of the
stats (`StatsWithoutBots`) and the runner that plays a bot's turn with pauses (`BotRunner`).
"""

import functools
import logging
import math
import random
import threading
import time

from . import checkout_routes as cr
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

# X01 has its own scale of five stages (beginner to pro), defined by how precisely a bot throws at the triple 20 in a
# fixed test (about 90 % of the darts on the board for stage 1, all of them from stage 3): the scatter in millimetres.
X01_SCATTER_MM = {1: 45.0, 2: 28.0, 3: 20.0, 4: 13.0, 5: 9.0}
X01_LEVELS = tuple(X01_SCATTER_MM)

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

    def __init__(self, level, rng=None, scatter=None):
        """*scatter*: the table of the scale the level is on, `SCATTER_MM` unless a game has its own."""
        scatter = scatter or SCATTER_MM
        if level not in scatter:
            raise ValueError(f"unknown bot level {level}")
        self.level = level
        self.sigma = scatter[level]
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


_BY_VALUE = {}
for _field in cr._FIELDS:
    _BY_VALUE.setdefault(cr._VALUES[_field], []).append(_field)

# Fields a bot throws at when it cannot finish and the triple 20 would leave a bad rest.
_SETUP_FIELDS = tuple(f"S{n}" for n in range(20, 0, -1)) + ("T20", "T19", "T18")
# The rests a bot likes to leave for a double, the best first.
_LEAVES = (32, 40, 16, 24, 36, 8, 20, 12, 28, 4, 18, 10, 6, 2, 50)


def _out_ok(out_mode, field):
    """Whether a dart on *field* may finish a leg."""
    if out_mode == "straight":
        return True
    return cr.is_double(field) or (out_mode == "master" and field[0] == "T")


def _difficulty(field):
    if field == cr.BULL:
        return 3
    if field == cr.OUTER_BULL:
        return 2
    kind, number = field[0], int(field[1:])
    if kind == "S":
        return 0
    if kind == "T":
        return 1 if number >= 18 else 2
    return 1


def _routes(rem, darts, out_mode):
    """Every way to finish *rem* with at most *darts* darts under this out mode."""
    found = []
    least = 1 if out_mode == "straight" else 2

    def walk(rest, left, path):
        if rest > left * 60:
            return
        for field in _BY_VALUE.get(rest, ()):
            if _out_ok(out_mode, field):
                found.append(tuple(path) + (field,))
        if left > 1:
            for field in cr._FIELDS:
                after = rest - cr._VALUES[field]
                if after >= least:
                    walk(after, left - 1, path + [field])

    walk(rem, darts, [])
    return found


@functools.lru_cache(maxsize=None)
def finish_route(rem, darts, out_mode):
    """The fields a bot throws to finish *rem* with at most *darts* darts, None when it cannot. With a double out
    it follows the checkout chart; otherwise (or when the chart route needs more darts than are left) it takes the
    shortest route and, among those, the one that is easiest to hit."""
    if out_mode == "double":
        standard = cr.STANDARD.get(rem)
        if standard and len(standard) <= darts:
            return standard
    for n in range(1, darts + 1):
        found = _routes(rem, n, out_mode)
        if found:
            return min(found, key=lambda route: (sum(_difficulty(f) for f in route), -cr.points(route[0])))
    return None


def _leave_rank(after, darts_left, out_mode):
    """How good a rest is to leave, the lower the better: first a rest that the darts still left in the turn can
    finish, then one that the next turn can, by the number of darts; among equals the rests players like."""
    like = _LEAVES.index(after) if after in _LEAVES else len(_LEAVES)
    route = finish_route(after, darts_left, out_mode) if darts_left else None
    if route:
        return (0, len(route), like)
    route = finish_route(after, 3, out_mode)
    return (1, len(route) if route else 4, like)


def _setup_target(rem, darts, out_mode):
    """A rest that cannot be finished yet: the field that leaves the best rest, the triple 20 when it ties.
    Never a dart that busts or, with a double or master out, leaves 1."""
    least = 1 if out_mode == "straight" else 2
    best = None
    for field in _SETUP_FIELDS:
        value = cr._VALUES[field]
        after = rem - value
        if after < least:
            continue
        key = (_leave_rank(after, darts - 1, out_mode), -value)
        if best is None or key < best[0]:
            best = (key, field)
    return best[1] if best else "S1"


def _opening_target(rem, in_mode, out_mode):
    """A double (or triple, with a master in) to start scoring with, one that does not bust."""
    least = 1 if out_mode == "straight" else 2
    kinds = ("D",) if in_mode == "double" else ("T", "D")
    for number in range(20, 0, -1):
        for kind in kinds:
            field = f"{kind}{number}"
            after = rem - cr._VALUES[field]
            if after >= least or (after == 0 and _out_ok(out_mode, field)):
                return field
    return "D1"


def x01_target(rem, darts, opened, in_mode, out_mode):
    """What a bot throws at with *rem* left, *darts* darts left in the turn and the in mode satisfied or not."""
    if not opened:
        return _opening_target(rem, in_mode, out_mode)
    route = finish_route(rem, darts, out_mode)
    return route[0] if route else _setup_target(rem, darts, out_mode)


def aim_x01(game, player, rng):
    """The bull in a bull-off; in the leg the triple 20 until the rest can be finished, then the route of the
    checkout chart."""
    if game.phase == "bull_off":
        return cr.BULL
    result = game._result
    rem = result["remaining"] if result else game.scores[player]
    opened = result["opened"] if result else game.opened[player]
    return x01_target(rem, 3 - len(game._last_throws), opened, game.in_mode, game.out_mode)


def darts_x01(game):
    """In a bull-off only the first dart of a visit counts."""
    return 1 if game.phase == "bull_off" else 3


def x01_turn_over(game):
    """A bust or a finish ends the turn, the darts left are not thrown."""
    return game._result is not None and game._result["status"] != "open"


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

    def __init__(self, controller, aim, darts, rng=None, sleep=time.sleep, spawn=None, over=None, scatter=None):
        """*over*: tells whether the turn of a game is over before its darts are thrown (a bust or a finish).
        *scatter*: the scatter table of the scale the levels of the game are on."""
        self._scatter = scatter
        self._ctrl = controller
        self._aim = aim
        self._darts = darts
        self._over = over
        self.on_darts = None        # called with the darts on the board whenever a bot's darts change, to show them
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

    def _show(self, throws):
        if self.on_darts:
            self.on_darts(list(throws))

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
            thrower = Thrower(self.levels[player], self._rng, self._scatter)
            with self._ctrl._lock:
                count = self._darts(game) if self._due(game) and game.current_player == player else 0
            for i in range(count):
                if i:
                    self._pause(self.DART_PAUSE)
                with self._ctrl._lock:
                    if self._ctrl.game is not game or game.state != "playing" \
                            or game.current_player != player or (self._over and self._over(game)):
                        break
                    throws.append(thrower.throw(self._aim(game, player, self._rng)))
                    game.on_board_state(i + 1, list(throws))
                    self._show(throws)
            if throws:
                self._pause(self.TAKEOUT_PAUSE)
                with self._ctrl._lock:
                    if self._ctrl.game is game:
                        game.on_board_state(0, [])
                    self._show([])
        except Exception:
            log.exception("Bot turn failed")
        finally:
            with self._ctrl._lock:
                if throws and self._ctrl.game is game and game._prev_count:
                    game._prev_count = 0        # the turn was cut short, do not carry its darts over
                self.playing = False
                self.poll()
