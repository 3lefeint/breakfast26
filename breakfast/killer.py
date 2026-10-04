"""Killer: every player owns a number and fights for the last life.

Each player gets a random number from 1 to 20 that nobody else has, and three lives. A double on
the own number makes a player a killer, at once, so the darts that follow in the same turn can
already attack. A killer takes one life per valid dart that hits the number of an opponent, who does
not have to be a killer yet. At no life left a player is out and skipped. The last player left wins
and the game ends right there, the remaining darts of the turn do not count.

Two options, both off by default:
- *singles*: off, only doubles take lives; on, singles take lives too. Triples never do and each dart
  takes one life, a double does not count twice. Becoming a killer always needs a double.
- *own goal*: a valid hit on the own number costs an active killer a life. The dart that makes the
  killer does not count.

The turn in progress is worked out afresh from its darts whenever one lands or is corrected, starting
from the state at the start of the turn, so a correction by tapping changes what the turn did.
"""

import copy
import json
import logging
import random

from .player_colors import assign_colors
from .turn_game import TurnGame, TurnGameController, dart_positions

log = logging.getLogger(__name__)

LIVES = 3
MAX_PLAYERS = 20
NUMBERS = range(1, 21)


class KillerGame(TurnGame):
    MODE = "Killer"
    TOPIC = "killer"

    def __init__(self, players, client, base_topic, own_goal=False, singles=False, numbers=None,
                 audio=None, on_change=None, stats_db=None, rng=None, match_id=None, colors=None):
        """*numbers*: {player: number} to fix the numbers (for a test), else they are drawn. *colors*:
        {player: {"color", "ring"}} for marking the numbers on the board, see player_colors.assign_colors()."""
        players = list(players)
        if len(players) < 2:
            raise ValueError("need at least 2 players")
        if len(players) > MAX_PLAYERS:
            raise ValueError(f"at most {MAX_PLAYERS} players")
        if len(set(players)) != len(players):
            raise ValueError("a player can only play once")
        rng = rng or random.Random()
        if numbers is None:
            numbers = dict(zip(players, rng.sample(list(NUMBERS), len(players))))
        elif set(numbers) != set(players) or len(set(numbers.values())) != len(players) \
                or any(n not in NUMBERS for n in numbers.values()):
            raise ValueError("every player needs a different number from 1 to 20")
        super().__init__(client, base_topic, audio=audio, on_change=on_change,
                         stats_db=stats_db, match_id=match_id)
        self.order = players
        self.own_goal = bool(own_goal)
        self.singles = bool(singles)
        self.numbers = dict(numbers)
        self.colors = colors or {}
        self.lives = {p: LIVES for p in players}
        self.killers = set()
        self.elimination_order = []      # in the order the players went out
        self.winner = None
        self.placements = {}
        self._current = players[0]
        self.turn_events = []            # what the darts of the turn in progress did
        self._published_events = set()
        self._turn_start = self._state_of(self._current)
        self._last_turn_throws = []
        self._last_turn_events = []
        self._last_turn_player = None
        if self.stats_db:
            self.stats_db.open_match(self.match_id, self.MODE, LIVES)
            self.stats_db.record_killer_setup(self.match_id, self.own_goal, self.singles)
        log.info("Game started: %s, own goal %s, singles %s", self.numbers, self.own_goal, self.singles)

    # ── the rules ────────────────────────────────────────────────────────────

    @property
    def current_player(self):
        return self._current if self.state == "playing" else None

    @property
    def active(self):
        return [p for p in self.order if self.lives[p] > 0]

    def _owner(self, number):
        return next((p for p in self.order if self.numbers[p] == number), None)

    def _takes_a_life(self, multiplier):
        """Is a dart of this multiplier a valid hit: a double, or a single if singles count."""
        return multiplier == 2 or (multiplier == 1 and self.singles)

    def _apply_dart(self, player, throw, dart_no):
        """What one dart does to the game. Returns the events it caused."""
        seg = throw.get("segment") or {}
        number, multiplier = seg.get("number") or 0, seg.get("multiplier") or 0
        events = []
        if not multiplier or number not in NUMBERS:
            return events
        if player not in self.killers:
            if number == self.numbers[player] and multiplier == 2:
                self.killers.add(player)
                events.append(self._event("killer", dart_no, player, number=number))
            return events
        if not self._takes_a_life(multiplier):
            return events
        owner = self._owner(number)
        if owner is None or self.lives[owner] == 0:
            return events
        if owner == player:
            if not self.own_goal:
                return events
            events.append(self._lose_a_life("own_goal", dart_no, player, player, number))
        else:
            events.append(self._lose_a_life("hit", dart_no, player, owner, number))
        victim = owner
        if self.lives[victim] == 0:
            self.elimination_order.append(victim)
            events.append(self._event("out", dart_no, player, victim=victim, number=number))
        return events

    def _lose_a_life(self, kind, dart_no, player, victim, number):
        self.lives[victim] -= 1
        return self._event(kind, dart_no, player, victim=victim, number=number)

    def _event(self, kind, dart_no, player, victim=None, number=None):
        return {"kind": kind, "dart": dart_no, "player": player, "victim": victim, "number": number,
                "lives": self.lives[victim] if victim else None}

    # ── the turn in progress ─────────────────────────────────────────────────

    def _state_of(self, player):
        """Everything that decides how the game goes on, as of now, for `player` to throw."""
        return copy.deepcopy({
            "player": player, "lives": self.lives, "killers": sorted(self.killers),
            "elimination_order": self.elimination_order, "winner": self.winner,
            "state": self.state, "placements": self.placements,
        })

    def _load_state(self, snap):
        snap = copy.deepcopy(snap)
        self.lives = snap["lives"]
        self.killers = set(snap["killers"])
        self.elimination_order = snap["elimination_order"]
        self.winner = snap["winner"]
        self.state = snap["state"]
        self.placements = snap["placements"]
        self._current = snap["player"]

    def _replay_turn(self):
        """Work out what the darts of the turn in progress did, from the start of the turn. A dart
        that leaves one player ends the game and the darts after it do not count."""
        self._load_state(self._turn_start)
        self.turn_events = []
        player = self._current
        for number, throw in enumerate(self._last_throws[:3], start=1):
            self.turn_events += self._apply_dart(player, throw, number)
            if len(self.active) <= 1 or self.lives[player] == 0:
                break
        if len(self.active) <= 1:
            self._declare_winner()
        self._announce_new_events()
        if self.state == "finished":
            self._complete_turn(list(self._last_throws))
        else:
            self._publish_state()

    def _declare_winner(self):
        self.winner = self.active[0]
        self.state = "finished"
        self.placements = {self.winner: 1}
        for place, name in enumerate(reversed(self.elimination_order), start=2):
            self.placements[name] = place

    def _announce_new_events(self):
        for event in self.turn_events:
            key = (event["kind"], event["dart"], event["victim"])
            if key not in self._published_events:
                self._published_events.add(key)
                self._publish_event(event["kind"], **{k: v for k, v in event.items() if k != "kind"})

    def _dart_seen(self, count, is_new_dart, is_correction):
        self._replay_turn()

    def correct_current_dart(self, dart_index, field):
        before = self.state
        super().correct_current_dart(dart_index, field)
        if before == "playing":
            self._replay_turn()

    def _end_turn(self):
        """The darts were pulled: the turn is over."""
        self._replay_turn()
        if self.state == "playing":
            self._complete_turn(list(self._last_throws))

    def _complete_turn(self, throws):
        """Record the turn as played and move on, or finish the game when it decided it."""
        player = self._turn_start["player"]
        self._turn_snapshot = self._turn_start
        self._push_history(self._turn_start, turn_recorded=self.stats_db is not None)
        self._last_turn_throws = throws
        self._last_turn_events = list(self.turn_events)
        self._last_turn_player = player
        self._publish_last_turn(self._current_darts)
        if self.stats_db:
            self.stats_db.insert_killer_turn(self.match_id, player, len(throws), self.turn_events,
                                             positions=dart_positions(throws))
        self._current_darts = []
        self._last_throws = []
        self._dart_overrides = {}
        self.turn_events = []
        self._published_events = set()
        if self.state == "finished":
            self._record_result()
            self._publish_event("game_won", winner=self.winner)
        else:
            self._current = self._next_after(player)
        self._turn_start = self._state_of(self._current)
        self._publish_state()
        self._publish_turn(reset=True)

    def _next_after(self, player):
        i = self.order.index(player)
        for step in range(1, len(self.order) + 1):
            candidate = self.order[(i + step) % len(self.order)]
            if self.lives[candidate] > 0:
                return candidate
        return player

    def _record_result(self):
        if not self.stats_db:
            return
        self.stats_db.record_killer_results(self.match_id, [
            (p, self.placements[p], self.lives[p] if p == self.winner else None, self.numbers[p])
            for p in self.order])
        self.stats_db.set_winner(self.match_id, self.winner)
        self.stats_db.close_match(self.match_id)

    def announce_start(self):
        """Publish the first state. Only once the game is assigned to its controller, since the
        state push builds its snapshot from there."""
        self._publish_state()
        self._publish_turn(reset=True)
        self._publish_last_turn([])

    # ── undo and corrections ─────────────────────────────────────────────────

    def _snapshot_state(self, player):
        return self._turn_start

    def _restore(self, snap):
        self._load_state(snap)
        self._turn_start = copy.deepcopy(snap)
        self.turn_events = []
        self._published_events = set()
        self._last_turn_throws = []
        self._last_turn_events = []
        self._last_turn_player = None

    def _forget_stored_turn(self, snap, was_finished):
        if was_finished:
            self.stats_db.delete_killer_results(self.match_id)
            self.stats_db.set_winner(self.match_id, None)
            self.stats_db.reopen_match(self.match_id)
        if snap["turn_recorded"]:
            self.stats_db.delete_last_killer_turn(self.match_id, snap["player"])

    def correct_last_dart(self, dart_index, field):
        """Correct one dart of the last finished turn, also after it ended the game: the game goes
        back to before that turn and plays it again with the corrected dart."""
        from .turn_game import parse_field
        if not self._history or not self._last_turn_throws or dart_index not in (0, 1, 2):
            log.warning("No turn to correct")
            return False
        snap = self._history.pop()
        was_finished = self.state == "finished"
        throws = list(self._last_turn_throws)
        while len(throws) <= dart_index:
            throws.append({"segment": {"number": 0, "multiplier": 0}})
        throws[dart_index] = parse_field(field)
        if self.stats_db:
            self._forget_stored_turn(snap, was_finished)
        self._restore(snap)
        self._last_throws = throws
        self._current_darts = [self.value_of(t) for t in throws]
        self._replay_turn()
        if self.state == "playing":
            self._complete_turn(list(self._last_throws))
        log.info("Last turn corrected: dart %d is %s", dart_index + 1, field)
        return True

    def correct_turn(self, new_total):
        """Killer has no turn total to correct, see correct_last_dart()."""
        log.warning("Correcting a turn total does not apply to Killer")

    # ── what the screens and MQTT get ────────────────────────────────────────

    def snapshot(self) -> dict:
        cp = self.current_player
        darts = [self.board_dart(t) for t in self._last_throws]
        return {
            "active": self.state == "playing",
            "state": self.state,
            "winner": self.winner,
            "current_player": cp,
            "current_darts": list(self._current_darts),
            "darts": darts,
            "turn_events": list(self.turn_events),
            "lives_max": LIVES,
            "rules": {"own_goal": self.own_goal, "singles": self.singles},
            # What it takes to start the same game again, with new numbers.
            "setup": {"own_goal": self.own_goal, "singles": self.singles},
            "order": list(self.order),
            "elimination_order": list(self.elimination_order),
            "players": [
                {
                    "name": p,
                    "number": self.numbers[p],
                    "lives": self.lives[p],
                    "killer": p in self.killers,
                    "out": self.lives[p] == 0,
                    "current": p == cp,
                    "placement": self.placements.get(p),
                    "color": self.colors.get(p, {}).get("color"),
                    "ring": self.colors.get(p, {}).get("ring"),
                }
                for p in self.order
            ],
            "last_turn": {
                "player": self._last_turn_player,
                "darts": [self.board_dart(t) for t in self._last_turn_throws],
                "events": list(self._last_turn_events),
            },
        }

    def _publish_state(self):
        state = {
            "state": self.state, "winner": self.winner, "current_player": self.current_player,
            "order": self.order, "rules": {"own_goal": self.own_goal, "singles": self.singles},
            "players": {p: {"number": self.numbers[p], "lives": self.lives[p], "killer": p in self.killers}
                        for p in self.order},
        }
        self.client.publish(self._topic("state"), json.dumps(state, ensure_ascii=False), retain=True)
        self.client.publish(self._topic("active"), "true" if self.state == "playing" else "false", retain=True)
        self._changed()


class KillerController(TurnGameController):
    TOPIC = "killer"

    def start(self, players, own_goal=False, singles=False):
        """Start a game. Raises ValueError for a setup that cannot be played."""
        chosen = self.stats_db.player_colors() if self.stats_db else {}
        game = KillerGame(
            players, self.mqtt_pub.client, self.base_topic, own_goal=own_goal, singles=singles,
            audio=self.audio, on_change=self._on_change, stats_db=self.stats_db,
            colors=assign_colors(players, chosen))
        with self._lock:
            self.game = game
        game.announce_start()

    def _command_start(self, cmd):
        players = [str(p).strip() for p in cmd.get("players", []) if str(p).strip()]
        self.start(players, own_goal=bool(cmd.get("own_goal", False)), singles=bool(cmd.get("singles", False)))
