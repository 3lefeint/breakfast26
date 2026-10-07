"""What the games that read three darts per turn from the board stream have in common.

`TurnGame` follows the darts of the turn in progress (a new dart, a correction of one),
applies a dart corrected by tapping on top of what the board reports, keeps the history for
undo, writes the turn out over MQTT and stores dart positions. A game decides what a dart is
worth (`value_of`), what happens when a turn ends (`_end_turn`) and how its state is saved
and restored (`_snapshot_state`, `_restore`).

`TurnGameController` owns the running game: it hands the board state to it, stops it and
answers the MQTT commands every game understands.
"""

import contextlib
import json
import logging
import threading
import uuid

from . import known_players as kp
from .dartboard import field_centers

log = logging.getLogger(__name__)

_FIELD_CENTERS = field_centers()


def dart_value(throw):
    """The face value of a dart, 0 for a miss."""
    seg = throw.get("segment", {})
    multiplier = seg.get("multiplier")
    if not multiplier:
        return 0
    return (seg.get("number") or 0) * multiplier


def parse_field(field):
    """A field string ('T20', 'D16', 'S5', '25', '50', '0') as a synthetic throw, shaped like
    a throw of the board."""
    field = (field or "").strip().upper()
    if field in ("", "0", "MISS"):
        number, multiplier = 0, 0
    elif field == "25":
        number, multiplier = 25, 1
    elif field == "50":
        number, multiplier = 25, 2
    elif field and field[0] in ("S", "D", "T"):
        number, multiplier = int(field[1:]), {"S": 1, "D": 2, "T": 3}[field[0]]
    else:
        number, multiplier = int(field), 1
    return {"segment": {"number": number, "multiplier": multiplier}}


def dart_positions(throws):
    """Where each dart of a turn landed, None for a dart without a field."""
    positions = []
    for throw in throws:
        coords = throw.get("coords")
        if isinstance(coords, dict) and "x" in coords and "y" in coords:
            positions.append({"field": (throw.get("segment") or {}).get("name"),
                              "x": float(coords["x"]), "y": float(coords["y"]),
                              "entry": throw.get("entry")})
        else:
            positions.append(_set_by_hand_position(throw))
    return positions


def _field_from_segment(throw):
    """The field name of a throw that only carries number and multiplier, None for a miss."""
    seg = throw.get("segment") or {}
    number, multiplier = seg.get("number") or 0, seg.get("multiplier") or 0
    if not multiplier:
        return None
    if number == 25:
        return "25" if multiplier == 1 else "50"
    return f"{'SDT'[multiplier - 1]}{number}"


def _set_by_hand_position(throw):
    """A dart set by tapping carries no coordinates, only its field. It is stored with the
    center of that field and marked as entered by hand; a miss has no field center."""
    field = _field_from_segment(throw)
    center = _FIELD_CENTERS.get(field) if field else None
    if not center:
        return None
    return {"field": field, "x": center["x"], "y": center["y"], "entry": "manual"}


