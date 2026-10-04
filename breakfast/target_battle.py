"""Target Battle: all players throw at the same target number, round after round.

Every round has one target from 1 to 20, the same for everybody. Each player throws one turn of
three darts per round, and only a dart on the target scores. After the last round the highest
total wins; several players on the same total all win. Optionally the players tied for the top
play on in tiebreak rounds, each on one new common target, until one of them has the highest
score of a round.

The scoring profile says what a hit is worth: single, double and triple 1, 2 and 3 points
(standard), or only one of them, 1 point (training profiles). Everything else scores 0.
"""

import copy
import json
import logging
import random

from .target_battle_scoring import SCORING
from .turn_game import TurnGame, TurnGameController, dart_positions

log = logging.getLogger(__name__)

MAX_ROUNDS = 99
TARGETS = range(1, 21)


class TargetBattleGame(TurnGame):
    MODE = "Target Battle"
    TOPIC = "target_battle"

    def __init__(self, players, client, base_topic, rounds=10, targets=None, scoring="standard",
                 tiebreak=False, audio=None, on_change=None, stats_db=None, rng=None, match_id=None):
        """*targets*: None for a random target each round, or one target per round."""
        players = list(players)
        if not players:
            raise ValueError("need at least one player")
        if len(set(players)) != len(players):
            raise ValueError("a player can only play once")
        if not 1 <= rounds <= MAX_ROUNDS:
            raise ValueError(f"rounds must be between 1 and {MAX_ROUNDS}")
        if scoring not in SCORING:
            raise ValueError(f"scoring must be one of {', '.join(SCORING)}")
        if targets is not None:
            targets = list(targets)
            if len(targets) != rounds or any(t not in TARGETS for t in targets):
                raise ValueError("targets need one number from 1 to 20 for every round")
        super().__init__(client, base_topic, audio=audio, on_change=on_change,
                         stats_db=stats_db, match_id=match_id)
        self.order = players
        self.rounds = rounds
        self.scoring = scoring
        self.tiebreak_enabled = bool(tiebreak)
        self.fixed_targets = targets
        self._rng = rng or random.Random()
        self._targets = {}           # (tiebreak, round) -> target, so a round keeps its target
        self._targets_picked = []    # the targets in the order they were picked
        self.scores = {p: 0 for p in players}
        self.round = 1
        self.in_tiebreak = False
        self.contenders = list(players)   # who throws in the current round
        self.turn_idx = 0
        self.round_scores = {}       # player -> points of this round, once the turn is over
        self.round_darts = {}        # player -> darts of this round, once the turn is over
        self.target = self._target_for(1, False)
        self.winners = []
        self.placements = {}
        if self.stats_db:
            self.stats_db.open_match(self.match_id, self.MODE, rounds)
        log.info("Game started: %s, %d rounds, %s", players, rounds, scoring)

    # ── targets and scoring ──────────────────────────────────────────────────

    def _target_for(self, round_no, tiebreak):
        key = (tiebreak, round_no)
        if key not in self._targets:
            if self.fixed_targets and not tiebreak:
                target = self.fixed_targets[round_no - 1]
            else:
                previous = self._targets_picked[-1] if self._targets_picked else None
                target = self._rng.choice([t for t in TARGETS if t != previous])
            self._targets[key] = target
            self._targets_picked.append(target)
        return self._targets[key]

    def value_of(self, throw):
        seg = throw.get("segment") or {}
        if seg.get("number") != self.target:
            return 0
        return SCORING[self.scoring].get(seg.get("multiplier") or 0, 0)

    @property
    def current_player(self):
        if self.state != "playing" or self.turn_idx >= len(self.contenders):
            return None
        return self.contenders[self.turn_idx]

    # ── the game ─────────────────────────────────────────────────────────────

    def announce_start(self):
        """Publish the first state. Only once the game is assigned to its controller, since the
        state push builds its snapshot from there."""
        self._publish_state()
        self._publish_turn(reset=True)
        self._publish_last_turn([])
        self._publish_event("round_start", round=self.round, target=self.target, tiebreak=False)

    def _end_turn(self):
        player = self.current_player
        points = sum(self._current_darts)
        throws = list(self._last_throws)
        self._turn_snapshot = self._snapshot_state(player)
        self._push_history(self._turn_snapshot, turn_recorded=self.stats_db is not None)
        self._publish_last_turn(self._current_darts)
        if self.stats_db:
            self.stats_db.insert_target_battle_turn(
                self.match_id, player, self.round, self.target, self.in_tiebreak, points,
                len(throws), positions=dart_positions(throws))
        self._current_darts = []
        self._last_throws = []
        self._dart_overrides = {}
        self._apply_turn(player, points, [self.board_dart(t) for t in throws])

    def _apply_turn(self, player, points, darts):
        """*darts*: the board view of the turn's darts, empty when they are not known."""
        self.round_scores[player] = points
        self.round_darts[player] = darts
        if not self.in_tiebreak:
            self.scores[player] += points
        self._publish_event("turn_end", player=player, score=points, round=self.round,
                            total=self.scores[player], tiebreak=self.in_tiebreak)
        self.turn_idx += 1
        if self.turn_idx >= len(self.contenders):
            self._end_round()
        else:
            self._publish_state()
            self._publish_turn(reset=True)

    def _end_round(self):
        if self.in_tiebreak:
            best = max(self.round_scores.values())
            leaders = [p for p in self.contenders if self.round_scores[p] == best]
            if len(leaders) == 1:
                return self._finish(leaders[0])
            return self._start_round(self.round + 1, tiebreak=True, contenders=leaders)
        if self.round < self.rounds:
            return self._start_round(self.round + 1, tiebreak=False, contenders=self.order)
        best = max(self.scores.values())
        leaders = [p for p in self.order if self.scores[p] == best]
        if len(leaders) > 1 and self.tiebreak_enabled:
            return self._start_round(1, tiebreak=True, contenders=leaders)
        self._finish(None)

    def _start_round(self, round_no, tiebreak, contenders):
        self.round = round_no
        self.in_tiebreak = tiebreak
        self.contenders = list(contenders)
        self.turn_idx = 0
        self.round_scores = {}
        self.round_darts = {}
        self.target = self._target_for(round_no, tiebreak)
        self._publish_event("round_start", round=round_no, target=self.target, tiebreak=tiebreak)
        self._publish_state()
        self._publish_turn(reset=True)

    def _finish(self, tiebreak_winner):
        """The game is over. A tiebreak winner ranks first, everybody else by total, players on
        the same total share a placement."""
        key = lambda p: (p != tiebreak_winner, -self.scores[p])
        self.placements = {p: 1 + sum(1 for q in self.order if key(q) < key(p)) for p in self.order}
        top = [p for p in self.order if self.placements[p] == 1]
        # Playing alone has a score but nobody to win against.
        self.winners = top if len(self.order) > 1 else []
        self.state = "finished"
        self.turn_idx = len(self.contenders)
        if self.stats_db:
            self.stats_db.record_target_battle_results(
                self.match_id, [(p, self.placements[p], self.scores[p]) for p in self.order])
            self.stats_db.set_winner(self.match_id, self.winners[0] if len(self.winners) == 1 else None)
            self.stats_db.close_match(self.match_id)
        self._publish_event("game_won", winners=self.winners, scores=self.scores)
        self._publish_state()
        self._publish_turn(reset=True)
        log.info("Finished: %s won, scores %s", self.winners or "nobody", self.scores)

    # ── undo and corrections ─────────────────────────────────────────────────

    def _snapshot_state(self, player):
        return copy.deepcopy({
            "player": player, "round": self.round, "in_tiebreak": self.in_tiebreak,
            "contenders": self.contenders, "turn_idx": self.turn_idx, "scores": self.scores,
            "round_scores": self.round_scores, "round_darts": self.round_darts,
            "target": self.target, "state": self.state, "winners": self.winners,
            "placements": self.placements,
        })

    def _restore(self, snap):
        snap = copy.deepcopy(snap)
        self.round = snap["round"]
        self.in_tiebreak = snap["in_tiebreak"]
        self.contenders = snap["contenders"]
        self.turn_idx = snap["turn_idx"]
        self.scores = snap["scores"]
        self.round_scores = snap["round_scores"]
        self.round_darts = snap["round_darts"]
        self.target = snap["target"]
        self.state = snap["state"]
        self.winners = snap["winners"]
        self.placements = snap["placements"]

    def _forget_stored_turn(self, snap, was_finished):
        if was_finished:
            self.stats_db.delete_target_battle_results(self.match_id)
            self.stats_db.set_winner(self.match_id, None)
            self.stats_db.reopen_match(self.match_id)
        if snap["turn_recorded"]:
            self.stats_db.delete_last_target_battle_turn(self.match_id, snap["player"])

    def correct_turn(self, new_total):
        """The total of the last finished turn was wrong: score it again with `new_total`. Its
        darts were misread, so they are no longer shown on the board."""
        snap = self._turn_snapshot
        if not snap:
            log.warning("No turn to correct")
            return
        new_total = max(0, int(new_total))
        was_finished = self.state == "finished"
        self._restore(snap)
        if self.stats_db:
            if was_finished:
                self.stats_db.delete_target_battle_results(self.match_id)
                self.stats_db.set_winner(self.match_id, None)
                self.stats_db.reopen_match(self.match_id)
            self.stats_db.correct_last_target_battle_turn(self.match_id, snap["player"], new_total)
        self._apply_turn(snap["player"], new_total, [])
        log.info("Turn corrected: total=%d", new_total)

    # ── what the screens and MQTT get ────────────────────────────────────────

    def snapshot(self) -> dict:
        cp = self.current_player
        darts = {p: list(d) for p, d in self.round_darts.items()}
        if cp and self._last_throws:
            darts[cp] = [self.board_dart(t) for t in self._last_throws]
        return {
            "active": self.state == "playing",
            "state": self.state,
            "round": self.round,
            "rounds": self.rounds,
            "tiebreak": self.in_tiebreak,
            "target": self.target,
            "scoring": self.scoring,
            "current_player": cp,
            "current_darts": list(self._current_darts),
            "order": list(self.order),
            "contenders": list(self.contenders),
            "winners": list(self.winners),
            "players": [
                {
                    "name": p,
                    "score": self.scores[p],
                    "round_score": self.round_scores.get(p),
                    "current": p == cp,
                    "placement": self.placements.get(p),
                }
                for p in self.order
            ],
            "round_darts": darts,
        }

    def _publish_state(self):
        state = {
            "state": self.state, "round": self.round, "rounds": self.rounds,
            "tiebreak": self.in_tiebreak, "target": self.target, "scoring": self.scoring,
            "current_player": self.current_player, "order": self.order, "winners": self.winners,
            "players": {p: {"score": self.scores[p], "round_score": self.round_scores.get(p)}
                        for p in self.order},
        }
        self.client.publish(self._topic("state"), json.dumps(state, ensure_ascii=False), retain=True)
        self.client.publish(self._topic("active"), "true" if self.state == "playing" else "false", retain=True)
        self.client.publish(self._topic("round"), str(self.round), retain=True)
        self.client.publish(self._topic("rounds"), str(self.rounds), retain=True)
        self.client.publish(self._topic("target"), str(self.target), retain=True)
        self._changed()


class TargetBattleController(TurnGameController):
    TOPIC = "target_battle"

    def start(self, players, rounds=10, targets=None, scoring="standard", tiebreak=False):
        """Start a game. Raises ValueError for a setup that cannot be played."""
        game = TargetBattleGame(
            players, self.mqtt_pub.client, self.base_topic, rounds=rounds, targets=targets,
            scoring=scoring, tiebreak=tiebreak, audio=self.audio, on_change=self._on_change,
            stats_db=self.stats_db)
        with self._lock:
            self.game = game
        game.announce_start()

    def _command_start(self, cmd):
        players = [str(p).strip() for p in cmd.get("players", []) if str(p).strip()]
        self.start(players, rounds=int(cmd.get("rounds", 10)), targets=cmd.get("targets"),
                   scoring=cmd.get("scoring", "standard"), tiebreak=bool(cmd.get("tiebreak", False)))
