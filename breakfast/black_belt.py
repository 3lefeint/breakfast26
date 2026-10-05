"""Black Belt: the doubles drill. One player works up a ladder of doubles without a restart.

The ladder runs D1, D2, ... D20 and ends with the bull's eye (or backwards, D20 down to D1, the
bull's eye still last). A dart on the double of the field that is up moves the ladder on. Each field
has three darts of its own; the darts still in hand after a hit are bonus darts at the next field
and do not use up its three. When a field is not hit with the bonus darts and then its own three,
the ladder starts again from the beginning. The belt is earned when the whole ladder is done in one
go. A run has no limit, it ends with the belt or when the player finishes it.
"""

import copy
import json
import logging

from .player_colors import assign_colors
from .turn_game import TurnGame, TurnGameController, dart_positions

log = logging.getLogger(__name__)

BULL = 25
OWN_DARTS = 3


def ladder(backwards=False):
    """The fields of the ladder in order, 25 for the bull's eye."""
    return [*(range(20, 0, -1) if backwards else range(1, 21)), BULL]


def is_hit(throw, field):
    """A dart on the double of the field, the bull's eye for 25."""
    seg = throw.get("segment") or {}
    return seg.get("number") == field and seg.get("multiplier") == 2


class Progress:
    """Where a run stands. `play()` moves it along with the darts of a turn."""

    def __init__(self, backwards=False):
        self.steps = ladder(backwards)
        self.pos = 0              # the index of the field that is up, len(steps) once the belt is earned
        self.own_left = OWN_DARTS
        self.restarts = 0
        self.furthest = 0         # the most fields done in one go
        self.attempts = []        # fields done in each attempt that ended with a restart
        self.belt = False

    @property
    def target(self):
        return self.steps[min(self.pos, len(self.steps) - 1)]

    def play(self, throws):
        """The darts of a turn, one record per dart that was thrown at the ladder: the field it was
        for, whether it hit, whether it was a bonus dart and whether the miss ended an attempt. Darts
        after the belt are not counted."""
        records = []
        bonus = False
        for throw in throws:
            if self.belt:
                break
            field = self.steps[self.pos]
            hit = is_hit(throw, field)
            record = {"step": self.pos, "field": field, "hit": hit, "bonus": bonus, "restart": False}
            if hit:
                self.pos += 1
                self.own_left = OWN_DARTS
                self.furthest = max(self.furthest, self.pos)
                bonus = True
                self.belt = self.pos == len(self.steps)
            elif not bonus:
                self.own_left -= 1
                if self.own_left == 0:
                    self.attempts.append(self.pos)
                    self.pos = 0
                    self.own_left = OWN_DARTS
                    self.restarts += 1
                    record["restart"] = True
            records.append(record)
        return records

    def copy(self):
        return copy.deepcopy(self)