class TurnGame:
    MODE = ""      # the game mode stored with the match, e.g. "Target Battle"
    TOPIC = ""     # the MQTT topic part of the game, e.g. "target_battle"

    def __init__(self, client, base_topic, audio=None, on_change=None, stats_db=None, match_id=None):
        self.client = client
        self.base_topic = base_topic
        self.audio = audio
        self.stats_db = stats_db
        self._on_change = on_change
        self.match_id = match_id or uuid.uuid4().hex
        self.state = "playing"
        self._prev_count = 0
        self._board_count = 0        # darts on the board right now, also while the game is not playing
        self._await_pull = False     # ignore the board until the darts that are on it now are pulled
        self._last_throws = []
        self._current_darts = []     # what each dart of the turn in progress is worth
        self._dart_overrides = {}    # dart index -> a dart corrected by tapping
        self._turn_snapshot = None   # the state before the last finished turn
        self._history = []           # stack of states before a turn, for undo()

    # ── what a game decides ──────────────────────────────────────────────────

    @property
    def current_player(self):
        raise NotImplementedError

    def value_of(self, throw):
        """What a dart is worth in this game."""
        return dart_value(throw)

    def _end_turn(self):
        """The darts were pulled: record the turn and move on."""
        raise NotImplementedError

    def _dart_seen(self, count, is_new_dart, is_correction):
        """A dart was added to the turn in progress or one of them was corrected."""

    def _snapshot_state(self, player):
        """Everything `_restore` needs to bring the game back to before `player`'s turn."""
        raise NotImplementedError

    def _restore(self, snap):
        raise NotImplementedError

    def _forget_stored_turn(self, snap, was_finished):
        """Take what an undone turn wrote to the stats database out again."""

    def _publish_state(self):
        raise NotImplementedError

    # ── following the board ──────────────────────────────────────────────────

    def on_board_state(self, count, throws):
        self._board_count = count
        if self._await_pull:
            if count == 0:
                self._await_pull = False
                self._prev_count = 0
            return
        if self.state != "playing":
            return
        if count > 0:
            new_vals = [self.value_of(t) for t in throws]
            is_new_dart = count > self._prev_count
            is_correction = count == self._prev_count and new_vals != self._current_darts
            if is_new_dart or is_correction:
                self._last_throws = list(throws)
                self._current_darts = new_vals
                # The board reports the whole turn afresh each time, so a dart corrected by
                # tapping has to be put back on top of it or the next dart would undo it.
                self._apply_dart_overrides()
                self._publish_turn()
                self._changed()
                if is_correction:
                    log.debug("Live correction detected: %s", new_vals)
                self._dart_seen(count, is_new_dart, is_correction)
        if count == 0 and self._prev_count > 0:
            self._end_turn()
        self._prev_count = count

    def correct_current_dart(self, dart_index, field):
        """Correct one dart of the turn still in progress, e.g. by tapping a field on the TV
        view. The corrected dart is what gets scored when the turn ends."""
        if self.state != "playing":
            return
        if dart_index not in (0, 1, 2):
            return
        self._dart_overrides[dart_index] = parse_field(field)
        self._apply_dart_overrides()
        self._publish_turn()
        self._changed()
        log.info("Dart %d corrected: %s", dart_index + 1, field)

    def _apply_dart_overrides(self):
        for idx, throw in self._dart_overrides.items():
            while len(self._last_throws) <= idx:
                self._last_throws.append({"segment": {"number": 0, "multiplier": 0}})
            while len(self._current_darts) <= idx:
                self._current_darts.append(0)
            self._last_throws[idx] = throw
            self._current_darts[idx] = self.value_of(throw)

    def board_dart(self, throw):
        """A dart for the board view: its field, what it is worth and where it sits."""
        field = (throw.get("segment") or {}).get("name") or _field_from_segment(throw)
        coords = throw.get("coords")
        if isinstance(coords, dict) and "x" in coords and "y" in coords:
            x, y = coords["x"], coords["y"]
        else:
            center = _FIELD_CENTERS.get(field) or {}      # a dart without coordinates: its field's center
            x, y = center.get("x"), center.get("y")
        return {"field": field, "points": self.value_of(throw), "x": x, "y": y}

    # ── undo ─────────────────────────────────────────────────────────────────

    def _push_history(self, snapshot, turn_recorded):
        """*turn_recorded*: whether a database row was written for the turn, so that undo()
        knows whether there is one to delete (False without a stats database)."""
        self._history.append({**snapshot, "turn_recorded": turn_recorded})

    def undo(self) -> bool:
        """Walk back the most recently completed turn, reopening a finished game when it is the
        turn that decided it. Repeatable. Returns False when there is nothing left to undo.
        Silent on purpose: an undo is a correction, not an event of the game."""
        if not self._history:
            return False
        snap = self._history.pop()
        was_finished = self.state == "finished"
        self._restore(snap)
        if self.stats_db:
            self._forget_stored_turn(snap, was_finished)
        self._current_darts = []
        self._dart_overrides = {}
        self._turn_snapshot = None
        self._publish_state()
        self._publish_turn(reset=True)
        log.info("Turn undone: %s is up", self.current_player)
        return True

    # ── output ───────────────────────────────────────────────────────────────

    def _changed(self):
        if self._on_change:
            self._on_change()

    def _audio_batch(self):
        """`self.audio.batch()`, or a no-op when audio is disabled."""
        return self.audio.batch() if self.audio else contextlib.nullcontext()

    def _announce(self, name):
        """Play *name*'s audio cue, `unknown_player` if there is no recording of it."""
        if not self.audio.play(name.lower()):
            self.audio.play("unknown_player")

    def _topic(self, suffix):
        return f"{self.base_topic}/{self.TOPIC}/{suffix}"

    def _publish_event(self, event_type, **fields):
        self.client.publish(self._topic(f"events/{event_type}"),
                            json.dumps({"type": event_type, **fields}, ensure_ascii=False), retain=False)
        log.info("%s: %s", event_type, fields)

    def _publish_turn(self, reset=False):
        darts = [] if reset else self._current_darts
        for i in range(3):
            self.client.publish(self._topic(f"current/dart{i + 1}"),
                                str(darts[i]) if i < len(darts) else "", retain=True)
        self.client.publish(self._topic("current/total"), str(sum(darts)), retain=True)

    def _publish_last_turn(self, dart_vals):
        for i in range(3):
            self.client.publish(self._topic(f"last_turn/dart{i + 1}"),
                                str(dart_vals[i]) if i < len(dart_vals) else "0", retain=True)
        self.client.publish(self._topic("last_turn/total"), str(sum(dart_vals)), retain=True)


