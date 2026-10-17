"""Warm-up: the round of the world over every segment. One player throws at a fixed series of fields until each is hit.

The series has eight stations: the big singles (between the triple ring and the double ring) from 1 to 20, the bull,
the small singles (between the bull and the triple ring) from 1 to 20, the bull, the doubles from 1 to 20, the bull,
the triples from 1 to 20 and the bull's eye. A run can go over all of them or over the kinds of field the player picks.
The stations keep their order, the bull is thrown between two stations that are picked (one that is picked alone is
followed by it, a bull picked alone is thrown once) and the bull's eye comes last. A dart in the right part of the
field that is up moves the series on, also for the darts that are left in the same turn. There is no limit of darts
per field. The run ends when every field has been hit or when the player finishes it.
"""

import copy
import json
import logging
import math

from .dartboard import DOUBLE_OUT_MM, TRIPLE_IN_MM
from .player_colors import assign_colors
from .turn_game import TurnGame, TurnGameController, dart_positions

log = logging.getLogger(__name__)

BIG, BULL, SMALL, DOUBLE, EYE, TRIPLE = "big", "bull", "small", "double", "eye", "triple"

# The kinds of field a run can go over, in the order the setup lists them.
KINDS = (BIG, SMALL, DOUBLE, TRIPLE, BULL, EYE)

# The stations of the full run in order: the kind of field and how many fields it has.
STATIONS = ((BIG, 20), (BULL, 1), (SMALL, 20), (BULL, 1), (DOUBLE, 20), (BULL, 1), (TRIPLE, 20), (EYE, 1))

# The station of the full run that a kind of field is, and the station of the bull that follows it. The triples have
# none in the full run, a run that ends on them and wants a bull takes the last one.
STATION_OF = {BIG: 0, SMALL: 2, DOUBLE: 4, TRIPLE: 6}
BULL_AFTER = {BIG: 1, SMALL: 3, DOUBLE: 5, TRIPLE: 5}
FIRST_BULL, EYE_STATION = 1, 7


def series():
    """Every field of the full run in order as (kind, number, station): 25 is the bull, 50 the bull's eye."""
    steps = []
    for station, (kind, count) in enumerate(STATIONS):
        if kind == BULL:
            steps.append((kind, 25, station))
        elif kind == EYE:
            steps.append((kind, 50, station))
        else:
            steps.extend((kind, number, station) for number in range(1, count + 1))
    return steps


STEPS = series()


def normalize_kinds(kinds):
    """The kinds a run goes over, in the order of the series. None or an empty list is all of them. Raises ValueError
    for a kind that does not exist."""
    if not kinds:
        return list(KINDS)
    unknown = [k for k in kinds if k not in KINDS]
    if unknown:
        raise ValueError(f"unknown station: {unknown[0]}")
    chosen = set(kinds)
    return [k for k in KINDS if k in chosen]


def fields_for(kinds):
    """The fields of a run over `kinds` as (index in the full series, kind, number, station). The picked stations keep
    the order of the series. The bull comes between two of them, behind a station that is picked alone and on its own
    when nothing else but the bull's eye is picked; the bull's eye is last."""
    chosen = set(normalize_kinds(kinds))
    main = [k for k in (BIG, SMALL, DOUBLE, TRIPLE) if k in chosen]

    def station_fields(station):
        return [(i, kind, number, s) for i, (kind, number, s) in enumerate(STEPS) if s == station]

    fields = []
    for pos, kind in enumerate(main):
        fields += station_fields(STATION_OF[kind])
        if BULL in chosen and (pos < len(main) - 1 or len(main) == 1):
            fields += station_fields(BULL_AFTER[kind])
    if BULL in chosen and not main:
        fields += station_fields(FIRST_BULL)
    if EYE in chosen:
        fields += station_fields(EYE_STATION)
    return fields


def single_ring(throw):
    """"outer" for a dart in the big single, "inner" for one in the small single. The board names the bed, a dart with a
    position is told by its distance to the center, and a dart with neither (set by field only) sits where the center
    of its field is, in the big single."""
    seg = throw.get("segment") or {}
    bed = str(seg.get("bed") or "").lower()
    if bed == "singleouter":
        return "outer"
    if bed == "singleinner":
        return "inner"
    coords = throw.get("coords")
    if isinstance(coords, dict) and "x" in coords and "y" in coords:
        radius_mm = math.hypot(float(coords["x"]), float(coords["y"])) * DOUBLE_OUT_MM
        return "inner" if radius_mm < TRIPLE_IN_MM else "outer"
    return "outer"


def is_hit(throw, step):
    """A dart in the right part of the field that is up. The bull takes the bull's eye as well."""
    kind, number = step[0], step[1]
    seg = throw.get("segment") or {}
    n, multiplier = seg.get("number"), seg.get("multiplier")
    if kind == BULL:
        return n == 25
    if kind == EYE:
        return n == 25 and multiplier == 2
    if n != number:
        return False
    if kind == DOUBLE:
        return multiplier == 2
    if kind == TRIPLE:
        return multiplier == 3
    if multiplier != 1:
        return False
    return single_ring(throw) == ("outer" if kind == BIG else "inner")