class BlackBeltGame(TurnGame):
    MODE = "Black Belt"
    TOPIC = "black_belt"

    def __init__(self, player, client, base_topic, backwards=False, audio=None, on_change=None,
                 stats_db=None, match_id=None, color=None):
        player = (player or "").strip()
        if not player:
            raise ValueError("need a player")
        super().__init__(client, base_topic, audio=audio, on_change=on_change,
                         stats_db=stats_db, match_id=match_id)
        self.player = player
        self.backwards = bool(backwards)
        self.color = color
        self.progress = Progress(self.backwards)
        self.thrown = 0
        self.turns = []           # the darts of every finished turn, as the board shows them
        self.result = None
        if self.stats_db:
            self.stats_db.open_match(self.match_id, self.MODE, 0)
            self.stats_db.record_black_belt_setup(self.match_id, player, self.backwards)
        log.info("Black Belt started: %s%s", player, ", backwards" if self.backwards else "")

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
        self._publish_event("start", player=self.player, backwards=self.backwards)

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
            self.stats_db.insert_black_belt_turn(
                self.match_id, self.player, records, positions=dart_positions(counted))
        self._current_darts, self._last_throws, self._dart_overrides = [], [], {}
        self.thrown += len(records)
        self.turns.append([{**self.board_dart(t), "hit": r["hit"]} for t, r in zip(counted, records)])
        self._publish_event("turn_end", player=self.player, hits=sum(1 for r in records if r["hit"]),
                            fields=self.progress.pos, restarts=self.progress.restarts)
        if self.progress.belt:
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
            "belt": p.belt, "furthest": p.furthest, "restarts": p.restarts, "darts": self.thrown,
            "attempts": [*p.attempts, p.pos] if not p.belt else [*p.attempts, len(p.steps)],
        }
        if self.stats_db:
            self.stats_db.set_black_belt_belt(self.match_id, p.belt)
            self.stats_db.close_match(self.match_id)
        self._publish_event("finished", player=self.player, belt=p.belt, furthest=p.furthest,
                            darts=self.thrown, restarts=p.restarts)
        self._publish_state()
        self._publish_turn(reset=True)
        log.info("Black Belt finished: %d fields, %d restarts, %d darts%s", p.furthest, p.restarts,
                 self.thrown, ", belt earned" if p.belt else "")

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
            self.stats_db.set_black_belt_belt(self.match_id, False)
            self.stats_db.reopen_match(self.match_id)
        if snap["turn_recorded"]:
            self.stats_db.delete_last_black_belt_turn(self.match_id, self.player)

    def correct_turn(self, new_total):
        """A turn has no total to correct here: tap a dart to correct it, or undo the turn."""
        log.warning("Black Belt has no turn total to correct")

    # ── what the screens and MQTT get ────────────────────────────────────────

    def snapshot(self) -> dict:
        """The state as the screens show it. While darts are on the board the ladder is shown as
        if they were counted, so it moves with every dart."""
        live = self.progress.copy()
        live_records = live.play(list(self._last_throws)) if self.state == "playing" else []
        p = live if self.state == "playing" else self.progress
        board = [{**self.board_dart(t), "hit": r["hit"]} for t, r in zip(self._last_throws, live_records)]
        all_darts = [d for turn in self.turns for d in turn]
        return {
            "active": self.state == "playing",
            "state": self.state,
            "player": self.player,
            "current_player": self.current_player,
            "color": self.color,
            "backwards": self.backwards,
            "steps": list(p.steps),
            "position": p.pos,              # fields done in this attempt
            "target": p.target,
            "own_left": p.own_left,
            # The darts still in hand after a hit are bonus darts at the field that is up.
            "bonus_darts": (max(0, 3 - len(live_records))
                            if live_records and (live_records[-1]["hit"] or live_records[-1]["bonus"]) else 0),
            "restarts": p.restarts,
            "furthest": p.furthest,
            "attempts": list(p.attempts),
            "thrown": self.thrown + len(live_records),
            "turn": len(self.turns) + 1,
            "belt": p.belt,
            "current_darts": [{"field": r["field"], "hit": r["hit"], "bonus": r["bonus"], "restart": r["restart"]}
                              for r in live_records],
            "round_darts": {self.player: board},
            "all_darts": [{"x": d["x"], "y": d["y"], "field": d["field"], "hit": d["hit"]}
                          for d in all_darts if d.get("x") is not None],
            "setup": {"player": self.player, "backwards": self.backwards},
            "result": self.result,
        }

    def _publish_state(self):
        p = self.progress
        state = {"state": self.state, "player": self.player, "backwards": self.backwards,
                 "target": p.target, "fields_done": p.pos, "furthest": p.furthest,
                 "restarts": p.restarts, "darts": self.thrown, "belt": p.belt}
        self.client.publish(self._topic("state"), json.dumps(state, ensure_ascii=False), retain=True)
        self.client.publish(self._topic("active"), "true" if self.state == "playing" else "false", retain=True)
        self.client.publish(self._topic("target"), str(p.target), retain=True)
        self.client.publish(self._topic("fields_done"), str(p.pos), retain=True)
        self.client.publish(self._topic("restarts"), str(p.restarts), retain=True)
        self._changed()


class BlackBeltController(TurnGameController):
    TOPIC = "black_belt"

    def start(self, player, backwards=False):
        """Start a run. Raises ValueError for a setup that cannot be played."""
        name = (player or "").strip()
        chosen = self.stats_db.player_colors() if self.stats_db else {}
        game = BlackBeltGame(
            name, self.mqtt_pub.client, self.base_topic, backwards=backwards, audio=self.audio,
            on_change=self._on_change, stats_db=self.stats_db,
            color=assign_colors([name], chosen)[name]["color"] if name else None)
        with self._lock:
            self.game = game
        game.announce_start()

    def finish_early(self):
        with self._lock:
            return bool(self.game and self.game.finish_early())

    def _command_start(self, cmd):
        players = [str(p).strip() for p in cmd.get("players", []) if str(p).strip()]
        player = str(cmd.get("player") or (players[0] if players else "")).strip()
        self.start(player, backwards=bool(cmd.get("backwards", False)))
