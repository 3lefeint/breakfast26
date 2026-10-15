"""X01 played in Breakfast: the darts come from the board, nothing needs an external match.

Players throw in turn from a start score down to zero. The rules that can be chosen: the in mode (straight: any
dart scores, double: the first scoring dart has to be a double, master: a double or a triple), the out mode (the
same three for the dart that finishes) and the number of legs to win. A turn that takes a player below zero, to one
with a double or master out, or to zero with a dart that does not finish, is a bust: the score of the turn does not
count and the turn is over. Darts after a bust or a finish are ignored until they are pulled.

Before the first leg the order is decided by a bull-off (everybody throws one dart at the bull, the closest throws
first, the others follow by distance, players tied throw again) or by lot. The first thrower of the following legs
moves one place on in that order.

The game does not write to the statistics itself. It tells the rest of the program what happens in the same events
an Autodarts match produces (`match-started`, `dartN-thrown`, `busted`, `game-won`, `match-won`, `darts-pulled`,
`game-started`), through `emit`, so the screens, the caller, the MQTT output and the statistics treat a match played
here like any other X01 match. Going back (undo, a corrected dart) is told with `x01-resync`.

The turn in progress is worked out afresh from its darts whenever one lands or is corrected, starting from the
state at the start of the turn.
"""

import copy
import logging
import random
import threading

from .turn_game import TurnGame, TurnGameController, parse_field

log = logging.getLogger(__name__)

IN_MODES = ("straight", "double", "master")
OUT_MODES = ("straight", "double", "master")
MIN_START, MAX_START = 2, 1501
MAX_LEGS = 25
MAX_ROUNDS = 999

# The opening calls follow the match start by this long, like in the other games, so the screen has time to
# come up and its audio page to connect.
START_CALLS_DELAY_S = 0.5

_TIE = 1e-9
_BED = {1: "single", 2: "double", 3: "triple"}


def _number_multiplier(throw):
    seg = (throw or {}).get("segment") or {}
    return seg.get("number") or 0, seg.get("multiplier") or 0


def _field_name(throw):
    """The name of a field in the style of the board: s5, d16, t20, 25 and d25 for the bull, m0 for a miss."""
    seg = (throw or {}).get("segment") or {}
    if seg.get("name"):
        return str(seg["name"]).lower()
    number, multiplier = _number_multiplier(throw)
    if not multiplier:
        return "m0"
    if number == 25:
        return "25" if multiplier == 1 else "d25"
    return f"{'sdt'[multiplier - 1]}{number}"


def _bed(throw):
    seg = (throw or {}).get("segment") or {}
    if seg.get("bed"):
        return str(seg["bed"]).lower()
    _, multiplier = _number_multiplier(throw)
    return _BED.get(multiplier, "outside")


def _in_ok(mode, multiplier):
    if mode == "double":
        return multiplier == 2
    if mode == "master":
        return multiplier in (2, 3)
    return True


def _out_ok(mode, multiplier):
    return _in_ok(mode, multiplier)


