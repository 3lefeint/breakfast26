"""Field training: one player throws a fixed number of darts at one field.

The field is a number from 1 to 20 or the bull (25). A dart on the field scores its multiplier:
single 1, double 2, triple 3; at the bull the outer bull (green) scores 1 and the bull's eye
(red) 2. Everything else scores 0. The classic drills are 100 darts at a number and 50 darts at
the bull. Turns are three darts; the last turn only has the darts that are left.

A run counts (personal best, rating, achievements) when every dart was thrown and there were at
least the standard number of darts for the field. Anything else, a shorter or an abandoned run, is
saved as practice.
"""

import copy
import json
import logging

from .player_colors import assign_colors
from .turn_game import TurnGame, TurnGameController, dart_positions

log = logging.getLogger(__name__)

BULL = 25
FIELDS = [*range(1, 21), BULL]
MAX_DARTS = 999

# The standard length of a run: what the ratings and the personal best refer to.
STANDARD_DARTS = {"number": 100, "bull": 50}

# Where a rating changes, in points over the standard length: below the first value a player is
# a beginner, up to the second one advanced, above it a pro. The bull values are the reference
# values of the drill (beginners about 20, advanced about 40, pros above 50). The values for a
# number are estimates, there are no published ones.
RATING_LIMITS = {"bull": (30, 50), "number": (60, 100)}


def kind_of(field):
    return "bull" if field == BULL else "number"


def standard_darts(field):
    return STANDARD_DARTS[kind_of(field)]


def rating(field, points, darts):
    """How a run is rated: "beginner", "advanced" or "pro". The points are scaled to the standard
    length first, so a run of another length is rated on the same scale."""
    if not darts:
        return None
    scaled = points * standard_darts(field) / darts
    low, high = RATING_LIMITS[kind_of(field)]
    if scaled < low:
        return "beginner"
    return "advanced" if scaled <= high else "pro"


def scaled_points(field, points, darts):
    """The points of a run on the scale of the standard length, to compare runs."""
    return round(points * standard_darts(field) / darts, 1) if darts else 0.0


