"""Checkout training: one player finishes a series of scores.

A finishable score (2 to 170, not one that no three darts can finish) is drawn, the player has up
to three darts and has to finish it on a double, the bull's eye counts. The attempt ends with the
finish, a bust (below zero, exactly one, or zero without a double) or when the darts are pulled,
and then the next score is drawn, whether the attempt worked or not. A run is a number of attempts
in a range of scores. The standard route of every score is in checkout_routes.
"""

import copy
import json
import logging
import random

from . import checkout_routes as routes
from .player_colors import assign_colors
from .turn_game import TurnGame, TurnGameController, dart_positions

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 100
DARTS = 3

# The ranges the setup offers.
RANGES = {"low": (2, 40), "mid": (41, 100), "high": (101, 170), "all": (2, 170)}


def outcome(score, fields):
    """How an attempt at *score* goes with the darts *fields*: the darts it took and whether it
    finished, as (darts used, "finished" | "bust" | "open"). "open" means no finish and no bust
    with the darts thrown, which ends the attempt at the latest after three."""
    used = 0
    state = "open"
    for i in range(1, min(len(fields), DARTS) + 1):
        used = i
        state = routes.after_darts(score, fields[:i])["state"]
        if state != "open":
            break
    return used, state


class CheckoutTrainingGame(TurnGame):
    MODE = "Checkout Training"
    TOPIC = "checkout_training"

    def __init__(self, player, client, base_topic, low=2, high=170, attempts=10, show_route=False,
                 audio=None, on_change=None, stats_db=None, match_id=None, color=None, rng=None):
        player = (player or "").strip()
        if not player:
            raise ValueError("need a player")
        if not 2 <= low <= high <= 170:
            raise ValueError("the range must lie between 2 and 170")
        if not any(routes.finishable(s) for s in range(low, high + 1)):
            raise ValueError("no finishable score in that range")
        if not 1 <= attempts <= MAX_ATTEMPTS:
            raise ValueError(f"attempts must be between 1 and {MAX_ATTEMPTS}")
        super().__init__(client, base_topic, audio=audio, on_change=on_change,
                         stats_db=stats_db, match_id=match_id)
        self.player = player
        self.low, self.high = low, high
        self.attempts = attempts
        self.show_route = bool(show_route)
        self.color = color
        self.rng = rng or random.Random()
        self.results = []                # the finished attempts, see _apply_attempt()
        self.completed = False
        self.result = None
        self.score = routes.draw(low, high, self.rng)
        if self.stats_db:
            self.stats_db.open_match(self.match_id, self.MODE, attempts)
            self.stats_db.record_checkout_training_setup(self.match_id, player, low, high, attempts, self.show_route)
        log.info("Checkout training started: %s, %d-%d, %d attempts", player, low, high, attempts)

    # ── the game ─────────────────────────────────────────────────────────────

    @property
    def current_player(self):
        return self.player if self.state == "playing" else None

    @property
    def attempt(self):
        """The number of the attempt that is on, from 1."""
        return min(len(self.results) + 1, self.attempts)

    def _fields(self, throws):
        return [routes.field_of(t) for t in throws][:DARTS]

    def announce_start(self):
        """Publish the first state. Only once the game is assigned to its controller, since the
        state push builds its snapshot from there."""
        self._publish_state()
        self._publish_turn(reset=True)
        self._publish_last_turn([])
        self._publish_event("start", player=self.player, low=self.low, high=self.high, attempts=self.attempts)

    def _end_turn(self):
        throws = list(self._last_throws)[:DARTS]
        if not throws:
            self._current_darts, self._last_throws, self._dart_overrides = [], [], {}
            return
        fields = self._fields(throws)
        used, state = outcome(self.score, fields)
        success = state == "finished"
        self._turn_snapshot = self._snapshot_state(self.player)
        self._push_history(self._turn_snapshot, turn_recorded=self.stats_db is not None)
        self._publish_last_turn(list(self._current_darts)[:DARTS])
        if self.stats_db:
            self.stats_db.insert_checkout_training_turn(
                self.match_id, self.player, len(self.results) + 1, self.score, success, used,
                fields[used - 1] if success else None, positions=dart_positions(throws[:used]))
        views = [self.board_dart(t) for t in throws[:used]]
        self._current_darts, self._last_throws, self._dart_overrides = [], [], {}
        self._apply_attempt(success, used, fields[:used], views)

    def _apply_attempt(self, success, used, fields, darts):
        self.results.append({
            "score": self.score, "success": success, "darts": used, "fields": fields,
            "route": routes.standard_route(self.score), "board": darts,
        })
        self._publish_event("attempt_end", player=self.player, score=self.score, success=success, darts=used)
        if len(self.results) >= self.attempts:
            self._finish(completed=True)
            return
        self.score = routes.draw(self.low, self.high, self.rng, avoid=[r["score"] for r in self.results[-3:]])
        self._publish_state()
        self._publish_turn(reset=True)

    def finish_early(self):
        """Stop the run and keep the attempts so far. Darts of an attempt that is still in progress
        are not counted. Returns False when there is no finished attempt, nothing to keep then."""
        if self.state != "playing" or not self.results:
            return False
        self._current_darts, self._last_throws, self._dart_overrides = [], [], {}
        self._finish(completed=False)
        return True

    def _finish(self, completed):
        self.completed = completed
        self.state = "finished"
        successes = sum(1 for r in self.results if r["success"])
        if self.stats_db:
            self.stats_db.set_checkout_training_completed(self.match_id, completed)
            self.stats_db.close_match(self.match_id)
        self.result = {
            "attempts": len(self.results), "successes": successes,
            "rate": round(successes / len(self.results), 3) if self.results else 0.0,
            "completed": completed,
            # What was missed, to practise next: every score that did not work, with its route.
            "missed": [{"score": r["score"], "route": r["route"]} for r in self.results if not r["success"]],
        }
        self._publish_event("finished", player=self.player, attempts=len(self.results), successes=successes)
        self._publish_state()
        self._publish_turn(reset=True)
        log.info("Checkout training finished: %d of %d", successes, len(self.results))

    # ── undo and corrections ─────────────────────────────────────────────────

    def _snapshot_state(self, player):
        return copy.deepcopy({"results": self.results, "score": self.score, "state": self.state,
                              "completed": self.completed, "result": self.result})

    def _restore(self, snap):
        snap = copy.deepcopy(snap)
        self.results = snap["results"]
        self.score = snap["score"]
        self.state = snap["state"]
        self.completed = snap["completed"]
        self.result = snap["result"]

    def _forget_stored_turn(self, snap, was_finished):
        if was_finished:
            self.stats_db.set_checkout_training_completed(self.match_id, False)
            self.stats_db.reopen_match(self.match_id)
        if snap["turn_recorded"]:
            self.stats_db.delete_last_checkout_training_turn(self.match_id, self.player)

    def correct_turn(self, new_total):
        """An attempt has no total to correct, the darts are what counts: tap a dart to correct
        it, or undo the attempt."""
        log.warning("Checkout training has no turn total to correct")

    # ── what the screens and MQTT get ────────────────────────────────────────

    def _live(self):
        """The attempt in progress: the darts so far, what is left and how it stands."""
        throws = list(self._last_throws)[:DARTS]
        if self.state != "playing" or not throws:
            return None
        fields = self._fields(throws)
        used, state = outcome(self.score, fields)
        rest = routes.after_darts(self.score, fields[:used])["rest"] if state != "bust" else self.score
        return {"darts": used, "state": state, "rest": rest}

    def snapshot(self) -> dict:
        throws = list(self._last_throws)[:DARTS] if self.state == "playing" else []
        live = self._live()
        rest = live["rest"] if live and live["state"] == "open" else (self.score if not live else None)
        successes = sum(1 for r in self.results if r["success"])
        return {
            "active": self.state == "playing",
            "state": self.state,
            "player": self.player,
            "current_player": self.current_player,
            "color": self.color,
            "low": self.low,
            "high": self.high,
            "attempts": self.attempts,
            "attempt": self.attempt,
            "score": self.score,
            "show_route": self.show_route,
            # The standard route of the score, or of what is left of it while darts are in flight.
            "route": routes.standard_route(self.score) if self.show_route else None,
            "rest_route": routes.standard_route(rest) if self.show_route and live and rest else None,
            "live": live,
            "current_darts": list(self._current_darts)[:DARTS],
            "round_darts": {self.player: [self.board_dart(t) for t in throws]},
            "results": [{k: r[k] for k in ("score", "success", "darts", "fields", "route")} for r in self.results],
            "last": ({k: self.results[-1][k] for k in ("score", "success", "darts", "fields", "route")}
                     if self.results else None),
            "successes": successes,
            "rate": round(successes / len(self.results), 3) if self.results else 0.0,
            # What it takes to start the same run again.
            "setup": {"player": self.player, "low": self.low, "high": self.high,
                      "attempts": self.attempts, "show_route": self.show_route},
            "result": self.result,
        }

    def _publish_state(self):
        state = {
            "state": self.state, "player": self.player, "low": self.low, "high": self.high,
            "attempts": self.attempts, "attempt": self.attempt, "score": self.score,
            "successes": sum(1 for r in self.results if r["success"]),
        }
        self.client.publish(self._topic("state"), json.dumps(state, ensure_ascii=False), retain=True)
        self.client.publish(self._topic("active"), "true" if self.state == "playing" else "false", retain=True)
        self.client.publish(self._topic("score"), str(self.score), retain=True)
        self.client.publish(self._topic("attempt"), str(self.attempt), retain=True)
        self._changed()


class CheckoutTrainingController(TurnGameController):
    TOPIC = "checkout_training"

    def start(self, player, low=2, high=170, attempts=10, show_route=False):
        """Start a run. Raises ValueError for a setup that cannot be played."""
        chosen = self.stats_db.player_colors() if self.stats_db else {}
        name = (player or "").strip()
        game = CheckoutTrainingGame(
            player, self.mqtt_pub.client, self.base_topic, low=low, high=high, attempts=attempts,
            show_route=show_route, audio=self.audio, on_change=self._on_change, stats_db=self.stats_db,
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
        low, high = RANGES.get(cmd.get("range"), (int(cmd.get("low", 2)), int(cmd.get("high", 170))))
        self.start(player, low=low, high=high, attempts=int(cmd.get("attempts", 10)),
                   show_route=bool(cmd.get("show_route", False)))