class X01Game(TurnGame):
    MODE = "X01"
    TOPIC = "x01_own"

    def __init__(self, players, emit, start=501, in_mode="straight", out_mode="double", legs=1, bull_off=True,
                 audio=None, on_change=None, stats_db=None, rng=None, match_id=None, start_delay=None,
                 tournament_id=None, on_end=None, max_rounds=None):
        """*emit*: where the events of the match go (the same function the events of an Autodarts match go to).
        *stats_db* only says that statistics are kept, so that undo takes a stored turn out again.
        *tournament_id*: the tournament this match belongs to, stored with the match. *on_end*: called with the
        winner when the match is won, and with None when an undo or a correction opens it again.
        *max_rounds*: when nobody has checked out after this many rounds (everybody threw that many turns) a
        bull-off decides the leg, the closest dart wins; None is no limit. It needs two players."""
        players = [str(p).strip() for p in players if str(p).strip()]
        if not players:
            raise ValueError("need at least 1 player")
        if len({p.lower() for p in players}) != len(players):
            raise ValueError("a player can only play once")
        if not MIN_START <= int(start) <= MAX_START:
            raise ValueError(f"the start score has to be between {MIN_START} and {MAX_START}")
        if in_mode not in IN_MODES or out_mode not in OUT_MODES:
            raise ValueError("in and out mode have to be straight, double or master")
        if not 1 <= int(legs) <= MAX_LEGS:
            raise ValueError(f"legs to win have to be between 1 and {MAX_LEGS}")
        if max_rounds is not None and not 1 <= int(max_rounds) <= MAX_ROUNDS:
            raise ValueError(f"max rounds have to be between 1 and {MAX_ROUNDS}")
        super().__init__(None, "", audio=audio, on_change=on_change, stats_db=stats_db, match_id=match_id)
        self._emit_to = emit
        self.tournament_id = tournament_id
        self._on_end = on_end
        self._rng = rng or random.Random()
        self._start_delay = START_CALLS_DELAY_S if start_delay is None else start_delay
        self._stopped = False
        self.start = int(start)
        self.in_mode, self.out_mode, self.legs = in_mode, out_mode, int(legs)
        self.bull_off = bool(bull_off) and len(players) > 1
        self.max_rounds = int(max_rounds) if max_rounds is not None and len(players) > 1 else None
        self.turns_in_leg = 0            # the turns played in this leg, for the max rounds
        self.tiebreak = False            # the bull-off that decides a leg after the max rounds is on
        self.order = list(players)
        if not self.bull_off:
            self._rng.shuffle(self.order)
        self.leg, self.leg_start = 1, 0
        self.legs_won = {p: 0 for p in players}
        self.scores = {p: self.start for p in players}
        self.opened = {p: in_mode == "straight" for p in players}
        self.winner = None
        self.phase = "bull_off" if self.bull_off else "playing"
        self._bo = {"final": [], "todo": [list(players)], "dist": {}, "shown": {}}      # the bull-off: who is placed, who throws, the distances
        self.current = self._bo_thrower() if self.bull_off else self.order[0]
        self._match_started = False
        self._silent = False             # a correction of a finished turn makes no calls
        self._one_dart_taken = False     # in the bull-off: the dart of this visit has counted, the darts are not pulled yet
        self._result = None              # what the darts of the turn in progress did
        self._em = self._fresh_em()      # what of it the rest of the program has been told
        self._turn_start = self._state_of()
        self._last_turn_throws = []
        self._last_turn_player = None
        log.info("Game started: %s, %d legs, in %s, out %s, bull-off %s", self.start, self.legs, in_mode, out_mode,
                 self.bull_off)

    # ── the rules ────────────────────────────────────────────────────────────

    @property
    def current_player(self):
        return self.current if self.state == "playing" else None

    @staticmethod
    def _fresh_em():
        return {"sig": [], "closed": None, "flushed": False, "thrown": False}

    def _state_of(self):
        """Everything that decides how the game goes on, as of now."""
        return copy.deepcopy({
            "phase": self.phase, "order": self.order, "bo": self._bo, "current": self.current, "scores": self.scores,
            "opened": self.opened, "legs_won": self.legs_won, "leg": self.leg, "leg_start": self.leg_start,
            "winner": self.winner, "state": self.state, "match_started": self._match_started,
            "turns_in_leg": self.turns_in_leg, "tiebreak": self.tiebreak})

    def _load_state(self, snap):
        snap = copy.deepcopy(snap)
        self.phase, self.order, self._bo, self.current = snap["phase"], snap["order"], snap["bo"], snap["current"]
        self.scores, self.opened, self.legs_won = snap["scores"], snap["opened"], snap["legs_won"]
        self.leg, self.leg_start, self.winner, self.state = snap["leg"], snap["leg_start"], snap["winner"], snap["state"]
        self._match_started = snap["match_started"]
        self.turns_in_leg, self.tiebreak = snap["turns_in_leg"], snap["tiebreak"]

    def _evaluate(self, st, throws):
        """What the darts of a turn do from the state `st` at its start. Returns the darts that count up to the one
        that ends the turn, whether it is a bust or a finish, and what is left."""
        player = st["current"]
        rem = start = st["scores"][player]
        opened = st["opened"][player]
        darts, status, total = [], "open", 0
        for throw in list(throws)[:3]:
            number, multiplier = _number_multiplier(throw)
            face = number * multiplier
            dart = {"throw": throw, "face": face, "counted": 0, "after": rem, "close": None, "name": _field_name(throw)}
            darts.append(dart)
            if not opened:
                if not _in_ok(self.in_mode, multiplier):
                    continue
                opened = True
            new = rem - face
            if new < 0 or (new == 0 and not _out_ok(self.out_mode, multiplier)) \
                    or (new == 1 and self.out_mode != "straight"):
                dart["close"], dart["after"], status = "bust", start, "bust"
                break
            rem, total = new, total + face
            dart["counted"], dart["after"] = face, rem
            if rem == 0:
                dart["close"], status = "checkout", "checkout"
                break
        left = start if status == "bust" else rem
        return {"darts": darts, "status": status, "total": 0 if status == "bust" else total, "remaining": left,
                "opened": st["opened"][player] if status == "bust" else opened, "start": start}

    # ── events for the rest of the program ───────────────────────────────────

    def _emit(self, event):
        if self._silent:
            event["silent"] = True
        try:
            self._emit_to(event)
        except Exception:
            log.exception("X01 event %s failed", event.get("event"))

    def _scores_for(self, scores):
        return {f"player{i + 1}": str(scores[p]) for i, p in enumerate(self.order)}

    def _common(self, player, scores=None):
        return {"player": player, "playerIndex": str(self.order.index(player)), "playerIsBot": "False",
                "remainingScores": self._scores_for(scores or self.scores)}

    def _view_scores(self, res):
        """The scores as they stand with the darts of the turn in progress."""
        scores = dict(self._turn_start["scores"])
        scores[self._turn_start["current"]] = res["remaining"]
        return scores

    def _position_fields(self, throw):
        coords = throw.get("coords")
        if isinstance(coords, dict) and "x" in coords and "y" in coords:
            return {"coords": {"x": coords["x"], "y": coords["y"]}, "entry": throw.get("entry")}
        dart = self.board_dart(throw)
        if dart["x"] is None:
            return {}
        return {"coords": {"x": dart["x"], "y": dart["y"]}, "entry": "manual"}      # tapped: the center of its field

    def _dart_fields(self, throw):
        number, multiplier = _number_multiplier(throw)
        return {"fieldName": _field_name(throw), "fieldNumber": number, "fieldMultiplier": multiplier,
                "type": _bed(throw), **self._position_fields(throw)}

    def _emit_match_started(self):
        self._match_started = True
        starter = self.order[self.leg_start]
        self._emit({**self._common(starter), "event": "match-started", "id": self.match_id,
                    "game": {"mode": "X01", "pointsStart": str(self.start), "special": None,
                             "players": list(self.order),
                             **({"tournamentId": self.tournament_id} if self.tournament_id else {})}})

    def _emit_resync(self, st, undo_stored, undo_leg=False):
        """Tell the program that the match is back at the state `st`; `undo_stored`: the turn that was stored is gone,
        `undo_leg`: the leg that the bull-off decided is gone."""
        player = st["current"]
        self._emit({**self._common(player, st["scores"]), "event": "x01-resync",
                    "game": {"leg": st["leg"], "legsWon": dict(st["legs_won"]), "players": list(st["order"]),
                             "undoStored": bool(undo_stored), "undoLeg": bool(undo_leg)}})

    def _sync_events(self, res):
        """Tell what the darts of the turn in progress did, as far as it has not been told. When a dart was
        corrected, the turn is told afresh from its start; those events make no calls."""
        st = self._turn_start
        player = st["current"]
        em = self._em
        sig = [(d["name"], d["counted"], d["after"]) for d in res["darts"] if d["close"] != "bust"]
        changed = sig[:len(em["sig"])] != em["sig"] or len(sig) < len(em["sig"]) \
            or (em["closed"] is not None and em["closed"] != res["status"])
        replay_silent = False
        if changed and (em["sig"] or em["closed"]):
            self._emit_resync(st, undo_stored=em["flushed"])
            em = self._em = self._fresh_em()
            replay_silent = True
        scores = self._view_scores(res)
        real = [d for d in res["darts"] if d["close"] != "bust"]
        for i, dart in enumerate(real):
            if i < len(em["sig"]):
                continue
            after = dict(st["scores"])
            after[player] = dart["after"]
            was_silent, self._silent = self._silent, self._silent or replay_silent
            self._emit({**self._common(player, after), "event": f"dart{i + 1}-thrown",
                        "game": {"mode": "X01", "pointsLeft": str(dart["after"]), "dartNumber": str(i + 1),
                                 "dartValue": str(dart["counted"]), **self._dart_fields(dart["throw"])}})
            self._silent = was_silent
            em["sig"].append((dart["name"], dart["counted"], dart["after"]))
        if res["status"] == "open" and len(real) == 3 and not em["thrown"]:
            em["thrown"] = True
            self._emit({**self._common(player, scores), "event": "darts-thrown",
                        "game": {"mode": "X01", "pointsLeft": str(res["remaining"]), "dartNumber": "3",
                                 "dartValue": str(res["total"])}})
        if res["status"] != "open" and em["closed"] is None:
            em["closed"] = res["status"]
            last = res["darts"][-1]
            if res["status"] == "bust":
                self._emit({**self._common(player, st["scores"]), "event": "busted",
                            "game": {"mode": "X01", "busted": "True", "pointsBeforeTurn": str(res["start"]),
                                     "field_name": last["name"], "dartNumber": str(len(res["darts"])),
                                     "dartValue": str(last["face"]), **self._dart_fields(last["throw"])}})
            else:
                em["flushed"] = True
                match_won = self.legs_won[player] + 1 >= self.legs
                self._emit({**self._common(player, scores), "event": "match-won" if match_won else "game-won",
                            "game": {"mode": "X01", "dartsThrownValue": str(res["total"]), "leg": self.leg,
                                     "winner": player, **self._dart_fields(last["throw"])}})

    # ── following the darts ──────────────────────────────────────────────────

    def _replay_turn(self):
        """Work out what the darts of the turn in progress did and tell it. A finish that ends the match ends
        the turn right there; any other turn ends when its darts are pulled."""
        if self.phase != "playing":
            return
        res = self._result = self._evaluate(self._turn_start, self._last_throws)
        self._sync_events(res)
        if res["status"] == "checkout" and self.legs_won[self._turn_start["current"]] + 1 >= self.legs \
                and self.state == "playing":
            self._complete_turn()
        else:
            self._changed()

    def _dart_seen(self, count, is_new_dart, is_correction):
        if self.phase == "bull_off":
            self._pre_dart_seen()
            return
        self._replay_turn()

    def correct_current_dart(self, dart_index, field):
        if self.phase == "bull_off":
            self._correct_bull_off_dart(dart_index, field)
            return
        before = self.state
        super().correct_current_dart(dart_index, field)
        if before == "playing":
            self._replay_turn()

    def next_turn(self):
        if self.phase == "bull_off":
            # The throw has counted and the darts are not pulled: go on without pulling them.
            if self.state != "playing" or not self._one_dart_taken:
                return False
            self._await_pull = self._board_count > 0
            self._prev_count = 0
            self._end_turn()
            return True
        return super().next_turn()

    def _end_turn(self):
        """The darts were pulled: the turn is over."""
        if self.phase == "bull_off":
            if self._one_dart_taken:           # the darts are pulled: the next one throws
                self._one_dart_taken = False
                self._bull_off_advance()
            return
        if self.state != "playing":
            return
        self._replay_turn()
        if self.state == "playing":
            self._complete_turn()

    def _complete_turn(self):
        """Record the turn as played and move on: the next player, the next leg, or the end of the match."""
        st = self._turn_start
        player = st["current"]
        res = self._result
        self._push_history(st, turn_recorded=self.stats_db is not None)
        self._last_turn_throws = list(self._last_throws)
        self._last_turn_player = player
        n_darts = len([d for d in res["darts"] if d["close"] != "bust"])
        busted = res["status"] == "bust"
        if not busted:
            self.scores[player] = res["remaining"]
            self.opened[player] = res["opened"]
        self._last_throws, self._current_darts, self._dart_overrides = [], [], {}
        self._result = None
        self._em = self._fresh_em()
        if res["status"] == "checkout":
            self.legs_won[player] += 1
            if self.legs_won[player] >= self.legs:
                self.winner, self.state = player, "finished"
                self._turn_start = self._state_of()
                self._changed()
                self._notify_end(player)
                return
            self.leg += 1
            self.leg_start = (self.leg_start + 1) % len(self.order)
            self.scores = {p: self.start for p in self.order}
            self.opened = {p: self.in_mode == "straight" for p in self.order}
            self.current = self.order[self.leg_start]
            self.turns_in_leg = 0
            new_leg = True
        else:
            self.current = self.order[(self.order.index(player) + 1) % len(self.order)]
            self.turns_in_leg += 1
            new_leg = False
        self._turn_start = self._state_of()
        self._emit({**self._common(self.current), "event": "darts-pulled",
                    "game": {"mode": "X01", "pointsLeft": str(self.scores[self.current]),
                             "dartsThrown": str(n_darts), "dartsThrownValue": str(res["total"]),
                             "busted": "True" if busted else "False", "newTurn": "True"}})
        if new_leg:
            self._emit({**self._common(self.current), "event": "game-started",
                        "game": {"mode": "X01", "pointsStart": str(self.start), "special": None,
                                 "players": list(self.order)}})
        elif self.max_rounds and self.turns_in_leg >= self.max_rounds * len(self.order):
            self._begin_tiebreak()
        self._changed()

    # ── the bull-off that decides a leg after the max rounds ─────────────────

    def _begin_tiebreak(self):
        """Nobody checked out within the max rounds: everybody throws one dart at the bull, the closest wins the leg.
        Players tied for the closest throw again."""
        self.tiebreak, self.phase = True, "bull_off"
        self._bo = {"final": [], "todo": [list(self.order)], "dist": {}, "shown": {}}
        self._one_dart_taken = False
        self.current = self._bo_thrower()
        self._turn_start = self._state_of()
        self._bull_off_calls(self.current, tie=False, done=False)

    def _decide_leg(self, winner):
        """The bull-off after the max rounds is decided: the winner takes the leg (and the match, with the legs to win)
        and the next leg starts. The darts are pulled already, so there is no turn to end."""
        match_won = self.legs_won[winner] + 1 >= self.legs
        self.tiebreak, self.phase = False, "playing"
        self.legs_won[winner] += 1
        self._emit({**self._common(winner), "event": "match-won" if match_won else "game-won",
                    "game": {"mode": "X01", "dartsThrownValue": "0", "leg": self.leg, "winner": winner,
                             "decidedBy": "bull_off"}})
        if self._history:
            self._history[-1]["leg_recorded"] = True        # an undo of the last throw takes the leg back
        if match_won:
            self.winner, self.state = winner, "finished"
            self._turn_start = self._state_of()
            self._changed()
            self._notify_end(winner)
            return
        self.leg += 1
        self.leg_start = (self.leg_start + 1) % len(self.order)
        self.scores = {p: self.start for p in self.order}
        self.opened = {p: self.in_mode == "straight" for p in self.order}
        self.current = self.order[self.leg_start]
        self.turns_in_leg = 0
        self._turn_start = self._state_of()
        self._emit({**self._common(self.current), "event": "game-started",
                    "game": {"mode": "X01", "pointsStart": str(self.start), "special": None,
                             "players": list(self.order)}})
        self._changed()

    # ── before the first leg: the bull-off ───────────────────────────────────

    def _bo_thrower(self):
        """Who throws next in the bull-off."""
        group = self._bo["todo"][0]
        return next(p for p in group if p not in self._bo["dist"])

    def _bull_distance(self, throw):
        """How far a dart is from the center, in units of the radius of the double ring; a dart without a
        field or a position is far away."""
        if not throw:
            return 99.0
        dart = self.board_dart(throw)
        if dart["x"] is None:
            return 99.0
        return (dart["x"] ** 2 + dart["y"] ** 2) ** 0.5

    def _pre_dart_seen(self):
        """A dart landed in the bull-off. Only the first one of a visit counts, it is noted at once, the
        others are ignored until the darts are pulled. Who throws next follows then."""
        throws, self._last_throws = list(self._last_throws), []
        self._current_darts = []
        self._dart_overrides = {}
        if self._one_dart_taken or not throws or self.phase != "bull_off":
            return
        self._bull_off_register(throws[0])

    def _bull_off_register(self, throw):
        """The dart of the visit: how far it is from the bull. The visit goes on until the darts are pulled."""
        self._one_dart_taken = True
        player = self.current
        self._push_history(self._state_of(), turn_recorded=False)
        distance = self._bull_distance(throw)
        self._bo["dist"][player] = distance
        self._bo["shown"][player] = distance
        self._last_turn_throws, self._last_turn_player = [throw], player
        self._changed()

    def _correct_bull_off_dart(self, dart_index, field):
        """Correct the dart of the visit in the bull-off, or enter one the board did not see."""
        if dart_index != 0 or self.state != "playing":
            return
        throw = parse_field(field)
        if self._one_dart_taken:
            distance = self._bull_distance(throw)
            self._bo["dist"][self.current] = distance
            self._bo["shown"][self.current] = distance
            self._last_turn_throws = [throw]
            self._changed()
        else:
            self._bull_off_register(throw)

    def _bull_off_advance(self):
        """The darts of the visit are pulled: place the player, or let the tied ones throw again, and call
        the next thrower; with everybody placed the order is set and the match starts."""
        group = self._bo["todo"][0]
        tie = False
        if all(p in self._bo["dist"] for p in group):
            ranked = sorted(group, key=lambda p: self._bo["dist"][p])
            split = []
            for p in ranked:
                if split and abs(self._bo["dist"][split[-1][0]] - self._bo["dist"][p]) < _TIE:
                    split[-1].append(p)
                else:
                    split.append([p])
            if self.tiebreak:
                # Only who is closest matters: the leader wins, tied leaders throw again.
                if len(split[0]) == 1:
                    self._decide_leg(split[0][0])
                    return
                self._bo = {"final": [], "todo": [split[0]], "dist": {}, "shown": self._bo["shown"]}
                tie = True
            else:
                self._bo["todo"][0:1] = split
                self._bo["dist"] = {}
                tie = any(len(g) > 1 for g in split)
                while self._bo["todo"] and len(self._bo["todo"][0]) == 1:
                    self._bo["final"].append(self._bo["todo"].pop(0)[0])
        if not self._bo["todo"]:
            self.order = list(self._bo["final"])
            self.phase = "playing"
            self.current = self.order[0]
            self.leg_start = 0
            self._turn_start = self._state_of()
            self._bull_off_calls(self.current, tie=False, done=True)
            self._start_match_soon()
        else:
            self.current = self._bo_thrower()
            self._turn_start = self._state_of()
            self._bull_off_calls(self.current, tie=tie, done=False)
        self._changed()

    def _bull_off_calls(self, thrown, tie, done):
        if not self.audio or self._silent:
            return
        with self._audio_batch():
            if tie:
                self.audio.play("bull_off_tie")
            if not done:
                self._announce(self.current)
                self.audio.play("bull_off")

    def _start_match_soon(self):
        if self._start_delay:
            threading.Timer(self._start_delay, self._start_match).start()
        else:
            self._start_match()

    def _start_match(self):
        if self._match_started or self._stopped or self.state != "playing":
            return
        self._emit_match_started()
        self._turn_start = self._state_of()
        self._changed()

    def announce_start(self):
        """The game is assigned to its controller: with a bull-off the first thrower is called, else the match
        starts."""
        self._changed()
        if self.phase == "bull_off":
            if self.audio:
                def call():
                    with self._audio_batch():
                        self._announce(self.current)
                        self.audio.play("bull_off")
                threading.Timer(self._start_delay, call).start()
        else:
            self._start_match_soon()

    # ── undo and corrections ─────────────────────────────────────────────────

    def _snapshot_state(self, player):
        return self._turn_start

    def _restore(self, snap):
        self._load_state(snap)
        self._turn_start = copy.deepcopy(snap)
        self._result = None
        self._em = self._fresh_em()
        self._last_turn_throws, self._last_turn_player = [], None
        self._one_dart_taken = False

    def _forget_stored_turn(self, snap, was_finished):
        """The statistics are taken back by the `x01-resync` event that follows the restore."""

    def _notify_end(self, winner):
        if self._on_end:
            try:
                self._on_end(winner)
            except Exception:
                log.exception("X01 end callback failed")

    def undo(self):
        """Walk back the most recently completed turn (or bull-off throw). Silent, like in the other games."""
        if not self._history:
            return False
        was_finished = self.state == "finished"
        recorded = bool(self._history[-1].get("turn_recorded"))
        leg_recorded = bool(self._history[-1].get("leg_recorded"))
        state_before = self._history[-1]
        if self._em["flushed"]:         # the turn in progress already won a leg: it is stored
            self._emit_resync(self._turn_start, undo_stored=True)
        ok = super().undo()
        if ok and state_before.get("match_started"):
            self._emit_resync(self._turn_start, undo_stored=recorded, undo_leg=leg_recorded)
        if ok and was_finished and self.state == "playing":
            self._notify_end(None)
        return ok

    def correct_last_dart(self, dart_index, field):
        """Correct a dart of the last finished turn, also after it ended the match: the game goes back to before
        that turn and plays it again with the corrected dart."""
        # The bull-off after the max rounds has begun but nobody threw yet: the last turn is still the last thing that
        # happened, so a dart of it can be corrected (it may have been a finish the board misread).
        if not self._history or self._history[-1]["phase"] != "playing" or not self._last_turn_throws \
                or dart_index not in (0, 1, 2):
            log.warning("No turn to correct")
            return False
        snap = self._history.pop()
        was_finished = self.state == "finished"
        throws = list(self._last_turn_throws)
        while len(throws) <= dart_index:
            throws.append({"segment": {"number": 0, "multiplier": 0}})
        throws[dart_index] = parse_field(field)
        self._restore(snap)
        if was_finished:
            self._notify_end(None)
        self._emit_resync(snap, undo_stored=bool(snap.get("turn_recorded")))
        self._last_throws = throws
        self._current_darts = [self.value_of(t) for t in throws]
        self._silent = True
        try:
            self._replay_turn()
            if self.state == "playing":
                self._complete_turn()
        finally:
            self._silent = False
        log.info("Last turn corrected: dart %d is %s", dart_index + 1, field)
        return True

    def correct_turn(self, new_total):
        log.warning("Correcting a turn total does not apply to X01")

    # ── what the screens get ─────────────────────────────────────────────────

    def _publish_state(self):
        self._changed()

    def _publish_turn(self, reset=False):
        """Nothing: the current darts reach MQTT through the events of the match."""

    def _publish_last_turn(self, dart_vals):
        """Nothing, see _publish_turn()."""

    def _publish_event(self, event_type, **fields):
        """Nothing, see _publish_turn()."""

    def snapshot(self) -> dict:
        cp = self.current_player
        scores = self.scores
        if self._result and self.phase == "playing":
            scores = self._view_scores(self._result)
        return {
            "active": self.state == "playing",
            "state": self.state,
            "phase": self.phase,
            "winner": self.winner,
            "current_player": cp,
            "match_id": self.match_id,
            "leg": self.leg,
            "pull_darts": self.phase == "bull_off" and self._one_dart_taken,      # the throw counted, the darts are on the board
            "tiebreak": self.tiebreak,
            "round": self.turns_in_leg // len(self.order) + 1,
            "rules": {"start": self.start, "in_mode": self.in_mode, "out_mode": self.out_mode, "legs": self.legs,
                      "bull_off": self.bull_off, "max_rounds": self.max_rounds},
            "setup": {"start": self.start, "in_mode": self.in_mode, "out_mode": self.out_mode, "legs": self.legs,
                      "bull_off": self.bull_off, "max_rounds": self.max_rounds},
            "order": list(self.order),
            "current_darts": list(self._current_darts),
            "darts": [self.board_dart(t) for t in self._last_throws],
            "players": [
                {
                    "name": p,
                    "remaining": scores[p],
                    "legs_won": self.legs_won[p],
                    "current": p == cp,
                    "bull_off_mm": round(self._bo["shown"][p] * 170) if p in self._bo["shown"] else None,
                    "placed": p in self._bo["final"],
                }
                for p in (self.order if self.phase == "playing" else list(self._bo["final"]) + [
                    q for g in self._bo["todo"] for q in g])
            ],
            "last_turn": {"player": self._last_turn_player,
                          "darts": [self.board_dart(t) for t in self._last_turn_throws]},
        }

    def stopped(self):
        """The game ends before it is won: tell the program."""
        self._stopped = True
        if self._match_started:
            self._emit({"event": "match-ended"})