class TurnGameController:
    TOPIC = ""

    def __init__(self, mqtt_pub, base_topic, stats_db=None, audio=None, on_change=None):
        self.mqtt_pub = mqtt_pub
        self.base_topic = base_topic
        self.stats_db = stats_db
        self.audio = audio
        self.game = None
        self._on_change = on_change
        self._lock = threading.RLock()

        mqtt_pub.subscribe(self._topic("command"), self._handle_command)
        mqtt_pub.client.publish(self._topic("active"), "false", retain=True)
        for i in range(1, 4):
            mqtt_pub.client.publish(self._topic(f"last_turn/dart{i}"), "0", retain=True)
        mqtt_pub.client.publish(self._topic("last_turn/total"), "0", retain=True)
        self._publish_known_players()

    def _topic(self, suffix):
        return f"{self.base_topic}/{self.TOPIC}/{suffix}"

    @property
    def active(self):
        return self.game is not None and self.game.state == "playing"

    def on_board_state(self, count, throws):
        with self._lock:
            if self.game:
                self.game.on_board_state(count, throws)

    def stop(self):
        with self._lock:
            self.game = None
        client = self.mqtt_pub.client
        client.publish(self._topic("active"), "false", retain=True)
        client.publish(self._topic("state"), "", retain=True)
        for i in range(1, 4):
            client.publish(self._topic(f"current/dart{i}"), "", retain=True)
            client.publish(self._topic(f"last_turn/dart{i}"), "", retain=True)
        client.publish(self._topic("current/total"), "", retain=True)
        client.publish(self._topic("last_turn/total"), "", retain=True)
        if self._on_change:
            self._on_change()
        log.info("Game stopped")

    def _command_start(self, cmd):
        """Start a game from an MQTT `start` command."""
        raise NotImplementedError

    def _handle_command(self, payload):
        try:
            cmd = json.loads(payload)
        except Exception:
            return
        action = cmd.get("action", "")
        if action == "start":
            try:
                self._command_start(cmd)
            except (TypeError, ValueError) as e:
                log.warning("Start command refused: %s", e)
        elif action == "stop":
            self.stop()
        elif action == "correct_turn":
            if self.game:
                self.game.correct_turn(int(cmd.get("total", 0)))
        elif action == "undo":
            if self.game:
                self.game.undo()
        elif action == "add_player":
            name = cmd.get("name", "").strip()
            if name:
                kp.add(name, self.stats_db)
                self._publish_known_players()
        elif action == "remove_player":
            # Hiding, since there is no separate roster to remove someone from.
            name = cmd.get("name", "").strip()
            if name and self.stats_db:
                self.stats_db.upsert_player(name, hidden=True)
                self._publish_known_players()

    def _publish_known_players(self):
        self.mqtt_pub.client.publish(
            self._topic("known_players"),
            json.dumps(kp.load(self.stats_db), ensure_ascii=False), retain=True)