class FieldTrainingGame(TurnGame):
    MODE = "Field Training"
    TOPIC = "field_training"

    def __init__(self, player, client, base_topic, field, darts=None, audio=None, on_change=None,
                 stats_db=None, match_id=None, color=None):
        player = (player or "").strip()
        if not player:
            raise ValueError("need a player")
        if field not in FIELDS:
            raise ValueError("field must be a number from 1 to 20 or 25 for the bull")
        darts = standard_darts(field) if darts is None else darts
        if not 1 <= darts <= MAX_DARTS:
            raise ValueError(f"darts must be between 1 and {MAX_DARTS}")
        super().__init__(client, base_topic, audio=audio, on_change=on_change,
                         stats_db=stats_db, match_id=match_id)
        self.player = player
        self.field = field
        self.darts = darts
        self.color = color
        self.thrown = 0
        self.points = 0
        self.hits = {1: 0, 2: 0, 3: 0}      # darts that scored 1, 2 and 3
        self.turns = []                     # the finished turns: {"points", "darts": [board view]}
        self.completed = False
        self.result = None
        if self.stats_db:
            self.stats_db.open_match(self.match_id, self.MODE, darts)
            self.stats_db.record_field_training_setup(self.match_id, player, field, darts)
        log.info("Field training started: %s, field %s, %d darts", player, field, darts)

    # ── scoring ──────────────────────────────────────────────────────────────

    def value_of(self, throw):
        seg = throw.get("segment") or {}
        if seg.get("number") != self.field:
            return 0
        multiplier = seg.get("multiplier") or 0
        return multiplier if 1 <= multiplier <= 3 else 0

    @property
    def current_player(self):
        return self.player if self.state == "playing" else None

    @property
    def remaining(self):
        return self.darts - self.thrown

    @property
    def counts(self):
        """Whether the run is a full one: all darts thrown, at least the standard number."""
        return self.completed and self.darts >= standard_darts(self.field)

    # ── the game ─────────────────────────────────────────────────────────────

    def announce_start(self):
        """Publish the first state. Only once the game is assigned to its controller, since the
        state push builds its snapshot from there."""
        self._publish_state()
        self._publish_turn(reset=True)
        self._publish_last_turn([])
        self._publish_event("start", player=self.player, field=self.field, darts=self.darts)

    def _end_turn(self):
        # A turn never takes more darts than are left; the board may show three.
        throws = list(self._last_throws)[:self.remaining]
        values = list(self._current_darts)[:self.remaining]
        if not throws:
            self._current_darts, self._last_throws, self._dart_overrides = [], [], {}
            return
        self._turn_snapshot = self._snapshot_state(self.player)
        self._push_history(self._turn_snapshot, turn_recorded=self.stats_db is not None)
        self._publish_last_turn(values)
        hits = {m: sum(1 for v in values if v == m) for m in (1, 2, 3)}
        if self.stats_db:
            self.stats_db.insert_field_training_turn(
                self.match_id, self.player, len(throws), sum(values), hits,
                positions=dart_positions(throws))
        self._current_darts, self._last_throws, self._dart_overrides = [], [], {}
        self._apply_turn(values, hits, [self.board_dart(t) for t in throws])

    def _apply_turn(self, values, hits, darts):
        self.thrown += len(values)
        self.points += sum(values)
        for m, n in hits.items():
            self.hits[m] += n
        self.turns.append({"points": sum(values), "darts": darts})
        self._publish_event("turn_end", player=self.player, score=sum(values),
                            thrown=self.thrown, points=self.points)
        if self.thrown >= self.darts:
            self._finish(completed=True)
        else:
            self._publish_state()
            self._publish_turn(reset=True)

    def finish_early(self):
        """Stop the run and keep what was thrown so far as practice. Darts of a turn that is
        still in progress are not counted. Returns False when no dart was thrown yet, there is
        nothing to keep then."""
        if self.state != "playing" or not self.thrown:
            return False
        self._current_darts, self._last_throws, self._dart_overrides = [], [], {}
        self._finish(completed=False)
        return True

    def _finish(self, completed):
        self.completed = completed
        self.state = "finished"
        best = None
        if self.stats_db:
            best = self.stats_db.field_training_best(self.player, self.field, exclude=self.match_id)
            self.stats_db.set_field_training_completed(self.match_id, self.counts)
            self.stats_db.close_match(self.match_id)
        scaled = scaled_points(self.field, self.points, self.thrown)
        self.result = {
            "points": self.points,
            "darts": self.thrown,
            "scaled_points": scaled,
            "hit_rate": self._hit_rate(),
            "counts": self.counts,
            # Only a full run is rated and can be a best; the best of the earlier ones, to
            # show what it was up against.
            "rating": rating(self.field, self.points, self.thrown) if self.counts else None,
            "previous_best": best,
            "personal_best": bool(self.counts and (best is None or scaled > best)),
        }
        self._publish_event("finished", player=self.player, points=self.points, darts=self.thrown,
                            completed=completed)
        self._publish_state()
        self._publish_turn(reset=True)
        log.info("Field training finished: %d points in %d darts%s", self.points, self.thrown,
                 "" if completed else " (stopped early)")

    def _hit_rate(self):
        return round(sum(self.hits.values()) / self.thrown, 3) if self.thrown else 0.0

    # ── undo and corrections ─────────────────────────────────────────────────

    def _snapshot_state(self, player):
        return copy.deepcopy({
            "thrown": self.thrown, "points": self.points, "hits": self.hits, "turns": self.turns,
            "state": self.state, "completed": self.completed, "result": self.result,
        })

    def _restore(self, snap):
        snap = copy.deepcopy(snap)
        self.thrown = snap["thrown"]
        self.points = snap["points"]
        self.hits = snap["hits"]
        self.turns = snap["turns"]
        self.state = snap["state"]
        self.completed = snap["completed"]
        self.result = snap["result"]

    def _forget_stored_turn(self, snap, was_finished):
        if was_finished:
            self.stats_db.set_field_training_completed(self.match_id, False)
            self.stats_db.reopen_match(self.match_id)
        if snap["turn_recorded"]:
            self.stats_db.delete_last_field_training_turn(self.match_id, self.player)

    def correct_turn(self, new_total):
        """A turn has no total to correct here, the darts are what counts: tap a dart to
        correct it, or undo the turn."""
        log.warning("Field training has no turn total to correct")

    # ── what the screens and MQTT get ────────────────────────────────────────

    def snapshot(self) -> dict:
        thrown_darts = [d for turn in self.turns for d in turn["darts"]]
        live = [self.board_dart(t) for t in self._last_throws] if self.state == "playing" else []
        return {
            "active": self.state == "playing",
            "state": self.state,
            "player": self.player,
            "current_player": self.current_player,
            "color": self.color,
            "field": self.field,
            "darts": self.darts,
            "thrown": self.thrown,
            "remaining": self.remaining,
            "points": self.points,
            "hits": {"singles": self.hits[1], "doubles": self.hits[2], "triples": self.hits[3]},
            "hit_rate": self._hit_rate(),
            "turn": len(self.turns) + 1,
            "current_darts": list(self._current_darts),
            "round_darts": {self.player: live},
            # The points of every finished turn, for the trend of the run.
            "turn_points": [t["points"] for t in self.turns],
            # Where every dart of the run landed, for the heatmap of the result.
            "all_darts": [{"x": d["x"], "y": d["y"], "field": d["field"], "points": d["points"]}
                          for d in thrown_darts if d.get("x") is not None],
            "standard_darts": standard_darts(self.field),
            # What it takes to start the same run again.
            "setup": {"player": self.player, "field": self.field, "darts": self.darts},
            "result": self.result,
        }

    def _publish_state(self):
        state = {
            "state": self.state, "player": self.player, "field": self.field, "darts": self.darts,
            "thrown": self.thrown, "points": self.points,
            "hits": {"singles": self.hits[1], "doubles": self.hits[2], "triples": self.hits[3]},
        }
        self.client.publish(self._topic("state"), json.dumps(state, ensure_ascii=False), retain=True)
        self.client.publish(self._topic("active"), "true" if self.state == "playing" else "false", retain=True)
        self.client.publish(self._topic("field"), str(self.field), retain=True)
        self.client.publish(self._topic("thrown"), str(self.thrown), retain=True)
        self.client.publish(self._topic("points"), str(self.points), retain=True)
        self._changed()


class FieldTrainingController(TurnGameController):
    TOPIC = "field_training"

    def start(self, player, field, darts=None):
        """Start a run. Raises ValueError for a setup that cannot be played."""
        chosen = self.stats_db.player_colors() if self.stats_db else {}
        game = FieldTrainingGame(
            player, self.mqtt_pub.client, self.base_topic, field, darts=darts, audio=self.audio,
            on_change=self._on_change, stats_db=self.stats_db,
            color=assign_colors([(player or "").strip()], chosen)[(player or "").strip()]["color"])
        with self._lock:
            self.game = game
        game.announce_start()

    def finish_early(self):
        with self._lock:
            return bool(self.game and self.game.finish_early())

    def _command_start(self, cmd):
        players = [str(p).strip() for p in cmd.get("players", []) if str(p).strip()]
        player = str(cmd.get("player") or (players[0] if players else "")).strip()
        darts = cmd.get("darts")
        self.start(player, int(cmd.get("field", 0)), darts=int(darts) if darts else None)