class X01Controller(TurnGameController):
    TOPIC = "x01_own"

    def __init__(self, emit, stats_db=None, audio=None, on_change=None):
        """*emit*: the function the events of the match go to. No MQTT commands: the match is started through
        the REST routes, what MQTT shows comes from the events of the match."""
        self.emit = emit
        self.stats_db = stats_db
        self.audio = audio
        self.game = None
        self._on_change = on_change
        self._lock = threading.RLock()
        self.bots = None

    def start(self, players, start=501, in_mode="straight", out_mode="double", legs=1, bull_off=True,
              tournament_id=None, on_end=None, max_rounds=None):
        """Start a match. Raises ValueError for a setup that cannot be played."""
        game = X01Game(players, self.emit, start=start, in_mode=in_mode, out_mode=out_mode, legs=legs,
                       bull_off=bull_off, audio=self.audio, on_change=self._on_change, stats_db=self.stats_db,
                       tournament_id=tournament_id, on_end=on_end, max_rounds=max_rounds)
        with self._lock:
            old, self.game = self.game, game
        if old:
            old.stopped()
        game.announce_start()
        return game

    @property
    def match_active(self):
        """A match is on, also before its first dart and after the last one."""
        return self.game is not None

    def stop(self):
        with self._lock:
            game, self.game = self.game, None
        if game:
            game.stopped()
        if self._on_change:
            self._on_change()
        log.info("Game stopped")