class Progress:
    """Where a run stands. `play()` moves it along with the darts of a turn."""

    def __init__(self, kinds=None):
        self.fields = fields_for(kinds)       # (index in the full series, kind, number, station) of every field
        self.pos = 0                          # the index of the field that is up, len(fields) once the run is done
        self.per_step = [0] * len(self.fields)  # the darts thrown at each field, the hit included

    @property
    def done(self):
        return self.pos >= len(self.fields)

    @property
    def target(self):
        _, kind, number, station = self.fields[min(self.pos, len(self.fields) - 1)]
        return {"kind": kind, "number": number, "station": station}

    def play(self, throws):
        """The darts of a turn, one record per dart that was thrown at the series: the field it was for and whether it
        hit. `step` is the place of the field in the full series. Darts after the last field are not counted."""
        records = []
        for throw in throws:
            if self.done:
                break
            index, kind, number, station = self.fields[self.pos]
            hit = is_hit(throw, (kind, number))
            records.append({"step": index, "kind": kind, "number": number, "station": station, "hit": hit})
            self.per_step[self.pos] += 1
            if hit:
                self.pos += 1
        return records

    def copy(self):
        return copy.deepcopy(self)


def station_totals(fields, per_step):
    """Per station of the run: the darts it took and how many fields it has, in the order of the series."""
    totals = {}
    for (_, kind, _, station), darts in zip(fields, per_step):
        row = totals.setdefault(station, {"kind": kind, "fields": 0, "darts": 0})
        row["fields"] += 1
        row["darts"] += darts
    return [totals[station] for station in sorted(totals)]


def slowest(fields, per_step, limit=5):
    """The fields that needed the most darts, most first (the earlier field first on a tie)."""
    ranked = sorted(((darts, -i) for i, darts in enumerate(per_step) if darts > 1), reverse=True)[:limit]
    return [{"step": fields[-i][0], "kind": fields[-i][1], "number": fields[-i][2], "darts": darts}
            for darts, i in ranked]


