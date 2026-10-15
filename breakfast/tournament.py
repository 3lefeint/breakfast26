"""X01 tournaments: single elimination, played with the X01 mode of Breakfast.

The bracket is rounded up to the next power of two. A seat without a player is a bye: the player facing it moves on
without a match. Every tournament has one start score and in/out mode and a number of legs to win per round. After a
match is won its result waits for half a minute (so it can still be undone or corrected), then the next open pairing
starts by itself; the result of the final waits for the owner. Bracket and progress are stored in `stats.db`, so a
tournament survives a restart of the backend (a match that was running does not: its pairing is played again).

`Bracket` is the plain logic (draw, seats, rounds, winners). `TournamentController` plays it: it starts one match at a
time through the X01 controller, learns how the match ended from the callback of the game, and stores the progress.
"""

import logging
import math
import random
import threading
import uuid
from datetime import datetime, timezone

from . import x01_game

log = logging.getLogger(__name__)

MIN_PLAYERS = 2
NEXT_MATCH_DELAY_S = 30         # how long the result of a match waits before the next one starts


def bracket_size(players):
    """The number of seats: the next power of two."""
    size = 2
    while size < players:
        size *= 2
    return size


def round_count(size):
    return int(math.log2(size))


def draw(players, rng=None):
    """Random seats for the players, byes included. Seats 2k and 2k+1 face each other in the first round. The byes
    are placed in different pairs, so no bye faces a bye."""
    players = list(players)
    n = len(players)
    if n < MIN_PLAYERS:
        raise ValueError(f"a tournament needs at least {MIN_PLAYERS} players")
    rng = rng or random.Random()
    size = bracket_size(n)
    byes = size - n
    seats = [None] * size
    bye_seats = set()
    for pair in rng.sample(range(size // 2), byes):
        bye_seats.add(pair * 2 + rng.randint(0, 1))
    free = [i for i in range(size) if i not in bye_seats]
    shuffled = players[:]
    rng.shuffle(shuffled)
    for seat, name in zip(free, shuffled):
        seats[seat] = name
    return seats


def validate_seats(seats):
    """The players of a list of seats. Raises ValueError when it cannot be played."""
    size = len(seats)
    if size < 2 or size & (size - 1):
        raise ValueError("the seats have to be a power of two")
    names = [s for s in seats if s]
    if len(names) < MIN_PLAYERS:
        raise ValueError(f"a tournament needs at least {MIN_PLAYERS} players")
    if len({n.lower() for n in names}) != len(names):
        raise ValueError("a player can only play once")
    for k in range(0, size, 2):
        if not seats[k] and not seats[k + 1]:
            raise ValueError("a bye cannot face a bye")
    if size != bracket_size(len(names)):
        raise ValueError("the seats have to match the number of players")
    return names


def validate_rules(start, in_mode, out_mode, legs_by_round, rounds, max_rounds=None):
    if not x01_game.MIN_START <= int(start) <= x01_game.MAX_START:
        raise ValueError(f"the start score has to be between {x01_game.MIN_START} and {x01_game.MAX_START}")
    if in_mode not in x01_game.IN_MODES or out_mode not in x01_game.OUT_MODES:
        raise ValueError("in and out mode have to be straight, double or master")
    if len(legs_by_round) != rounds:
        raise ValueError(f"the legs to win are needed for {rounds} rounds")
    if any(not 1 <= int(n) <= x01_game.MAX_LEGS for n in legs_by_round):
        raise ValueError(f"legs to win have to be between 1 and {x01_game.MAX_LEGS}")
    if max_rounds is not None and not 1 <= int(max_rounds) <= x01_game.MAX_ROUNDS:
        raise ValueError(f"max rounds have to be between 1 and {x01_game.MAX_ROUNDS}")


class Bracket:
    """The rounds of a tournament. Round 0 is made from the seats, each later round from the winners of the one
    before. A match is {a, b, winner, bye, match_id, legs}; a and b are names or None."""

    def __init__(self, seats, legs_by_round, rounds=None):
        validate_seats(seats)
        self.seats = list(seats)
        self.legs_by_round = [int(n) for n in legs_by_round]
        size = len(seats)
        if rounds is None:
            self.rounds = [[self._match() for _ in range(size >> (r + 1))] for r in range(round_count(size))]
            for i, match in enumerate(self.rounds[0]):
                match["a"], match["b"] = seats[2 * i], seats[2 * i + 1]
            for i, match in enumerate(self.rounds[0]):
                if bool(match["a"]) != bool(match["b"]):          # a bye: the other player moves on
                    self._set_winner(0, i, match["a"] or match["b"], bye=True)
        else:
            self.rounds = rounds

    @staticmethod
    def _match():
        return {"a": None, "b": None, "winner": None, "bye": False, "match_id": None, "legs": None}

    def _set_winner(self, r, i, winner, bye=False, match_id=None, legs=None):
        match = self.rounds[r][i]
        match.update(winner=winner, bye=bye, match_id=match_id, legs=legs)
        if r + 1 < len(self.rounds):
            self.rounds[r + 1][i // 2]["a" if i % 2 == 0 else "b"] = winner

    def next_match(self):
        """(round, index) of the first match that can be played: both players known, no winner yet. None when
        there is none (the tournament is over)."""
        for r, matches in enumerate(self.rounds):
            for i, m in enumerate(matches):
                if m["a"] and m["b"] and not m["winner"]:
                    return r, i
        return None

    def record(self, r, i, winner, match_id=None, legs=None):
        match = self.rounds[r][i]
        if winner not in (match["a"], match["b"]) or match["winner"]:
            raise ValueError("not a match to record that winner for")
        self._set_winner(r, i, winner, match_id=match_id, legs=legs)

    @property
    def winner(self):
        return self.rounds[-1][0]["winner"]

    def to_dict(self):
        return {"seats": list(self.seats), "legs_by_round": list(self.legs_by_round),
                "rounds": [[dict(m, legs=dict(m["legs"]) if m["legs"] else None) for m in matches]
                           for matches in self.rounds]}

    @classmethod
    def from_dict(cls, data):
        return cls(data["seats"], data["legs_by_round"], rounds=data["rounds"])


class TournamentController:
    def __init__(self, x01_ctrl, stats_db=None, on_change=None, next_delay=NEXT_MATCH_DELAY_S,
                 timer_factory=threading.Timer):
        self.x01 = x01_ctrl
        self.stats_db = stats_db
        self._on_change = on_change
        self._next_delay = next_delay
        self._timer_factory = timer_factory
        self._timer = None
        self._lock = threading.RLock()
        self.t = None               # {"id", "created_at", "config", "bracket", "status"} of the tournament on screen
        self.phase = None           # None, "idle" (between matches), "match", "pending" (a result waits), "finished"
        self.current = None         # (round, index) of the match in play
        self.pending = None         # {"round", "index", "winner", "legs", "next_in"}
        self._restore()

    # ── state ────────────────────────────────────────────────────────────────

    @property
    def running(self):
        """A tournament is on: it blocks the other games, also between its matches."""
        return self.t is not None and self.t["status"] == "running"

    def _restore(self):
        row = self.stats_db.running_tournament() if self.stats_db else None
        if not row:
            return
        data = row["data"]
        self.t = {"id": row["id"], "created_at": row["created_at"], "config": data["config"],
                  "bracket": Bracket.from_dict(data["bracket"]), "status": "running"}
        self.phase = "idle"
        log.info("Tournament %s resumed", row["id"])

    def _persist(self):
        if not (self.stats_db and self.t):
            return
        self.stats_db.save_tournament(
            self.t["id"], self.t["status"],
            {"config": self.t["config"], "bracket": self.t["bracket"].to_dict(),
             "winner": self.t["bracket"].winner}, created_at=self.t["created_at"])

    def _changed(self):
        if self._on_change:
            self._on_change()

    def snapshot(self):
        with self._lock:
            if not self.t:
                return {"active": False}
            bracket = self.t["bracket"]
            nxt = bracket.next_match()
            match = bracket.rounds[nxt[0]][nxt[1]] if nxt else None
            return {
                "active": True,
                "phase": self.phase,
                "id": self.t["id"],
                "status": self.t["status"],
                "config": self.t["config"],
                "rounds": bracket.to_dict()["rounds"],
                "current": {"round": self.current[0], "index": self.current[1]} if self.current else None,
                "pending": dict(self.pending) if self.pending else None,
                "next": {"round": nxt[0], "index": nxt[1], "a": match["a"], "b": match["b"]} if match else None,
                "winner": bracket.winner,
            }

    # ── playing it ───────────────────────────────────────────────────────────

    def start(self, seats, start=501, in_mode="straight", out_mode="double", legs_by_round=None, bull_off=True,
              max_rounds=None):
        """Start a tournament with these seats (None is a bye). *bull_off*: a bull-off decides who throws first in the
        first leg of every match, else it is drawn. *max_rounds*: after this many rounds without a checkout a bull-off
        decides the leg, None is no limit. Raises ValueError for a setup that cannot be played."""
        with self._lock:
            if self.running:
                raise ValueError("a tournament is already running")
            names = validate_seats(seats)
            rounds = round_count(len(seats))
            legs_by_round = list(legs_by_round) if legs_by_round is not None else [1] * rounds
            validate_rules(start, in_mode, out_mode, legs_by_round, rounds, max_rounds)
            bracket = Bracket(seats, legs_by_round)
            self.t = {"id": uuid.uuid4().hex, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "config": {"start": int(start), "in_mode": in_mode, "out_mode": out_mode,
                                 "legs_by_round": [int(n) for n in legs_by_round], "bull_off": bool(bull_off),
                                 "max_rounds": int(max_rounds) if max_rounds is not None else None,
                                 "players": names},
                      "bracket": bracket, "status": "running"}
            self.phase, self.current, self.pending = "idle", None, None
            self._persist()
        log.info("Tournament started: %d players", len(names))
        self._start_next()
        return self.t["id"]

    def _start_next(self):
        """Start the next open pairing, or end the tournament when there is none."""
        with self._lock:
            if not self.running:
                return False
            bracket = self.t["bracket"]
            nxt = bracket.next_match()
            if not nxt:
                self._finish()
                return False
            r, i = nxt
            match = bracket.rounds[r][i]
            cfg = self.t["config"]
            self.current, self.pending, self.phase = (r, i), None, "match"
        game = self.x01.start([match["a"], match["b"]], start=cfg["start"], in_mode=cfg["in_mode"],
                              out_mode=cfg["out_mode"], legs=cfg["legs_by_round"][r], bull_off=cfg.get("bull_off", True), max_rounds=cfg.get("max_rounds"),
                              tournament_id=self.t["id"], on_end=self._on_match_end)
        with self._lock:
            match["match_id"] = game.match_id
            self._persist()
        self._changed()
        return True

    def _finish(self):
        self.t["status"] = "finished"
        self.phase, self.current, self.pending = "finished", None, None
        self._persist()
        log.info("Tournament finished, winner %s", self.t["bracket"].winner)

    def _on_match_end(self, winner):
        """The game of the match in play was won (winner), or opened again by an undo (None)."""
        with self._lock:
            if self.phase not in ("match", "pending") or not self.current:
                return
            self._cancel_timer()
            if winner is None:
                self.phase, self.pending = "match", None
            else:
                r, i = self.current
                final = r == len(self.t["bracket"].rounds) - 1
                game = self.x01.game
                self.pending = {"round": r, "index": i, "winner": winner,
                                "legs": dict(game.legs_won) if game else None,
                                "next_in": None if final else self._next_delay}
                self.phase = "pending"
                if not final and self._next_delay > 0:
                    self._arm_timer()
        self._changed()

    def _arm_timer(self):
        self._timer = self._timer_factory(1.0, self._tick)
        self._timer.daemon = True
        self._timer.start()

    def _cancel_timer(self):
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def _tick(self):
        with self._lock:
            if self.phase != "pending" or not self.pending or self.pending["next_in"] is None:
                return
            self.pending["next_in"] -= 1
            due = self.pending["next_in"] <= 0
            if not due:
                self._arm_timer()
        if due:
            self.next()
        else:
            self._changed()

    def next(self):
        """Go on at once: record a waiting result and start the next match (or end the tournament after the final),
        or start the next match when none is in play (after a restart). False when there is nothing to do."""
        with self._lock:
            if self.phase == "pending":
                self._cancel_timer()
                p, bracket = self.pending, self.t["bracket"]
                match = bracket.rounds[p["round"]][p["index"]]
                bracket.record(p["round"], p["index"], p["winner"], match_id=match["match_id"], legs=p["legs"])
                self.pending, self.current = None, None
                done = bracket.winner is not None
                if done:
                    self._finish()
                else:
                    self.phase = "idle"
                    self._persist()
            elif self.phase == "idle":
                done = False
            else:
                return False
        self.x01.stop()            # the match that was won, for the screens
        if not done:
            self._start_next()
        self._changed()
        return True

    def abort(self):
        """End the tournament and mark it as aborted; the played matches and their statistics stay, a match in
        play is discarded. False when no tournament is running."""
        with self._lock:
            if not self.running:
                return False
            self._cancel_timer()
            self.t["status"] = "aborted"
            self._persist()
            self.t, self.phase, self.current, self.pending = None, None, None, None
        self.x01.stop()
        self._changed()
        log.info("Tournament aborted")
        return True

    def close(self):
        """Clear a finished tournament from the screens."""
        with self._lock:
            if not self.t or self.t["status"] == "running":
                return False
            self.t, self.phase, self.current, self.pending = None, None, None, None
        self._changed()
        return True