class WarmUpGame(TurnGame):
    MODE = "Warm-up"
    TOPIC = "warm_up"

    def __init__(self, player, client, base_topic, kinds=None, audio=None, on_change=None, stats_db=None,
                 match_id=None, color=None):
        player = (player or "").strip()
        if not player:
            raise ValueError("need a player")
        kinds = normalize_kinds(kinds)
        super().__init__(client, base_topic, audio=audio, on_change=on_change,
                         stats_db=stats_db, match_id=match_id)
        self.player = player
        self.kinds = kinds
        self.color = color
        self.progress = Progress(kinds)
        self.thrown = 0
        self.turns = []           # the darts of every finished turn, as the board shows them
        self.result = None
        if self.stats_db:
            self.stats_db.open_match(self.match_id, self.MODE, 0)
            self.stats_db.record_warm_up_setup(self.match_id, player, kinds)
        log.info("Warm-up started: %s%s", player, "" if len(kinds) == len(KINDS) else ", " + " ".join(kinds))

    @property
    def current_player(self):
        return self.player if self.state == "playing" else None

    # ── the game ─────────────────────────────────────────────────────────────

    def announce_start(self):
        """Publish the first state. Only once the game is assigned to its controller, since the
        state push builds its snapshot from there."""
        self._publish_state()
        self._publish_turn(reset=True)
        self._publish_last_turn([])
        self._publish_event("start", player=self.player, stations=self.kinds)

    def _end_turn(self):
        throws = list(self._last_throws)
        if not throws:
            self._current_darts, self._last_throws, self._dart_overrides = [], [], {}
            return
        self._turn_snapshot = self._snapshot_state(self.player)
        self._push_history(self._turn_snapshot, turn_recorded=self.stats_db is not None)
        values = list(self._current_darts)
        self._publish_last_turn(values)
        records = self.progress.play(throws)
        counted = throws[:len(records)]
        if self.stats_db:
            self.stats_db.insert_warm_up_turn(
                self.match_id, self.player, records, positions=dart_positions(counted))
        self._current_darts, self._last_throws, self._dart_overrides = [], [], {}
        self.thrown += len(records)
        self.turns.append([{**self.board_dart(t), "hit": r["hit"]} for t, r in zip(counted, records)])
        self._publish_event("turn_end", player=self.player, hits=sum(1 for r in records if r["hit"]),
                            fields=self.progress.pos)
        if self.progress.done:
            self._finish()
        else:
            self._publish_state()
            self._publish_turn(reset=True)

    def finish_early(self):
        """End the run and keep what was thrown. Darts of a turn that is still in progress are not
        counted. Returns False when no dart was thrown yet, there is nothing to keep then."""
        if self.state != "playing" or not self.thrown:
            return False
        self._current_darts, self._last_throws, self._dart_overrides = [], [], {}
        self._finish()
        return True

    def _finish(self):
        self.state = "finished"
        p = self.progress
        self.result = {
            "complete": p.done, "fields": p.pos, "darts": self.thrown,
            "stations": station_totals(p.fields, p.per_step), "slowest": slowest(p.fields, p.per_step),
        }
        if self.stats_db:
            self.stats_db.set_warm_up_complete(self.match_id, p.done)
            self.stats_db.close_match(self.match_id)
        self._publish_event("finished", player=self.player, complete=p.done, fields=p.pos, darts=self.thrown)
        self._publish_state()
        self._publish_turn(reset=True)
        log.info("Warm-up finished: %d of %d fields, %d darts", p.pos, len(p.fields), self.thrown)

    # ── undo ─────────────────────────────────────────────────────────────────

    def _snapshot_state(self, player):
        return copy.deepcopy({
            "progress": self.progress, "thrown": self.thrown, "turns": self.turns,
            "state": self.state, "result": self.result,
        })

    def _restore(self, snap):
        snap = copy.deepcopy(snap)
        self.progress = snap["progress"]
        self.thrown = snap["thrown"]
        self.turns = snap["turns"]
        self.state = snap["state"]
        self.result = snap["result"]

    def _forget_stored_turn(self, snap, was_finished):
        if was_finished:
            self.stats_db.set_warm_up_complete(self.match_id, False)
            self.stats_db.reopen_match(self.match_id)
        if snap["turn_recorded"]:
            self.stats_db.delete_last_warm_up_turn(self.match_id, self.player)

    def correct_turn(self, new_total):
        """A turn has no total to correct here: tap a dart to correct it, or undo the turn."""
        log.warning("Warm-up has no turn total to correct")

    # ── what the screens and MQTT get ────────────────────────────────────────

    def snapshot(self) -> dict:
        """The state as the screens show it. While darts are on the board the series is shown as
        if they were counted, so it moves with every dart."""
        live = self.progress.copy()
        live_records = live.play(list(self._last_throws)) if self.state == "playing" else []
        p = live if self.state == "playing" else self.progress
        board = [{**self.board_dart(t), "hit": r["hit"]} for t, r in zip(self._last_throws, live_records)]
        all_darts = [d for turn in self.turns for d in turn]
        stations = []
        for _, kind, _, station in p.fields:
            if station not in [s["index"] for s in stations]:
                stations.append({"index": station, "kind": kind})
        return {
            "active": self.state == "playing",
            "state": self.state,
            "match_id": self.match_id,
            "player": self.player,
            "current_player": self.current_player,
            "color": self.color,
            "kinds": list(self.kinds),
            "all": len(self.kinds) == len(KINDS),
            "steps": [[kind, number, station] for _, kind, number, station in p.fields],
            "stations": stations,
            "position": p.pos,                # fields done
            "target": p.target,
            "per_step": list(p.per_step),
            "thrown": self.thrown + len(live_records),
            "turn": len(self.turns) + 1,
            "complete": p.done,
            "current_darts": [{"kind": r["kind"], "number": r["number"], "hit": r["hit"]} for r in live_records],
            "round_darts": {self.player: board},
            "all_darts": [{"x": d["x"], "y": d["y"], "field": d["field"], "hit": d["hit"]}
                          for d in all_darts if d.get("x") is not None],
            "setup": {"player": self.player, "stations": list(self.kinds)},
            "result": self.result,
        }

    def _publish_state(self):
        p = self.progress
        target = p.target
        state = {"state": self.state, "player": self.player, "stations": self.kinds, "target": target,
                 "fields_done": p.pos, "fields": len(p.fields), "darts": self.thrown, "complete": p.done}
        self.client.publish(self._topic("state"), json.dumps(state, ensure_ascii=False), retain=True)
        self.client.publish(self._topic("active"), "true" if self.state == "playing" else "false", retain=True)
        self.client.publish(self._topic("target"), f"{target['kind']} {target['number']}", retain=True)
        self.client.publish(self._topic("fields_done"), str(p.pos), retain=True)
        self._changed()


class WarmUpController(TurnGameController):
    TOPIC = "warm_up"

    def start(self, player, kinds=None):
        """Start a run over `kinds` (all of them when none are given). Raises ValueError for a setup that cannot
        be played."""
        name = (player or "").strip()
        chosen = self.stats_db.player_colors() if self.stats_db else {}
        game = WarmUpGame(
            name, self.mqtt_pub.client, self.base_topic, kinds=kinds, audio=self.audio, on_change=self._on_change,
            stats_db=self.stats_db, color=assign_colors([name], chosen)[name]["color"] if name else None)
        with self._lock:
            self.game = game
        game.announce_start()

    def finish_early(self):
        with self._lock:
            return bool(self.game and self.game.finish_early())

    def _command_start(self, cmd):
        players = [str(p).strip() for p in cmd.get("players", []) if str(p).strip()]
        player = str(cmd.get("player") or (players[0] if players else "")).strip()
        self.start(player, [str(k) for k in cmd.get("stations") or []])
